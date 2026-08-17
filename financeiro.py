from __future__ import annotations

from datetime import date, datetime
import pandas as pd
import streamlit as st

from database import conectar
from utils import cabecalho_pagina


STATUS_PAGAR = ["Pendente", "Pago", "Cancelado"]
STATUS_RECEBER = ["Pendente", "Recebido", "Vencido", "Cancelado"]
STATUS_RECEBER_VISUAL = ["🟡 Pendente", "🟢 Recebido", "🔴 Vencido", "⚪ Cancelado"]
STATUS_PAGAR_VISUAL = ["🟠 Pendente", "🔵 Pago", "⚪ Cancelado"]
MAP_STATUS_RECEBER = {"Pendente": "🟡 Pendente", "Recebido": "🟢 Recebido", "Vencido": "🔴 Vencido", "Cancelado": "⚪ Cancelado"}
MAP_STATUS_PAGAR = {"Pendente": "🟠 Pendente", "Pago": "🔵 Pago", "Cancelado": "⚪ Cancelado"}
MAP_STATUS_LIMPO = {v: k for k, v in {**MAP_STATUS_RECEBER, **MAP_STATUS_PAGAR}.items()}


def _texto(valor):
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except Exception:
        pass
    t = str(valor).strip()
    return "" if t.lower() in {"nan", "none", "nat", "<na>"} else t


def _data(valor):
    if not valor:
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(valor), formato).date()
        except ValueError:
            pass
    return None


def _dinheiro(valor):
    return f"R$ {float(valor or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def listar_receber():
    with conectar() as conn:
        automaticas = pd.read_sql_query(
            """
            SELECT
                'AUTOMATICA' AS Origem,
                fr.id AS id,
                NULL AS projeto_id,
                c.numero_proposta AS Projeto,
                c.nome AS Cliente,
                'Parcela ' || fr.parcela AS Descrição,
                fr.parcela AS Parcela,
                fr.valor AS Valor,
                fr.vencimento AS Vencimento,
                fr.status AS Status,
                fr.data_recebimento AS Recebimento,
                '' AS Observações
            FROM faturamento_receber fr
            JOIN clientes c ON c.id = fr.cliente_id
            """,
            conn,
        )

        manuais = pd.read_sql_query(
            """
            SELECT
                'MANUAL' AS Origem,
                crm.id AS id,
                crm.projeto_id AS projeto_id,
                COALESCE(p.numero,'') AS Projeto,
                crm.cliente AS Cliente,
                crm.descricao AS Descrição,
                NULL AS Parcela,
                crm.valor AS Valor,
                crm.vencimento AS Vencimento,
                crm.status AS Status,
                crm.data_recebimento AS Recebimento,
                crm.observacoes AS Observações
            FROM contas_receber_manual crm
            LEFT JOIN projetos p ON p.id=crm.projeto_id
            """,
            conn,
        )

    dados = pd.concat([automaticas, manuais], ignore_index=True)
    if dados.empty:
        return dados

    dados["_venc"] = pd.to_datetime(dados["Vencimento"], dayfirst=True, errors="coerce")
    dados = dados.sort_values(
        ["_venc", "Projeto", "Cliente", "id"],
        ascending=[True, True, True, True],
        na_position="last",
    ).drop(columns=["_venc"])
    return dados.reset_index(drop=True)


