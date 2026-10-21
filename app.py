"""投資信託ポートフォリオ評価 Streamlit Web GUI アプリケーション。"""

from __future__ import annotations

import sys
from pathlib import Path

# Deterministic sys.path configuration
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import altair as alt
import pandas as pd
import streamlit as st

from backup_manager import get_backup_dir, run_backup, set_backup_dir
from src.calculator import evaluate_portfolio
from src.formatter import format_rate, format_yen
from src.models import PortfolioItem
from src.nav_fetcher import fetch_latest_nav_and_names
from src.portfolio_loader import (
    PRESET_FUNDS,
    load_portfolio_csv,
    parse_portfolio_csv_content,
    save_portfolio_csv,
)
from src.sbi_importer import (
    ImportCandidate,
    MergeMode,
    decode_csv_bytes,
    load_custom_aliases,
    merge_candidates_into_portfolio,
    normalize_string_key,
    parse_sbi_portfolio_csv,
    resolve_candidates,
    save_custom_aliases,
)

st.set_page_config(
    page_title="Fund Manager - 投資信託資産管理",
    page_icon="📈",
    layout="wide",
)


@st.cache_data(ttl=3600)
def cached_fetch_nav_and_names(
    targets_tuple: tuple[tuple[str, str], ...],
    cache_dir_str: str,
) -> tuple[str, dict[str, float], dict[str, str]]:
    """基準価額および銘柄名の取得結果を1時間キャッシュする。"""
    targets = dict(targets_tuple)
    return fetch_latest_nav_and_names(
        targets=targets,
        cache_dir=Path(cache_dir_str),
    )


# ---------------------------------------------------------
# Zone 1: Sidebar (Configuration, Backup, Metadata)
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 設定 & 管理")

    force_refresh = st.button("🔄 基準価額データを再取得", use_container_width=True)
    if force_refresh:
        st.cache_data.clear()
        st.session_state["cache_cleared_msg"] = "キャッシュをクリアし、最新データを再取得しました。"
        st.rerun()

    if "cache_cleared_msg" in st.session_state:
        st.success(str(st.session_state.pop("cache_cleared_msg")))

    uploaded_nav_csv = st.file_uploader(
        "最新基準価額CSVを手動登録",
        type=["csv"],
        help="最新の基準価額CSVをアップロードして ./data/cache/latest_nav.csv を更新します。",
    )
    if uploaded_nav_csv is not None:
        save_target = _PROJECT_ROOT / "data" / "cache" / "latest_nav.csv"
        save_target.parent.mkdir(parents=True, exist_ok=True)
        save_target.write_bytes(uploaded_nav_csv.getvalue())
        st.cache_data.clear()
        st.session_state["cache_cleared_msg"] = "最新基準価額CSVをキャッシュに保存しました。"
        st.rerun()

    st.divider()

    # Python-backup-script 規格のUI実装
    st.subheader("データ保護・バックアップ")
    current_dir = str(get_backup_dir())
    new_dir = st.text_input("保存先フォルダ", value=current_dir)
    if new_dir != current_dir and st.button("保存先パスを更新", use_container_width=True):
        save_res = set_backup_dir(new_dir)
        if save_res["success"]:
            st.success(str(save_res["message"]))
            st.rerun()
        else:
            st.error(str(save_res["message"]))

    if st.button("今すぐバックアップを実行", use_container_width=True):
        with st.spinner("圧縮・整合性検証中..."):
            res = run_backup(app_name="fund_manager")
        if res["success"]:
            st.success(str(res["message"]))
            st.caption(f"完了日時: {res.get('timestamp')}")
            st.caption(f"保存先: {res.get('destination')}")
        else:
            st.error(str(res.get("message")))

    st.divider()
    st.caption("Fund Manager v0.2.0 | Python 3.14+")

# ---------------------------------------------------------
# Zone 2: Header
# ---------------------------------------------------------
st.title("📈 投資信託 ポートフォリオ評価ダッシュボード")
st.caption(
    "投資信託協会の最新基準価額とローカル資産を突き合わせ、口座（タンク）ごとの資産評価とアロケーションを可視化します。"
)

