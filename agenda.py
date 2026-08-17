from datetime import date
import pandas as pd
import streamlit as st
from database import conectar
from utils import cabecalho_pagina


def carregar_tarefas_abertas():
    with conectar() as conn:
        dados = pd.read_sql_query(
            """
            SELECT p.id AS Projeto_ID, p.numero AS Projeto, c.nome AS Cliente,
                   p.servico AS Serviço, t.id AS Tarefa_ID, t.prazo AS Prazo
            FROM projetos p
            JOIN clientes c ON c.id = p.cliente_id
            JOIN tarefas t ON t.projeto_id = p.id
            WHERE COALESCE(t.status,'') NOT IN ('Concluído','Cancelado','Não se aplica')
            ORDER BY p.numero DESC, t.id
            """, conn,
        )
    if not dados.empty:
        dados["Data_Real"] = pd.to_datetime(dados["Prazo"], dayfirst=True, errors="coerce")
    return dados


def resumir(dados):
    if dados.empty:
        return pd.DataFrame()
    resumo = (dados.groupby(["Projeto_ID","Projeto","Cliente","Serviço"], as_index=False)
              .agg(Tarefas_Abertas=("Tarefa_ID","count"), Data_Real=("Data_Real","min")))
    resumo["Próxima_Data"] = resumo["Data_Real"].dt.strftime("%d/%m/%Y")
    return resumo.sort_values(["Data_Real","Projeto"], ascending=[True,False], na_position="last")


def tela_agenda():
    cabecalho_pagina("Agenda")
    tarefas = carregar_tarefas_abertas()
    if tarefas.empty:
        st.info("Nenhum projeto com tarefas abertas.")
        return

    hoje = pd.Timestamp(date.today())
    col1, col2 = st.columns(2)
    with col1:
        periodo = st.selectbox("Período", ["Todos","Atrasados","Hoje","Próximos 7 dias","Próximos 30 dias","Sem data"])
    with col2:
        opcoes = ["Todos"] + tarefas[["Projeto","Cliente"]].drop_duplicates().apply(
            lambda l: f'{l["Projeto"]} | {l["Cliente"]}', axis=1).tolist()
        filtro_projeto = st.selectbox("Projeto", opcoes)

    data_especifica = st.date_input("Consultar data específica", value=None, format="DD/MM/YYYY")
    dados = tarefas.copy()

    if filtro_projeto != "Todos":
        numero = filtro_projeto.split("|")[0].strip()
        dados = dados[dados["Projeto"].astype(str) == numero]

    # O filtro é aplicado nas tarefas antes do resumo. Assim, um projeto com
    # uma tarefa vencida e outra nos próximos 30 dias continua aparecendo corretamente.
    if data_especifica:
        dados = dados[dados["Data_Real"] == pd.Timestamp(data_especifica)]
    elif periodo == "Atrasados":
        dados = dados[dados["Data_Real"].notna() & (dados["Data_Real"] < hoje)]
    elif periodo == "Hoje":
        dados = dados[dados["Data_Real"] == hoje]
    elif periodo == "Próximos 7 dias":
        dados = dados[dados["Data_Real"].notna() & (dados["Data_Real"] >= hoje) & (dados["Data_Real"] <= hoje + pd.Timedelta(days=7))]
    elif periodo == "Próximos 30 dias":
        dados = dados[dados["Data_Real"].notna() & (dados["Data_Real"] >= hoje) & (dados["Data_Real"] <= hoje + pd.Timedelta(days=30))]
    elif periodo == "Sem data":
        dados = dados[dados["Data_Real"].isna()]

    agenda = resumir(dados)
    st.caption(f"{len(agenda)} projeto(s) encontrado(s)")
    if agenda.empty:
        st.warning("Nenhum projeto encontrado para os filtros selecionados.")
        return

    exibir = agenda[["Projeto","Cliente","Serviço","Tarefas_Abertas","Próxima_Data"]].rename(
        columns={"Tarefas_Abertas":"Tarefas abertas","Próxima_Data":"Próxima data"})
    exibir["Próxima data"] = exibir["Próxima data"].fillna("Sem data")
    st.dataframe(exibir, hide_index=True, width="stretch", height=520)
