"""Rebalance tab rendering for asset genre configuration and trade estimation."""

from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from src.formatter import format_yen
from src.models import (
    ASSET_GENRE_OPTIONS,
    AssetGenre,
    PortfolioReport,
    RebalanceConfig,
    RebalanceSummary,
)
from src.rebalancer import calculate_rebalance_summary, save_rebalance_config


def _render_trade_action_cards(summary: RebalanceSummary) -> None:
    """総額不変リバランスおよびノーセル買い増し目安の2カードを描画する。"""
    st.markdown("##### 💡 リバランス売買アクション")
    card_switch, card_nosell = st.columns(2)

    with card_switch, st.container(border=True):
        st.markdown("**🔄 総額不変リバランス（売却＋購入）**")
        st.caption(
            f"現在の総資産（{format_yen(summary.total_valuation)}）を維持して基準比率へ調整する場合の売買額です。"
        )
        eq = summary.equity
        bd = summary.bond

        if eq.trade_amount == 0:
            st.success("現在の資産比率は基準比率と一致しています（売買不要）。")
        elif eq.trade_amount < 0:
            sell_amt = abs(eq.trade_amount)
            buy_amt = bd.trade_amount
            st.info(
                f"📉 **株式** を **{format_yen(sell_amt)}** 売却し、📈 **債券** を **{format_yen(buy_amt)}** 購入してください。"
            )
        else:
            sell_amt = abs(bd.trade_amount)
            buy_amt = eq.trade_amount
            st.info(
                f"📉 **債券** を **{format_yen(sell_amt)}** 売却し、📈 **株式** を **{format_yen(buy_amt)}** 購入してください。"
            )

        m_col1, m_col2 = st.columns(2)
        with m_col1:
            st.metric(
                label=f"{eq.genre.value}（{eq.direction.value}）",
                value=format_yen(eq.trade_amount, prefix_sign=True),
                delta=f"現在 {eq.current_ratio:.1f}% ({eq.ratio_diff:+.1f}pt)",
                delta_color="off",
                border=True,
            )
        with m_col2:
            st.metric(
                label=f"{bd.genre.value}（{bd.direction.value}）",
                value=format_yen(bd.trade_amount, prefix_sign=True),
                delta=f"現在 {bd.current_ratio:.1f}% ({bd.ratio_diff:+.1f}pt)",
                delta_color="off",
                border=True,
            )

    with card_nosell, st.container(border=True):
        st.markdown("**➕ ノーセルリバランス目安（買い増しのみ）**")
        st.caption("既存資産を売却せず、追加投資のみで基準比率へ到達させるための必要額です。")
        if not summary.no_sell_achievable:
            st.warning(
                "⚠️ 基準比率が 0% の資産を現在保有しているため、売却なしの買い増しのみでは目標比率へ到達できません。"
                "総額不変リバランス（売却）をご検討ください。"
            )
        elif summary.no_sell_buy_genre is None or not summary.no_sell_buy_amount:
            st.success("すでに基準比率と一致しているため、追加購入は不要です。")
        else:
            st.info(
                f"📈 **{summary.no_sell_buy_genre.value}** を **{format_yen(summary.no_sell_buy_amount)}** 買い増すと基準比率に到達します。"
            )
            st.metric(
                label="必要追加資金",
                value=format_yen(summary.no_sell_buy_amount),
                delta=f"買い増し後総資産: {format_yen(summary.no_sell_post_total)}",
                delta_color="off",
                border=True,
            )


