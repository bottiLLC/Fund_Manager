"""Master management tab rendering for portfolio configuration and editing."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from backup_manager import run_backup
from src.models import HOLDER_OPTIONS, PortfolioItem
from src.portfolio_loader import (
    CANONICAL_PRESET_FUNDS,
    PRESET_FUNDS,
    parse_portfolio_csv_content,
    save_portfolio_csv,
)
from src.sbi_importer import decode_csv_bytes


def render_master_tab(
    portfolio_csv_path: Path,
    portfolio_items: list[PortfolioItem],
) -> None:
    """保有資産マスター管理タブを描画する。

    新規登録フォーム、データエディタ編集、安全な削除、および標準CSVアップロードを提供する。

    Args:
        portfolio_csv_path: portfolio.csv のファイルパス。
        portfolio_items: 現在読み込まれている保有資産リスト。
    """
    st.subheader("📝 保有資産マスター管理 (portfolio.csv)")
    st.caption(
        "`account, 協会コード, ISINコード, units, cost_basis` を管理します。"
        "銘柄名および最新基準価額は投信総合検索ライブラリーから自動取得されます。"
    )

    # プリセット選択補助
    with st.expander("💡 主要9銘柄プリセットから入力コードを選択", expanded=False):
        preset_names = [
            f"{code} | {info['name']}"
            for code, info in CANONICAL_PRESET_FUNDS.items()
            if len(code) == 8
        ]
        selected_preset_str = st.selectbox(
            "主要銘柄リスト",
            ["-- 選択してください --", *sorted(preset_names)],
            help="選択すると下の新規追加フォームにコードが自動反映されます。",
        )
        selected_code = ""
        selected_isin = ""
        if selected_preset_str and selected_preset_str != "-- 選択してください --":
            selected_code = selected_preset_str.split(" | ")[0]
            selected_isin = CANONICAL_PRESET_FUNDS[selected_code]["isin"]
            st.info(f"選択中: 協会コード `{selected_code}` / ISINコード `{selected_isin}`")

    # 1. 新規追加フォーム (Formカプセル化)
    with st.form("add_holding_form", clear_on_submit=True):
        st.markdown("##### ➕ 新規保有資産の追加")
        add_col0, add_col1, add_col2, add_col3 = st.columns([1, 2, 2, 2])
        with add_col0:
            form_holder = st.selectbox(
                "法人/個人",
                list(HOLDER_OPTIONS),
                help="所有者区分（法人・個人等）を選択します。",
            )
        with add_col1:
            form_account = st.selectbox(
                "格納口座 (account)",
                [
                    "NISA預り（つみたて投資枠）",
                    "NISA預り（成長投資枠）",
                    "NISA預り（旧つみたてNISA預り）",
                    "一般預り",
                    "特定預り",
                    "iDeCo",
                    "DC",
                ],
                help="保有資産を管理する口座区分を指定します。",
            )
        with add_col2:
            form_code = st.text_input(
                "協会コード (8桁半角英数字)",
                value=selected_code,
                max_chars=8,
                help="投資信託協会の8桁ファンドコード（例: 0331418A）",
            )
        with add_col3:
            form_isin = st.text_input(
                "ISINコード (12桁半角英数字)",
                value=selected_isin,
                max_chars=12,
                help="国際証券識別番号 (例: JP90C000H1T1)",
            )

        add_col4, add_col5 = st.columns(2)
        with add_col4:
            form_units = st.number_input(
                "保有口数 (units)",
                min_value=0.0001,
                value=100000.0,
                step=1000.0,
                format="%.4f",
                help="保有しているファンドの総口数を入力します。",
            )
        with add_col5:
            form_cost = st.number_input(
                "取得簿価 (cost_basis, 円 / 0は簿価管理不要)",
                min_value=0,
                value=0,
                step=10000,
                help="簿価管理を行う場合の取得元本合計（円単位）。不要な場合は0。",
            )

        submitted_add = st.form_submit_button(
            "ポートフォリオに追加",
            icon=":material/add:",
            type="primary",
            width="stretch",
        )

    if submitted_add:
        try:
            new_item = PortfolioItem(
                holder=form_holder,
                account=form_account,
                code=form_code,
                isin=form_isin,
                name=PRESET_FUNDS.get(form_code.upper(), {}).get("name", ""),
                units=form_units,
                cost_basis=form_cost,
            )
            updated_items = [*portfolio_items, new_item]
            save_portfolio_csv(portfolio_csv_path, updated_items)
            st.cache_data.clear()
            st.success(
                f"[{form_holder}] {form_account} に銘柄コード {new_item.code} を正常に追加しました。"
            )
            st.rerun()
        except Exception as ex:
            st.error(
                f"【追加エラー】入力値の検証に失敗しました: {ex}\n【対処方法】8桁の半角英数協会コードおよび口数を確認してください。"
            )

    st.divider()

    # 2. データエディタによる編集・削除・一括保存
    st.markdown("##### 📋 登録済みポートフォリオの直接編集・削除")
    edit_data = [
        {
            "delete": False,
            "holder": it.holder,
            "account": it.account,
            "code": it.code,
            "isin": it.isin,
            "units": it.units,
            "cost_basis": it.cost_basis,
            "name": it.name,
        }
        for it in portfolio_items
    ]
    edit_df = pd.DataFrame(
        edit_data,
        columns=["delete", "holder", "account", "code", "isin", "units", "cost_basis", "name"],
    )

    known_accounts = sorted(
        {
            *([it.account for it in portfolio_items]),
            "NISA預り（つみたて投資枠）",
            "NISA預り（成長投資枠）",
            "NISA預り（旧つみたてNISA預り）",
            "一般預り",
            "特定預り",
            "iDeCo",
            "DC",
        }
    )

    edited_df = st.data_editor(
        edit_df,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_order=[
            "delete",
            "holder",
            "account",
            "code",
            "isin",
            "units",
            "cost_basis",
            "name",
        ],
        column_config={
            "delete": st.column_config.CheckboxColumn(
                "削除",
                help="削除する場合はチェックを入れてください",
                default=False,
            ),
            "holder": st.column_config.SelectboxColumn(
                "法人/個人",
                options=list(HOLDER_OPTIONS),
                required=True,
                default="個人",
                help="所有者区分",
            ),
            "account": st.column_config.SelectboxColumn(
                "格納口座",
                options=known_accounts,
                required=True,
                help="格納口座区分",
            ),
            "code": st.column_config.TextColumn(
                "協会コード", max_chars=8, required=True, help="8桁英数コード"
            ),
            "isin": st.column_config.TextColumn(
                "ISINコード", max_chars=12, required=True, help="12桁ISIN"
            ),
            "units": st.column_config.NumberColumn(
                "保有口数", min_value=0.0001, required=True, help="口数"
            ),
            "cost_basis": st.column_config.NumberColumn(
                "取得簿価(円)", min_value=0, required=True, help="簿価円"
            ),
            "name": st.column_config.TextColumn(
                "銘柄名(Web自動取得)", disabled=True, help="自動取得銘柄名"
            ),
        },
        key="portfolio_data_editor",
    )

    is_delete_series = edited_df["delete"].fillna(False).astype(bool)
    delete_count = int(is_delete_series.sum())

    if delete_count > 0:
        st.warning(f"⚠️ 削除対象として **{delete_count} 件** の銘柄にチェックが入っています。")
        confirm_delete = st.checkbox(
            f"不可逆な操作を確認: チェックした {delete_count} 件の銘柄を完全に削除します",
            key="chk_confirm_delete_items",
            help="破壊的操作防止のための安全確認です。チェックを入れると削除ボタンが有効化されます。",
        )
    else:
        st.caption(
            "※ 銘柄を削除する場合は、表の一番左端「削除」列のチェックボックスをONにしてください。"
        )
        confirm_delete = False

    col_save, col_delete = st.columns([1, 1])
    with col_save:
        save_btn = st.button(
            "💾 変更を portfolio.csv に保存して再計算",
            icon=":material/save:",
            type="primary" if delete_count == 0 else "secondary",
            width="stretch",
            key="save_portfolio_changes_btn",
            help="テーブル上で編集した内容を portfolio.csv に反映します。",
        )
    with col_delete:
        delete_btn = st.button(
            f"🗑️ チェックした銘柄 ({delete_count}件) を削除",
            icon=":material/delete:",
            type="secondary",
            disabled=(delete_count == 0 or not confirm_delete),
            width="stretch",
            key="delete_portfolio_checked_btn",
            help="チェックした銘柄を削除します（事前確認チェックが必要です）。",
        )

    if delete_btn and delete_count > 0 and confirm_delete:
        try:
            with st.spinner("安全バックアップを作成し銘柄を削除中..."):
                run_backup(app_name="pre_delete")
                remaining_items: list[PortfolioItem] = []
                for _, r in edited_df.iterrows():
                    if not bool(r.get("delete", False)):
                        holder_val = str(r.get("holder", "個人")).strip() or "個人"
                        account_val = str(r["account"]).strip()
                        code_val = str(r["code"]).strip()
                        isin_val = str(r["isin"]).strip()
                        units_val = float(r["units"])
                        cost_val = int(r["cost_basis"])
                        if account_val and code_val:
                            remaining_items.append(
                                PortfolioItem(
                                    holder=holder_val,
                                    account=account_val,
                                    code=code_val,
                                    isin=isin_val,
                                    name=str(r.get("name") or ""),
                                    units=units_val,
                                    cost_basis=cost_val,
                                )
                            )
                save_portfolio_csv(portfolio_csv_path, remaining_items)
                st.cache_data.clear()
            st.success(f"{delete_count} 件の銘柄を削除し、portfolio.csv を正常に更新しました。")
            st.rerun()
        except Exception as del_err:
            st.error(f"【削除エラー】{del_err}\n【対処方法】データの整合性を確認してください。")

    if save_btn:
        try:
            with st.spinner("ポートフォリオデータを更新中..."):
                validated_save_items: list[PortfolioItem] = []
                for _, r in edited_df.iterrows():
                    if bool(r.get("delete", False)):
                        continue
                    holder_val = str(r.get("holder", "個人")).strip() or "個人"
                    account_val = str(r["account"]).strip()
                    code_val = str(r["code"]).strip()
                    isin_val = str(r["isin"]).strip()
                    units_val = float(r["units"])
                    cost_val = int(r["cost_basis"])
                    if account_val and code_val:
                        validated_save_items.append(
                            PortfolioItem(
                                holder=holder_val,
                                account=account_val,
                                code=code_val,
                                isin=isin_val,
                                name=str(r.get("name") or ""),
                                units=units_val,
                                cost_basis=cost_val,
                            )
                        )

                if not validated_save_items:
                    st.error(
                        "【エラー】保存対象の有効な銘柄データがありません。\n【対処方法】有効な行を残して保存してください。"
                    )
                else:
                    if delete_count > 0:
                        run_backup(app_name="pre_delete")
                    save_portfolio_csv(portfolio_csv_path, validated_save_items)
                    st.cache_data.clear()
                    st.success("portfolio.csv を正常に更新しました。最新の集計を実行します。")
                    st.rerun()
        except Exception as save_err:
            st.error(
                f"【保存エラー】{save_err}\n【対処方法】各項目の型および必須入力を確認してください。"
            )

    # 3. 標準ポートフォリオCSV直接アップロードフォーム (Formカプセル化)
    st.divider()
    st.markdown("##### 📄 保有資産CSV (portfolio.csv) アップロード")
    st.caption("標準フォーマットのCSVをアップロードし、追記または洗い替えで登録します。")

    with st.form("std_portfolio_csv_form", clear_on_submit=False):
        std_col1, std_col2 = st.columns([2, 1])
        with std_col1:
            uploaded_std_csv = st.file_uploader(
                "portfolio.csv を選択",
                type=["csv"],
                key="std_portfolio_csv_uploader",
                help="account,code,isin,units,cost_basis ヘッダを含むCSVに対応しています。",
            )
        with std_col2:
            std_upload_mode = st.radio(
                "反映方式",
                options=["append", "replace_all"],
                format_func=lambda m: (
                    "➕ 追記 (既存を維持)" if m == "append" else "🔄 洗い替え (全置換)"
                ),
                key="std_csv_mode_radio",
                help="既存データを保持して追加するか、全データを置換するかを選択します。",
            )

        confirm_replace_std = st.checkbox(
            "⚠️ 洗い替え（全置換）を選択した場合、既存の全保有データが上書き消去されることを確認しました",
            value=False,
            help="破壊的操作を防ぐためのセーフティチェックです。",
        )

        btn_std_submit = st.form_submit_button(
            "📥 CSVを取り込んでポートフォリオに反映",
            icon=":material/upload:",
            type="secondary",
            width="stretch",
        )

    if btn_std_submit:
        if uploaded_std_csv is None:
            st.error(
                "【エラー】CSVファイルが選択されていません。\n【対処方法】有効な portfolio.csv を指定してください。"
            )
        elif std_upload_mode == "replace_all" and not confirm_replace_std:
            st.error(
                "【安全確認エラー】洗い替え方式の実行には確認チェックが必要です。\n【対処方法】上記の警告確認チェックボックスをONにしてください。"
            )
        else:
            try:
                with st.spinner("CSV解析およびポートフォリオ反映中..."):
                    content_str = decode_csv_bytes(uploaded_std_csv.getvalue())
                    incoming_std_items = parse_portfolio_csv_content(content_str)

                    run_backup(app_name="pre_std_csv_upload")
                    if std_upload_mode == "replace_all":
                        final_std_items = incoming_std_items
                    else:
                        final_std_items = [*portfolio_items, *incoming_std_items]

                    save_portfolio_csv(portfolio_csv_path, final_std_items)
                    st.cache_data.clear()
                st.success(f"CSVを正常に取り込みました（反映後合計: {len(final_std_items)} 件）。")
                st.rerun()
            except Exception as std_ex:
                st.error(
                    f"【CSV取り込みエラー】{std_ex}\n【対処方法】CSVヘッダーおよびデータ行の形式を確認してください。"
                )
