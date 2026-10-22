"""SBI Securities CSV import wizard component."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from backup_manager import run_backup
from src.formatter import format_yen
from src.models import HOLDER_OPTIONS, PortfolioItem
from src.portfolio_loader import save_portfolio_csv
from src.sbi_importer import (
    ImportCandidate,
    MergeMode,
    decode_csv_bytes,
    extract_account_name,
    load_custom_aliases,
    merge_candidates_into_portfolio,
    normalize_string_key,
    parse_sbi_portfolio_csv,
    resolve_candidates,
    save_custom_aliases,
)


def render_sbi_import_section(
    project_root: Path,
    portfolio_items: list[PortfolioItem],
    portfolio_csv_path: Path,
) -> None:
    """SBI証券CSVポートフォリオインポートセクションを描画する。

    口座マッピング設定、未特定銘柄コード補完、2段階安全確認、および反映処理を行う。

    Args:
        project_root: プロジェクトルートの絶対パス。
        portfolio_items: 現在読み込まれている保有資産リスト。
        portfolio_csv_path: portfolio.csv のファイルパス。
    """
    st.subheader("📥 SBI証券CSVポートフォリオインポート")
    st.caption(
        "SBI証券のポートフォリオ管理画面からエクスポートしたCSVファイルを取り込み、"
        "銘柄名からの投信協会コード自動逆引き、事前バックアップ、および洗い替え/追記保存を実行します。"
    )

    # 取込完了通知＆結果詳細の表示
    if "sbi_import_result" in st.session_state:
        res = st.session_state["sbi_import_result"]
        st.success(
            f"🎉 SBI証券CSVの取り込みが完了しました（全 {res['count']} 件保存完了）。事前バックアップ: `{res['backup_filename']}`"
        )
        with st.expander("📊 最新の取込結果サマリー・明細を確認", expanded=True):
            st.markdown(f"- **反映方式**: {res['mode_label']}")
            st.markdown(f"- **保存ファイル**: `{portfolio_csv_path.name}`")
            if res.get("items"):
                st.dataframe(pd.DataFrame(res["items"]), use_container_width=True)
            if st.button(
                "✕ 取込結果メッセージを閉じる", type="secondary", key="btn_close_sbi_result"
            ):
                del st.session_state["sbi_import_result"]
                st.rerun()

    sbi_file = st.file_uploader(
        "SBI証券のポートフォリオCSVを選択",
        type=["csv"],
        key="sbi_csv_uploader",
        help="SBI証券でダウンロードしたShift-JIS/CP932/UTF-8のCSVに対応しています。",
    )

    if sbi_file is None:
        return

    try:
        raw_csv_text = decode_csv_bytes(sbi_file.getvalue())
        sbi_records = parse_sbi_portfolio_csv(raw_csv_text)

        if not sbi_records:
            st.warning("⚠️ アップロードされたCSVから有効な投資信託明細が検出されませんでした。")
            return

        alias_store_path = project_root / "data" / "custom_fund_aliases.json"
        custom_aliases = load_custom_aliases(alias_store_path)

        # 検出されたセクション口座名の一覧
        detected_sections = sorted({r.raw_account_section for r in sbi_records})
        existing_accounts = sorted({it.account for it in portfolio_items})
        if not existing_accounts:
            existing_accounts = ["法人", "NISA", "特定", "iDeCo", "DC", "一般"]

        st.markdown("##### 1. 所有者区分（法人/個人）および格納口座マッピング設定")
        st.caption(
            "SBI証券CSVから読み取った口座区分を自動入力しています。法人/個人区分は手入力（選択）してください。"
        )

        global_holder = st.radio(
            "今回インポートする明細の所有者区分（デフォルト）",
            options=list(HOLDER_OPTIONS),
            horizontal=True,
            index=0,
            key="sbi_global_holder_radio",
            help="インポート対象の明細全体の標準的な所有者区分を指定します。",
        )

        account_map: dict[str, str] = {}
        holder_map: dict[str, str] = {}
        map_cols = st.columns(min(len(detected_sections), 3))
        for idx, section in enumerate(detected_sections):
            col = map_cols[idx % len(map_cols)]
            with col:
                default_target = extract_account_name(section)
                options_list = sorted(
                    {
                        *existing_accounts,
                        default_target,
                        "NISA預り（つみたて投資枠）",
                        "NISA預り（成長投資枠）",
                        "NISA預り（旧つみたてNISA預り）",
                        "一般預り",
                        "特定預り",
                    }
                )
                holder_options = list(HOLDER_OPTIONS)
                if "DC" in section or default_target == "DC":
                    default_sec_holder_idx = holder_options.index("個人(DC)")
                elif global_holder in holder_options:
                    default_sec_holder_idx = holder_options.index(global_holder)
                else:
                    default_sec_holder_idx = 0

                selected_holder = st.selectbox(
                    f"『{section}』の法人/個人",
                    options=holder_options,
                    index=default_sec_holder_idx,
                    key=f"sec_holder_{idx}",
                    help=f"{section} の所有者区分",
                )
                selected_acc = st.selectbox(
                    f"『{section}』の格納口座",
                    options=options_list,
                    index=options_list.index(
                        default_target if default_target in options_list else options_list[0]
                    ),
                    key=f"acc_map_{idx}",
                    help="CSVのセクションから自動入力されています。必要に応じて変更可能です。",
                )
                account_map[default_target] = selected_acc
                holder_map[default_target] = selected_holder

        # 名寄せ解決
        candidates = resolve_candidates(
            records=sbi_records,
            existing_items=portfolio_items,
            custom_aliases=custom_aliases,
            account_override_map=account_map,
            default_holder=global_holder,
            holder_override_map=holder_map,
        )

        st.markdown("##### 2. インポート候補プレビュー & コード検証")
        unresolved_count = sum(1 for c in candidates if not c.is_resolved)

        if unresolved_count > 0:
            st.warning(
                f"⚠️ **{unresolved_count} 件** の銘柄で投信協会コード（8桁）の自動特定が未完了です。"
                "下記の入力欄に8桁コードを入力すると自動学習され、次回以降も自動照合されます。"
            )

        # 未特定銘柄コード入力・反映設定フォーム
        resolved_candidates: list[ImportCandidate] = []
        new_learned_aliases: dict[str, tuple[str, str]] = {}

        with st.form("sbi_finalize_import_form", clear_on_submit=False):
            for c_idx, c in enumerate(candidates):
                if not c.is_resolved:
                    st.markdown(f"**未特定銘柄: {c.source_record.fund_name}**")
                    input_col1, input_col2 = st.columns(2)
                    with input_col1:
                        manual_code = (
                            st.text_input(
                                "投信協会コード (8桁)",
                                max_chars=8,
                                key=f"manual_code_{c_idx}",
                                help="例: 0331418A（半角英数字8桁）",
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
                                holder=c.holder,
                                resolved_code=manual_code,
                                resolved_isin=manual_isin,
                                is_resolved=True,
                            )
                        )
                    else:
                        resolved_candidates.append(c)
                else:
                    resolved_candidates.append(c)

            st.markdown("##### 3. 反映方式の選択 & インポート確定")
            merge_mode_selected = st.radio(
                "反映方式",
                options=[
                    MergeMode.APPEND,
                    MergeMode.REPLACE_ALL,
                ],
                format_func=lambda m: {
                    MergeMode.APPEND: (
                        "【➕ 追記方式】既存の保有資産を維持し、今回分を追加（同一銘柄も別行として保持）"
                    ),
                    MergeMode.REPLACE_ALL: (
                        "【🔄 洗い替え方式】既存の portfolio.csv を全消去し、今回アップロードされたCSV内容で完全置換"
                    ),
                }[m],
                help="追記方式または洗い替え（全置換）方式を選択します。",
            )

            confirm_replace_all = st.checkbox(
                "⚠️ 洗い替え（全置換）を選択した場合、既存の保有資産データが全て消去されることを確認しました",
                value=False,
                help="不可逆な破壊的操作に対する安全確認です。",
            )

            submit_sbi = st.form_submit_button(
                "🚀 SBI証券ポートフォリオを取り込んで保存",
                type="primary",
                use_container_width=True,
            )

        # プレビューテーブル表示
        preview_rows = [
            {
                "ステータス": "✅ 照合完了" if rc.is_resolved else "❌ 未解決",
                "法人/個人": rc.holder,
                "格納口座": rc.target_account,
                "ファンド名": rc.source_record.fund_name,
                "協会コード": rc.resolved_code or "---",
                "ISIN": rc.resolved_isin or "---",
                "保有口数": rc.source_record.quantity,
                "取得単価": rc.source_record.acquisition_price,
                "取得価額(簿価, 円)": format_yen(rc.source_record.calculated_cost_basis),
                "評価額(円)": format_yen(int(round(rc.source_record.valuation))),
            }
            for rc in resolved_candidates
        ]
        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)

        if submit_sbi:
            all_ready = all(rc.is_resolved for rc in resolved_candidates)
            if not all_ready:
                st.error(
                    "【エラー】投信協会コードが未特定の銘柄が存在します。\n"
                    "【対処方法】上記の未特定銘柄フォームに8桁の半角英数コードを入力してください。"
                )
                st.stop()

            if merge_mode_selected == MergeMode.REPLACE_ALL and not confirm_replace_all:
                st.error(
                    "【安全確認エラー】洗い替え方式を実行するには確認チェックが必要です。\n"
                    "【対処方法】上記の警告確認チェックボックスをONにして再度実行してください。"
                )
                st.stop()

            with st.spinner("事前セーフティバックアップおよびデータ統合を実行中..."):
                # 1. 事前バックアップの強制実行
                backup_res = run_backup(app_name="pre_sbi_import")
                if not backup_res.get("success"):
                    st.error(
                        f"【致命的エラー】事前バックアップに失敗したため処理を中断しました: {backup_res.get('message')}\n"
                        "【対処方法】バックアップ保存先フォルダの権限を確認してください。"
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

                # 5. 結果セッションステート設定
                mode_text = (
                    "追記方式（既存データ保持＋今回分追加）"
                    if merge_mode_selected == MergeMode.APPEND
                    else "洗い替え方式（今回分で全置換）"
                )
                st.session_state["sbi_import_result"] = {
                    "count": len(merged_portfolio),
                    "backup_filename": backup_res.get("filename", "バックアップ完了"),
                    "mode_label": mode_text,
                    "items": [
                        {
                            "法人/個人": item.holder,
                            "格納口座": item.account,
                            "協会コード": item.code,
                            "ISIN": item.isin,
                            "銘柄名": item.name,
                            "保有口数": item.units,
                            "取得簿価(円)": format_yen(item.cost_basis),
                        }
                        for item in merged_portfolio
                    ],
                }

            st.rerun()

    except Exception as import_err:
        st.error(
            f"【CSVインポート処理エラー】{import_err}\n"
            "【対処方法】CSVファイルの文字コードおよびヘッダー形式（SBI証券標準フォーマット）を確認してください。"
        )
