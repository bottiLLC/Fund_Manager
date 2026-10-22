"""Dashboard tab rendering for portfolio valuation and allocation."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.formatter import format_rate, format_yen
from src.models import PortfolioReport


def render_dashboard_tab(report: PortfolioReport) -> None:
    """ポートフォリオ評価ダッシュボードタブを描画する。

    KPIメトリクス、口座別配分ドーナツチャート、および保有銘柄明細テーブルを表示する。

    Args:
        report: ポートフォリオ集計・評価レポート。
    """
    if not report.holdings:
        st.info(
            "ℹ️ 現在、保有銘柄が登録されていません。「📝 保有資産マスター管理」タブから銘柄を追加、またはCSVを取り込んでください。"
        )
        return

    if "(Fallback)" in report.as_of_date:
        st.warning(
            "⚠️ **内蔵フォールバック値を使用中**: 投信協会URLからのデータ取得に失敗したため、"
            "内蔵の固定値データを表示しています。「再取得」を押しても外部通信が失敗する場合は値は変化しません。"
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

    summary_data = [
        {
            "口座名": tank.account,
            "評価額 (円)": tank.valuation_total,
            "構成比率 (%)": tank.ratio,
            "含み損益": format_yen(tank.profit_loss_total, prefix_sign=True),
            "配分バー": tank.bar,
        }
        for tank in report.tank_summaries
    ]
    summary_df = pd.DataFrame(
        summary_data,
        columns=["口座名", "評価額 (円)", "構成比率 (%)", "含み損益", "配分バー"],
    )

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
                "法人/個人": h.item.holder,
                "格納口座": h.item.account,
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
