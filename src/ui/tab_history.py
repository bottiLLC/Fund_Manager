"""ファンド別推移・履歴分析タブ描画コンポーネント。"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from src.formatter import format_yen
from src.history_db import PERIOD_OPTIONS, HistoryRepository, calculate_start_date


def render_history_tab(history_repo: HistoryRepository) -> None:
    """ファンド別推移・履歴分析タブを描画する。

    ファンドセレクタ、増減サマリーメトリクス、取得簿価・口数・現在値の時系列グラフ、
    および過去スナップショット履歴明細テーブルを表示する。

    Args:
        history_repo: ポートフォリオ履歴データベースリポジトリ。
    """
    st.subheader("📈 ファンド別推移・履歴分析")

    distinct_funds = history_repo.get_distinct_funds()
    if not distinct_funds:
        st.info(
            "ℹ️ 過去のファンド履歴スナップショットが記録されていません。ポートフォリオ評価データが記録されると時系列分析が可能になります。"
        )
        return

    # 1. ファンドセレクタと表示期間セレクタ
    col_fund, col_period = st.columns([3, 2])
    with col_fund:
        label_to_fund = {f.display_label: f for f in distinct_funds}
        selected_label = st.selectbox(
            "対象ファンドを選択",
            options=list(label_to_fund.keys()),
            index=0,
            help="「法人/個人」「格納口座」「協会コード」「ISIN」が一致する一意なファンドを選択します。",
        )
    with col_period:
        selected_period = st.radio(
            "表示期間",
            options=PERIOD_OPTIONS,
            index=3,
            horizontal=True,
            key="history_period_mode",
            help="チャートの表示期間を切り替えます。",
        )

    if not selected_label:
        return

    selected_fund = label_to_fund[selected_label]
    latest_date = history_repo.get_latest_recorded_date()
    start_date = calculate_start_date(latest_date, selected_period) if latest_date else None

    df_history = history_repo.get_fund_history_df(
        holder=selected_fund.holder,
        account=selected_fund.account,
        code=selected_fund.code,
        isin=selected_fund.isin,
        start_date=start_date,
    )

    if df_history.empty:
        st.warning("⚠️ 選択されたファンドの履歴データが見つかりませんでした。")
        return

    # 2. 増減サマリーカード
    first_row = df_history.iloc[0]
    latest_row = df_history.iloc[-1]

    delta_units = float(latest_row["units"]) - float(first_row["units"])
    delta_cost = int(latest_row["cost_basis"]) - int(first_row["cost_basis"])
    delta_val = int(latest_row["valuation"]) - int(first_row["valuation"])
    delta_nav = float(latest_row["nav"]) - float(first_row["nav"])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            label="最新保有口数",
            value=f"{latest_row['units']:,.1f} 口",
            delta=f"{delta_units:+,.1f} 口 (初回比)" if len(df_history) > 1 else None,
            border=True,
        )
    with col2:
        st.metric(
            label="最新取得簿価",
            value=format_yen(int(latest_row["cost_basis"])),
            delta=format_yen(delta_cost, prefix_sign=True) + " (初回比)"
            if len(df_history) > 1 and latest_row["cost_basis"] > 0
            else None,
            border=True,
        )
    with col3:
        st.metric(
            label="最新現在値 (評価額)",
            value=format_yen(int(latest_row["valuation"])),
            delta=format_yen(delta_val, prefix_sign=True) + " (初回比)"
            if len(df_history) > 1
            else None,
            border=True,
        )
    with col4:
        st.metric(
            label="最新基準価額",
            value=f"¥{latest_row['nav']:,.0f}",
            delta=f"{delta_nav:+,.0f} 円 (初回比)" if len(df_history) > 1 else None,
            border=True,
        )

    st.divider()

    # 3. 取得簿価・口数・現在値（基準価額/評価額）の時系列推移チャート
    st.subheader("📊 時系列推移チャート")
    tab_chart_val, tab_chart_cost, tab_chart_units = st.tabs(
        ["💹 資産推移（評価額面 × 取得簿価折れ線）", "💰 取得簿価推移", "📦 保有口数推移"]
    )

    with tab_chart_val:
        # 1. 評価額面グラフ（資産ボリューム）
        val_area = (
            alt.Chart(df_history)
            .mark_area(opacity=0.35, color="#1f77b4")
            .encode(
                x=alt.X(
                    "recorded_date:T",
                    title="記録日",
                    axis=alt.Axis(format="%Y-%m-%d", labelAngle=-45),
                ),
                y=alt.Y("valuation:Q", title="資産額 (円)", axis=alt.Axis(format="~s")),
                tooltip=[
                    alt.Tooltip("recorded_date:T", title="記録日", format="%Y-%m-%d"),
                    alt.Tooltip("valuation:Q", title="評価額 (円)", format=",.0f"),
                    alt.Tooltip("cost_basis:Q", title="取得簿価 (円)", format=",.0f"),
                    alt.Tooltip("profit_loss:Q", title="含み損益 (円)", format=",.0f"),
                ],
            )
        )

        # 2. 取得簿価折れ線グラフ（元本ライン）
        cost_line = (
            alt.Chart(df_history)
            .mark_line(point=True, color="#2ca02c", strokeWidth=2)
            .encode(
                x=alt.X("recorded_date:T"),
                y=alt.Y("cost_basis:Q", title="資産額 (円)"),
                tooltip=[
                    alt.Tooltip("recorded_date:T", title="記録日", format="%Y-%m-%d"),
                    alt.Tooltip("valuation:Q", title="評価額 (円)", format=",.0f"),
                    alt.Tooltip("cost_basis:Q", title="取得簿価 (円)", format=",.0f"),
                ],
            )
        )

        # 3. 合成レイヤーチャート（面が線を上回れば含み益、下回れば含み損）
        asset_layer_chart = (
            alt.layer(val_area, cost_line)
            .resolve_scale(y="shared")
            .properties(
                height=320,
                title=f"{selected_fund.name} - 資産推移（評価額面グラフ × 取得簿価折れ線）",
            )
        )
        st.altair_chart(asset_layer_chart, width="stretch")

        # 基準価額 (NAV) 単体推移
        nav_chart = (
            alt.Chart(df_history)
            .mark_line(point=True, color="#ff7f0e")
            .encode(
                x=alt.X(
                    "recorded_date:T",
                    title="記録日",
                    axis=alt.Axis(format="%Y-%m-%d", labelAngle=-45),
                ),
                y=alt.Y("nav:Q", title="基準価額 (円/1万口)", axis=alt.Axis(format="~s")),
                tooltip=[
                    alt.Tooltip("recorded_date:T", title="記録日", format="%Y-%m-%d"),
                    alt.Tooltip("nav:Q", title="基準価額 (円)", format=",.0f"),
                ],
            )
            .properties(height=240, title=f"{selected_fund.name} - 基準価額 (円) 推移")
        )
        st.altair_chart(nav_chart, width="stretch")

    with tab_chart_cost:
        cost_chart = (
            alt.Chart(df_history)
            .mark_line(point=True, color="#2ca02c")
            .encode(
                x=alt.X(
                    "recorded_date:T",
                    title="記録日",
                    axis=alt.Axis(format="%Y-%m-%d", labelAngle=-45),
                ),
                y=alt.Y("cost_basis:Q", title="取得簿価 (円)", axis=alt.Axis(format="~s")),
                tooltip=[
                    alt.Tooltip("recorded_date:T", title="記録日", format="%Y-%m-%d"),
                    alt.Tooltip("cost_basis:Q", title="取得簿価 (円)", format=",.0f"),
                ],
            )
            .properties(height=320, title=f"{selected_fund.name} - 取得簿価 (円) 推移")
        )
        st.altair_chart(cost_chart, width="stretch")

    with tab_chart_units:
        units_chart = (
            alt.Chart(df_history)
            .mark_line(point=True, color="#9467bd")
            .encode(
                x=alt.X(
                    "recorded_date:T",
                    title="記録日",
                    axis=alt.Axis(format="%Y-%m-%d", labelAngle=-45),
                ),
                y=alt.Y("units:Q", title="保有口数 (口)", axis=alt.Axis(format="~s")),
                tooltip=[
                    alt.Tooltip("recorded_date:T", title="記録日", format="%Y-%m-%d"),
                    alt.Tooltip("units:Q", title="保有口数 (口)", format=",.1f"),
                ],
            )
            .properties(height=320, title=f"{selected_fund.name} - 保有口数 (口) 推移")
        )
        st.altair_chart(units_chart, width="stretch")

    st.divider()

    # 4. 履歴明細テーブル & CSVエクスポート
    st.subheader("📋 履歴明細データ")
    display_df = df_history.sort_values("recorded_date", ascending=False).copy()
    display_df["保有口数"] = display_df["units"].apply(lambda x: f"{x:,.1f}")
    display_df["取得簿価"] = display_df["cost_basis"].apply(
        lambda x: f"¥{x:,.0f}" if x > 0 else "-"
    )
    display_df["基準価額"] = display_df["nav"].apply(lambda x: f"¥{x:,.0f}")
    display_df["現在評価額"] = display_df["valuation"].apply(lambda x: f"¥{x:,.0f}")
    display_df["含み損益"] = display_df["profit_loss"].apply(
        lambda x: format_yen(x, prefix_sign=True) if pd.notna(x) else "-"
    )

    table_cols = [
        "recorded_date",
        "保有口数",
        "取得簿価",
        "基準価額",
        "現在評価額",
        "含み損益",
    ]
    renamed_df = display_df[table_cols].rename(columns={"recorded_date": "記録日"})

    st.dataframe(renamed_df, width="stretch", hide_index=True)

    csv_data = df_history.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        label=f"📥 {selected_fund.name} の履歴データをCSVダウンロード",
        data=csv_data,
        file_name=f"history_{selected_fund.code}_{selected_fund.holder}.csv",
        mime="text/csv",
        type="secondary",
        icon=":material/download:",
        width="stretch",
    )
