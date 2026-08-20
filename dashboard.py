from datetime import date

import pandas as pd
import streamlit as st

from database import conectar
from utils import cabecalho_pagina

st.markdown('''
    <style>
        /* Alinha os textos e botões para a esquerda */
        div[data-testid="metric-container"] {
            text-align: left !important;
        }
        div.stButton > button {
            text-align: left !important;
            width: 100% !important;
        }
        div[data-testid="stMarkdownContainer"] p {
            text-align: left !important;
        }
    </style>
''', unsafe_allow_html=True)

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

def status_visual(valor):
    texto = str(valor or "").strip()
    return STATUS_VISUAL.get(texto, texto)

def status_banco(valor):
    texto = str(valor or "").strip()
    return STATUS_BANCO.get(texto, texto)


def ordenar_projetos_por_numero(df):
    """Ordena propostas do menor para o maior."""
    if df is None or df.empty:
        return df
    x = df.copy()
    partes = x["Projeto"].astype(str).str.extract(r"(\d{4})\D*(\d+)")
    x["_ano"] = pd.to_numeric(partes[0], errors="coerce")
    x["_num"] = pd.to_numeric(partes[1], errors="coerce")
    x = x.sort_values(["_ano", "_num", "Projeto"], ascending=True, na_position="last")
    return x.drop(columns=["_ano", "_num"])


@st.cache_data(ttl=5, show_spinner=False)
def carregar_dados_dashboard():
    with conectar() as conn:
        projetos = pd.read_sql_query(
            """
            SELECT p.id, p.numero AS "Projeto", c.nome AS "Cliente",
                   p.servico AS "Serviço", p.gestor AS "Gestor",
                   p.responsavel_tecnico AS "Responsável_Técnico",
                   p.prazo AS "Prazo", p.status AS "Status",
                   p.concluido_em AS "Concluído_em"
            FROM projetos p
            JOIN clientes c ON c.id = p.cliente_id
            ORDER BY p.numero DESC
            """,
            conn,
        )
        tarefas = pd.read_sql_query(
            """
            SELECT t.id, p.numero AS "Projeto", c.nome AS "Cliente",
                   t.etapa AS "Etapa", t.tarefa AS "Tarefa",
                   t.responsavel AS "Responsável", t.prazo AS "Prazo",
                   t.status AS "Status", t.prioridade AS "Prioridade",
                   t.observacoes AS "Observações"
            FROM tarefas t
            JOIN projetos p ON p.id = t.projeto_id
            JOIN clientes c ON c.id = p.cliente_id
            WHERE TRIM(COALESCE(t.prioridade, '')) IN ('📌 URGENTE', 'URGENTE')
              AND TRIM(COALESCE(t.status, '')) NOT IN ('Concluído', 'Cancelado', 'Não se aplica')
            ORDER BY p.numero DESC, t.ordem, t.id
            """,
            conn,
        )
    return projetos, tarefas


