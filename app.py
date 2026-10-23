"""投資信託ポートフォリオ評価 Streamlit Web GUI アプリケーション。"""

from __future__ import annotations

import sys
from pathlib import Path

# Deterministic sys.path configuration
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import streamlit as st

from src.calculator import create_snapshots_from_report, evaluate_portfolio
from src.history_db import HistoryRepository
from src.nav_fetcher import NavFetchResult, fetch_latest_nav_and_names
from src.portfolio_loader import PRESET_FUNDS, load_portfolio_csv
from src.ui.header import render_app_header
from src.ui.sbi_wizard import render_sbi_import_section
from src.ui.sidebar import render_app_sidebar
from src.ui.tab_dashboard import render_dashboard_tab
from src.ui.tab_history import render_history_tab
from src.ui.tab_master import render_master_tab

# ---------------------------------------------------------
# Page Configuration
# ---------------------------------------------------------
st.set_page_config(
    page_title="Fund Manager - 投資信託資産管理",
    page_icon="📈",
    layout="wide",
)


# ---------------------------------------------------------
# Caching Layer
# ---------------------------------------------------------
@st.cache_data(ttl=3600)
def cached_fetch_nav_and_names(
    targets_tuple: tuple[tuple[str, str], ...],
    cache_dir_str: str,
) -> NavFetchResult:
    """基準価額および銘柄名の取得結果を1時間キャッシュする。"""
    return fetch_latest_nav_and_names(
        targets=dict(targets_tuple),
        cache_dir=Path(cache_dir_str),
    )


# ---------------------------------------------------------
# Zone 1: Sidebar (Configuration, Backup, Metadata)
# ---------------------------------------------------------
render_app_sidebar(project_root=_PROJECT_ROOT)

# ---------------------------------------------------------
# Zone 1: Header (Title, Objective, Version Metadata)
# ---------------------------------------------------------
render_app_header()

# ---------------------------------------------------------
# Zone 2: Data Loading & Portfolio Evaluation
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
    fetch_result = cached_fetch_nav_and_names(target_pairs, str(cache_dir))
    as_of_date = fetch_result[0]
    nav_map = fetch_result[1]
    name_map = fetch_result[2]
    fetched_at = getattr(fetch_result, "fetched_at", None)
    fallback_funds = getattr(fetch_result, "fallback_funds", [])

    # サイドバーの再取得要求に対するフィードバック生成
    if st.session_state.pop("refresh_pending", False):
        if "(Fallback)" in as_of_date:
            st.session_state["refresh_feedback"] = (
                "error",
                "外部通信に失敗したため、内蔵フォールバック値を使用しました。",
            )
        elif fallback_funds:
            st.session_state["refresh_feedback"] = (
                "warning",
                f"一部銘柄（{len(fallback_funds)}件）の取得に失敗したためフォールバック値を使用しました。",
            )
        else:
            st.session_state["refresh_feedback"] = (
                "success",
                "キャッシュをクリアし、最新データを再取得しました。",
            )
        st.rerun()

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
    fetched_at=fetched_at,
    fallback_funds=fallback_funds,
)

# ---------------------------------------------------------
# Zone 3: History Persistence & Snapshot Upsert
# ---------------------------------------------------------
history_db_path = _PROJECT_ROOT / "data" / "fund_history.db"
history_repo = HistoryRepository(history_db_path)

if report.holdings:
    snapshots = create_snapshots_from_report(report)
    history_repo.upsert_snapshots(snapshots)

# ---------------------------------------------------------
# Zone 4: Main Workspace (Tabs segregation)
# ---------------------------------------------------------
tab_dashboard, tab_history, tab_master = st.tabs(
    ["📊 ポートフォリオ評価", "📈 ファンド推移", "📝 保有資産マスター管理"]
)

with tab_dashboard:
    render_dashboard_tab(report=report, history_repo=history_repo)

with tab_history:
    render_history_tab(history_repo=history_repo)

with tab_master:
    render_master_tab(
        portfolio_csv_path=portfolio_csv_path,
        portfolio_items=portfolio_items,
    )
    st.divider()
    render_sbi_import_section(
        project_root=_PROJECT_ROOT,
        portfolio_items=portfolio_items,
        portfolio_csv_path=portfolio_csv_path,
    )