def _render_ratio_comparison(summary: RebalanceSummary) -> None:
    """現在比率と基準比率の比較グラフおよびジャンル別明細テーブルを描画する。"""
    st.markdown("##### 📊 現在比率 vs 基準比率の比較")
    eq = summary.equity
    bd = summary.bond

    comp_df = pd.DataFrame(
        [
            {"区分": "現在比率", "ジャンル": eq.genre.value, "比率 (%)": eq.current_ratio},
            {"区分": "現在比率", "ジャンル": bd.genre.value, "比率 (%)": bd.current_ratio},
            {"区分": "基準比率", "ジャンル": eq.genre.value, "比率 (%)": eq.target_ratio},
            {"区分": "基準比率", "ジャンル": bd.genre.value, "比率 (%)": bd.target_ratio},
        ]
    )

    comp_chart = (
        alt.Chart(comp_df)
        .mark_bar(size=26)
        .encode(
            x=alt.X(
                "比率 (%):Q",
                stack="normalize",
                axis=alt.Axis(format="%", title=None),
            ),
            y=alt.Y("区分:N", sort=["現在比率", "基準比率"], title=None),
            color=alt.Color(
                "ジャンル:N",
                scale=alt.Scale(domain=["株式", "債券"], range=["#1f77b4", "#2ca02c"]),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=[
                alt.Tooltip("区分:N", title="区分"),
                alt.Tooltip("ジャンル:N", title="ジャンル"),
                alt.Tooltip("比率 (%):Q", title="比率 (%)", format=".1f"),
            ],
        )
        .properties(height=130)
    )
    st.altair_chart(comp_chart, width="stretch")

    table_rows = [
        {
            "ジャンル": alloc.genre.value,
            "現在評価額 (円)": alloc.valuation_total,
            "現在比率 (%)": alloc.current_ratio,
            "目標評価額 (円)": alloc.target_valuation,
            "基準比率 (%)": alloc.target_ratio,
            "乖離 (pt)": alloc.ratio_diff,
            "売買指示": alloc.direction.value,
            "売買金額 (円)": format_yen(alloc.trade_amount, prefix_sign=True),
        }
        for alloc in (eq, bd)
    ]
    table_df = pd.DataFrame(table_rows)
    st.dataframe(
        table_df.style.format(
            {
                "現在評価額 (円)": "¥{:,.0f}",
                "現在比率 (%)": "{:.1f}%",
                "目標評価額 (円)": "¥{:,.0f}",
                "基準比率 (%)": "{:.1f}%",
                "乖離 (pt)": "{:+.1f}pt",
            }
        ),
        width="stretch",
        hide_index=True,
    )


def render_rebalance_tab(
    report: PortfolioReport,
    config: RebalanceConfig,
    config_path: Path,
) -> None:
    """リバランス設定・資産クラス集計・売買提案タブを描画する。"""
    if not report.holdings:
        st.info(
            "ℹ️ 現在、保有銘柄が登録されていません。「📝 保有資産マスター管理」タブから銘柄を追加、またはCSVを取り込んでください。"
        )
        return

    st.subheader("⚖️ 資産クラス配分 & リバランス計算")

    # 1. 基準比率設定（ライブ試算 + 永続保存）
    with st.container(border=True):
        st.markdown("##### 🎯 基準比率の設定（株式 : 債券 = 合計 100%）")
        ctrl_col, ratio_col, save_col = st.columns([3, 1, 1])
        with ctrl_col:
            selected_equity_ratio = float(
                st.slider(
                    "株式の基準比率 (%)",
                    min_value=0.0,
                    max_value=100.0,
                    value=float(config.target_equity_ratio),
                    step=1.0,
                    format="%.1f%%",
                    key="rebalance_target_equity_slider",
                    help="株式の目標比率を設定します。債券の目標比率は自動的に 100% - 株式比率 となります。",
                )
            )
        selected_bond_ratio = round(100.0 - selected_equity_ratio, 1)
        with ratio_col:
            st.metric(
                label="債券の基準比率",
                value=f"{selected_bond_ratio:.1f}%",
                border=True,
            )
        has_ratio_change = abs(selected_equity_ratio - config.target_equity_ratio) >= 0.05
        with save_col:
            save_ratio_btn = st.button(
                "基準比率を保存",
                icon=":material/save:",
                type="primary" if has_ratio_change else "secondary",
                width="stretch",
                key="save_rebalance_ratio_btn",
                help="設定した基準比率を rebalance_config.json に保存します。",
            )

        if has_ratio_change:
            st.caption(
                f"※ 試算中（未保存）: 保存済み基準比率は 株式 {config.target_equity_ratio:.1f}% / 債券 {config.target_bond_ratio:.1f}% です。"
            )

        if save_ratio_btn:
            try:
                updated_cfg = RebalanceConfig(
                    target_equity_ratio=selected_equity_ratio,
                    fund_genres=dict(config.fund_genres),
                )
                save_rebalance_config(config_path, updated_cfg)
                st.toast("基準比率を保存しました。", icon=":material/check_circle:")
                st.rerun()
            except Exception as ex:
                st.error(f"【保存エラー】基準比率の保存に失敗しました: {ex}")

    preview_config = RebalanceConfig(
        target_equity_ratio=selected_equity_ratio,
        fund_genres=dict(config.fund_genres),
    )
    summary = calculate_rebalance_summary(report=report, config=preview_config)

    # 2. リバランス売買提案カード
    _render_trade_action_cards(summary)

    st.divider()

    # 3. 現在比率 vs 基準比率 比較可視化 & テーブル
    _render_ratio_comparison(summary)

    st.divider()

    # 4. 銘柄ごとのジャンル分け設定
    st.markdown("##### 🏷️ 銘柄ごとのジャンル分け設定（株式 / 債券）")
    st.caption(
        "同一銘柄コードを複数口座で保有している場合、ここでの分類が全口座へ一括適用されます。"
        "SBI証券CSVの洗い替えインポート後も設定は保持されます。"
    )

    fund_rows = [
        {
            "code": f.code,
            "name": f.name,
            "holding_count": f.holding_count,
            "valuation_total": f.valuation_total,
            "genre": f.genre.value,
            "status": "設定済" if f.is_configured else "自動推定",
        }
        for f in summary.fund_summaries
    ]
    fund_df = pd.DataFrame(
        fund_rows,
        columns=["code", "name", "holding_count", "valuation_total", "genre", "status"],
    )

    edited_df = st.data_editor(
        fund_df,
        num_rows="fixed",
        width="stretch",
        hide_index=True,
        column_config={
            "code": st.column_config.TextColumn("協会コード", disabled=True),
            "name": st.column_config.TextColumn("銘柄名", disabled=True),
            "holding_count": st.column_config.NumberColumn(
                "保有口座数", disabled=True, format="%d"
            ),
            "valuation_total": st.column_config.NumberColumn(
                "評価額合計 (円)", disabled=True, format="¥%d"
            ),
            "genre": st.column_config.SelectboxColumn(
                "ジャンル",
                options=[g.value for g in ASSET_GENRE_OPTIONS],
                required=True,
                help="株式または債券を選択してください。",
            ),
            "status": st.column_config.TextColumn("設定状態", disabled=True),
        },
        key="rebalance_fund_genre_editor",
    )

    save_genres_btn = st.button(
        "銘柄ジャンル設定を保存",
        icon=":material/save:",
        type="primary",
        width="stretch",
        key="save_rebalance_genres_btn",
        help="各銘柄の株式/債券分類を rebalance_config.json に保存します。",
    )

    if save_genres_btn:
        try:
            merged_genres = dict(config.fund_genres)
            for _, row in edited_df.iterrows():
                code_val = str(row["code"]).strip().upper()
                genre_val = AssetGenre(str(row["genre"]).strip())
                if code_val:
                    merged_genres[code_val] = genre_val

            updated_cfg = RebalanceConfig(
                target_equity_ratio=selected_equity_ratio,
                fund_genres=merged_genres,
            )
            save_rebalance_config(config_path, updated_cfg)
            st.toast("銘柄ジャンル設定を保存しました。", icon=":material/check_circle:")
            st.rerun()
        except Exception as ex:
            st.error(f"【保存エラー】銘柄ジャンル設定の保存に失敗しました: {ex}")
