from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections.abc import Sequence

import psycopg
from psycopg_pool import ConnectionPool


# ============================================================
# SUPABASE / POSTGRESQL
# ============================================================
# A senha NÃO fica gravada neste arquivo.
# No Windows, configure a variável de ambiente GEO_DB_PASSWORD.
#
# Transaction Pooler do Supabase (IPv4), porta 6543.
# Prepared statements ficam desativados porque o Transaction
# Pooler não os suporta.
PG_HOST = os.getenv("GEO_DB_HOST", "aws-0-sa-east-1.pooler.supabase.com")
PG_PORT = int(os.getenv("GEO_DB_PORT", "6543"))
PG_DB = os.getenv("GEO_DB_NAME", "postgres")
PG_USER = os.getenv("GEO_DB_USER", "postgres.opnmnuhrsddwmdmnocys")
PG_PASSWORD = os.getenv("GEO_DB_PASSWORD", "")

PG_POOL_MIN = int(os.getenv("GEO_DB_POOL_MIN", "1"))
PG_POOL_MAX = int(os.getenv("GEO_DB_POOL_MAX", "4"))

_POOL = None


def _obter_pool():
    """
    Cria o pool apenas uma vez por processo Streamlit.
    Depois disso, as telas reaproveitam conexões já abertas.
    """
    global _POOL

    if not PG_PASSWORD:
        raise RuntimeError(
            "Senha do Supabase não configurada. "
            "Defina a variável de ambiente GEO_DB_PASSWORD antes de iniciar o GEO ERP."
        )

    if _POOL is None:
        _POOL = ConnectionPool(
            conninfo="",
            kwargs={
                "host": PG_HOST,
                "port": PG_PORT,
                "dbname": PG_DB,
                "user": PG_USER,
                "password": PG_PASSWORD,
                "sslmode": "require",
                # Necessário para Supabase Transaction Pooler (porta 6543).
                "prepare_threshold": None,
            },
            min_size=PG_POOL_MIN,
            max_size=PG_POOL_MAX,
            timeout=15,
            open=True,
        )

    return _POOL


class CompatRow(Sequence):
    """Linha compatível com sqlite3.Row: aceita linha[0] e linha["campo"]."""

    def __init__(self, valores, colunas):
        self._valores = tuple(valores)
        self._colunas = tuple(colunas)
        self._indice = {nome: i for i, nome in enumerate(self._colunas)}

    def __getitem__(self, chave):
        if isinstance(chave, str):
            return self._valores[self._indice[chave]]
        return self._valores[chave]

    def __len__(self):
        return len(self._valores)

    def __iter__(self):
        return iter(self._valores)

    def keys(self):
        return list(self._colunas)

    def __repr__(self):
        return repr(dict(zip(self._colunas, self._valores)))


def _converter_placeholders(query: str) -> str:
    """
    Converte placeholders SQLite ? para PostgreSQL %s,
    sem alterar ? que eventualmente estejam dentro de strings SQL.
    """
    resultado = []
    em_string = False
    i = 0

    while i < len(query):
        ch = query[i]

        if ch == "'":
            resultado.append(ch)

            # Aspas simples duplicadas dentro de string SQL: ''
            if em_string and i + 1 < len(query) and query[i + 1] == "'":
                resultado.append("'")
                i += 2
                continue

            em_string = not em_string
            i += 1
            continue

        if ch == "?" and not em_string:
            resultado.append("%s")
        else:
            resultado.append(ch)

        i += 1

    return "".join(resultado)


def _eh_insert_com_id(query: str) -> bool:
    texto = query.strip().lower()
    if not texto.startswith("insert into"):
        return False
    if " returning " in f" {texto} ":
        return False

    # Tabelas usadas pelo ERP em que o código atual espera cursor.lastrowid.
    return bool(
        re.match(
            r"insert\s+into\s+[\"']?"
            r"(clientes|projetos|tarefas|usuarios|faturamento_receber|"
            r"documentos_projeto|contas_pagar|contas_receber_manual)"
            r"[\"']?\b",
            texto,
            flags=re.I,
        )
    )


