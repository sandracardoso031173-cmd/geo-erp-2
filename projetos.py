from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import mimetypes
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

from database import conectar
from storage_geo import (
    upload_documento,
    remover_documento,
    criar_url_assinada,
    caminho_storage,
)
from utils import (
    ETAPAS_TAREFAS_PADRAO, PRIORIDADES, RESPONSAVEIS, STATUS_TAREFA,
    cabecalho_pagina, converter_data, data_para_banco,
)


STATUS_VISUAL = {
    "Concluído": "🟢 Concluído",
    "Pendente": "🟡 Pendente",
    "Em andamento": "🔵 Em andamento",
    "Aguardando": "🟠 Aguardando",
    "Paralisado": "🟣 Paralisado",
    "Não se aplica": "⚪ Não se aplica",
    "Cancelado": "⚫ Cancelado",
    "Atrasado": "🔴 Atrasado",
}

STATUS_BANCO = {visual: puro for puro, visual in STATUS_VISUAL.items()}

PRIORIDADES_PROJETO = list(dict.fromkeys(["📌 URGENTE"] + list(PRIORIDADES)))

def texto_limpo(valor):
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except Exception:
        pass
    texto = str(valor).strip()
    return "" if texto.lower() in {"nan", "none", "nat", "<na>"} else texto


def status_visual(valor):
    texto = str(valor or "").strip()
    return STATUS_VISUAL.get(texto, texto)

def status_banco(valor):
    texto = str(valor or "").strip()
    return STATUS_BANCO.get(texto, texto)


@st.cache_data(ttl=10, show_spinner=False)
def listar_projetos():
    with conectar() as conn:
        return pd.read_sql_query(
            """
            SELECT p.id, p.numero AS Número, c.nome AS Cliente,
                   p.servico AS Serviço, p.modelo AS Modelo,
                   p.gestor AS Gestor, p.responsavel_tecnico AS Responsável_Técnico,
                   p.processo_cetesb AS Processo_CETESB, p.valor AS Valor,
                   p.prazo AS Prazo, p.status AS Status,
                   p.observacoes AS Observações, p.concluido_em AS Concluído_em,
                   p.atualizado_em AS Atualizado_em
            FROM projetos p JOIN clientes c ON c.id=p.cliente_id
            ORDER BY COALESCE(p.atualizado_em,'') DESC, p.numero DESC
            """, conn)


@st.cache_data(ttl=10, show_spinner=False)
def buscar_tarefas(projeto_id):
    with conectar() as conn:
        return pd.read_sql_query(
            """
            SELECT id, etapa AS Etapa, tarefa AS Tarefa,
                   responsavel AS Responsável, prazo AS Data,
                   prioridade AS Prioridade, status AS Status,
                   nao_se_aplica AS Não_se_aplica,
                   observacoes AS Observações, ordem AS Ordem
            FROM tarefas WHERE projeto_id=?
            ORDER BY etapa, COALESCE(ordem,9999), id
            """, conn, params=(int(projeto_id),))



@st.cache_data(ttl=30, show_spinner=False)
def listar_clientes_para_novo_projeto():
    with conectar() as conn:
        return pd.read_sql_query(
            "SELECT id, numero_proposta, nome FROM clientes ORDER BY nome, numero_proposta",
            conn,
        )


def limpar_cache_projetos():
    listar_projetos.clear()
    buscar_tarefas.clear()
    listar_documentos_projeto.clear()
    listar_clientes_para_novo_projeto.clear()


def marcar_atualizado(conn, projeto_id: int):
    conn.execute(
        "UPDATE projetos SET atualizado_em=? WHERE id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), projeto_id),
    )


