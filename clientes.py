from datetime import date, datetime
import calendar
import pandas as pd
import streamlit as st
from database import conectar
from utils import cabecalho_pagina, ETAPAS_TAREFAS_PADRAO


t.markdown('''
    <style>
        /* Alinha os textos e botões para a esquerda, forçando múltiplas linhas */
        div[data-testid="metric-container"] {
            text-align: left !important;
        }
        div.stButton > button {
            width: 100% !important;
            justify-content: flex-start !important; /* Força o alinhamento flexível */
            padding-left: 15px !important; /* Dá um leve respiro na margem */
        }
        div.stButton > button * {
            text-align: left !important; /* Garante que todas as linhas de texto fiquem à esquerda */
        }
        div[data-testid="stMarkdownContainer"] p {
            text-align: left !important;
        }
    </style>
''', unsafe_allow_html=True)


def listar_clientes():
    with conectar() as conn:
        return pd.read_sql_query(
            """SELECT id, numero_proposta AS Proposta, nome AS Cliente,
               cnpj AS CNPJ, contato AS Contato, telefone AS Telefone, email AS Email,
               endereco AS Endereço, observacoes AS Observações,
               servico_proposta AS Serviço, valor_proposta AS Valor,
               data_proposta AS Data, status_proposta AS Status_Proposta,
               forma_pagamento AS Forma_Pagamento, numero_parcelas AS Parcelas,
               primeiro_vencimento AS Primeiro_Vencimento,
               status_faturamento AS Status_Faturamento
               FROM clientes
               ORDER BY numero_proposta DESC, nome""",
            conn,
        )


def proxima_proposta():
    """Gera automaticamente o próximo número sequencial do ano atual."""
    from datetime import date
    ano = date.today().year
    with conectar() as conn:
        linhas = conn.execute(
            "SELECT numero_proposta FROM clientes WHERE numero_proposta IS NOT NULL"
        ).fetchall()
    maior = 0
    for linha in linhas:
        valor = str(linha[0] or "").strip()
        if valor.startswith(f"{ano}."):
            try:
                maior = max(maior, int(valor.split(".", 1)[1]))
            except (ValueError, IndexError):
                pass
    return f"{ano}.{maior + 1:03d}"