def _extrair_aliases_sql(query: str) -> dict[str, str]:
    """
    Captura aliases escritos no SQL (AS Proposta, AS Número, AS Vencimento etc.)
    para preservar exatamente maiúsculas, acentos e underscores no resultado.

    PostgreSQL converte identificadores não citados para minúsculas.
    Esta camada restaura o alias como foi escrito pelo ERP, sem exigir
    alteração em clientes.py, projetos.py, financeiro.py, admin.py etc.
    """
    aliases = {}

    padrao = re.compile(
        r'\bAS\s+(?:"([^"]+)"|([A-Za-zÀ-ÿ_][A-Za-z0-9À-ÿ_]*))',
        flags=re.IGNORECASE,
    )

    for match in padrao.finditer(query):
        alias = match.group(1) or match.group(2)
        if alias:
            aliases[alias.lower()] = alias

    return aliases


def _descricao_compat(cursor_description, aliases: dict[str, str]):
    """
    Retorna uma descrição DB-API equivalente, mas com os nomes das colunas
    usando o alias original esperado pelo código antigo.
    """
    if not cursor_description:
        return cursor_description

    descricao = []
    for item in cursor_description:
        nome_original = item.name
        nome = aliases.get(str(nome_original).lower(), nome_original)

        # pandas usa principalmente a posição 0 (nome da coluna).
        descricao.append(
            (
                nome,
                getattr(item, "type_code", None),
                getattr(item, "display_size", None),
                getattr(item, "internal_size", None),
                getattr(item, "precision", None),
                getattr(item, "scale", None),
                getattr(item, "null_ok", None),
            )
        )
    return descricao


class CompatCursor:
    """Cursor psycopg com a interface que o ERP já usa com sqlite3."""

    def __init__(self, cursor):
        self._cursor = cursor
        self.lastrowid = None
        self._aliases = {}

    @property
    def description(self):
        return _descricao_compat(self._cursor.description, self._aliases)

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def execute(self, query, params=None):
        query_original = str(query)
        self._aliases = _extrair_aliases_sql(query_original)
        sql_pg = _converter_placeholders(query_original)

        retornar_id = _eh_insert_com_id(sql_pg)
        if retornar_id:
            sql_pg = sql_pg.rstrip().rstrip(";") + " RETURNING id"

        self._cursor.execute(sql_pg, params or ())

        if retornar_id:
            linha = self._cursor.fetchone()
            self.lastrowid = int(linha[0]) if linha else None

        return self

    def executemany(self, query, params_seq):
        query_original = str(query)
        self._aliases = _extrair_aliases_sql(query_original)
        sql_pg = _converter_placeholders(query_original)
        self._cursor.executemany(sql_pg, params_seq)
        return self

    def _nomes_colunas(self):
        if not self._cursor.description:
            return []
        return [
            self._aliases.get(str(d.name).lower(), d.name)
            for d in self._cursor.description
        ]

    def fetchone(self):
        linha = self._cursor.fetchone()
        if linha is None:
            return None
        return CompatRow(linha, self._nomes_colunas())

    def fetchall(self):
        linhas = self._cursor.fetchall()
        colunas = self._nomes_colunas()
        return [CompatRow(linha, colunas) for linha in linhas]

    def close(self):
        self._cursor.close()

    def __iter__(self):
        colunas = self._nomes_colunas()
        for linha in self._cursor:
            yield CompatRow(linha, colunas)


class CompatConnection:
    """
    Wrapper para permitir que clientes.py, projetos.py, financeiro.py,
    dashboard.py etc. continuem usando conn.execute(... ? ...).
    """

    def __init__(self):
        self._pool = _obter_pool()
        self._conn = self._pool.getconn()
        self._fechada = False

    def cursor(self):
        return CompatCursor(self._conn.cursor())

    def execute(self, query, params=None):
        cur = self.cursor()
        return cur.execute(query, params)

    def executemany(self, query, params_seq):
        cur = self.cursor()
        return cur.executemany(query, params_seq)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        if self._fechada:
            return
        try:
            # Evita devolver conexão "idle in transaction" para o pool.
            self._conn.rollback()
        except Exception:
            pass
        finally:
            self._pool.putconn(self._conn)
            self._fechada = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._fechada:
            return False

        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._pool.putconn(self._conn)
            self._fechada = True

        return False


