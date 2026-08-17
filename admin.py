import pandas as pd
import streamlit as st
from database import conectar, gerar_hash_senha
from utils import cabecalho_pagina

def carregar_totais():
    with conectar() as conn:
        return (conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM projetos").fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM tarefas").fetchone()[0])

def carregar_resumo():
    with conectar() as conn:
        return pd.read_sql_query(
            """SELECT p.numero AS Projeto, c.nome AS Cliente, p.servico AS Serviço,
                      p.status AS Status, p.concluido_em AS Concluído_em
               FROM projetos p JOIN clientes c ON c.id=p.cliente_id ORDER BY p.numero DESC""", conn)

def listar_usuarios():
    with conectar() as conn:
        return pd.read_sql_query(
            """SELECT id, nome AS Nome, usuario AS Usuário, perfil AS Perfil,
                      CASE WHEN ativo=1 THEN 'Ativo' ELSE 'Inativo' END AS Status
               FROM usuarios ORDER BY nome""", conn)

def tela_administracao():
    cabecalho_pagina("Administração")
    clientes, projetos, tarefas = carregar_totais()
    c1,c2,c3 = st.columns(3)
    c1.metric("Clientes", clientes); c2.metric("Projetos", projetos); c3.metric("Tarefas", tarefas)

    st.divider(); st.subheader("Usuários")
    usuarios = listar_usuarios()
    st.dataframe(usuarios[["Nome","Usuário","Perfil","Status"]], hide_index=True, width="stretch")

    with st.expander("➕ Novo usuário"):
        nome = st.text_input("Nome")
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha inicial", type="password")
        perfil = st.selectbox("Perfil", ["Usuário","Administrador"])
        if st.button("CADASTRAR USUÁRIO", type="primary", width="stretch"):
            if not nome.strip() or not usuario.strip() or len(senha) < 6:
                st.error("Preencha nome, usuário e senha com pelo menos 6 caracteres.")
            else:
                try:
                    with conectar() as conn:
                        conn.execute("INSERT INTO usuarios(nome,usuario,senha_hash,perfil,ativo) VALUES(?,?,?,?,1)",
                                     (nome.strip(), usuario.strip(), gerar_hash_senha(senha), perfil))
                        conn.commit()
                    st.success("Usuário cadastrado."); st.rerun()
                except Exception:
                    st.error("Este usuário já existe.")

    if not usuarios.empty:
        st.divider(); st.subheader("Alterar senha")
        opcoes = {f'{r["Nome"]} | {r["Usuário"]}': int(r["id"]) for _,r in usuarios.iterrows()}
        escolhido = st.selectbox("Usuário", list(opcoes))
        nova = st.text_input("Nova senha", type="password")
        if st.button("ALTERAR SENHA", width="stretch"):
            if len(nova) < 6:
                st.error("A senha deve ter pelo menos 6 caracteres.")
            else:
                with conectar() as conn:
                    conn.execute("UPDATE usuarios SET senha_hash=? WHERE id=?",
                                 (gerar_hash_senha(nova), opcoes[escolhido]))
                    conn.commit()
                st.success("Senha alterada.")

    st.divider(); st.subheader("Resumo dos projetos")
    resumo = carregar_resumo(); resumo["Concluído_em"] = resumo["Concluído_em"].fillna("—")
    st.dataframe(resumo, hide_index=True, width="stretch", height=480)