def cadastrar_cliente(proposta,nome,cnpj,contato,telefone,email,endereco,observacoes,
                      servico,valor,data_proposta,status_proposta,
                      forma_pagamento,numero_parcelas,primeiro_vencimento,status_faturamento):
    with conectar() as conn:
        conn.execute(
            """INSERT INTO clientes(
                numero_proposta,nome,cnpj,contato,telefone,email,endereco,observacoes,
                servico_proposta,valor_proposta,data_proposta,status_proposta,
                forma_pagamento,numero_parcelas,primeiro_vencimento,status_faturamento
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                proposta.strip(), nome.strip().upper(), cnpj.strip(), contato.strip(),
                telefone.strip(), email.strip(), endereco.strip(), observacoes.strip(),
                servico.strip(), float(valor or 0), data_proposta, status_proposta,
                forma_pagamento.strip(), int(numero_parcelas or 1),
                primeiro_vencimento, status_faturamento,
            )
        )
        conn.commit()


def alterar_cliente(cid,proposta,nome,cnpj,contato,telefone,email,endereco,observacoes,
                    servico,valor,data_proposta,status_proposta,
                    forma_pagamento,numero_parcelas,primeiro_vencimento,status_faturamento):
    with conectar() as conn:
        conn.execute(
            """UPDATE clientes SET numero_proposta=?,nome=?,cnpj=?,contato=?,telefone=?,email=?,
               endereco=?,observacoes=?,servico_proposta=?,valor_proposta=?,data_proposta=?,
               status_proposta=?,forma_pagamento=?,numero_parcelas=?,primeiro_vencimento=?,
               status_faturamento=? WHERE id=?""",
            (
                proposta.strip(), nome.strip().upper(), cnpj.strip(), contato.strip(),
                telefone.strip(), email.strip(), endereco.strip(), observacoes.strip(),
                servico.strip(), float(valor or 0), data_proposta, status_proposta,
                forma_pagamento.strip(), int(numero_parcelas or 1),
                primeiro_vencimento, status_faturamento, int(cid),
            )
        )
        conn.commit()


def _somar_mes(data_base, meses):
    ano = data_base.year + (data_base.month - 1 + meses) // 12
    mes = (data_base.month - 1 + meses) % 12 + 1
    dia = min(data_base.day, calendar.monthrange(ano, mes)[1])
    return data_base.replace(year=ano, month=mes, day=dia)


def gerar_parcelas_faturamento(cliente_id, valor_total, qtd_parcelas, primeiro_vencimento, status="Pendente"):
    """Cria/ajusta parcelas sem vincular o status delas ao status geral do faturamento."""
    if not primeiro_vencimento:
        return
    qtd = max(1, int(qtd_parcelas or 1))
    total = float(valor_total or 0)
    base = total / qtd

    with conectar() as conn:
        existentes = {
            int(r["parcela"]): r
            for r in conn.execute(
                "SELECT id, parcela, status FROM faturamento_receber WHERE cliente_id=?",
                (int(cliente_id),)
            ).fetchall()
        }

        acumulado = 0.0
        for parcela in range(1, qtd + 1):
            valor_parcela = round(base, 2)
            if parcela == qtd:
                valor_parcela = round(total - acumulado, 2)
            acumulado += valor_parcela
            venc = _somar_mes(primeiro_vencimento, parcela - 1).strftime("%d/%m/%Y")

            if parcela in existentes:
                conn.execute(
                    "UPDATE faturamento_receber SET valor=?, vencimento=? WHERE id=?",
                    (valor_parcela, venc, int(existentes[parcela]["id"]))
                )
            else:
                conn.execute(
                    "INSERT INTO faturamento_receber(cliente_id,parcela,valor,vencimento,status) "
                    "VALUES(?,?,?,?,?)",
                    (int(cliente_id), parcela, valor_parcela, venc, "Pendente")
                )

        conn.execute(
            "DELETE FROM faturamento_receber WHERE cliente_id=? AND parcela>?",
            (int(cliente_id), qtd)
        )
        conn.commit()


def atualizar_status_parcela(cliente_id, parcela, status):
    with conectar() as conn:
        conn.execute(
            "UPDATE faturamento_receber SET status=? WHERE cliente_id=? AND parcela=?",
            (status, int(cliente_id), int(parcela))
        )
        conn.commit()


def listar_parcelas(cliente_id):
    with conectar() as conn:
        return pd.read_sql_query(
            "SELECT parcela AS Parcela, valor AS Valor, vencimento AS Vencimento, status AS Status "
            "FROM faturamento_receber WHERE cliente_id=? ORDER BY parcela",
            conn, params=(int(cliente_id),)
        )


def criar_projeto_da_proposta(cliente_id):
    with conectar() as conn:
        c = conn.execute(
            "SELECT numero_proposta, servico_proposta, valor_proposta FROM clientes WHERE id=?",
            (int(cliente_id),)
        ).fetchone()
        if not c:
            return False, "Cadastro não encontrado."
        numero = str(c["numero_proposta"] or "").strip()
        servico = str(c["servico_proposta"] or "").strip()
        if not numero or not servico:
            return False, "Informe número da proposta e serviço antes de criar o projeto."
        if conn.execute("SELECT 1 FROM projetos WHERE numero=?", (numero,)).fetchone():
            return False, "Já existe um projeto com este número."

        cur = conn.execute(
            "INSERT INTO projetos(numero,cliente_id,servico,valor,status,atualizado_em) VALUES(?,?,?,?,?,?)",
            (numero, int(cliente_id), servico, float(c["valor_proposta"] or 0), "Pendente",
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        projeto_id = cur.lastrowid
        ordem = 1
        for etapa, lista in ETAPAS_TAREFAS_PADRAO.items():
            for tarefa in lista:
                if tarefa == "Outra tarefa":
                    continue
                conn.execute(
                    "INSERT INTO tarefas(projeto_id,etapa,tarefa,prioridade,status,nao_se_aplica,ordem) "
                    "VALUES(?,?,?,'Alta','Pendente',0,?)",
                    (projeto_id, etapa, tarefa, ordem),
                )
                ordem += 1
        conn.commit()
    return True, "Projeto criado com sucesso."


def cliente_tem_projetos(cid):
    with conectar() as conn:
        return conn.execute("SELECT COUNT(*) FROM projetos WHERE cliente_id=?", (int(cid),)).fetchone()[0] > 0

def excluir_cliente(cid):
    with conectar() as conn:
        conn.execute("DELETE FROM clientes WHERE id=?", (int(cid),))
        conn.commit()

def tela_clientes():
    cabecalho_pagina("Clientes / Propostas")

    with st.expander("➕ Nova proposta / cliente", expanded=False):
        with st.form("novo_cliente", clear_on_submit=True):
            a,b = st.columns(2)
            with a:
                proposta = st.text_input("Nº da Proposta *", value=proxima_proposta(), disabled=True)
                nome = st.text_input("Cliente *")
                servico = st.text_input("Serviço *")
                valor = st.number_input("Valor da Proposta (R$)", min_value=0.0, step=100.0, format="%.2f")
                data_prop = st.date_input("Data da Proposta", value=date.today(), format="DD/MM/YYYY")
                status_prop = st.selectbox("Status da Proposta", ["Elaboração","Enviada","Aprovada","Recusada"])
                cnpj = st.text_input("CNPJ")
                contato = st.text_input("Contato")
            with b:
                telefone = st.text_input("Telefone")
                email = st.text_input("E-mail")
                endereco = st.text_input("Endereço")
                forma_pag = st.text_input("Forma de Pagamento", placeholder="Ex.: 30/60/90 dias")
                parcelas = st.number_input("Nº de Parcelas", min_value=1, max_value=60, value=1, step=1)
                primeiro_venc = st.date_input("1º Vencimento", value=None, format="DD/MM/YYYY")
                status_fat = st.selectbox("Status do Faturamento", ["Pendente","Faturado","Recebido","Vencido"])
                obs = st.text_area("Observações")
            salvar = st.form_submit_button("SALVAR CLIENTE / PROPOSTA", type="primary", width="stretch")

        if salvar:
            if not proposta.strip() or not nome.strip() or not servico.strip():
                st.error("Preencha Nº da Proposta, Cliente e Serviço.")
            else:
                cadastrar_cliente(
                    proposta,nome,cnpj,contato,telefone,email,endereco,obs,
                    servico,valor,data_prop.strftime("%d/%m/%Y"),status_prop,
                    forma_pag,parcelas,
                    primeiro_venc.strftime("%d/%m/%Y") if primeiro_venc else None,
                    status_fat
                )
                with conectar() as conn:
                    cid_novo = conn.execute(
                        "SELECT id FROM clientes WHERE numero_proposta=? ORDER BY id DESC LIMIT 1",
                        (proposta.strip(),)
                    ).fetchone()["id"]
                if primeiro_venc:
                    gerar_parcelas_faturamento(cid_novo, valor, parcelas, primeiro_venc, status_fat)
                st.success(f"Cliente / proposta {proposta} cadastrado com sucesso.")
                st.rerun()

    clientes = listar_clientes()
    if clientes.empty:
        st.info("Nenhum cliente cadastrado.")
        return

    # CSS somente para os botões da listagem de propostas:
    # alinhados à esquerda e em negrito.
    st.markdown(
        """
        <style>
        div[data-testid="stButton"]:has(button[kind="secondary"]) > button {
            text-align: left !important;
        }
        div[data-testid="stButton"] > button {
            justify-content: flex-start !important;
        }
        div[data-testid="stButton"] > button > div,
        div[data-testid="stButton"] > button p {
            width: 100% !important;
            text-align: left !important;
        }
        div[data-testid="stButton"] > button p {
            font-weight: 700 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    proposta_aberta_id = st.session_state.get("proposta_aberta_id")

    # ---------------------------------------------------------
    # LISTA DE PROPOSTAS
    # ---------------------------------------------------------
    if proposta_aberta_id is None:
        st.markdown("### Propostas")
        busca = st.text_input(
            "Pesquisar proposta",
            placeholder="Digite nº da proposta, cliente, serviço, CNPJ ou contato",
            key="busca_propostas",
        )

        dados = clientes.copy()
        if busca.strip():
            x = busca.strip().lower()
            dados = dados[
                dados["Proposta"].fillna("").astype(str).str.lower().str.contains(x) |
                dados["Cliente"].fillna("").astype(str).str.lower().str.contains(x) |
                dados["CNPJ"].fillna("").astype(str).str.lower().str.contains(x) |
                dados["Contato"].fillna("").astype(str).str.lower().str.contains(x) |
                dados["Serviço"].fillna("").astype(str).str.lower().str.contains(x)
            ]

        # Ordenação decrescente por número de proposta.
        partes = dados["Proposta"].fillna("").astype(str).str.extract(r"(\d{4})\D*(\d+)")
        dados["_ano"] = pd.to_numeric(partes[0], errors="coerce")
        dados["_num"] = pd.to_numeric(partes[1], errors="coerce")
        dados = dados.sort_values(
            ["_ano", "_num", "Cliente"],
            ascending=[False, False, True],
            na_position="last",
        )

        st.caption("Clique uma vez na proposta para abrir a ficha completa.")

        for _, item in dados.iterrows():
            cid_item = int(item["id"])

            proposta_val = item["Proposta"]
            proposta_txt = (
                "SEM PROPOSTA"
                if pd.isna(proposta_val) or str(proposta_val).strip().lower() in {"", "nan", "none"}
                else str(proposta_val).strip()
            )

            cliente_txt = str(item["Cliente"] or "").strip()

            servico_val = item["Serviço"]
            servico_txt = (
                ""
                if pd.isna(servico_val) or str(servico_val).strip().lower() in {"", "nan", "none"}
                else str(servico_val).strip()
            )

            status_val = item["Status_Proposta"]
            status_txt = (
                "Elaboração"
                if pd.isna(status_val) or str(status_val).strip().lower() in {"", "nan", "none"}
                else str(status_val).strip()
            )

            rotulo = f"{proposta_txt} | {cliente_txt}"
            if servico_txt:
                rotulo += f" — {servico_txt}"
            rotulo += f" — {status_txt}"

            if st.button(
                rotulo,
                key=f"abrir_proposta_{cid_item}",
                width="stretch",
            ):
                st.session_state["proposta_aberta_id"] = cid_item
                st.rerun()

        with st.expander("📋 Tabela geral de propostas", expanded=False):
            st.dataframe(
                dados[
                    [
                        "Proposta","Cliente","Serviço","Valor","Data",
                        "Status_Proposta","Forma_Pagamento","Parcelas",
                        "Primeiro_Vencimento","Status_Faturamento"
                    ]
                ],
                width="stretch",
                hide_index=True,
            )
        return

    # ---------------------------------------------------------
    # FICHA COMPLETA DA PROPOSTA
    # ---------------------------------------------------------
    registro = clientes[clientes["id"].astype(int) == int(proposta_aberta_id)]
    if registro.empty:
        st.session_state.pop("proposta_aberta_id", None)
        st.rerun()

    r = registro.iloc[0]
    cid = int(r["id"])

    if st.button("← VOLTAR PARA PROPOSTAS", key=f"voltar_propostas_{cid}"):
        st.session_state.pop("proposta_aberta_id", None)
        st.rerun()

    proposta_titulo = (
        "SEM PROPOSTA"
        if pd.isna(r["Proposta"]) or str(r["Proposta"]).strip().lower() in {"", "nan", "none"}
        else str(r["Proposta"]).strip()
    )
    cliente_titulo = str(r["Cliente"] or "").strip()

    st.markdown(f"## {proposta_titulo} | {cliente_titulo}")
    st.caption("Ficha completa da proposta — consulte e altere tudo no mesmo lugar.")

    with st.form(f"ficha_proposta_{cid}"):
        a, b = st.columns(2)

        with a:
            p = st.text_input("Nº da Proposta *", value=proposta_titulo if proposta_titulo != "SEM PROPOSTA" else "")
            n = st.text_input("Cliente *", value=cliente_titulo)

            servico_atual = "" if pd.isna(r["Serviço"]) else str(r["Serviço"] or "")
            s = st.text_input("Serviço *", value=servico_atual)

            valor_atual = 0.0 if pd.isna(r["Valor"]) else float(r["Valor"] or 0)
            v = st.number_input(
                "Valor da Proposta (R$)",
                min_value=0.0,
                value=valor_atual,
                step=100.0,
                format="%.2f",
            )

            d = pd.to_datetime(r["Data"], dayfirst=True, errors="coerce")
            dp = st.date_input(
                "Data da Proposta",
                value=d.date() if not pd.isna(d) else date.today(),
                format="DD/MM/YYYY",
            )

            status_opts = ["Elaboração", "Enviada", "Aprovada", "Recusada"]
            status_atual = "Elaboração" if pd.isna(r["Status_Proposta"]) else str(r["Status_Proposta"] or "Elaboração")
            sp = st.selectbox(
                "Status da Proposta",
                status_opts,
                index=status_opts.index(status_atual) if status_atual in status_opts else 0,
            )

            c = st.text_input("CNPJ", value="" if pd.isna(r["CNPJ"]) else str(r["CNPJ"] or ""))
            co = st.text_input("Contato", value="" if pd.isna(r["Contato"]) else str(r["Contato"] or ""))

        with b:
            t = st.text_input("Telefone", value="" if pd.isna(r["Telefone"]) else str(r["Telefone"] or ""))
            e = st.text_input("E-mail", value="" if pd.isna(r["Email"]) else str(r["Email"] or ""))
            en = st.text_input("Endereço", value="" if pd.isna(r["Endereço"]) else str(r["Endereço"] or ""))

            fp = st.text_input(
                "Forma de Pagamento",
                value="" if pd.isna(r["Forma_Pagamento"]) else str(r["Forma_Pagamento"] or ""),
                placeholder="Ex.: 30/60/90 dias",
            )

            parc_atual = 1 if pd.isna(r["Parcelas"]) else int(r["Parcelas"] or 1)
            parc = st.number_input(
                "Nº de Parcelas",
                min_value=1,
                max_value=60,
                value=parc_atual,
                step=1,
            )

            pv = pd.to_datetime(r["Primeiro_Vencimento"], dayfirst=True, errors="coerce")
            pvv = st.date_input(
                "1º Vencimento",
                value=pv.date() if not pd.isna(pv) else None,
                format="DD/MM/YYYY",
            )

            sf_opts = ["Pendente", "Faturado", "Recebido", "Vencido"]
            sf_atual = "Pendente" if pd.isna(r["Status_Faturamento"]) else str(r["Status_Faturamento"] or "Pendente")
            sf = st.selectbox(
                "Status do Faturamento",
                sf_opts,
                index=sf_opts.index(sf_atual) if sf_atual in sf_opts else 0,
            )

            o = st.text_area(
                "Observações",
                value="" if pd.isna(r["Observações"]) else str(r["Observações"] or ""),
                height=120,
            )

        salvar = st.form_submit_button(
            "💾 SALVAR ALTERAÇÕES",
            type="primary",
            width="stretch",
        )

    if salvar:
        if not p.strip() or not n.strip() or not s.strip():
            st.error("Preencha Nº da Proposta, Cliente e Serviço.")
        else:
            alterar_cliente(
                cid, p, n, c, co, t, e, en, o, s, v,
                dp.strftime("%d/%m/%Y"), sp,
                fp, parc,
                pvv.strftime("%d/%m/%Y") if pvv else None,
                sf,
            )
            if pvv:
                gerar_parcelas_faturamento(cid, v, parc, pvv, sf)

            st.success("Proposta atualizada com sucesso.")
            st.rerun()

    st.markdown("### Faturamento")
    st.caption("O Status do Faturamento acima é geral da proposta. O status abaixo é individual de cada parcela.")
    parcelas_df = listar_parcelas(cid)
    if parcelas_df.empty:
        st.info("Nenhuma parcela gerada. Informe o 1º vencimento e salve a proposta.")
    else:
        parcelas_editadas = st.data_editor(
            parcelas_df,
            hide_index=True,
            width="stretch",
            disabled=["Parcela", "Valor", "Vencimento"],
            column_config={
                "Parcela": st.column_config.NumberColumn("Parcela", format="%d"),
                "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                "Vencimento": st.column_config.TextColumn("Vencimento"),
                "Status": st.column_config.SelectboxColumn(
                    "Status da Parcela",
                    options=["Pendente", "Recebido", "Vencido", "Cancelado"],
                    required=True,
                ),
            },
            key=f"parcelas_editor_{cid}",
        )
        if st.button("💾 SALVAR STATUS DAS PARCELAS", key=f"salvar_parcelas_{cid}", width="stretch"):
            for _, linha in parcelas_editadas.iterrows():
                atualizar_status_parcela(cid, int(linha["Parcela"]), str(linha["Status"]))
            st.success("Status das parcelas atualizado com sucesso.")
            st.rerun()

    status_atual_registro = "" if pd.isna(r["Status_Proposta"]) else str(r["Status_Proposta"] or "")
    if status_atual_registro == "Aprovada":
        if st.button(
            "✅ CRIAR PROJETO A PARTIR DA PROPOSTA",
            key=f"criar_proj_{cid}",
            width="stretch",
        ):
            sucesso, mensagem = criar_projeto_da_proposta(cid)
            if sucesso:
                st.success(mensagem)
                st.info("Projeto criado com o mesmo número da proposta. Ele já está disponível na tela Projetos.")
            else:
                st.warning(mensagem)

    with st.expander("🗑️ Excluir esta proposta / cliente", expanded=False):
        if cliente_tem_projetos(cid):
            st.warning(
                "Este cadastro possui projeto(s) vinculado(s). "
                "Exclua primeiro os projetos vinculados."
            )
        else:
            confirmar = st.checkbox(
                "Confirmo que desejo excluir definitivamente este cadastro.",
                key=f"confirmar_exclusao_ficha_{cid}",
            )
            if st.button(
                "EXCLUIR DEFINITIVAMENTE",
                disabled=not confirmar,
                width="stretch",
                key=f"excluir_ficha_{cid}",
            ):
                excluir_cliente(cid)
                st.session_state.pop("proposta_aberta_id", None)
                st.success("Cadastro excluído com sucesso.")
                st.rerun()