# ---------------------------------------------------------
# Zone 3: Data Loading & Calculation
# ---------------------------------------------------------
portfolio_csv_path = _PROJECT_ROOT / "data" / "portfolio.csv"

try:
    portfolio_items = load_portfolio_csv(portfolio_csv_path)
except Exception as e:
    st.error(f"保有資産CSVの読み込みエラー: {e}")
    st.stop()

target_pairs = tuple(sorted({(item.code, item.isin) for item in portfolio_items}))
cache_dir = _PROJECT_ROOT / "data" / "cache"

with st.spinner("基準価額データを取得中..."):
    as_of_date, nav_map, name_map = cached_fetch_nav_and_names(target_pairs, str(cache_dir))

# 銘柄名の補完
hydrated_items = [
    item.model_copy(
        update={
            "name": name_map.get(item.code)
            or item.name
            or PRESET_FUNDS.get(item.code, {}).get("name")
            or f"ファンド {item.code}"
        }
    )
    for item in portfolio_items
]

report = evaluate_portfolio(
    items=hydrated_items,
    nav_map=nav_map,
    as_of_date=as_of_date,
)

# ---------------------------------------------------------
# Zone 4: Tabs Workspace (Dashboard & Master Input)
# ---------------------------------------------------------
tab_dashboard, tab_master = st.tabs(["📊 ポートフォリオ評価", "📝 保有資産マスター管理"])

