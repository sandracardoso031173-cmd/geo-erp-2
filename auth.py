from pathlib import Path
import streamlit as st
from database import autenticar_usuario

LOGO = Path("logo_geotecnysan.png")

def usuario_logado():
    return st.session_state.get("usuario_logado")

def exigir_login():
    if usuario_logado():
        return True
    _, centro, _ = st.columns([1, 1.1, 1])
    with centro:
        if LOGO.exists():
            st.image(str(LOGO), width="stretch")
        st.markdown(
            "<h2 style='text-align:center;color:#0B6E4F;margin-bottom:.15rem;'>GEO ERP 2.2</h2>"
            "<p style='text-align:center;color:#52645B;margin-top:0;'>Gestão de Projetos Ambientais</p>",
            unsafe_allow_html=True,
        )
        with st.form("login"):
            usuario = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("ENTRAR", type="primary", width="stretch")
        if entrar:
            u = autenticar_usuario(usuario, senha)
            if u:
                st.session_state["usuario_logado"] = u
                st.session_state["pagina"] = "Dashboard"
                st.rerun()
            st.error("Usuário ou senha inválidos.")
    return False

def sair():
    st.session_state.pop("usuario_logado", None)
    st.rerun()