def conectar():
    return CompatConnection()


def status_pool():
    """Informações simples do pool para diagnóstico, sem expor senha."""
    pool = _obter_pool()
    stats = pool.get_stats()
    return {
        "pool_min": PG_POOL_MIN,
        "pool_max": PG_POOL_MAX,
        "pool_size": stats.get("pool_size"),
        "pool_available": stats.get("pool_available"),
        "requests_waiting": stats.get("requests_waiting"),
    }


def _validar_identificador(nome: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nome):
        raise ValueError(f"Identificador SQL inválido: {nome}")
    return nome


def _adicionar_coluna_se_ausente(conn, tabela, coluna, definicao):
    tabela = _validar_identificador(tabela)
    coluna = _validar_identificador(coluna)

    existe = conn.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name=?
          AND column_name=?
        """,
        (tabela, coluna),
    ).fetchone()

    if not existe:
        conn.execute(
            f'ALTER TABLE "{tabela}" ADD COLUMN "{coluna}" {definicao}'
        )


# ============================================================
# USUÁRIOS
# ============================================================

def gerar_hash_senha(senha: str) -> str:
    salt = os.urandom(16)
    derivada = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), salt, 200_000
    )
    return f"{salt.hex()}${derivada.hex()}"


def verificar_senha(senha: str, senha_hash: str) -> bool:
    try:
        salt_hex, hash_hex = senha_hash.split("$", 1)
        calculado = hashlib.pbkdf2_hmac(
            "sha256",
            senha.encode("utf-8"),
            bytes.fromhex(salt_hex),
            200_000,
        )
        return hmac.compare_digest(calculado, bytes.fromhex(hash_hex))
    except Exception:
        return False


def autenticar_usuario(usuario: str, senha: str):
    with conectar() as conn:
        r = conn.execute(
            """
            SELECT id,nome,usuario,senha_hash,perfil,ativo
            FROM usuarios
            WHERE LOWER(usuario)=LOWER(?)
            """,
            (usuario.strip(),),
        ).fetchone()

    if (
        not r
        or int(r["ativo"] or 0) != 1
        or not verificar_senha(senha, r["senha_hash"])
    ):
        return None

    return {
        "id": int(r["id"]),
        "nome": r["nome"],
        "usuario": r["usuario"],
        "perfil": r["perfil"],
    }


# ============================================================
# INICIALIZAÇÃO / CONFERÊNCIA DO BANCO
# ============================================================

TABELAS_ESPERADAS = {
    "clientes",
    "projetos",
    "usuarios",
    "tarefas",
    "faturamento_receber",
    "documentos_projeto",
    "contas_pagar",
    "contas_receber_manual",
}


def criar_banco():
    """
    No PostgreSQL as tabelas já foram criadas e migradas no Supabase.
    Aqui apenas validamos a estrutura, aplicamos pequenas migrações
    futuras de colunas e preservamos a criação dos usuários iniciais.
    """
    with conectar() as conn:
        linhas = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema='public'
            """
        ).fetchall()

        existentes = {linha["table_name"] for linha in linhas}
        faltando = TABELAS_ESPERADAS - existentes

        if faltando:
            raise RuntimeError(
                "Banco Supabase incompleto. Tabelas ausentes: "
                + ", ".join(sorted(faltando))
            )

        # Migrações compatíveis com versões anteriores do ERP.
        _adicionar_coluna_se_ausente(
            conn, "clientes", "numero_proposta", "TEXT"
        )
        _adicionar_coluna_se_ausente(
            conn, "clientes", "servico_proposta", "TEXT"
        )
        _adicionar_coluna_se_ausente(
            conn, "clientes", "valor_proposta", "DOUBLE PRECISION"
        )
        _adicionar_coluna_se_ausente(
            conn, "clientes", "data_proposta", "TEXT"
        )
        _adicionar_coluna_se_ausente(
            conn, "clientes", "status_proposta",
            "TEXT DEFAULT 'Elaboração'"
        )
        _adicionar_coluna_se_ausente(
            conn, "clientes", "forma_pagamento", "TEXT"
        )
        _adicionar_coluna_se_ausente(
            conn, "clientes", "numero_parcelas", "INTEGER DEFAULT 1"
        )
        _adicionar_coluna_se_ausente(
            conn, "clientes", "primeiro_vencimento", "TEXT"
        )
        _adicionar_coluna_se_ausente(
            conn, "clientes", "status_faturamento",
            "TEXT DEFAULT 'Pendente'"
        )
        _adicionar_coluna_se_ausente(
            conn, "faturamento_receber", "data_recebimento", "TEXT"
        )
        _adicionar_coluna_se_ausente(
            conn, "projetos", "concluido_em", "TEXT"
        )
        _adicionar_coluna_se_ausente(
            conn, "projetos", "atualizado_em", "TEXT"
        )

        conn.execute(
            """
            UPDATE projetos
            SET atualizado_em = COALESCE(
                atualizado_em,
                '2000-01-01 00:00:00'
            )
            """
        )

        usuarios_iniciais = [
            ("Sandra Cardoso", "Sandra", "123456", "Administrador"),
            ("Adalto Luiz Barbosa", "Adalto", "123456", "Administrador"),
        ]

        for nome, usuario, senha, perfil in usuarios_iniciais:
            existe = conn.execute(
                "SELECT 1 FROM usuarios WHERE LOWER(usuario)=LOWER(?)",
                (usuario,),
            ).fetchone()

            if not existe:
                conn.execute(
                    """
                    INSERT INTO usuarios
                    (nome,usuario,senha_hash,perfil,ativo)
                    VALUES(?,?,?,?,1)
                    """,
                    (
                        nome,
                        usuario,
                        gerar_hash_senha(senha),
                        perfil,
                    ),
                )

        conn.commit()


