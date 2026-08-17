from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

NOME_EMPRESA = "GEOTECNYSAN CONSULTORIA AMBIENTAL"

STATUS_TAREFA = [
    "Pendente", "Em andamento", "Aguardando", "Paralisado",
    "Concluído", "Não se aplica", "Cancelado",
]
PRIORIDADES = ["Baixa", "Média", "Alta"]

# Catálogo limpo, baseado nas tarefas-padrão da planilha de importação.
ETAPAS_TAREFAS_PADRAO = {
    "COMERCIAL": [
        "Proposta Elaborada", "Proposta Enviada", "Proposta Aprovada", "Faturamento",
    ],
    "CAMPO": [
        "Agendamento de Campo", "Mobilização da Equipe", "Preparar Documentação de Campo",
        "Locação dos Pontos", "Sondagem", "Desenvolvimento dos Poços",
        "Instalação de Poços", "Medição do Nível d'Água", "Amostragem",
        "Levantamento Fotográfico", "Desmobilização",
    ],
    "LABORATÓRIO": [
        "Solicitação de Kit", "Amostras Enviadas", "Laudos Recebidos", "Validação dos Resultados",
    ],
    "DOCUMENTAÇÃO": [
        "Preparar Documentação", "ART", "Declaração", "Manifesto", "Organização de Documentos",
    ],
    "RELATÓRIO": [
        "Elaborar Relatório de Ensaio", "Elaborar Relatório Técnico", "Revisão Final",
    ],
    "CETESB": [
        "Comunique-se", "Protocolo", "Aguardando CETESB", "Exigência Técnica",
        "Manifestação", "Processo Encerrado",
    ],
    "FINANCEIRO": ["Emissão de Boletos"],
    "ESTUDOS": ["Estudo Hidrogeológico"],
    "GERAL": ["Reunião", "Outra tarefa"],
}

RESPONSAVEIS = ["Sandra", "Adalto", "Laboratório", "Equipe de Campo", "Terceiros"]


def aplicar_estilo_global() -> None:
    st.markdown(
        """
        <style>
            .block-container {padding-top:1.25rem; padding-bottom:2rem; max-width:1500px;}
            h1 {margin-top:0 !important;}
            div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {font-size:0.88rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def cabecalho_pagina(titulo: str) -> None:
    st.markdown(
        f"""
        <div style="font-size:0.82rem;font-weight:700;letter-spacing:0.08em;color:#52606d;margin-bottom:0.1rem;">
            {NOME_EMPRESA}
        </div>
        <h1 style="margin:0 0 1rem 0;font-size:2.2rem;">{titulo}</h1>
        """,
        unsafe_allow_html=True,
    )


def converter_data(valor):
    if valor is None or valor == "" or pd.isna(valor):
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    convertido = pd.to_datetime(valor, dayfirst=True, errors="coerce")
    return None if pd.isna(convertido) else convertido.date()


def data_para_banco(valor) -> str | None:
    data = converter_data(valor)
    return data.strftime("%d/%m/%Y") if data else None
