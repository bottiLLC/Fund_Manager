"""投資信託ポートフォリオ評価 Streamlit Web GUI アプリケーション。"""

from __future__ import annotations

import sys
from datetime import date
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
from src.nav_fetcher import fetch_latest_nav
from src.portfolio_loader import load_portfolio_csv

st.set_page_config(
    page_title="Fund Manager - 投資信託資産管理",
    page_icon="📈",
    layout="wide",
)


@st.cache_data(ttl=3600)
def cached_fetch_nav(
    target_codes_tuple: tuple[str, ...],
    cache_dir_str: str,
) -> tuple[str, dict[str, float]]:
    """基準価額の取得結果を1時間キャッシュする。"""
    return fetch_latest_nav(
        target_codes=set(target_codes_tuple),
        cache_dir=Path(cache_dir_str),
    )


# ---------------------------------------------------------
# Zone 1: Sidebar (Configuration, Backup, Metadata)
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 設定 & 管理")
    dc_base_input = st.date_input(
        "DC仮想積立 基準日",
        value=date(2025, 1, 1),
        help="DC口座で指定銘柄の仮想購入口数を算出するための積立開始日",
    )

    force_refresh = st.button("🔄 基準価額データを再取得", use_container_width=True)
    if force_refresh:
        st.cache_data.clear()
        st.success("キャッシュをクリアしました。最新データを再取得します。")
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
    st.caption("Fund Manager v0.1.0 | Python 3.14+")

# ---------------------------------------------------------
# Zone 2: Header
# ---------------------------------------------------------
st.title("📈 投資信託 ポートフォリオ評価ダッシュボード")
st.caption(
    "投資信託協会の最新基準価額とローカル資産を突き合わせ、口座（タンク）ごとの資産評価とアロケーションを可視化します。"
)

# ---------------------------------------------------------
# Zone 3: Main Workspace (Form, Computation, Metrics & Visualization)
# ---------------------------------------------------------
portfolio_csv_path = _PROJECT_ROOT / "data" / "portfolio.csv"

try:
    portfolio_items = load_portfolio_csv(portfolio_csv_path)
except Exception as e:
    st.error(f"保有資産CSVの読み込みエラー: {e}")
    st.stop()

target_codes = tuple(sorted({item.code for item in portfolio_items}))
cache_dir = _PROJECT_ROOT / "data" / "cache"

with st.spinner("基準価額データを取得中..."):
    as_of_date, nav_map = cached_fetch_nav(target_codes, str(cache_dir))

report = evaluate_portfolio(
    items=portfolio_items,
    nav_map=nav_map,
    as_of_date=as_of_date,
    dc_base_date=dc_base_input,
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
            (report.total_profit_loss / (report.total_valuation - report.total_profit_loss)) * 100.0
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
    # Altairによるリッチなドーナツチャート
    pie_chart = (
        alt.Chart(summary_df)
        .mark_arc(innerRadius=65, outerRadius=115)
        .encode(
            theta=alt.Theta(field="評価額 (円)", type="quantitative"),
            color=alt.Color(field="口座名", type="nominal", legend=alt.Legend(title="口座種別")),
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
    if h.virtual_units > 0:
        units_display += " *"

    detail_rows.append(
        {
            "口座": h.item.account,
            "銘柄名": h.item.name,
            "コード": h.item.code,
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

if any(h.virtual_units > 0 for h in report.holdings):
    st.caption("※ 保有口数末尾の '*' はDC口座の経過月数に応じた仮想積立加山口数を含みます。")