def atualizar_receber(dados: pd.DataFrame):
    with conectar() as conn:
        for _, r in dados.iterrows():
            recebimento = r.get("Recebimento")
            if recebimento is None or pd.isna(recebimento):
                recebimento_txt = None
            elif isinstance(recebimento, pd.Timestamp):
                recebimento_txt = recebimento.strftime("%d/%m/%Y")
            elif isinstance(recebimento, date):
                recebimento_txt = recebimento.strftime("%d/%m/%Y")
            else:
                recebimento_txt = _texto(recebimento) or None

            vencimento = r.get("Vencimento")
            if vencimento is None or pd.isna(vencimento):
                vencimento_txt = None
            elif isinstance(vencimento, pd.Timestamp):
                vencimento_txt = vencimento.strftime("%d/%m/%Y")
            elif isinstance(vencimento, date):
                vencimento_txt = vencimento.strftime("%d/%m/%Y")
            else:
                vencimento_txt = _texto(vencimento) or None

            origem = _texto(r.get("Origem"))
            if origem == "AUTOMATICA":
                conn.execute(
                    """UPDATE faturamento_receber
                       SET valor=?, vencimento=?, status=?, data_recebimento=?
                       WHERE id=?""",
                    (
                        float(r.get("Valor") or 0),
                        vencimento_txt,
                        MAP_STATUS_LIMPO.get(str(r["Status"]), str(r["Status"])),
                        recebimento_txt,
                        int(r["id"]),
                    ),
                )
            else:
                conn.execute(
                    """UPDATE contas_receber_manual
                       SET cliente=?, descricao=?, valor=?, vencimento=?,
                           status=?, data_recebimento=?, observacoes=?
                       WHERE id=?""",
                    (
                        _texto(r.get("Cliente")),
                        _texto(r.get("Descrição")),
                        float(r.get("Valor") or 0),
                        vencimento_txt,
                        MAP_STATUS_LIMPO.get(str(r["Status"]), str(r["Status"])),
                        recebimento_txt,
                        _texto(r.get("Observações")) or None,
                        int(r["id"]),
                    ),
                )
        conn.commit()


def incluir_receber_manual(projeto_id, cliente, descricao, valor, vencimento, status, recebimento, observacoes):
    venc_txt = vencimento.strftime("%d/%m/%Y") if vencimento else None
    rec_txt = recebimento.strftime("%d/%m/%Y") if recebimento else None
    projeto_val = int(projeto_id) if projeto_id else None

    with conectar() as conn:
        duplicado = conn.execute(
            """
            SELECT 1 FROM contas_receber_manual
            WHERE COALESCE(projeto_id,0)=COALESCE(?,0)
              AND LOWER(TRIM(cliente))=LOWER(TRIM(?))
              AND LOWER(TRIM(descricao))=LOWER(TRIM(?))
              AND ABS(COALESCE(valor,0)-?) < 0.001
              AND COALESCE(vencimento,'')=COALESCE(?, '')
            LIMIT 1
            """,
            (projeto_val, cliente.strip(), descricao.strip(), float(valor or 0), venc_txt),
        ).fetchone()

        if duplicado:
            return False

        conn.execute(
            """
            INSERT INTO contas_receber_manual
            (projeto_id, cliente, descricao, valor, vencimento, status,
             data_recebimento, observacoes, criado_em)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                projeto_val,
                cliente.strip(),
                descricao.strip(),
                float(valor or 0),
                venc_txt,
                status,
                rec_txt,
                observacoes.strip() or None,
                datetime.now().strftime("%d/%m/%Y %H:%M"),
            ),
        )
        conn.commit()
    return True


def excluir_receber_manual(lancamento_id: int):
    with conectar() as conn:
        conn.execute(
            "DELETE FROM contas_receber_manual WHERE id=?",
            (int(lancamento_id),),
        )
        conn.commit()


def excluir_receber(origem: str, lancamento_id: int):
    with conectar() as conn:
        if str(origem).strip().upper() == "AUTOMATICA":
            conn.execute("DELETE FROM faturamento_receber WHERE id=?", (int(lancamento_id),))
        else:
            conn.execute("DELETE FROM contas_receber_manual WHERE id=?", (int(lancamento_id),))
        conn.commit()


def listar_projetos_financeiro():
    with conectar() as conn:
        return pd.read_sql_query(
            """
            SELECT p.id, p.numero AS Projeto, c.nome AS Cliente
            FROM projetos p
            JOIN clientes c ON c.id=p.cliente_id
            ORDER BY p.numero DESC
            """,
            conn,
        )


def listar_pagar():
    with conectar() as conn:
        return pd.read_sql_query(
            """
            SELECT cp.id,
                   COALESCE(p.numero,'') AS Projeto,
                   cp.fornecedor AS Fornecedor,
                   cp.descricao AS Descrição,
                   cp.valor AS Valor,
                   cp.vencimento AS Vencimento,
                   cp.status AS Status,
                   cp.data_pagamento AS Pagamento,
                   cp.observacoes AS Observações
            FROM contas_pagar cp
            LEFT JOIN projetos p ON p.id=cp.projeto_id
            ORDER BY
                CASE WHEN cp.vencimento IS NULL OR cp.vencimento='' THEN 1 ELSE 0 END,
                substr(cp.vencimento,7,4),
                substr(cp.vencimento,4,2),
                substr(cp.vencimento,1,2),
                cp.id DESC
            """,
            conn,
        )


def incluir_pagar(projeto_id, fornecedor, descricao, valor, vencimento, status, pagamento, observacoes):
    venc_txt = vencimento.strftime("%d/%m/%Y") if vencimento else None
    pag_txt = pagamento.strftime("%d/%m/%Y") if pagamento else None
    projeto_val = int(projeto_id) if projeto_id else None

    with conectar() as conn:
        duplicado = conn.execute(
            """
            SELECT 1 FROM contas_pagar
            WHERE COALESCE(projeto_id,0)=COALESCE(?,0)
              AND LOWER(TRIM(fornecedor))=LOWER(TRIM(?))
              AND LOWER(TRIM(descricao))=LOWER(TRIM(?))
              AND ABS(COALESCE(valor,0)-?) < 0.001
              AND COALESCE(vencimento,'')=COALESCE(?, '')
            LIMIT 1
            """,
            (projeto_val, fornecedor.strip(), descricao.strip(), float(valor or 0), venc_txt),
        ).fetchone()

        if duplicado:
            return False

        conn.execute(
            """
            INSERT INTO contas_pagar
            (projeto_id, fornecedor, descricao, valor, vencimento, status,
             data_pagamento, observacoes, criado_em)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                projeto_val,
                fornecedor.strip(),
                descricao.strip(),
                float(valor or 0),
                venc_txt,
                status,
                pag_txt,
                observacoes.strip() or None,
                datetime.now().strftime("%d/%m/%Y %H:%M"),
            ),
        )
        conn.commit()
    return True