def recalcular_status_projeto(conn, projeto_id: int, status_preferido: str | None = None) -> str:
    linhas = conn.execute(
        "SELECT status, nao_se_aplica FROM tarefas WHERE projeto_id=?", (projeto_id,)
    ).fetchall()
    aplicaveis = [l for l in linhas if int(l["nao_se_aplica"] or 0)==0 and (l["status"] or "").strip() not in {"Não se aplica","Cancelado"}]

    if aplicaveis and all((l["status"] or "").strip()=="Concluído" for l in aplicaveis):
        novo, concluido = "Concluído", date.today().strftime("%d/%m/%Y")
    else:
        novo = status_preferido or (
            "Em andamento" if any((l["status"] or "").strip() in {"Em andamento","Aguardando","Paralisado"} for l in aplicaveis)
            else "Pendente"
        )
        concluido = date.today().strftime("%d/%m/%Y") if novo=="Concluído" else None

    conn.execute("UPDATE projetos SET status=?, concluido_em=? WHERE id=?", (novo, concluido, projeto_id))
    return novo


def salvar_projeto_e_tarefas(
    projeto_id: int, status: str, processo_cetesb: str, responsavel_tecnico: str,
    prazo, observacao_geral: str, dados_editados: pd.DataFrame | None,
):
    with conectar() as conn:
        conn.execute(
            """UPDATE projetos SET processo_cetesb=?, responsavel_tecnico=?, prazo=?, observacoes=? WHERE id=?""",
            (processo_cetesb.strip() or None, responsavel_tecnico.strip() or None, data_para_banco(prazo),
             observacao_geral.strip() or None, projeto_id),
        )
        if dados_editados is not None:
            urgentes = dados_editados[
                dados_editados["Prioridade"].fillna("").astype(str).str.strip().isin(["📌 URGENTE", "URGENTE"])
            ]
            if len(urgentes) > 7:
                raise ValueError("Cada projeto pode ter no máximo 7 tarefas marcadas como 📌 URGENTE.")

            for _, linha in dados_editados.iterrows():
                status_tarefa = str(linha.get("Status") or "").strip() or "Pendente"
                conn.execute(
                    """UPDATE tarefas SET etapa=?, tarefa=?, responsavel=?, prazo=?,
                       prioridade=?, status=?, nao_se_aplica=?, observacoes=? WHERE id=?""",
                    (linha.get("Etapa"), linha.get("Tarefa"), linha.get("Responsável"),
                     data_para_banco(linha.get("Data")), linha.get("Prioridade"), status_tarefa,
                     1 if status_tarefa=="Não se aplica" else 0,
                     linha.get("Observações"), int(linha["id"])),
                )
        recalcular_status_projeto(conn, projeto_id, status_preferido=status)
        marcar_atualizado(conn, projeto_id)
        conn.commit()

    limpar_cache_projetos()