# ============================================================
# STATUS DOS PROJETOS
# ============================================================

def sincronizar_status_projetos():
    """
    Sincroniza status dos projetos com uma única consulta no PostgreSQL.

    Antes, o ERP buscava todos os projetos e depois fazia uma consulta
    separada de tarefas para cada projeto. No Supabase isso adiciona
    latência de rede desnecessária. Esta versão faz o cálculo no próprio
    PostgreSQL e atualiza tudo em uma única ida ao banco.
    """
    from datetime import date

    hoje = date.today().strftime("%d/%m/%Y")

    with conectar() as conn:
        conn.execute(
            """
            WITH resumo AS (
                SELECT
                    p.id,
                    COUNT(t.id) FILTER (
                        WHERE COALESCE(t.nao_se_aplica, 0) = 0
                          AND TRIM(COALESCE(t.status, ''))
                              NOT IN ('Não se aplica', 'Cancelado')
                    ) AS aplicaveis,
                    BOOL_AND(TRIM(COALESCE(t.status, '')) = 'Concluído') FILTER (
                        WHERE COALESCE(t.nao_se_aplica, 0) = 0
                          AND TRIM(COALESCE(t.status, ''))
                              NOT IN ('Não se aplica', 'Cancelado')
                    ) AS todos_concluidos
                FROM projetos p
                LEFT JOIN tarefas t ON t.projeto_id = p.id
                GROUP BY p.id
            )
            UPDATE projetos p
            SET
                status = CASE
                    WHEN r.aplicaveis > 0
                         AND COALESCE(r.todos_concluidos, FALSE)
                    THEN 'Concluído'
                    WHEN TRIM(COALESCE(p.status, '')) <> ''
                    THEN p.status
                    ELSE 'Pendente'
                END,
                concluido_em = CASE
                    WHEN r.aplicaveis > 0
                         AND COALESCE(r.todos_concluidos, FALSE)
                    THEN COALESCE(p.concluido_em, ?)
                    WHEN TRIM(COALESCE(p.status, '')) = 'Concluído'
                    THEN p.concluido_em
                    ELSE NULL
                END
            FROM resumo r
            WHERE p.id = r.id
            """,
            (hoje,),
        )
        conn.commit()