def atualizar_pagar(dados: pd.DataFrame):
    with conectar() as conn:
        for _, r in dados.iterrows():
            pagamento = r.get("Pagamento")
            if pagamento is None or pd.isna(pagamento):
                pagamento_txt = None
            elif isinstance(pagamento, pd.Timestamp):
                pagamento_txt = pagamento.strftime("%d/%m/%Y")
            elif isinstance(pagamento, date):
                pagamento_txt = pagamento.strftime("%d/%m/%Y")
            else:
                pagamento_txt = _texto(pagamento) or None

            vencimento = r.get("Vencimento")
            if vencimento is None or pd.isna(vencimento):
                vencimento_txt = None
            elif isinstance(vencimento, pd.Timestamp):
                vencimento_txt = vencimento.strftime("%d/%m/%Y")
            elif isinstance(vencimento, date):
                vencimento_txt = vencimento.strftime("%d/%m/%Y")
            else:
                vencimento_txt = _texto(vencimento) or None

            conn.execute(
                """
                UPDATE contas_pagar
                SET fornecedor=?, descricao=?, valor=?, vencimento=?,
                    status=?, data_pagamento=?, observacoes=?
                WHERE id=?
                """,
                (
                    _texto(r.get("Fornecedor")),
                    _texto(r.get("Descrição")),
                    float(r.get("Valor") or 0),
                    vencimento_txt,
                    MAP_STATUS_LIMPO.get(str(r["Status"]), str(r["Status"])),
                    pagamento_txt,
                    _texto(r.get("Observações")) or None,
                    int(r["id"]),
                ),
            )
        conn.commit()


def excluir_pagar(lancamento_id: int):
    with conectar() as conn:
        conn.execute("DELETE FROM contas_pagar WHERE id=?", (int(lancamento_id),))
        conn.commit()