def adicionar_tarefa(projeto_id, etapa, tarefa, responsavel, data_prazo, prioridade, status, observacoes):
    with conectar() as conn:
        if str(prioridade or "").strip() in {"📌 URGENTE", "URGENTE"}:
            qtd_urgentes = conn.execute(
                """SELECT COUNT(*) FROM tarefas
                   WHERE projeto_id=? AND prioridade IN ('📌 URGENTE','URGENTE')""",
                (int(projeto_id),),
            ).fetchone()[0]
            if int(qtd_urgentes or 0) >= 7:
                raise ValueError("Cada projeto pode ter no máximo 7 tarefas marcadas como 📌 URGENTE.")
        ordem = conn.execute("SELECT COALESCE(MAX(ordem),0) FROM tarefas WHERE projeto_id=?", (int(projeto_id),)).fetchone()[0]
        conn.execute(
            """INSERT INTO tarefas(projeto_id,etapa,tarefa,responsavel,prazo,prioridade,status,
               nao_se_aplica,observacoes,ordem) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (int(projeto_id), etapa.strip().upper(), tarefa.strip(), responsavel,
             data_para_banco(data_prazo), prioridade, status,
             1 if status=="Não se aplica" else 0, observacoes.strip(), int(ordem)+1),
        )
        recalcular_status_projeto(conn, int(projeto_id))
        marcar_atualizado(conn, int(projeto_id))
        conn.commit()

    limpar_cache_projetos()

@st.cache_data(ttl=10, show_spinner=False)
def listar_documentos_projeto(projeto_id: int):
    with conectar() as conn:
        return pd.read_sql_query(
            """SELECT id, nome_arquivo AS Arquivo, caminho AS Caminho,
                      data_inclusao AS Data
               FROM documentos_projeto
               WHERE projeto_id=?
               ORDER BY id DESC""",
            conn,
            params=(int(projeto_id),),
        )


def salvar_documentos_projeto(projeto_id: int, numero_projeto: str, arquivos):
    """
    Salva novos anexos no bucket privado Cloudflare R2.

    O banco continua usando a coluna caminho, mas agora o valor é:
        r2:<caminho-do-objeto>

    Arquivos antigos com caminho local continuam compatíveis até serem migrados.
    """
    if not arquivos:
        return 0

    total = 0

    with conectar() as conn:
        for arquivo in arquivos:
            nome_original = Path(arquivo.name).name

            # Mantém a regra atual do ERP: não duplica o mesmo nome no projeto.
            ja_existe = conn.execute(
                """SELECT 1 FROM documentos_projeto
                   WHERE projeto_id=? AND LOWER(nome_arquivo)=LOWER(?)""",
                (int(projeto_id), nome_original),
            ).fetchone()

            if ja_existe:
                continue

            objeto = upload_documento(
                projeto_id=int(projeto_id),
                numero_projeto=str(numero_projeto),
                nome_arquivo=nome_original,
                conteudo=arquivo.getvalue(),
                content_type=getattr(arquivo, "type", None),
            )

            conn.execute(
                """INSERT INTO documentos_projeto
                   (projeto_id, nome_arquivo, caminho, data_inclusao)
                   VALUES (?, ?, ?, ?)""",
                (
                    int(projeto_id),
                    nome_original,
                    caminho_storage(objeto),
                    datetime.now().strftime("%d/%m/%Y %H:%M"),
                ),
            )
            total += 1

        conn.commit()

    if total:
        limpar_cache_projetos()

    return total


def excluir_documento_projeto(documento_id: int):
    """
    Exclui o objeto do Storage antes de remover o registro do banco.

    Para documentos antigos ainda não migrados, preserva a exclusão local.
    """
    with conectar() as conn:
        registro = conn.execute(
            "SELECT caminho FROM documentos_projeto WHERE id=?",
            (int(documento_id),),
        ).fetchone()

        if registro:
            caminho_txt = str(registro["caminho"] or "")

            if caminho_txt.startswith("r2:"):
                remover_documento(caminho_txt.removeprefix("r2:"))
            else:
                caminho_local = Path(caminho_txt)
                try:
                    if caminho_local.exists():
                        caminho_local.unlink()
                except OSError:
                    pass

        conn.execute(
            "DELETE FROM documentos_projeto WHERE id=?",
            (int(documento_id),),
        )
        conn.commit()

    limpar_cache_projetos()


def excluir_projeto(projeto_id: int):
    """Exclui somente o projeto e suas tarefas. O cliente permanece cadastrado."""
    with conectar() as conn:
        conn.execute("DELETE FROM tarefas WHERE projeto_id=?", (int(projeto_id),))
        conn.execute("DELETE FROM projetos WHERE id=?", (int(projeto_id),))
        conn.commit()

    limpar_cache_projetos()

def gerar_excel_projeto(projeto: pd.Series, tarefas: pd.DataFrame) -> bytes:
    from io import BytesIO

    arquivo = BytesIO()

    dados_projeto = pd.DataFrame([
        {
            "Número": projeto.get("Número", ""),
            "Cliente": projeto.get("Cliente", ""),
            "Serviço": projeto.get("Serviço", ""),
            "Gestor": projeto.get("Gestor", ""),
            "Responsável Técnico": projeto.get("Responsável_Técnico", ""),
            "Processo CETESB": projeto.get("Processo_CETESB", ""),
            "Valor": projeto.get("Valor", ""),
            "Prazo": projeto.get("Prazo", ""),
            "Status": projeto.get("Status", ""),
            "Observações": projeto.get("Observações", ""),
            "Concluído em": projeto.get("Concluído_em", ""),
        }
    ])

    colunas = [
        "Etapa",
        "Tarefa",
        "Responsável",
        "Data",
        "Status",
        "Prioridade",
        "Observações",
    ]

    tarefas_excel = tarefas.copy()

    for c in colunas:
        if c not in tarefas_excel.columns:
            tarefas_excel[c] = ""

    tarefas_excel = tarefas_excel[colunas]

    with pd.ExcelWriter(arquivo, engine="openpyxl") as writer:
        dados_projeto.to_excel(
            writer,
            sheet_name="Projeto",
            index=False,
        )

        tarefas_excel.to_excel(
            writer,
            sheet_name="Tarefas",
            index=False,
        )

    arquivo.seek(0)
    return arquivo.getvalue()

def mostrar_ultimos_projetos(projetos: pd.DataFrame):
    st.markdown("<div style='background:#DDF3D4;padding:.42rem .65rem;font-weight:700;border-radius:4px 4px 0 0;'>Todos os projetos — clique para abrir</div>", unsafe_allow_html=True)
    dados_lista = projetos.copy()
    partes = dados_lista["Número"].astype(str).str.extract(r"(\\d{4})\\D*(\\d+)")
    dados_lista["_ano"] = pd.to_numeric(partes[0], errors="coerce")
    dados_lista["_numero"] = pd.to_numeric(partes[1], errors="coerce")
    dados_lista = dados_lista.sort_values(["_ano","_numero","Número"], ascending=[False,False,False], na_position="last")
    st.markdown(
        """
        <style>
        div.stButton > button {
            justify-content: flex-start !important;
            text-align: left !important;
            font-weight: 700 !important;
        }
        div.stButton > button > div,
        div.stButton > button > div[data-testid="stMarkdownContainer"],
        div.stButton > button [data-testid="stMarkdownContainer"],
        div.stButton > button p {
            width: 100% !important;
            justify-content: flex-start !important;
            text-align: left !important;
            font-weight: 700 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for _, p in dados_lista.iterrows():
        texto = f'{p["Número"]} | {p["Cliente"]}'
        if st.button(texto, key=f"projeto_lista_{int(p['id'])}", width="stretch"):
            st.session_state["projeto_pendente"] = texto
            st.rerun()


def tela_projetos():
    cabecalho_pagina("Projetos")
    projetos = listar_projetos()
    if projetos.empty:
        st.info("Nenhum projeto cadastrado."); return

    with st.expander("➕ CADASTRAR NOVO PROJETO", expanded=False):
        clientes_novo = listar_clientes_para_novo_projeto()

        if clientes_novo.empty:
            st.warning("Cadastre primeiro o cliente na tela Clientes.")
        else:
            opcoes_cliente = {
                f'{(r["numero_proposta"] or "SEM PROPOSTA")} | {r["nome"]}': int(r["id"])
                for _, r in clientes_novo.iterrows()
            }
            opcoes_cliente_lista = ["Selecione ou pesquise um cliente/proposta..."] + list(opcoes_cliente.keys())
            cliente_novo = st.selectbox(
                "Cliente / Nº da Proposta",
                opcoes_cliente_lista,
                index=0,
                key="cad_proj_cliente",
                placeholder="Digite para pesquisar cliente ou nº da proposta",
            )
            cliente_selecionado = cliente_novo != "Selecione ou pesquise um cliente/proposta..."
            proposta_padrao = cliente_novo.split("|", 1)[0].strip() if cliente_selecionado else ""
            numero_novo = st.text_input(
                "Nº do Projeto / Proposta *",
                value="" if proposta_padrao == "SEM PROPOSTA" else proposta_padrao,
                key="cad_proj_numero",
                disabled=not cliente_selecionado,
            )
            servico_novo = st.text_input("Serviço *", key="cad_proj_servico")

            c1, c2 = st.columns(2)
            with c1:
                gestor_novo = st.text_input("Gestor", key="cad_proj_gestor")
                rt_novo = st.text_input("Responsável Técnico", key="cad_proj_rt")
            with c2:
                processo_novo = st.text_input("Processo CETESB", key="cad_proj_processo")
                prazo_novo = st.date_input(
                    "Prazo do Projeto", value=None, format="DD/MM/YYYY", key="cad_proj_prazo"
                )

            observacoes_novo = st.text_area("Observações", key="cad_proj_obs")

            if st.button(
                "SALVAR NOVO PROJETO",
                type="primary",
                width="stretch",
                key="salvar_cad_proj",
            ):
                if not cliente_selecionado:
                    st.error("Selecione primeiro o cliente / Nº da Proposta.")
                elif not numero_novo.strip() or not servico_novo.strip():
                    st.error("Preencha o Nº do Projeto/Proposta e o Serviço.")
                else:
                    with conectar() as conn:
                        existe = conn.execute(
                            "SELECT 1 FROM projetos WHERE numero=?",
                            (numero_novo.strip(),),
                        ).fetchone()

                        if existe:
                            st.error("Já existe um projeto com este número.")
                        else:
                            cursor = conn.execute(
                                """INSERT INTO projetos
                                   (numero, cliente_id, servico, gestor, responsavel_tecnico,
                                    processo_cetesb, prazo, status, atualizado_em, observacoes)
                                   VALUES (?, ?, ?, ?, ?, ?, ?, 'Pendente', ?, ?)""",
                                (
                                    numero_novo.strip(),
                                    opcoes_cliente[cliente_novo],
                                    servico_novo.strip(),
                                    gestor_novo.strip() or None,
                                    rt_novo.strip() or None,
                                    processo_novo.strip() or None,
                                    data_para_banco(prazo_novo),
                                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    observacoes_novo.strip() or None,
                                ),
                            )
                            projeto_id_novo = cursor.lastrowid

                            ordem = 1
                            for etapa, lista_tarefas in ETAPAS_TAREFAS_PADRAO.items():
                                for tarefa_padrao in lista_tarefas:
                                    if tarefa_padrao == "Outra tarefa":
                                        continue
                                    conn.execute(
                                        """INSERT INTO tarefas
                                           (projeto_id, etapa, tarefa, prioridade, status,
                                            nao_se_aplica, ordem)
                                           VALUES (?, ?, ?, 'Alta', 'Pendente', 0, ?)""",
                                        (projeto_id_novo, etapa, tarefa_padrao, ordem),
                                    )
                                    ordem += 1
                            conn.commit()
                            limpar_cache_projetos()

                            st.session_state["projeto_pendente"] = (
                                f'{numero_novo.strip()} | '
                                f'{cliente_novo.split("|", 1)[1].strip()}'
                            )
                            st.success("Projeto cadastrado com sucesso.")
                            st.rerun()

    busca = st.text_input("Pesquisar projeto", placeholder="Digite o número, cliente ou serviço")
    dados = projetos.copy()
    if busca.strip():
        termo = busca.strip().lower()
        dados = dados[
            dados["Número"].fillna("").astype(str).str.lower().str.contains(termo)
            | dados["Cliente"].fillna("").str.lower().str.contains(termo)
            | dados["Serviço"].fillna("").str.lower().str.contains(termo)
        ]
    if dados.empty:
        st.warning("Nenhum projeto encontrado."); return

    opcoes = dados.apply(lambda l: f'{l["Número"]} | {l["Cliente"]}', axis=1).tolist()
    opcoes_com_placeholder = ["Selecione um projeto..."] + opcoes

    projeto_pendente = st.session_state.pop("projeto_pendente", None)
    if projeto_pendente in opcoes_com_placeholder:
        st.session_state["seletor_projeto"] = projeto_pendente

    if st.session_state.get("seletor_projeto") not in opcoes_com_placeholder:
        st.session_state["seletor_projeto"] = "Selecione um projeto..."

    escolhido = st.selectbox(
        "Selecione o projeto",
        opcoes_com_placeholder,
        key="seletor_projeto",
    )
    if escolhido == "Selecione um projeto...":
        mostrar_ultimos_projetos(projetos)
        return

    numero = escolhido.split("|")[0].strip()
    projeto = dados[dados["Número"].astype(str)==numero].iloc[0]
    projeto_id = int(projeto["id"])

    if st.button("← VOLTAR PARA LISTA DE PROJETOS", key=f"voltar_{projeto_id}"):
        st.session_state["projeto_pendente"] = "Selecione um projeto..."
        st.rerun()

    with st.expander("🗑️ EXCLUIR PROJETO", expanded=False):
        st.warning(
            f"Esta ação excluirá o projeto {projeto['Número']} | {projeto['Cliente']} "
            "e todas as tarefas vinculadas. O cadastro do cliente será mantido."
        )
        confirmar_exclusao = st.checkbox(
            "Confirmo que desejo excluir este projeto.",
            key=f"confirmar_exclusao_{projeto_id}",
        )
        if st.button(
            "EXCLUIR PROJETO DEFINITIVAMENTE",
            disabled=not confirmar_exclusao,
            key=f"excluir_projeto_{projeto_id}",
            width="stretch",
        ):
            excluir_projeto(projeto_id)
            st.session_state["projeto_pendente"] = "Selecione um projeto..."
            st.success("Projeto excluído com sucesso. O cliente foi mantido.")
            st.rerun()

    st.markdown(
        f"""<div style="background:#DDF3D4;color:#111;font-weight:700;font-size:1.2rem;text-align:center;padding:.45rem;border-radius:4px 4px 0 0;">{projeto['Número']} | {projeto['Cliente']}</div>
        <div style="background:#E2F0D9;color:#2F4F2F;font-weight:600;padding:.35rem .6rem;margin-bottom:.4rem;">Serviço: {projeto['Serviço']}</div>""",
        unsafe_allow_html=True,
    )

    c1,c2,c3,c4 = st.columns(4)
    status_atual = projeto["Status"] or "Pendente"
    status_opcoes_puros = ["Pendente","Em andamento","Aguardando","Paralisado","Concluído","Cancelado"]
    if status_atual not in status_opcoes_puros:
        status_opcoes_puros.insert(0, status_atual)
    status_opcoes_visuais = [status_visual(s) for s in status_opcoes_puros]
    status_atual_visual = status_visual(status_atual)
    with c1:
        status_projeto_visual = st.selectbox(
            "Status",
            status_opcoes_visuais,
            index=status_opcoes_visuais.index(status_atual_visual),
        )
        status_projeto = status_banco(status_projeto_visual)
    with c2:
        processo_cetesb = st.text_input(
            "Processo CETESB",
            value=texto_limpo(projeto["Processo_CETESB"]),
            key=f"processo_cetesb_{projeto_id}",
        )
    with c3:
        resp_tecnico = st.text_input(
            "Responsável Técnico",
            value=texto_limpo(projeto["Responsável_Técnico"]),
            key=f"resp_tecnico_{projeto_id}",
        )
    with c4:
        prazo = st.date_input(
            "Prazo do Projeto",
            value=converter_data(projeto["Prazo"]),
            format="DD/MM/YYYY",
            key=f"prazo_projeto_{projeto_id}",
        )

    tarefas = buscar_tarefas(projeto_id)
    dados_editados = None
    if tarefas.empty:
        observacao_geral = st.text_area(
            "📝 Observação Geral do Projeto",
            value=projeto["Observações"] or "",
            placeholder="Digite uma observação geral do projeto...",
            height=82,
            key=f"observacao_geral_{projeto_id}",
        )
        st.info("Nenhuma tarefa cadastrada para este projeto.")
    else:
        col_nao, col_obs_geral = st.columns([1, 3])
        with col_nao:
            mostrar_nao = st.checkbox('Exibir tarefas "Não se aplica"', value=False, key=f"mostrar_nao_{projeto_id}")
        with col_obs_geral:
            observacao_geral = st.text_area(
                "📝 Observação Geral do Projeto",
                value=projeto["Observações"] or "",
                placeholder="Digite uma observação geral do projeto...",
                height=82,
                key=f"observacao_geral_{projeto_id}",
            )
        dados_tarefas = tarefas.copy()
        dados_tarefas["Data"] = dados_tarefas["Data"].apply(converter_data)
        dados_tarefas["Status"] = dados_tarefas["Status"].apply(status_visual)
        if not mostrar_nao:
            dados_tarefas = dados_tarefas[(dados_tarefas["Não_se_aplica"].fillna(0).astype(int)==0) & (dados_tarefas["Status"].fillna("").str.strip()!="⚪ Não se aplica")]
        colunas = ["id","Etapa","Tarefa","Responsável","Data","Status","Prioridade","Observações"]
        dados_editados = st.data_editor(
            dados_tarefas[colunas],
            hide_index=True,
            width="stretch",
            height=520,
            num_rows="fixed",
            disabled=["id"],
            key=f"editor_{projeto_id}",
            column_config={
                "id": None,
                "Etapa": st.column_config.TextColumn("Etapa", width="small"),
                "Tarefa": st.column_config.TextColumn("Tarefa", width="medium"),
                "Responsável": st.column_config.SelectboxColumn(
                    "Responsável",
                    options=RESPONSAVEIS,
                    width="small",
                ),
                "Data": st.column_config.DateColumn(
                    "Data",
                    format="DD/MM/YYYY",
                    width="small",
                ),
                "Status": st.column_config.SelectboxColumn(
                    "Status",
                    options=[status_visual(s) for s in STATUS_TAREFA],
                    width="small",
                ),
                "Prioridade": st.column_config.SelectboxColumn(
                    "Prioridade",
                    options=PRIORIDADES_PROJETO,
                    width="small",
                ),
                "Observações": st.column_config.TextColumn(
                    "Observações",
                    width="medium",
                    max_chars=500,
                ),
            },
        )


    col_salvar, col_exportar = st.columns(2)

    with col_salvar:
        if st.button(
            "💾 SALVAR PROJETO E TAREFAS",
            type="primary",
            width="stretch",
        ):
            dados_para_salvar = dados_editados.copy() if dados_editados is not None else None
            if dados_para_salvar is not None and "Status" in dados_para_salvar.columns:
                dados_para_salvar["Status"] = dados_para_salvar["Status"].apply(status_banco)

            salvar_projeto_e_tarefas(
                projeto_id,
                status_projeto,
                processo_cetesb,
                resp_tecnico,
                prazo,
                observacao_geral,
                dados_para_salvar,
            )
            st.success("Projeto e tarefas salvos com sucesso.")
            st.rerun()

    with col_exportar:
        chave_excel = f"excel_projeto_{projeto_id}"
        if st.button(
            "📤 GERAR EXPORTAÇÃO",
            key=f"gerar_excel_{projeto_id}",
            width="stretch",
        ):
            st.session_state[chave_excel] = gerar_excel_projeto(projeto, tarefas)

        if chave_excel in st.session_state:
            st.download_button(
                "⬇️ BAIXAR EXCEL",
                data=st.session_state[chave_excel],
                file_name=f"Projeto_{projeto['Número']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
                key=f"baixar_excel_{projeto_id}",
            )


    with st.expander("➕ Adicionar nova tarefa"):
        # Fora de st.form: a lista de tarefas muda imediatamente quando a etapa é alterada.
        etapa = st.selectbox("Etapa *", list(ETAPAS_TAREFAS_PADRAO.keys()), key=f"etapa_nova_{projeto_id}")
        opcoes_tarefa = ETAPAS_TAREFAS_PADRAO[etapa]
        tarefa_sel = st.selectbox("Tarefa *", opcoes_tarefa, key=f"tarefa_nova_{projeto_id}_{etapa}")
        tarefa_livre = st.text_input("Descreva a tarefa *", key=f"livre_{projeto_id}") if tarefa_sel=="Outra tarefa" else ""
        a,b = st.columns(2)
        with a:
            responsavel = st.selectbox("Responsável", RESPONSAVEIS, key=f"resp_nova_{projeto_id}")
            data_prazo = st.date_input("Data", value=None, format="DD/MM/YYYY", key=f"data_nova_{projeto_id}")
        with b:
            prioridade = st.selectbox("Prioridade", PRIORIDADES_PROJETO, index=2 if len(PRIORIDADES_PROJETO) > 2 else 1, key=f"prio_nova_{projeto_id}")
            status_visual_novo = st.selectbox(
                "Status",
                [status_visual(s) for s in STATUS_TAREFA],
                key=f"status_nova_{projeto_id}",
            )
            status = status_banco(status_visual_novo)
        observacoes = st.text_area("Observações", height=90, key=f"obs_nova_{projeto_id}")
        if st.button("ADICIONAR TAREFA", type="primary", width="stretch", key=f"add_{projeto_id}"):
            tarefa_final = tarefa_livre.strip() if tarefa_sel=="Outra tarefa" else tarefa_sel
            if not tarefa_final:
                st.error("Preencha a tarefa.")
            else:
                adicionar_tarefa(projeto_id,etapa,tarefa_final,responsavel,data_prazo,prioridade,status,observacoes)
                st.success("Tarefa adicionada com sucesso."); st.rerun()

    st.divider()
    mostrar_documentos = st.toggle(
        "📁 ABRIR DOCUMENTOS DO PROJETO",
        value=False,
        key=f"mostrar_documentos_{projeto_id}",
        help="Os documentos só são carregados quando esta opção estiver aberta.",
    )

    if mostrar_documentos:
        st.subheader("📁 Documentos do Projeto")

        if f"docs_upload_versao_{projeto_id}" not in st.session_state:
            st.session_state[f"docs_upload_versao_{projeto_id}"] = 0

        upload_versao = st.session_state[f"docs_upload_versao_{projeto_id}"]

        arquivos_upload = st.file_uploader(
            "Adicionar documentos",
            accept_multiple_files=True,
            key=f"docs_upload_{projeto_id}_{upload_versao}",
            help="Selecione um ou mais arquivos para vincular a este projeto.",
        )

        if st.button(
            "📎 SALVAR DOCUMENTOS",
            key=f"salvar_docs_{projeto_id}",
            width="stretch",
            disabled=not arquivos_upload,
        ):
            try:
                qtd = salvar_documentos_projeto(
                    projeto_id,
                    str(projeto["Número"]),
                    arquivos_upload,
                )
            except Exception as exc:
                st.error(f"Não foi possível enviar o documento à nuvem: {exc}")
                qtd = None

            if qtd:
                st.success(f"{qtd} documento(s) salvo(s) no projeto.")
                st.session_state[f"docs_upload_versao_{projeto_id}"] += 1
                st.rerun()
            elif qtd == 0:
                st.info("Os arquivos selecionados já estavam salvos neste projeto e não foram duplicados.")

        documentos = listar_documentos_projeto(projeto_id)

        if documentos.empty:
            st.caption("Nenhum documento anexado a este projeto.")
        else:
            st.caption("Documentos armazenados de forma centralizada e privada no Cloudflare R2.")

            for _, doc in documentos.iterrows():
                caminho_txt = str(doc["Caminho"] or "")
                doc_id = int(doc["id"])
                c_nome, c_data, c_baixar, c_excluir = st.columns([5, 2, 1.4, 1.2])

                with c_nome:
                    st.markdown(f"**{doc['Arquivo']}**")
                with c_data:
                    st.caption(str(doc["Data"] or ""))

                with c_baixar:
                    if caminho_txt.startswith("r2:"):
                        if st.button(
                            "⬇️ Abrir",
                            key=f"abrir_doc_{doc_id}",
                            width="stretch",
                        ):
                            try:
                                url = criar_url_assinada(
                                    caminho_txt.removeprefix("r2:"),
                                    expires_in=300,
                                )
                                st.session_state[f"url_doc_{doc_id}"] = url
                            except Exception as exc:
                                st.error(f"Erro ao abrir: {exc}")

                        url_doc = st.session_state.get(f"url_doc_{doc_id}")
                        if url_doc:
                            st.link_button(
                                "↗️ Documento",
                                url_doc,
                                width="stretch",
                            )
                    else:
                        # Compatibilidade temporária com os anexos antigos locais.
                        caminho_local = Path(caminho_txt)
                        if caminho_local.exists():
                            mime = mimetypes.guess_type(caminho_local.name)[0] or "application/octet-stream"
                            st.download_button(
                                "⬇️ Abrir",
                                data=caminho_local.read_bytes(),
                                file_name=caminho_local.name,
                                mime=mime,
                                key=f"baixar_local_{doc_id}",
                                width="stretch",
                            )
                        else:
                            st.caption("Pendente de migração")

                with c_excluir:
                    if st.button(
                        "🗑️ Excluir",
                        key=f"excluir_doc_{doc_id}",
                        width="stretch",
                    ):
                        try:
                            excluir_documento_projeto(doc_id)
                        except Exception as exc:
                            st.error(f"Não foi possível excluir o documento: {exc}")
                        else:
                            st.rerun()

