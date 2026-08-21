import streamlit as st

def aplicar_estilo():
    st.markdown("""
<style>

/* PLANO B: Força Bruta Absoluta para Streamlit 1.61+ */
        .stButton > button {
            display: block !important;
            width: 100% !important;
            text-align: left !important;
            padding-left: 15px !important;
        }
        
        .stButton > button * {
            text-align: left !important;
            display: block !important;
        }
        
/* APP */
.stApp{
    background:#f4f6f9;
}

/* SIDEBAR */
section[data-testid="stSidebar"]{
    background:#0B6E4F;
}

section[data-testid="stSidebar"] *{
    color:white !important;
}

/* TÍTULOS */
h1,h2,h3{
    color:#0B6E4F;
    font-weight:700;
}

/* BOTÕES */
.stButton>button{
    background:#CFE8D8;
    color:#17211D;
    border:1px solid #B8D8C6;
    border-radius:8px;
    font-weight:600;
    height:42px;
}

.stButton>button:hover{
    background:#BFDCCB;
    color:#101713;
    border:1px solid #A9CCB8;
}

/* INPUTS */

.stTextInput input,
.stSelectbox,
.stDateInput{
    border-radius:8px;
}

/* MÉTRICAS */

[data-testid="stMetric"]{
    background:white;
    border-radius:12px;
    padding:15px;
    box-shadow:0 2px 8px rgba(0,0,0,.08);
}
/* TABELAS */

thead tr{
    background:#0B6E4F !important;
    color:white !important;
    font-weight:700;
}

tbody tr:nth-child(even){
    background:#F4F8F6 !important;
}

tbody tr:hover{
    background:#E7F4EC !important;
}
/* DATAFRAME */

[data-testid="stDataFrame"]{
    border-radius:10px;
}


/* CONTRASTE E IDENTIDADE PREMIUM */
.stButton>button p,
.stButton>button span{
    color:#17211D !important;
}

button[kind="primary"],
[data-testid="stFormSubmitButton"] button{
    background:#168A5B !important;
    color:white !important;
    border:1px solid #168A5B !important;
    font-weight:700 !important;
}

button[kind="primary"]:hover,
[data-testid="stFormSubmitButton"] button:hover{
    background:#0F7650 !important;
    color:white !important;
    border-color:#0F7650 !important;
}

/* LOGIN */
[data-testid="stForm"]{
    background:#FFFFFF;
    border:1px solid #D8E7DF;
    border-radius:14px;
    padding:1.25rem;
    box-shadow:0 6px 22px rgba(11,110,79,.08);
}

[data-testid="stTextInput"] input{
    color:#171A18 !important;
}

[data-testid="stTextInput"] label,
[data-testid="stTextInput"] label p{
    color:#26312C !important;
    font-weight:600 !important;
}

</style>
""",unsafe_allow_html=True)