def tela_financeiro():
    cabecalho_pagina("Financeiro")

    receber = listar_receber()
    pagar = listar_pagar()

    hoje = pd.Timestamp.today().normalize()

    venc_receber = pd.to_datetime(receber["Vencimento"], dayfirst=True, errors="coerce")
    status_receber_base = receber["Status"].fillna("")
    mascara_vencido = (
        (status_receber_base == "Vencido")
        | (
            (venc_receber < hoje)
            & ~status_receber_base.isin(["Recebido", "Cancelado"])
        )
    )

    total_vencido = receber.loc[mascara_vencido, "Valor"].fillna(0).sum()
    total_a_receber = receber.loc[
        ~mascara_vencido
        & ~status_receber_base.isin(["Recebido", "Cancelado", "Vencido"]),
        "Valor"
    ].fillna(0).sum()
    total_recebido = receber.loc[
        status_receber_base == "Recebido", "Valor"
    ].fillna(0).sum()

    total_a_pagar = pagar.loc[
        ~pagar["Status"].fillna("").isin(["Pago", "Cancelado"]), "Valor"
    ].fillna(0).sum()
    total_pago = pagar.loc[
        pagar["Status"].fillna("") == "Pago", "Valor"
    ].fillna(0).sum()

    c1, c2, c3, c4, c5 = st.columns(5)

    def card_financeiro(coluna, titulo, valor, fundo, borda, icone):
        with coluna:
            st.markdown(
                f"""
                <div style="
                    background:{fundo};
                    border:1px solid {borda};
                    border-radius:14px;
                    padding:18px 20px;
                    min-height:120px;
                    box-shadow:0 3px 10px rgba(0,0,0,.05);
                ">
                    <div style="font-size:1rem;font-weight:700;margin-bottom:12px;">
                        {icone} {titulo}
                    </div>
                    <div style="font-size:1.72rem;font-weight:500;">{valor}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    card_financeiro(c1, "A RECEBER", _dinheiro(total_a_receber), "#FFF7D6", "#F0D77A", "🟡")
    card_financeiro(c2, "VENCIDO", _dinheiro(total_vencido), "#FDE2E2", "#E8A5A5", "🔴")
    card_financeiro(c3, "RECEBIDO", _dinheiro(total_recebido), "#E2F4E8", "#A9D8B8", "🟢")
    card_financeiro(c4, "A PAGAR", _dinheiro(total_a_pagar), "#FFE8D6", "#F0B98D", "🟠")
    card_financeiro(c5, "PAGO", _dinheiro(total_pago), "#E2ECFA", "#AFC7E8", "🔵")

    st.divider()

    aba_receber, aba_pagar = st.tabs(["💰 CONTAS A RECEBER", "💸 CONTAS A PAGAR"])

    with aba_receber:
        st.caption(
            "As parcelas das propostas entram automaticamente. "
            "Também é possível incluir um recebimento manual."
        )

        with st.expander("➕ NOVO LANÇAMENTO", expanded=False):
            projetos = listar_projetos_financeiro()
            opcoes_projeto = {"Sem projeto": None}
            cliente_por_projeto = {}
            for _, p in projetos.iterrows():
                rotulo = f'{_texto(p["Projeto"])} | {_texto(p["Cliente"])}'
                opcoes_projeto[rotulo] = int(p["id"])
                cliente_por_projeto[rotulo] = _texto(p["Cliente"])

            with st.form("form_novo_receber", clear_on_submit=True):
                projeto_receber = st.selectbox(
                    "Nº Projeto (opcional)",
                    list(opcoes_projeto.keys()),
                    key="fin_projeto_receber_manual",
                )

                cliente_padrao = cliente_por_projeto.get(projeto_receber, "")
                a, b = st.columns(2)
                with a:
                    cliente_manual = st.text_input(
                        "Cliente *",
                        value=cliente_padrao,
                        disabled=projeto_receber != "Sem projeto",
                        key="fin_cliente_receber_manual",
                    )
                    descricao_receber = st.text_input(
                        "Descrição *",
                        key="fin_descricao_receber_manual",
                    )
                    valor_receber = st.number_input(
                        "Valor (R$)",
                        min_value=0.0,
                        step=100.0,
                        format="%.2f",
                        key="fin_valor_receber_manual",
                    )
                with b:
                    venc_receber = st.date_input(
                        "Vencimento",
                        value=None,
                        format="DD/MM/YYYY",
                        key="fin_venc_receber_manual",
                    )
                    status_receber = st.selectbox(
                        "Status",
                        STATUS_RECEBER,
                        key="fin_status_receber_manual",
                    )
                    data_receber = st.date_input(
                        "Data de Recebimento",
                        value=None,
                        format="DD/MM/YYYY",
                        key="fin_data_receber_manual",
                    )

                obs_receber = st.text_area(
                    "Observação",
                    height=80,
                    key="fin_obs_receber_manual",
                )

                salvar_receber_manual = st.form_submit_button(
                    "SALVAR LANÇAMENTO",
                    type="primary",
                    width="stretch",
                )

            if salvar_receber_manual:
                cliente_final = cliente_padrao if projeto_receber != "Sem projeto" else cliente_manual
                if not cliente_final.strip() or not descricao_receber.strip():
                    st.error("Preencha Cliente e Descrição.")
                else:
                    criado = incluir_receber_manual(
                        opcoes_projeto[projeto_receber],
                        cliente_final,
                        descricao_receber,
                        valor_receber,
                        venc_receber,
                        status_receber,
                        data_receber,
                        obs_receber,
                    )
                    if criado:
                        st.success("Lançamento a receber salvo.")
                    else:
                        st.warning("Este lançamento já existe e não foi duplicado.")
                    st.rerun()

        receber = listar_receber()

        if receber.empty:
            st.info("Nenhuma conta a receber cadastrada.")
        else:
            filtro1, filtro2 = st.columns([2, 1])
            with filtro1:
                busca = st.text_input(
                    "Pesquisar",
                    placeholder="Nº Projeto, cliente ou descrição",
                    key="fin_busca_receber",
                )
            with filtro2:
                status_filtro = st.selectbox(
                    "Status",
                    ["Todos"] + STATUS_RECEBER,
                    key="fin_status_receber",
                )

            dados = receber.copy()
            if busca.strip():
                x = busca.strip().lower()
                dados = dados[
                    dados["Projeto"].fillna("").astype(str).str.lower().str.contains(x)
                    | dados["Cliente"].fillna("").astype(str).str.lower().str.contains(x)
                    | dados["Descrição"].fillna("").astype(str).str.lower().str.contains(x)
                ]
            if status_filtro != "Todos":
                dados = dados[dados["Status"].fillna("") == status_filtro]

            dados_editor = dados[
                [
                    "Origem", "id", "Projeto", "Cliente", "Descrição",
                    "Valor", "Vencimento", "Status", "Recebimento", "Observações"
                ]
            ].copy()

            dados_editor["Vencimento"] = pd.to_datetime(
                dados_editor["Vencimento"], dayfirst=True, errors="coerce"
            ).dt.date
            dados_editor["Recebimento"] = pd.to_datetime(
                dados_editor["Recebimento"], dayfirst=True, errors="coerce"
            ).dt.date

            hoje_data = pd.Timestamp.today().date()
            def _status_receber_visual(row):
                status = str(row["Status"] or "")
                venc = row["Vencimento"]
                if status not in ("Recebido", "Cancelado") and venc is not None and not pd.isna(venc) and venc < hoje_data:
                    status = "Vencido"
                return MAP_STATUS_RECEBER.get(status, status)

            dados_editor["Status"] = dados_editor.apply(_status_receber_visual, axis=1)

            editado = st.data_editor(
                dados_editor,
                hide_index=True,
                width="stretch",
                disabled=["Origem", "id", "Projeto"],
                column_config={
                    "Origem": None,
                    "id": None,
                    "Projeto": st.column_config.TextColumn("Nº Projeto"),
                    "Cliente": st.column_config.TextColumn("Cliente"),
                    "Descrição": st.column_config.TextColumn("Descrição"),
                    "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                    "Vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY"),
                    "Status": st.column_config.SelectboxColumn(
                        "Status",
                        options=STATUS_RECEBER_VISUAL,
                        required=True,
                    ),
                    "Recebimento": st.column_config.DateColumn(
                        "Data de Recebimento",
                        format="DD/MM/YYYY",
                    ),
                    "Observações": st.column_config.TextColumn(
                        "Observação",
                        width="medium",
                    ),
                },
                key="editor_fin_receber",
            )

            if st.button(
                "💾 SALVAR ALTERAÇÕES DAS CONTAS A RECEBER",
                type="primary",
                width="stretch",
            ):
                atualizar_receber(editado)
                st.success("Contas a receber atualizadas. Cards recalculados.")
                st.rerun()

            with st.expander("🗑️ EXCLUIR LANÇAMENTO", expanded=False):
                opcoes_exclusao = {}
                for _, r in dados.iterrows():
                    origem = _texto(r["Origem"]).upper()
                    tipo = "PARCELA DA PROPOSTA" if origem == "AUTOMATICA" else "LANÇAMENTO MANUAL"
                    rotulo = (
                        f'{tipo} | {_texto(r["Projeto"])} | {_texto(r["Cliente"])} | '
                        f'{_texto(r["Descrição"])} | {_dinheiro(r["Valor"])}'
                    )
                    opcoes_exclusao[rotulo] = (origem, int(r["id"]))

                if not opcoes_exclusao:
                    st.caption("Nenhum lançamento visível para excluir.")
                else:
                    excluir_rec = st.selectbox(
                        "Selecione o lançamento",
                        ["Selecione..."] + list(opcoes_exclusao.keys()),
                        key="fin_excluir_receber",
                    )

                    if excluir_rec != "Selecione...":
                        origem_sel, id_sel = opcoes_exclusao[excluir_rec]

                        if origem_sel == "AUTOMATICA":
                            st.warning(
                                "Este lançamento veio automaticamente da proposta. "
                                "A exclusão remove esta parcela do Financeiro. "
                                "Se a proposta for salva novamente com a mesma quantidade de parcelas, "
                                "ela poderá ser recriada."
                            )
                        else:
                            st.warning("Esta ação excluirá definitivamente o lançamento manual selecionado.")

                        confirmar_exclusao = st.checkbox(
                            "Confirmo que desejo excluir este lançamento.",
                            key="confirmar_excluir_receber",
                        )

                        if st.button(
                            "🗑️ EXCLUIR LANÇAMENTO DEFINITIVAMENTE",
                            key="btn_excluir_receber",
                            width="stretch",
                            disabled=not confirmar_exclusao,
                        ):
                            excluir_receber(origem_sel, id_sel)
                            st.success("Lançamento excluído com sucesso.")
                            st.rerun()

    with aba_pagar:
        with st.expander("➕ NOVO LANÇAMENTO", expanded=False):
            projetos = listar_projetos_financeiro()
            opcoes = {"Sem projeto": None}
            for _, p in projetos.iterrows():
                opcoes[f'{_texto(p["Projeto"])} | {_texto(p["Cliente"])}'] = int(p["id"])

            with st.form("form_novo_pagar", clear_on_submit=True):
                projeto_escolhido = st.selectbox(
                    "Nº Projeto (opcional)",
                    list(opcoes.keys()),
                    key="fin_projeto_pagar",
                )

                a, b = st.columns(2)
                with a:
                    fornecedor = st.text_input("Fornecedor *", key="fin_fornecedor")
                    descricao = st.text_input("Descrição *", key="fin_descricao")
                    valor = st.number_input(
                        "Valor (R$)",
                        min_value=0.0,
                        step=100.0,
                        format="%.2f",
                        key="fin_valor_pagar",
                    )
                with b:
                    vencimento = st.date_input(
                        "Vencimento",
                        value=None,
                        format="DD/MM/YYYY",
                        key="fin_vencimento_pagar",
                    )
                    status = st.selectbox(
                        "Status",
                        STATUS_PAGAR,
                        key="fin_status_pagar_novo",
                    )
                    pagamento = st.date_input(
                        "Data de Pagamento",
                        value=None,
                        format="DD/MM/YYYY",
                        key="fin_pagamento_pagar",
                    )

                observacoes = st.text_area(
                    "Observação",
                    height=80,
                    key="fin_obs_pagar",
                )

                salvar_novo = st.form_submit_button(
                    "SALVAR LANÇAMENTO",
                    type="primary",
                    width="stretch",
                )

            if salvar_novo:
                if not fornecedor.strip() or not descricao.strip():
                    st.error("Preencha Fornecedor e Descrição.")
                else:
                    criado = incluir_pagar(
                        opcoes[projeto_escolhido],
                        fornecedor,
                        descricao,
                        valor,
                        vencimento,
                        status,
                        pagamento,
                        observacoes,
                    )
                    if criado:
                        st.success("Lançamento salvo.")
                    else:
                        st.warning("Este lançamento já existe e não foi duplicado.")
                    st.rerun()

        if pagar.empty:
            st.info("Nenhuma conta a pagar cadastrada.")
        else:
            f1, f2 = st.columns([2, 1])
            with f1:
                busca_p = st.text_input(
                    "Pesquisar contas a pagar",
                    placeholder="Nº Projeto, fornecedor ou descrição",
                    key="fin_busca_pagar",
                )
            with f2:
                status_p = st.selectbox(
                    "Status",
                    ["Todos", "Pendente", "Pago", "Cancelado"],
                    key="fin_status_pagar",
                )

            dados_p = pagar.copy()
            if busca_p.strip():
                x = busca_p.strip().lower()
                dados_p = dados_p[
                    dados_p["Projeto"].fillna("").astype(str).str.lower().str.contains(x)
                    | dados_p["Fornecedor"].fillna("").astype(str).str.lower().str.contains(x)
                    | dados_p["Descrição"].fillna("").astype(str).str.lower().str.contains(x)
                ]
            if status_p != "Todos":
                dados_p = dados_p[dados_p["Status"].fillna("") == status_p]

            dados_p_editor = dados_p[
                ["id", "Projeto", "Fornecedor", "Descrição", "Valor",
                 "Vencimento", "Status", "Pagamento", "Observações"]
            ].copy()

            # O banco guarda a data como texto; o Streamlit DateColumn precisa
            # receber valores do tipo data/datetime.
            dados_p_editor["Vencimento"] = pd.to_datetime(
                dados_p_editor["Vencimento"],
                dayfirst=True,
                errors="coerce",
            ).dt.date
            dados_p_editor["Pagamento"] = pd.to_datetime(
                dados_p_editor["Pagamento"],
                dayfirst=True,
                errors="coerce",
            ).dt.date
            dados_p_editor["Status"] = dados_p_editor["Status"].map(
                lambda s: MAP_STATUS_PAGAR.get(str(s), str(s))
            )

            editado_p = st.data_editor(
                dados_p_editor,
                hide_index=True,
                width="stretch",
                disabled=["id", "Projeto"],
                column_config={
                    "id": None,
                    "Projeto": st.column_config.TextColumn("Nº Projeto"),
                    "Fornecedor": st.column_config.TextColumn("Fornecedor"),
                    "Descrição": st.column_config.TextColumn("Descrição"),
                    "Valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                    "Vencimento": st.column_config.DateColumn(
                        "Vencimento",
                        format="DD/MM/YYYY",
                    ),
                    "Status": st.column_config.SelectboxColumn(
                        "Status",
                        options=STATUS_PAGAR_VISUAL,
                        required=True,
                    ),
                    "Pagamento": st.column_config.DateColumn(
                        "Data de Pagamento",
                        format="DD/MM/YYYY",
                    ),
                    "Observações": st.column_config.TextColumn(
                        "Observação",
                        width="medium",
                    ),
                },
                key="editor_fin_pagar",
            )

            if st.button("💾 SALVAR ALTERAÇÕES DAS CONTAS A PAGAR", type="primary", width="stretch"):
                atualizar_pagar(editado_p)
                st.success("Contas a pagar atualizadas.")
                st.rerun()

            with st.expander("🗑️ EXCLUIR LANÇAMENTO", expanded=False):
                ids_visiveis = {
                    f'{int(r["id"])} | {_texto(r["Projeto"])} | {_texto(r["Fornecedor"])} | {_dinheiro(r["Valor"])}': int(r["id"])
                    for _, r in dados_p.iterrows()
                }
                if ids_visiveis:
                    excluir_escolhido = st.selectbox(
                        "Selecione o lançamento",
                        ["Selecione..."] + list(ids_visiveis.keys()),
                        key="fin_excluir_pagar",
                    )
                    if excluir_escolhido != "Selecione...":
                        st.warning("Esta ação excluirá o lançamento financeiro selecionado.")
                        if st.button("EXCLUIR LANÇAMENTO DEFINITIVAMENTE", width="stretch"):
                            excluir_pagar(ids_visiveis[excluir_escolhido])
                            st.success("Lançamento excluído.")
                            st.rerun()
