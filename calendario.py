import streamlit as st
import pandas as pd
from database import conectar

def tela_calendario():
    st.title("📅 Calendário")

    conn = conectar()

    try:
        tarefas = pd.read_sql("""
            SELECT
                p.numero AS Projeto,
                p.cliente AS Cliente,
                t.tarefa AS Tarefa,
                t.data AS Data,
                t.status AS Status,
                t.responsavel AS Responsável
            FROM tarefas t
            JOIN projetos p ON p.id = t.projeto_id
            WHERE t.data IS NOT NULL
            ORDER BY t.data
        """, conn)

        if tarefas.empty:
            st.info("Nenhuma tarefa com data cadastrada.")
            return

        st.dataframe(
            tarefas,
            use_container_width=True,
            hide_index=True
        )

    finally:
        conn.close()