def tela_dashboard():
    cabecalho_pagina("Dashboard")
    projetos, tarefas = carregar_dados_dashboard()

    if projetos.empty:
        st.info("Nenhum projeto cadastrado.")
        return

    st.markdown("#### 🔎 Localizar projeto")
    busca_projeto = st.text_input(
        "Digite o número da proposta ou o nome do cliente",
        placeholder="Ex.: 2026.032 ou YARA",
        label_visibility="collapsed",
        key="dashboard_busca_projeto",
    )

    if busca_projeto.strip():
        termo = busca_projeto.strip()
        encontrados = projetos[
            projetos["Projeto"].astype(str).str.contains(termo, case=False, na=False, regex=False)
            | projetos["Cliente"].astype(str).str.contains(termo, case=False, na=False, regex=False)
        ].copy()
        encontrados = ordenar_projetos_por_numero(encontrados)

        if encontrados.empty:
            st.warning("Nenhum projeto encontrado.")
        else:
            for _, projeto_busca in encontrados.head(10).iterrows():
                st.markdown(
                    f"""<div style="padding:.38rem .55rem;margin:.18rem 0;border-left:4px solid #0B6E4F;
                    background:#FFFFFF;border-radius:5px;">
                    <b>{projeto_busca["Projeto"]} | {projeto_busca["Cliente"]}</b><br>
                    <span style="font-size:.90rem;"><b>Status:</b> {status_visual(projeto_busca.get("Status"))}</span>
                    </div>""",
                    unsafe_allow_html=True,
                )

    hoje = pd.Timestamp(date.today())

    projetos["Data_Prazo_Projeto"] = pd.to_datetime(
        projetos["Prazo"], dayfirst=True, errors="coerce"
    )
    projetos["Data_Conclusao"] = pd.to_datetime(
        projetos["Concluído_em"],
        dayfirst=True,
        errors="coerce",
    )

    encerrados = {"Concluído", "Cancelado", "Não se aplica"}

    # Prazo oficial do projeto: referência para Atrasados e Vencem em 7 dias.
    projetos_abertos_prazo = projetos[
        ~projetos["Status"].fillna("").isin(encerrados)
    ].copy()

    atrasados_projetos = projetos_abertos_prazo[
        projetos_abertos_prazo["Data_Prazo_Projeto"].notna()
        & (projetos_abertos_prazo["Data_Prazo_Projeto"] < hoje)
    ].copy()

    proximos_7_projetos = projetos_abertos_prazo[
        projetos_abertos_prazo["Data_Prazo_Projeto"].notna()
        & (projetos_abertos_prazo["Data_Prazo_Projeto"] >= hoje)
        & (projetos_abertos_prazo["Data_Prazo_Projeto"] <= hoje + pd.Timedelta(days=7))
    ].copy()

    concluidos = projetos[projetos["Status"].fillna("") == "Concluído"].copy()
    paralisados = projetos[projetos["Status"].fillna("") == "Paralisado"].copy()
    pendentes = projetos[projetos["Status"].fillna("") == "Pendente"].copy()
    aguardando = projetos[projetos["Status"].fillna("") == "Aguardando"].copy()
    em_andamento = projetos[projetos["Status"].fillna("") == "Em andamento"].copy()

    ativos = projetos[
        ~projetos["Status"].fillna("").isin(["Concluído", "Cancelado", "Paralisado"])
    ].copy()

    cards = [
        ("📊 Projetos ativos", len(ativos), "ativos"),
        ("🔵 Em andamento", len(em_andamento), "em_andamento"),
        ("🔴 Projetos atrasados", len(atrasados_projetos), "atrasados"),
        ("🟠 Projetos aguardando", len(aguardando), "aguardando"),
        ("🟡 Projetos pendentes", len(pendentes), "pendentes"),
        ("🟣 Projetos paralisados", len(paralisados), "paralisados"),
        ("🟤 Vencem em 7 dias", len(proximos_7_projetos), "vencem_7"),
        ("🟢 Concluídos", len(concluidos), "concluidos"),
    ]

    grupos_cards = [cards[:4], cards[4:]]
    for grupo in grupos_cards:
        cols = st.columns(4)
        for indice, (rotulo, valor, chave) in enumerate(grupo):
            with cols[indice]:
                st.metric(rotulo, valor)
                if st.button("VER PROJETOS", key=f"card_{chave}", width="stretch"):
                    st.session_state["dashboard_card_aberto"] = (
                        None if st.session_state.get("dashboard_card_aberto") == chave else chave
                    )
                    st.rerun()

    card_aberto = st.session_state.get("dashboard_card_aberto")
    conjuntos = {
        "ativos": ("📊 Projetos ativos", ativos, None),
        "em_andamento": ("🔵 Em andamento", em_andamento, "🔵 Em andamento"),
        "atrasados": ("🔴 Projetos atrasados", atrasados_projetos, "🔴 Atrasado"),
        "paralisados": ("🟣 Projetos paralisados", paralisados, "🟣 Paralisado"),
        "aguardando": ("🟠 Projetos aguardando", aguardando, "🟠 Aguardando"),
        "pendentes": ("🟡 Projetos pendentes", pendentes, "🟡 Pendente"),
        "vencem_7": ("🟠 Vencem em 7 dias", proximos_7_projetos, None),
        "concluidos": ("🟢 Concluídos", concluidos, "🟢 Concluído"),
    }

    if card_aberto in conjuntos:
        titulo_card, lista_card, status_forcado = conjuntos[card_aberto]
        st.markdown(f"### {titulo_card}")

        if lista_card.empty:
            st.info("Nenhum projeto nesta categoria.")
        else:
            lista_card = lista_card.drop_duplicates(subset=["Projeto"]).copy()
            lista_card = ordenar_projetos_por_numero(lista_card)
            for inicio in range(0, len(lista_card), 4):
                linha = st.columns(4)
                bloco = lista_card.iloc[inicio:inicio + 4]
                for coluna, (_, p) in zip(linha, bloco.iterrows()):
                    prazo_txt = ""
                    if pd.notna(p.get("Prazo")) and str(p.get("Prazo")).strip():
                        dt_prazo = pd.to_datetime(p.get("Prazo"), dayfirst=True, errors="coerce")
                        prazo_txt = dt_prazo.strftime("%d/%m/%Y") if not pd.isna(dt_prazo) else str(p.get("Prazo"))

                    status_txt = status_forcado or status_visual(p.get("Status"))

                    tarefas_projeto = tarefas[
                        tarefas["Projeto"].astype(str) == str(p["Projeto"])
                    ].copy()
                    urgente = tarefas_projeto.head(7)

                    proximas_tarefas = []
                    for _, tarefa_urgente in urgente.iterrows():
                        nome_tarefa = str(tarefa_urgente.get("Tarefa") or "").strip()
                        if not nome_tarefa:
                            continue
                        data_tarefa = pd.to_datetime(tarefa_urgente.get("Prazo"), dayfirst=True, errors="coerce")
                        data_txt = data_tarefa.strftime("%d/%m/%Y") if not pd.isna(data_tarefa) else ""
                        proximas_tarefas.append((nome_tarefa, data_txt))

                    bloco_proxima = ""
                    if proximas_tarefas:
                        itens_proximas = "<br>".join(
                            f"<strong>{i}. {tarefa}</strong>"
                            + (f' <span style="font-weight:400;color:#6B6250;">— {data_txt}</span>' if data_txt else "")
                            for i, (tarefa, data_txt) in enumerate(proximas_tarefas, start=1)
                        )
                        bloco_proxima = f"""<div style="margin-top:.35rem;padding:.35rem .42rem;
                        background:#FFF4CC;border-left:3px solid #E0A800;border-radius:5px;
                        font-size:.80rem;line-height:1.28;">
                        <b>📌 PRÓXIMAS TAREFAS</b><br>{itens_proximas}</div>"""

                    with coluna:
                        st.markdown(
                            f"""<div style="border:1px solid #D8E7DF;border-radius:10px;
                            padding:.58rem;min-height:128px;background:#FFFFFF;
                            box-shadow:0 2px 8px rgba(11,110,79,.06);">
                            <div style="font-weight:800;color:#0B6E4F;font-size:.98rem;">{p["Projeto"]}</div>
                            <div style="font-weight:700;color:#17211D;margin:.08rem 0 .20rem 0;font-size:.92rem;">{p["Cliente"]}</div>
                            <div style="font-size:.82rem;color:#3B4741;">{p["Serviço"] or ""}</div>
                            <div style="font-size:.80rem;margin-top:.25rem;"><b>Prazo do Projeto:</b> {prazo_txt or "—"}</div>
                            <div style="font-size:.80rem;margin-top:.15rem;">{status_txt}</div>
                            {bloco_proxima}
                            </div>""",
                            unsafe_allow_html=True,
                        )
                        if st.button(
                            "ABRIR PROJETO",
                            key=f"abrir_{card_aberto}_{int(p['id'])}",
                            width="stretch",
                        ):
                            st.session_state["projeto_pendente"] = f'{p["Projeto"]} | {p["Cliente"]}'
                            st.session_state["pagina_pendente"] = "Projetos"
                            st.rerun()

    st.divider()
    st.subheader("Projetos por cliente")

    projetos_cliente = (
        projetos.groupby("Cliente")
        .size()
        .reset_index(name="Projetos")
        .sort_values("Projetos", ascending=False)
    )

    st.dataframe(
        projetos_cliente,
        hide_index=True,
        width="stretch",
        height=220,
        )