with tab_dashboard:
    if "(Fallback)" in report.as_of_date:
        st.warning(
            "⚠️ **内蔵フォールバック値を使用中**: 投信協会URLからのデータ取得に失敗（HTTP 404等）したため、"
            "内蔵の固定値データを表示しています。「再取得」を押しても外部通信が失敗するため値は変化しません。"
            "手動で最新データを反映する場合は、サイドバーの「最新基準価額CSVを手動登録」をご利用ください。"
        )
    elif "(Cached)" in report.as_of_date:
        st.info(
            f"ℹ️ **ローカルキャッシュ使用中**: `./data/cache/` の基準価額を表示しています（基準日: {report.as_of_date}）。"
        )

    # 1. KPI メトリクス表示
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            label="総資産評価額",
            value=format_yen(report.total_valuation),
        )
    with col2:
        if report.total_profit_loss is not None:
            pl_rate = (
                (report.total_profit_loss / (report.total_valuation - report.total_profit_loss))
                * 100.0
                if (report.total_valuation - report.total_profit_loss) > 0
                else 0.0
            )
            st.metric(
                label="総含み損益",
                value=format_yen(report.total_profit_loss, prefix_sign=True),
                delta=f"{pl_rate:+.1f}%",
            )
        else:
            st.metric(label="総含み損益", value="-")
    with col3:
        st.metric(
            label="基準価額データ取得日",
            value=report.as_of_date,
        )

    st.divider()

    # 2. タンク別サマリー & アセットアロケーション可視化
    st.subheader("📊 タンク別サマリー & アセットアロケーション")

    summary_data = []
    for tank in report.tank_summaries:
        summary_data.append(
            {
                "口座名": tank.account,
                "評価額 (円)": tank.valuation_total,
                "構成比率 (%)": tank.ratio,
                "含み損益": format_yen(tank.profit_loss_total, prefix_sign=True),
                "配分バー": tank.bar,
            }
        )
    summary_df = pd.DataFrame(summary_data)

    chart_col, table_col = st.columns([1, 1])

    with chart_col:
        pie_chart = (
            alt.Chart(summary_df)
            .mark_arc(innerRadius=65, outerRadius=115)
            .encode(
                theta=alt.Theta(field="評価額 (円)", type="quantitative"),
                color=alt.Color(
                    field="口座名", type="nominal", legend=alt.Legend(title="口座種別")
                ),
                tooltip=["口座名", "評価額 (円)", "構成比率 (%)", "含み損益"],
            )
            .properties(height=300)
        )
        st.altair_chart(pie_chart, use_container_width=True)

    with table_col:
        st.dataframe(
            summary_df[["口座名", "評価額 (円)", "構成比率 (%)", "含み損益"]].style.format(
                {
                    "評価額 (円)": "¥{:,.0f}",
                    "構成比率 (%)": "{:.1f}%",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # 3. 保有銘柄明細テーブル
    st.subheader("📋 保有銘柄明細テーブル")

    detail_rows = []
    for h in report.holdings:
        pl_str = (
            f"{format_yen(h.profit_loss, prefix_sign=True)} {format_rate(h.profit_loss_rate)}"
            if h.profit_loss is not None
            else "-"
        )
        units_display = f"{h.effective_units:,.1f}"

        detail_rows.append(
            {
                "口座": h.item.account,
                "銘柄名": h.item.name,
                "協会コード": h.item.code,
                "ISINコード": h.item.isin,
                "基準価額 (円)": h.nav,
                "保有口数": units_display,
                "評価額 (円)": h.valuation,
                "取得簿価 (円)": h.item.cost_basis if h.item.cost_basis > 0 else None,
                "含み損益": pl_str,
            }
        )

    detail_df = pd.DataFrame(detail_rows)

    st.dataframe(
        detail_df.style.format(
            {
                "基準価額 (円)": "¥{:,.0f}",
                "評価額 (円)": "¥{:,.0f}",
                "取得簿価 (円)": lambda x: f"¥{x:,.0f}" if pd.notna(x) else "-",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )


with tab_master:
    st.subheader("📝 保有資産マスター管理 (portfolio.csv)")
    st.caption(
        "`account, 協会コード, ISINコード, units, cost_basis` を管理します。"
        "銘柄名および最新基準価額は投信総合検索ライブラリーから自動取得されます。"
    )

    # プリセット選択補助
    with st.expander("💡 主要9銘柄プリセットから入力コードを選択", expanded=False):
        preset_names = [
            f"{code} | {info['name']}" for code, info in PRESET_FUNDS.items() if len(code) == 8
        ]
        selected_preset_str = st.selectbox(
            "主要銘柄リスト", ["-- 選択してください --", *sorted(preset_names)]
        )
        selected_code = ""
        selected_isin = ""
        if selected_preset_str and selected_preset_str != "-- 選択してください --":
            selected_code = selected_preset_str.split(" | ")[0]
            selected_isin = PRESET_FUNDS[selected_code]["isin"]
            st.info(f"選択中: 協会コード `{selected_code}` / ISINコード `{selected_isin}`")

    # 新規追加フォーム
    with st.form("add_holding_form", clear_on_submit=True):
        st.markdown("##### ➕ 新規保有資産の追加")
        add_col1, add_col2, add_col3 = st.columns(3)
        with add_col1:
            form_account = st.selectbox(
                "口座種別 (account)",
                ["法人", "NISA", "特定", "iDeCo", "DC", "一般"],
            )
        with add_col2:
            form_code = st.text_input(
                "協会コード (8桁半角英数字)",
                value=selected_code,
                max_chars=8,
                help="投資信託協会の8桁ファンドコード",
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
            )
        with add_col5:
            form_cost = st.number_input(
                "取得簿価 (cost_basis, 円 / 0は簿価管理不要)",
                min_value=0,
                value=0,
                step=10000,
            )

        submitted_add = st.form_submit_button("ポートフォリオに追加", use_container_width=True)
        if submitted_add:
            try:
                new_item = PortfolioItem(
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
                st.success(f"{form_account} に銘柄コード {new_item.code} を追加しました。")
                st.rerun()
            except Exception as ex:
                st.error(f"追加エラー: {ex}")

    st.divider()

    # データエディタによる編集・削除・一括保存
    st.markdown("##### 📋 登録済みポートフォリオの直接編集・削除")
    edit_data = [
        {
            "delete": False,
            "account": it.account,
            "code": it.code,
            "isin": it.isin,
            "units": it.units,
            "cost_basis": it.cost_basis,
            "name": it.name,
        }
        for it in portfolio_items
    ]
    edit_df = pd.DataFrame(edit_data)

    edited_df = st.data_editor(
        edit_df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_order=[
            "delete",
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
            "account": st.column_config.SelectboxColumn(
                "口座種別",
                options=["法人", "NISA", "特定", "iDeCo", "DC", "一般"],
                required=True,
            ),
            "code": st.column_config.TextColumn("協会コード", max_chars=8, required=True),
            "isin": st.column_config.TextColumn("ISINコード", max_chars=12, required=True),
            "units": st.column_config.NumberColumn("保有口数", min_value=0.0001, required=True),
            "cost_basis": st.column_config.NumberColumn("取得簿価(円)", min_value=0, required=True),
            "name": st.column_config.TextColumn("銘柄名(Web自動取得)", disabled=True),
        },
        key="portfolio_data_editor",
    )

    is_delete_series = edited_df["delete"].fillna(False).astype(bool)
    delete_count = int(is_delete_series.sum())

    if delete_count > 0:
        st.warning(f"⚠️ 削除対象として **{delete_count} 件** の銘柄にチェックが入っています（ON）。")
    else:
        st.caption(
            "※ 銘柄を削除する場合は、表の一番左端「削除」列のチェックボックスをONにしてください。"
        )

    col_save, col_delete = st.columns([1, 1])
    with col_save:
        save_btn = st.button(
            "💾 変更を portfolio.csv に保存して再計算",
            type="primary" if delete_count == 0 else "secondary",
            use_container_width=True,
            key="save_portfolio_changes_btn",
        )
    with col_delete:
        delete_btn = st.button(
            f"🗑️ チェックした銘柄 ({delete_count}件) を削除",
            type="primary" if delete_count > 0 else "secondary",
            disabled=(delete_count == 0),
            use_container_width=True,
            key="delete_portfolio_checked_btn",
        )

    if delete_btn and delete_count > 0:
        try:
            run_backup(app_name="pre_delete")
            remaining_items: list[PortfolioItem] = []
            for _, r in edited_df.iterrows():
                if not bool(r.get("delete", False)):
                    account_val = str(r["account"]).strip()
                    code_val = str(r["code"]).strip()
                    isin_val = str(r["isin"]).strip()
                    units_val = float(r["units"])
                    cost_val = int(r["cost_basis"])
                    if account_val and code_val:
                        remaining_items.append(
                            PortfolioItem(
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
            st.error(f"削除エラー: {del_err}")

    if save_btn:
        try:
            validated_save_items: list[PortfolioItem] = []
            for _, r in edited_df.iterrows():
                if bool(r.get("delete", False)):
                    continue
                account_val = str(r["account"]).strip()
                code_val = str(r["code"]).strip()
                isin_val = str(r["isin"]).strip()
                units_val = float(r["units"])
                cost_val = int(r["cost_basis"])
                if account_val and code_val:
                    validated_save_items.append(
                        PortfolioItem(
                            account=account_val,
                            code=code_val,
                            isin=isin_val,
                            name=str(r.get("name") or ""),
                            units=units_val,
                            cost_basis=cost_val,
                        )
                    )

            if not validated_save_items:
                st.error("保存対象の有効な銘柄データがありません。")
            else:
                if delete_count > 0:
                    run_backup(app_name="pre_delete")
                save_portfolio_csv(portfolio_csv_path, validated_save_items)
                st.cache_data.clear()
                st.success("portfolio.csv を正常に更新しました。最新の集計を実行します。")
                st.rerun()
        except Exception as save_err:
            st.error(f"保存エラー: {save_err}")

    # ---------------------------------------------------------
    # Zone 2-C: 標準ポートフォリオCSV直接アップロード
    # ---------------------------------------------------------
    st.divider()
    st.markdown("##### 📄 保有資産CSV (portfolio.csv) アップロード")
    st.caption("標準フォーマットのCSVをアップロードし、追記または洗い替えで登録します。")

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
        )

    if uploaded_std_csv is not None and st.button(
        "📥 CSVを取り込んでポートフォリオに反映",
        type="primary",
        key="btn_apply_std_csv",
        use_container_width=True,
    ):
        try:
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
            st.error(f"CSV取り込みエラー: {std_ex}")

    st.divider()

    # ---------------------------------------------------------
    # Zone 2-D: SBI証券CSVインポート
    # ---------------------------------------------------------
    st.subheader("📥 SBI証券CSVポートフォリオインポート")
    st.caption(
        "SBI証券のポートフォリオ管理画面からエクスポートしたCSVファイルを取り込み、"
        "銘柄名からの投信協会コード自動逆引き、事前バックアップ、および洗い替え/追記保存を実行します。"
    )

    sbi_file = st.file_uploader(
        "SBI証券のポートフォリオCSVを選択",
        type=["csv"],
        key="sbi_csv_uploader",
        help="SBI証券でダウンロードしたShift-JIS/CP932/UTF-8のCSVに対応しています。",
    )

    if sbi_file is not None:
        try:
            raw_csv_text = decode_csv_bytes(sbi_file.getvalue())
            sbi_records = parse_sbi_portfolio_csv(raw_csv_text)

            if not sbi_records:
                st.warning("アップロードされたCSVから有効な投資信託明細が検出されませんでした。")
            else:
                alias_store_path = _PROJECT_ROOT / "data" / "custom_fund_aliases.json"
                custom_aliases = load_custom_aliases(alias_store_path)

                # 検出されたセクション口座名の一覧
                detected_sections = sorted({r.raw_account_section for r in sbi_records})
                existing_accounts = sorted({it.account for it in portfolio_items})
                if not existing_accounts:
                    existing_accounts = ["法人", "NISA", "特定", "iDeCo", "DC", "一般"]

                st.markdown("##### 1. 口座（タンク）名マッピング設定")
                st.caption(
                    "SBI証券上の口座区分を、本アプリで管理する口座名（タンク）へ対応付けます。"
                )

                account_map: dict[str, str] = {}
                map_cols = st.columns(min(len(detected_sections), 3))
                for idx, section in enumerate(detected_sections):
                    col = map_cols[idx % len(map_cols)]
                    with col:
                        # デフォルト推論
                        from src.sbi_importer import extract_account_name

                        default_target = extract_account_name(section)
                        # 既存アカウントと近似するものがあれば選択肢の初期値にする
                        matched_initial = (
                            default_target
                            if default_target in existing_accounts
                            else existing_accounts[0]
                        )
                        options_list = sorted({*existing_accounts, default_target})
                        selected_acc = st.selectbox(
                            f"『{section}』の格納先",
                            options=options_list,
                            index=options_list.index(
                                default_target
                                if default_target in existing_accounts
                                else matched_initial
                            ),
                            key=f"acc_map_{idx}",
                        )
                        account_map[default_target] = selected_acc

                # 名寄せ解決
                candidates = resolve_candidates(
                    records=sbi_records,
                    existing_items=portfolio_items,
                    custom_aliases=custom_aliases,
                    account_override_map=account_map,
                )

                st.markdown("##### 2. インポート候補プレビュー & コード検証")
                unresolved_count = sum(1 for c in candidates if not c.is_resolved)

                if unresolved_count > 0:
                    st.warning(
                        f"⚠️ {unresolved_count} 件の銘柄で投信協会コード（8桁）の自動特定が未完了です。"
                        "下記の入力欄に8桁コードを入力すると自動学習され、次回以降も自動照合されます。"
                    )

                # 手動コード補完UI
                resolved_candidates: list[ImportCandidate] = []
                new_learned_aliases: dict[str, tuple[str, str]] = {}

                for c_idx, c in enumerate(candidates):
                    if not c.is_resolved:
                        with st.expander(f"未特定銘柄: {c.source_record.fund_name}", expanded=True):
                            input_col1, input_col2 = st.columns(2)
                            with input_col1:
                                manual_code = (
                                    st.text_input(
                                        "投信協会コード (8桁)",
                                        max_chars=8,
                                        key=f"manual_code_{c_idx}",
                                        help="例: 0331418A",
                                    )
                                    .strip()
                                    .upper()
                                )
                            with input_col2:
                                manual_isin = (
                                    st.text_input(
                                        "ISINコード (12桁, 任意)",
                                        max_chars=12,
                                        key=f"manual_isin_{c_idx}",
                                        help="例: JP90C000H1T1",
                                    )
                                    .strip()
                                    .upper()
                                )

                            if len(manual_code) == 8:
                                norm_k = normalize_string_key(c.source_record.fund_name)
                                new_learned_aliases[norm_k] = (manual_code, manual_isin)
                                resolved_candidates.append(
                                    ImportCandidate(
                                        source_record=c.source_record,
                                        target_account=c.target_account,
                                        resolved_code=manual_code,
                                        resolved_isin=manual_isin,
                                        is_resolved=True,
                                    )
                                )
                            else:
                                resolved_candidates.append(c)
                    else:
                        resolved_candidates.append(c)

                # 候補プレビューテーブル表示
                preview_rows = [
                    {
                        "ステータス": "✅ 照合完了" if rc.is_resolved else "❌ 未解決",
                        "格納口座": rc.target_account,
                        "ファンド名": rc.source_record.fund_name,
                        "協会コード": rc.resolved_code or "---",
                        "ISIN": rc.resolved_isin or "---",
                        "保有口数": rc.source_record.quantity,
                        "取得単価": rc.source_record.acquisition_price,
                        "算出簿価(円)": format_yen(rc.source_record.calculated_cost_basis),
                        "評価額(円)": format_yen(int(round(rc.source_record.valuation))),
                    }
                    for rc in resolved_candidates
                ]
                st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)

                st.markdown("##### 3. 反映方式の選択 & インポート確定")
                merge_mode_selected = st.radio(
                    "反映方式",
                    options=[
                        MergeMode.APPEND,
                        MergeMode.REPLACE_ALL,
                    ],
                    format_func=lambda m: {
                        MergeMode.APPEND: (
                            "【➕ 追記方式】既存の保有資産を維持し、今回分を追加（法人・個人の同一銘柄も別行として独立保持）"
                        ),
                        MergeMode.REPLACE_ALL: (
                            "【🔄 洗い替え方式】既存の portfolio.csv を全消去し、今回アップロードされたCSV内容で完全置換"
                        ),
                    }[m],
                )

                all_ready = all(rc.is_resolved for rc in resolved_candidates)

                if st.button(
                    "🚀 SBI証券ポートフォリオを取り込んで保存",
                    type="primary",
                    disabled=not all_ready,
                    use_container_width=True,
                ):
                    with st.spinner("事前セーフティバックアップおよびデータ統合を実行中..."):
                        # 1. 事前バックアップの強制実行
                        backup_res = run_backup(app_name="pre_sbi_import")
                        if not backup_res.get("success"):
                            st.error(
                                f"事前バックアップに失敗したため処理を中断しました: {backup_res.get('message')}"
                            )
                            st.stop()

                        # 2. 新規学習エイリアスの永続保存
                        if new_learned_aliases:
                            merged_aliases = {**custom_aliases, **new_learned_aliases}
                            save_custom_aliases(alias_store_path, merged_aliases)

                        # 3. マージ処理
                        merged_portfolio = merge_candidates_into_portfolio(
                            existing_items=portfolio_items,
                            resolved_candidates=resolved_candidates,
                            merge_mode=merge_mode_selected,
                        )

                        # 4. 原子的保存
                        save_portfolio_csv(portfolio_csv_path, merged_portfolio)
                        st.cache_data.clear()

                    st.success(
                        f"🎉 インポートが完了しました（全 {len(merged_portfolio)} 件）。事前バックアップ作成済み: {backup_res.get('filename')}"
                    )
                    st.rerun()

        except Exception as import_err:
            st.error(f"CSVインポート処理中にエラーが発生しました: {import_err}")
