"""Dashboard tab rendering for portfolio valuation and allocation."""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.formatter import format_rate, format_yen
from src.history_db import PERIOD_OPTIONS, HistoryRepository, calculate_start_date
from src.models import PortfolioReport


def render_dashboard_tab(
    report: PortfolioReport,
    history_repo: HistoryRepository | None = None,
) -> None:
    """ポートフォリオ評価ダッシュボードタブを描画する。

    KPIメトリクス、総資産推移積み上げ面グラフ（取得価額折れ線重畳）、口座別配分ドーナツチャート、および保有銘柄明細テーブルを表示する。

    Args:
        report: ポートフォリオ集計・評価レポート。
        history_repo: ポートフォリオ履歴データベースリポジトリ。
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
    elif report.fallback_funds:
        failed_str = ", ".join(report.fallback_funds)
        st.warning(
            f"⚠️ **一部銘柄フォールバック中**: 次の銘柄の最新データ取得に失敗したため、内蔵固定値を使用しています: "
            f"`{failed_str}`"
        )
    elif "(Cached)" in report.as_of_date:
        st.info(
            f"ℹ️ **ローカルキャッシュ使用中**: `./data/cache/` の基準価額を表示しています（基準日: {report.as_of_date}）。"
        )

    # 基準価額取得日時表示（総資産評価額の上部）
    if report.fetched_at:
        st.caption(
            f"🕒 **基準価額取得日時**: {report.fetched_at} （データ基準日: {report.as_of_date}）"
        )

    # 1. KPI メトリクス表示
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                label="総資産評価額",
                value=format_yen(report.total_valuation),
                border=True,
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
                    border=True,
                )
            else:
                st.metric(label="総含み損益", value="-", border=True)
        with col3:
            st.metric(
                label="基準価額のデータ基準日",
                value=report.as_of_date,
                help=(
                    "投信協会が公表している基準価額の算出基準日です。"
                    "土日祝を除く平日の夜間（19:00〜21:30頃）に当日付データへと更新されます。"
                ),
                border=True,
            )

    st.divider()

    # 2. 総資産の推移（積み上げ面グラフ ＆ 取得価額合計）
    if history_repo is not None:
        st.subheader("📈 総資産の推移（積み上げ面グラフ ＆ 取得価額合計）")
        col_period, col_group = st.columns(2)
        with col_period:
            selected_period = st.radio(
                "表示期間",
                options=PERIOD_OPTIONS,
                index=3,
                horizontal=True,
                key="dashboard_period_mode",
                help="チャートの表示期間を切り替えます。",
            )
        with col_group:
            group_mode = st.radio(
                "積み上げ区分",
                options=["銘柄別", "格納口座別", "法人/個人別"],
                index=0,
                horizontal=True,
                key="dashboard_stacked_group_mode",
                help="面グラフの積み上げ要素を切り替えます。",
            )

        latest_date = history_repo.get_latest_recorded_date()
        start_date = calculate_start_date(latest_date, selected_period) if latest_date else None

        col_map = {"銘柄別": "name", "格納口座別": "account", "法人/個人別": "holder"}
        target_group_col = col_map.get(group_mode, "name")

        stacked_df = history_repo.get_stacked_asset_df(
            group_by=target_group_col, start_date=start_date
        )
        total_df = history_repo.get_total_asset_history_df(start_date=start_date)
        if not stacked_df.empty and not total_df.empty:
            area_chart = (
                alt.Chart(stacked_df)
                .mark_area(opacity=0.6)
                .encode(
                    x=alt.X(
                        "recorded_date:T",
                        title="記録基準日",
                        axis=alt.Axis(format="%Y-%m-%d", labelAngle=-45),
                    ),
                    y=alt.Y(
                        "valuation:Q",
                        title="総資産評価額 (円)",
                        stack="zero",
                        axis=alt.Axis(format="~s"),
                    ),
                    color=alt.Color(
                        "group_key:N",
                        title="内訳",
                        legend=alt.Legend(orient="bottom", columns=3),
                    ),
                    tooltip=[
                        alt.Tooltip("recorded_date:T", title="記録日", format="%Y-%m-%d"),
                        alt.Tooltip("group_key:N", title="区分"),
                        alt.Tooltip("valuation:Q", title="評価額 (円)", format=",.0f"),
                    ],
                )
            )

            # 2. 取得価額合計の折れ線グラフ
            line_chart = (
                alt.Chart(total_df)
                .mark_line(point=True, color="#ff4b4b", strokeWidth=2.5)
                .encode(
                    x=alt.X("recorded_date:T"),
                    y=alt.Y("total_cost_basis:Q", title="資産額 (円)"),
                    tooltip=[
                        alt.Tooltip("recorded_date:T", title="記録日", format="%Y-%m-%d"),
                        alt.Tooltip("total_valuation:Q", title="総評価額 (円)", format=",.0f"),
                        alt.Tooltip("total_cost_basis:Q", title="総取得価額 (円)", format=",.0f"),
                        alt.Tooltip("total_profit_loss:Q", title="総含み損益 (円)", format=",.0f"),
                    ],
                )
            )

            # 3. Y軸スケールを共有して合成
            combined_chart = (
                alt.layer(area_chart, line_chart).resolve_scale(y="shared").properties(height=360)
            )
            st.altair_chart(combined_chart, width="stretch")
        elif latest_date:
            st.info("ℹ️ 指定された期間内の履歴データが存在しません。「全期間」を選択してください。")
        else:
            st.info(
                "ℹ️ 過去の履歴データがまだ記録されていません。スナップショットが記録されると時系列グラフが表示されます。"
            )

        st.divider()

    # 3. タンク別サマリー & アセットアロケーション可視化

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
        st.altair_chart(pie_chart, width="stretch")

    with table_col:
        st.dataframe(
            summary_df[["口座名", "評価額 (円)", "構成比率 (%)", "含み損益"]].style.format(
                {
                    "評価額 (円)": "¥{:,.0f}",
                    "構成比率 (%)": "{:.1f}%",
                }
            ),
            width="stretch",
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
        width="stretch",
        hide_index=True,
    )
