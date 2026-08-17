from pathlib import Path
import streamlit as st

from admin import tela_administracao
from auth import exigir_login, sair, usuario_logado
from clientes import tela_clientes
from dashboard import tela_dashboard
from database import criar_banco, sincronizar_status_projetos
from financeiro import tela_financeiro
from projetos import tela_projetos
from utils import aplicar_estilo_global
from styles import aplicar_estilo


st.set_page_config(
    page_title="GEO ERP 2.2",
    page_icon="🌎",
    layout="wide",
)


@st.cache_resource(show_spinner=False)
def inicializar_sistema():
    """
    Executa somente uma vez por processo do Streamlit.

    Antes, criar_banco() e sincronizar_status_projetos() rodavam
    em TODA reexecução do Streamlit (cada clique, troca de página,
    botão, filtro etc.), causando dezenas de consultas e updates
    no Supabase repetidamente.
    """
    criar_banco()
    sincronizar_status_projetos()
    return True


aplicar_estilo()
inicializar_sistema()
aplicar_estilo_global()


if not exigir_login():
    st.stop()

usuario = usuario_logado()

logo = Path("logo_geotecnysan.png")
if logo.exists():
    _, centro, _ = st.columns([1, 1.25, 1])
    with centro:
        st.image(str(logo), width="stretch")


if "pagina" not in st.session_state:
    st.session_state["pagina"] = "Dashboard"

pagina_pendente = st.session_state.pop("pagina_pendente", None)
if pagina_pendente:
    st.session_state["pagina"] = pagina_pendente

if st.query_params.get("projeto"):
    st.session_state["pagina"] = "Projetos"


st.sidebar.title("GEO ERP 2.2")
st.sidebar.caption(f'Usuário: {usuario["nome"]}')

paginas = ["Dashboard", "Clientes / Propostas", "Projetos", "Financeiro"]
if usuario["perfil"] == "Administrador":
    paginas.append("Administração")

pagina = st.sidebar.radio("Menu", paginas, key="pagina")

if st.sidebar.button("SAIR", width="stretch"):
    sair()


if pagina == "Dashboard":
    tela_dashboard()
elif pagina == "Clientes / Propostas":
    tela_clientes()
elif pagina == "Projetos":
    tela_projetos()
elif pagina == "Financeiro":
    tela_financeiro()
elif pagina == "Administração":
    tela_administracao()
