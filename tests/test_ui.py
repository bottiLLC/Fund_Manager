"""Unit tests for src.ui presentation layer modules."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.history_db import HistoryRepository
from src.models import HoldingEvaluation, PortfolioItem, PortfolioReport, TankSummary
from src.sbi_importer import ImportCandidate, SbiRawRecord
from src.ui.header import render_app_header
from src.ui.sbi_wizard import render_sbi_import_section
from src.ui.sidebar import render_app_sidebar
from src.ui.tab_dashboard import render_dashboard_tab
from src.ui.tab_history import render_history_tab
from src.ui.tab_master import render_master_tab


def mock_columns(spec: object, *_: object, **__: object) -> list[MagicMock]:
    """st.columns の可変長モック生成ヘルパー。"""
    if isinstance(spec, (list, tuple)):
        return [MagicMock() for _ in range(len(spec))]
    if isinstance(spec, int):
        return [MagicMock() for _ in range(spec)]
    return [MagicMock(), MagicMock()]


def test_render_app_header() -> None:
    """ヘッダーの描画およびメタデータ表示を検証する。"""
    with patch("streamlit.title") as mock_title, patch("streamlit.caption") as mock_caption:
        render_app_header(version="v1.0.0", python_ver="3.14")
        mock_title.assert_called_once()
        assert "投資信託 ポートフォリオ評価ダッシュボード" in mock_title.call_args[0][0]
        assert mock_caption.call_count == 2
        assert "v1.0.0" in mock_caption.call_args_list[1][0][0]


def test_render_app_sidebar_refresh_and_upload(tmp_path: Path) -> None:
    """サイドバーの再取得ボタンおよびCSV手動登録の挙動を検証する。"""
    session_mock: dict[str, object] = {"cache_cleared_msg": "前回メッセージ"}
    uploaded_file = MagicMock()
    uploaded_file.getvalue.return_value = b"header\n0331418A,30000\n"

    with (
        patch("streamlit.sidebar"),
        patch("streamlit.header"),
        patch("streamlit.button", side_effect=[True, False]),
        patch("streamlit.cache_data.clear") as mock_clear,
        patch("streamlit.rerun") as mock_rerun,
        patch("streamlit.session_state", session_mock),
        patch("streamlit.file_uploader", return_value=uploaded_file),
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.form"),
        patch("streamlit.form_submit_button", return_value=False),
        patch("streamlit.caption"),
    ):
        render_app_sidebar(project_root=tmp_path)
        mock_clear.assert_called()
        mock_rerun.assert_called()


def test_render_app_sidebar_backup_flow(tmp_path: Path) -> None:
    """サイドバーのバックアップ設定更新および即時実行の分岐を検証する。"""
    session_mock: dict[str, object] = {}

    with (
        patch("streamlit.sidebar"),
        patch("streamlit.header"),
        patch("streamlit.button", side_effect=[False, True]),
        patch("streamlit.session_state", session_mock),
        patch("streamlit.file_uploader", return_value=None),
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.form"),
        patch("streamlit.text_input", return_value="C:/new_backup_dir"),
        patch("streamlit.form_submit_button", return_value=True),
        patch("src.ui.sidebar.get_backup_dir", return_value=Path("C:/old_dir")),
        patch(
            "src.ui.sidebar.set_backup_dir",
            return_value={"success": True, "message": "保存先更新完了"},
        ),
        patch(
            "src.ui.sidebar.run_backup",
            return_value={
                "success": True,
                "message": "バックアップ成功",
                "timestamp": "2026-10-22",
                "destination": "C:/dst",
            },
        ),
        patch("streamlit.success") as mock_success,
        patch("streamlit.caption"),
        patch("streamlit.rerun") as mock_rerun,
    ):
        render_app_sidebar(project_root=tmp_path)
        mock_success.assert_any_call("保存先更新完了")
        mock_success.assert_any_call("バックアップ成功")
        mock_rerun.assert_called_once()

    # バックアップ失敗時のエラー表示
    with (
        patch("streamlit.sidebar"),
        patch("streamlit.header"),
        patch("streamlit.button", side_effect=[False, True]),
        patch("streamlit.session_state", session_mock),
        patch("streamlit.file_uploader", return_value=None),
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.form"),
        patch("streamlit.text_input", return_value="C:/new_backup_dir"),
        patch("streamlit.form_submit_button", return_value=True),
        patch("src.ui.sidebar.get_backup_dir", return_value=Path("C:/old_dir")),
        patch(
            "src.ui.sidebar.set_backup_dir",
            return_value={"success": False, "message": "権限エラー"},
        ),
        patch("src.ui.sidebar.run_backup", return_value={"success": False, "message": "容量不足"}),
        patch("streamlit.error") as mock_error,
        patch("streamlit.caption"),
    ):
        render_app_sidebar(project_root=tmp_path)
        assert mock_error.call_count >= 2


def test_render_dashboard_tab_empty() -> None:
    """保有データが空のときの案内メッセージ表示を検証する。"""
    report = PortfolioReport(
        as_of_date="2026-10-22",
        holdings=[],
        tank_summaries=[],
        total_valuation=0,
        total_profit_loss=None,
    )
    with patch("streamlit.info") as mock_info:
        render_dashboard_tab(report)
        mock_info.assert_called_once()
        assert "現在、保有銘柄が登録されていません" in mock_info.call_args[0][0]


def test_render_dashboard_tab_populated() -> None:
    """保有データが存在する場合の各種KPI、グラフ、テーブル描画を検証する。"""
    item = PortfolioItem(
        holder="個人",
        account="NISA預り（成長投資枠）",
        code="0331418A",
        isin="JP90C000H1T1",
        name="テスト全世界株",
        units=10000.0,
        cost_basis=150000,
    )
    holding = HoldingEvaluation(
        item=item,
        nav=20000.0,
        valuation=200000,
        profit_loss=50000,
        profit_loss_rate=0.3333,
        effective_units=10000.0,
    )
    tank = TankSummary(
        account="NISA預り（成長投資枠）",
        valuation_total=200000,
        ratio=100.0,
        bar="##########",
        profit_loss_total=50000,
    )
    report = PortfolioReport(
        as_of_date="2026-10-22 (Cached)",
        holdings=[holding],
        tank_summaries=[tank],
        total_valuation=200000,
        total_profit_loss=50000,
    )

    with (
        patch("streamlit.info") as mock_info,
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.metric") as mock_metric,
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.altair_chart"),
        patch("streamlit.dataframe") as mock_df,
    ):
        render_dashboard_tab(report)
        mock_info.assert_called_once()
        assert "(Cached)" in mock_info.call_args[0][0]
        assert mock_metric.call_count == 3
        assert mock_df.call_count == 2


def test_render_dashboard_tab_fallback_and_no_profit_loss() -> None:
    """フォールバック値および取得簿価なし（損益None）の描画を検証する。"""
    item = PortfolioItem(
        holder="個人",
        account="特定預り",
        code="0331418A",
        isin="JP90C000H1T1",
        name="テスト株",
        units=5000.0,
        cost_basis=0,
    )
    holding = HoldingEvaluation(
        item=item,
        nav=10000.0,
        valuation=50000,
        profit_loss=None,
        profit_loss_rate=None,
        effective_units=5000.0,
    )
    report = PortfolioReport(
        as_of_date="2026-10-22 (Fallback)",
        holdings=[holding],
        tank_summaries=[],
        total_valuation=50000,
        total_profit_loss=None,
    )

    with (
        patch("streamlit.warning") as mock_warning,
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.metric"),
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.altair_chart"),
        patch("streamlit.dataframe"),
    ):
        render_dashboard_tab(report)
        mock_warning.assert_called_once()
        assert "内蔵フォールバック値を使用中" in mock_warning.call_args[0][0]


def test_render_master_tab_add_item(tmp_path: Path) -> None:
    """新規保有資産追加フォームの正常系およびエラー系を検証する。"""
    csv_file = tmp_path / "portfolio.csv"
    items: list[PortfolioItem] = []

    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", side_effect=["0331418A | テスト", "個人", "特定預り"]),
        patch("streamlit.info"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.text_input", side_effect=["0331418A", "JP90C000H1T1"]),
        patch("streamlit.number_input", side_effect=[10000.0, 150000]),
        patch("streamlit.form_submit_button", side_effect=[True, False]),
        patch("streamlit.cache_data.clear") as mock_clear,
        patch("streamlit.success") as mock_success,
        patch("streamlit.rerun") as mock_rerun,
        patch("streamlit.data_editor", return_value=MagicMock(iterrows=lambda: iter([]))),
        patch("streamlit.checkbox", return_value=False),
        patch("streamlit.button", return_value=False),
        patch("streamlit.divider"),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=items)
        mock_clear.assert_called()
        mock_success.assert_called()
        mock_rerun.assert_called()


def test_render_master_tab_validation_error(tmp_path: Path) -> None:
    """新規追加時のバリデーションエラー表示を検証する。"""
    csv_file = tmp_path / "portfolio.csv"
    items: list[PortfolioItem] = []

    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", side_effect=["-- 選択してください --", "個人", "特定預り"]),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.text_input", side_effect=["INVALID", "INVALID"]),
        patch("streamlit.number_input", side_effect=[10000.0, 150000]),
        patch("streamlit.form_submit_button", side_effect=[True, False]),
        patch("streamlit.error") as mock_error,
        patch("streamlit.data_editor", return_value=MagicMock(iterrows=lambda: iter([]))),
        patch("streamlit.checkbox", return_value=False),
        patch("streamlit.button", return_value=False),
        patch("streamlit.divider"),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=items)
        mock_error.assert_called()
        assert "追加エラー" in mock_error.call_args[0][0]


def test_render_master_tab_delete_and_save(tmp_path: Path) -> None:
    """データエディタの変更保存および2段階確認削除の挙動を検証する。"""
    csv_file = tmp_path / "portfolio.csv"
    import pandas as pd

    df_data = pd.DataFrame(
        [
            {
                "delete": True,
                "holder": "個人",
                "account": "特定預り",
                "code": "0331418A",
                "isin": "JP90C000H1T1",
                "units": 1000.0,
                "cost_basis": 10000,
                "name": "A",
            },
            {
                "delete": False,
                "holder": "法人",
                "account": "一般預り",
                "code": "03312187",
                "isin": "JP90C000H1T2",
                "units": 2000.0,
                "cost_basis": 20000,
                "name": "B",
            },
        ]
    )

    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", return_value="-- 選択してください --"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.form_submit_button", return_value=False),
        patch("streamlit.data_editor", return_value=df_data),
        patch("streamlit.warning"),
        patch("streamlit.checkbox", return_value=True),
        patch("streamlit.button", side_effect=[False, True]),  # col_save=False, col_delete=True
        patch("src.ui.tab_master.run_backup") as mock_backup,
        patch("src.ui.tab_master.save_portfolio_csv") as mock_save,
        patch("streamlit.cache_data.clear") as mock_clear,
        patch("streamlit.success") as mock_success,
        patch("streamlit.rerun") as mock_rerun,
        patch("streamlit.divider"),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=[])
        mock_backup.assert_called_once()
        mock_save.assert_called_once()
        saved_items = mock_save.call_args[0][1]
        assert len(saved_items) == 1
        assert saved_items[0].code == "03312187"
        mock_clear.assert_called()
        mock_success.assert_called()
        mock_rerun.assert_called()


def test_render_master_tab_delete_error(tmp_path: Path) -> None:
    """削除処理中に例外が発生した場合のエラー表示を検証する。"""
    csv_file = tmp_path / "portfolio.csv"
    import pandas as pd

    df_data = pd.DataFrame(
        [
            {
                "delete": True,
                "holder": "個人",
                "account": "特定預り",
                "code": "0331418A",
                "isin": "JP90C000H1T1",
                "units": 1000.0,
                "cost_basis": 10000,
                "name": "A",
            }
        ]
    )

    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", return_value="-- 選択してください --"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.form_submit_button", return_value=False),
        patch("streamlit.data_editor", return_value=df_data),
        patch("streamlit.warning"),
        patch("streamlit.checkbox", return_value=True),
        patch("streamlit.button", side_effect=[False, True]),
        patch("src.ui.tab_master.run_backup", side_effect=RuntimeError("バックアップ失敗")),
        patch("streamlit.error") as mock_error,
        patch("streamlit.divider"),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=[])
        mock_error.assert_called()
        assert "削除エラー" in mock_error.call_args[0][0]


def test_render_master_tab_save_button_flow(tmp_path: Path) -> None:
    """データエディタの保存ボタン押下による正常保存、空データ時、例外発生時の分岐を検証する。"""
    csv_file = tmp_path / "portfolio.csv"
    import pandas as pd

    # deleteチェックありを含む保存（delete_count > 0 の時のバックアップ実行パスを検証）
    df_valid_with_del = pd.DataFrame(
        [
            {
                "delete": True,
                "holder": "個人",
                "account": "特定預り",
                "code": "0331418A",
                "isin": "JP90C000H1T1",
                "units": 1000.0,
                "cost_basis": 10000,
                "name": "A",
            },
            {
                "delete": False,
                "holder": "個人",
                "account": "特定預り",
                "code": "03312187",
                "isin": "JP90C000H1T2",
                "units": 2000.0,
                "cost_basis": 20000,
                "name": "B",
            },
        ]
    )

    # 1. 正常保存 (deleteチェックありで保存を押下し、未チェック行のみが保存されバックアップが走る)
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", return_value="-- 選択してください --"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.form_submit_button", return_value=False),
        patch("streamlit.data_editor", return_value=df_valid_with_del),
        patch("streamlit.warning"),
        patch("streamlit.checkbox", return_value=False),
        patch("streamlit.button", side_effect=[True, False]),  # save_btn=True
        patch("src.ui.tab_master.run_backup") as mock_bk,
        patch("src.ui.tab_master.save_portfolio_csv") as mock_save,
        patch("streamlit.cache_data.clear"),
        patch("streamlit.success") as mock_success,
        patch("streamlit.rerun"),
        patch("streamlit.divider"),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=[])
        mock_bk.assert_called_once()
        mock_save.assert_called_once()
        mock_success.assert_called()

    # 2. 有効データなしエラー
    df_empty = pd.DataFrame(
        [
            {
                "delete": True,
                "holder": "個人",
                "account": "特定預り",
                "code": "0331418A",
                "isin": "JP90C000H1T1",
                "units": 1000.0,
                "cost_basis": 10000,
                "name": "A",
            }
        ]
    )
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", return_value="-- 選択してください --"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.form_submit_button", return_value=False),
        patch("streamlit.data_editor", return_value=df_empty),
        patch("streamlit.warning"),
        patch("streamlit.checkbox", return_value=False),
        patch("streamlit.button", side_effect=[True, False]),
        patch("streamlit.error") as mock_error,
        patch("streamlit.divider"),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=[])
        mock_error.assert_called()
        assert "保存対象の有効な銘柄データがありません" in mock_error.call_args[0][0]

    # 3. 保存時例外エラー
    df_single = pd.DataFrame(
        [
            {
                "delete": False,
                "holder": "個人",
                "account": "特定預り",
                "code": "0331418A",
                "isin": "JP90C000H1T1",
                "units": 1000.0,
                "cost_basis": 10000,
                "name": "A",
            }
        ]
    )
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", return_value="-- 選択してください --"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.form_submit_button", return_value=False),
        patch("streamlit.data_editor", return_value=df_single),
        patch("streamlit.button", side_effect=[True, False]),
        patch("src.ui.tab_master.save_portfolio_csv", side_effect=OSError("ディスク満杯")),
        patch("streamlit.error") as mock_error,
        patch("streamlit.divider"),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=[])
        mock_error.assert_called()
        assert "保存エラー" in mock_error.call_args[0][0]


def test_render_master_tab_std_csv_upload(tmp_path: Path) -> None:
    """標準CSVアップロードの追記および洗い替えセーフティ確認を検証する。"""
    csv_file = tmp_path / "portfolio.csv"
    csv_mock = MagicMock()
    csv_mock.getvalue.return_value = (
        "account,code,isin,units,cost_basis\n特定預り,0331418A,JP90C000H1T1,1000,10000\n".encode()
    )

    # 1. 追記モード（append）での正常インポート
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", return_value="-- 選択してください --"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.data_editor", return_value=MagicMock(iterrows=lambda: iter([]))),
        patch("streamlit.button", return_value=False),
        patch("streamlit.file_uploader", return_value=csv_mock),
        patch("streamlit.radio", return_value="append"),
        patch("streamlit.checkbox", return_value=False),
        patch("src.ui.tab_master.run_backup"),
        patch("src.ui.tab_master.save_portfolio_csv") as mock_save,
        patch("streamlit.cache_data.clear") as mock_clear,
        patch("streamlit.success") as mock_success,
        patch("streamlit.rerun") as mock_rerun,
        patch("streamlit.divider"),
        patch("streamlit.form_submit_button", return_value=True),
    ):
        existing_item = PortfolioItem(
            holder="個人",
            account="NISA",
            code="03311181",
            isin="JP90C000H1T3",
            name="A",
            units=100.0,
            cost_basis=1000,
        )
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=[existing_item])
        mock_save.assert_called_once()
        # 既存1件 + 取り込み1件 = 2件
        assert len(mock_save.call_args[0][1]) == 2
        mock_clear.assert_called()
        mock_success.assert_called()
        mock_rerun.assert_called()

    # 2. 洗い替え未確認エラー
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", return_value="-- 選択してください --"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.data_editor", return_value=MagicMock(iterrows=lambda: iter([]))),
        patch("streamlit.button", return_value=False),
        patch("streamlit.file_uploader", return_value=csv_mock),
        patch("streamlit.radio", return_value="replace_all"),
        patch("streamlit.checkbox", return_value=False),  # confirm_replace_std = False
        patch("streamlit.error") as mock_error,
        patch("streamlit.divider"),
        patch("streamlit.form_submit_button", return_value=True),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=[])
        mock_error.assert_called()
        assert "安全確認エラー" in mock_error.call_args[0][0]

    # 3. 洗い替え確認済みでの正常インポート
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", return_value="-- 選択してください --"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.data_editor", return_value=MagicMock(iterrows=lambda: iter([]))),
        patch("streamlit.button", return_value=False),
        patch("streamlit.file_uploader", return_value=csv_mock),
        patch("streamlit.radio", return_value="replace_all"),
        patch("streamlit.checkbox", return_value=True),  # confirm_replace_std = True
        patch("src.ui.tab_master.run_backup"),
        patch("src.ui.tab_master.save_portfolio_csv") as mock_save,
        patch("streamlit.cache_data.clear") as mock_clear,
        patch("streamlit.success") as mock_success,
        patch("streamlit.rerun") as mock_rerun,
        patch("streamlit.divider"),
        patch("streamlit.form_submit_button", return_value=True),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=[])
        mock_save.assert_called_once()
        assert len(mock_save.call_args[0][1]) == 1
        mock_clear.assert_called()
        mock_success.assert_called()
        mock_rerun.assert_called()

    # 4. ファイル未選択エラー
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", return_value="-- 選択してください --"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.data_editor", return_value=MagicMock(iterrows=lambda: iter([]))),
        patch("streamlit.button", return_value=False),
        patch("streamlit.file_uploader", return_value=None),
        patch("streamlit.radio", return_value="append"),
        patch("streamlit.checkbox", return_value=False),
        patch("streamlit.error") as mock_error,
        patch("streamlit.divider"),
        patch("streamlit.form_submit_button", return_value=True),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=[])
        mock_error.assert_called()
        assert "CSVファイルが選択されていません" in mock_error.call_args[0][0]

    # 5. 解析時例外エラー
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.expander"),
        patch("streamlit.selectbox", return_value="-- 選択してください --"),
        patch("streamlit.form"),
        patch("streamlit.markdown"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.data_editor", return_value=MagicMock(iterrows=lambda: iter([]))),
        patch("streamlit.button", return_value=False),
        patch("streamlit.file_uploader", return_value=csv_mock),
        patch("streamlit.radio", return_value="append"),
        patch("streamlit.checkbox", return_value=False),
        patch(
            "src.ui.tab_master.parse_portfolio_csv_content",
            side_effect=ValueError("フォーマット異常"),
        ),
        patch("streamlit.error") as mock_error,
        patch("streamlit.divider"),
        patch("streamlit.form_submit_button", return_value=True),
    ):
        render_master_tab(portfolio_csv_path=csv_file, portfolio_items=[])
        mock_error.assert_called()
        assert "CSV取り込みエラー" in mock_error.call_args[0][0]


def test_render_sbi_import_section_branches(tmp_path: Path) -> None:
    """SBI証券インポートセクションの早期リターン、未特定銘柄、検証エラー、バックアップ失敗等を検証する。"""
    portfolio_csv = tmp_path / "portfolio.csv"

    # 1. ファイル未選択時（早期リターン）
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.file_uploader", return_value=None),
    ):
        render_sbi_import_section(
            project_root=tmp_path, portfolio_items=[], portfolio_csv_path=portfolio_csv
        )

    # 2. 空明細時（警告表示）
    mock_empty_file = MagicMock()
    mock_empty_file.getvalue.return_value = b""
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.file_uploader", return_value=mock_empty_file),
        patch("src.ui.sbi_wizard.parse_sbi_portfolio_csv", return_value=[]),
        patch("streamlit.warning") as mock_warn,
    ):
        render_sbi_import_section(
            project_root=tmp_path, portfolio_items=[], portfolio_csv_path=portfolio_csv
        )
        mock_warn.assert_called_once()
        assert "有効な投資信託明細が検出されませんでした" in mock_warn.call_args[0][0]

    class CustomStop(BaseException):
        pass

    # 3. 未特定銘柄あり・入力未完了での送信時エラー
    sbi_mock = MagicMock()
    sbi_mock.getvalue.return_value = """\
"投資信託（金額/DC口座）"
"ファンド名","買付日","数量","取得単価","現在値","損益","評価額"
"謎の未登録投資信託","----/--/--",1000,10000,12000,2000,12000
""".encode("cp932")

    unresolved_candidate = ImportCandidate(
        source_record=SbiRawRecord(
            raw_account_section="投資信託（金額/DC口座）",
            fund_name="謎の未登録投資信託",
            quantity=1000.0,
            acquisition_price=10000.0,
            current_price=12000.0,
            profit_loss=2000.0,
            valuation=12000.0,
        ),
        target_account="DC",
        holder="個人(DC)",
        resolved_code="",
        resolved_isin="",
        is_resolved=False,
    )

    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.file_uploader", return_value=sbi_mock),
        patch("src.ui.sbi_wizard.resolve_candidates", return_value=[unresolved_candidate]),
        patch("streamlit.markdown"),
        patch("streamlit.radio", side_effect=["その他区分", "append"]),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.selectbox", side_effect=["個人(DC)", "DC"]),
        patch("streamlit.form"),
        patch("streamlit.text_input", side_effect=["", ""]),  # 未入力
        patch("streamlit.checkbox", return_value=True),
        patch("streamlit.form_submit_button", return_value=True),
        patch("streamlit.dataframe"),
        patch("streamlit.error") as mock_error,
        patch("streamlit.stop", side_effect=CustomStop),
    ):
        with pytest.raises(CustomStop):
            render_sbi_import_section(
                project_root=tmp_path, portfolio_items=[], portfolio_csv_path=portfolio_csv
            )
        mock_error.assert_called()
        assert "投信協会コードが未特定の銘柄が存在します" in mock_error.call_args[0][0]

    # 4. 洗い替え未確認エラー
    resolved_candidate = ImportCandidate(
        source_record=unresolved_candidate.source_record,
        target_account="DC",
        holder="個人(DC)",
        resolved_code="0331418A",
        resolved_isin="JP90C000H1T1",
        is_resolved=True,
    )

    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.file_uploader", return_value=sbi_mock),
        patch("src.ui.sbi_wizard.resolve_candidates", return_value=[resolved_candidate]),
        patch("streamlit.markdown"),
        patch("streamlit.radio", side_effect=["個人", "replace_all"]),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.selectbox", side_effect=["個人(DC)", "DC"]),
        patch("streamlit.form"),
        patch("streamlit.checkbox", return_value=False),  # confirm_replace_all = False
        patch("streamlit.form_submit_button", return_value=True),
        patch("streamlit.dataframe"),
        patch("streamlit.error") as mock_error,
        patch("streamlit.stop", side_effect=CustomStop),
    ):
        with pytest.raises(CustomStop):
            render_sbi_import_section(
                project_root=tmp_path, portfolio_items=[], portfolio_csv_path=portfolio_csv
            )
        mock_error.assert_called()
        assert "洗い替え方式を実行するには確認チェックが必要です" in mock_error.call_args[0][0]

    # 5. 事前バックアップ失敗エラー
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.file_uploader", return_value=sbi_mock),
        patch("src.ui.sbi_wizard.resolve_candidates", return_value=[resolved_candidate]),
        patch("streamlit.markdown"),
        patch("streamlit.radio", side_effect=["個人", "append"]),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.selectbox", side_effect=["個人(DC)", "DC"]),
        patch("streamlit.form"),
        patch("streamlit.checkbox", return_value=True),
        patch("streamlit.form_submit_button", return_value=True),
        patch("streamlit.dataframe"),
        patch(
            "src.ui.sbi_wizard.run_backup", return_value={"success": False, "message": "書込不可"}
        ),
        patch("streamlit.error") as mock_error,
        patch("streamlit.stop", side_effect=CustomStop),
    ):
        with pytest.raises(CustomStop):
            render_sbi_import_section(
                project_root=tmp_path, portfolio_items=[], portfolio_csv_path=portfolio_csv
            )
        mock_error.assert_called()
        assert "事前バックアップに失敗したため処理を中断しました" in mock_error.call_args[0][0]

    # 6. CSVインポート例外発生時
    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.file_uploader", return_value=sbi_mock),
        patch(
            "src.ui.sbi_wizard.decode_csv_bytes",
            side_effect=UnicodeDecodeError("cp932", b"", 0, 1, "invalid"),
        ),
        patch("streamlit.error") as mock_error,
    ):
        render_sbi_import_section(
            project_root=tmp_path, portfolio_items=[], portfolio_csv_path=portfolio_csv
        )
        mock_error.assert_called()
        assert "CSVインポート処理エラー" in mock_error.call_args[0][0]


def test_render_sbi_import_section_manual_code_learning(tmp_path: Path) -> None:
    """未特定銘柄に8桁コードを入力してエイリアス学習と正常インポートが行われる分岐を検証する。"""
    portfolio_csv = tmp_path / "portfolio.csv"
    sbi_mock = MagicMock()
    sbi_mock.getvalue.return_value = """\
"投資信託（金額/特定預り）"
"ファンド名","買付日","数量","取得単価","現在値","損益","評価額"
"手動特定対象ファンド","----/--/--",1000,10000,12000,2000,12000
""".encode("cp932")

    unresolved_candidate = ImportCandidate(
        source_record=SbiRawRecord(
            raw_account_section="投資信託（金額/特定預り）",
            fund_name="手動特定対象ファンド",
            quantity=1000.0,
            acquisition_price=10000.0,
            current_price=12000.0,
            profit_loss=2000.0,
            valuation=12000.0,
        ),
        target_account="特定預り",
        holder="個人",
        resolved_code="",
        resolved_isin="",
        is_resolved=False,
    )

    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.file_uploader", return_value=sbi_mock),
        patch("src.ui.sbi_wizard.resolve_candidates", return_value=[unresolved_candidate]),
        patch("streamlit.markdown"),
        patch("streamlit.radio", side_effect=["個人", "replace_all"]),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.selectbox", side_effect=["個人", "特定預り"]),
        patch("streamlit.form"),
        patch("streamlit.text_input", side_effect=["0331418A", "JP90C000H1T1"]),  # 8桁入力
        patch("streamlit.checkbox", return_value=True),  # confirm_replace_all = True
        patch("streamlit.form_submit_button", return_value=True),
        patch("streamlit.dataframe"),
        patch("src.ui.sbi_wizard.run_backup", return_value={"success": True, "filename": "bk.zip"}),
        patch("src.ui.sbi_wizard.save_custom_aliases") as mock_save_alias,
        patch("src.ui.sbi_wizard.save_portfolio_csv") as mock_save_port,
        patch("streamlit.cache_data.clear"),
        patch("streamlit.rerun"),
    ):
        render_sbi_import_section(
            project_root=tmp_path, portfolio_items=[], portfolio_csv_path=portfolio_csv
        )
        mock_save_alias.assert_called_once()
        mock_save_port.assert_called_once()


def test_render_sbi_import_section_flow(tmp_path: Path) -> None:
    """SBI証券インポートセクションの解決済み候補インポート確定を検証する。"""
    portfolio_csv = tmp_path / "portfolio.csv"
    sbi_mock = MagicMock()
    sbi_mock.getvalue.return_value = """\
"投資信託（金額/NISA口座（成長投資枠））"
"ファンド名","買付日","数量","取得単価","現在値","損益","評価額"
"ｅＭＡＸＩＳ Ｓｌｉｍ 全世界株式（オール・カントリー）","----/--/--",1000,20000,25000,5000,25000
""".encode("cp932")

    session_mock: dict[str, object] = {}

    with (
        patch("streamlit.subheader"),
        patch("streamlit.caption"),
        patch("streamlit.session_state", session_mock),
        patch("streamlit.file_uploader", return_value=sbi_mock),
        patch("streamlit.markdown"),
        patch("streamlit.radio", side_effect=["個人", "append"]),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.selectbox", side_effect=["個人", "NISA預り（成長投資枠）"]),
        patch("streamlit.form"),
        patch("streamlit.checkbox", return_value=True),
        patch("streamlit.form_submit_button", return_value=True),
        patch("streamlit.dataframe"),
        patch(
            "src.ui.sbi_wizard.run_backup", return_value={"success": True, "filename": "backup.zip"}
        ),
        patch("src.ui.sbi_wizard.save_portfolio_csv") as mock_save,
        patch("streamlit.cache_data.clear") as mock_clear,
        patch("streamlit.rerun") as mock_rerun,
    ):
        render_sbi_import_section(
            project_root=tmp_path,
            portfolio_items=[],
            portfolio_csv_path=portfolio_csv,
        )
        mock_save.assert_called_once()
        mock_clear.assert_called()
        mock_rerun.assert_called()
        assert "sbi_import_result" in session_mock


def test_render_dashboard_tab_partial_fallback_and_fetched_at() -> None:
    """部分フォールバック警告と基準価額取得日時キャプションの描画を検証する。"""
    item = PortfolioItem(
        holder="個人",
        account="特定預り",
        code="0331418A",
        isin="JP90C000H1T1",
        name="テスト株",
        units=5000.0,
        cost_basis=10000,
    )
    holding = HoldingEvaluation(
        item=item,
        nav=10000.0,
        valuation=50000,
        profit_loss=40000,
        profit_loss_rate=4.0,
        effective_units=5000.0,
    )
    report = PortfolioReport(
        as_of_date="2026-10-22",
        fetched_at="2026-10-23 11:35:00",
        fallback_funds=["03311187"],
        holdings=[holding],
        tank_summaries=[],
        total_valuation=50000,
        total_profit_loss=40000,
    )

    with (
        patch("streamlit.warning") as mock_warning,
        patch("streamlit.caption") as mock_caption,
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.metric"),
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.altair_chart"),
        patch("streamlit.dataframe"),
    ):
        render_dashboard_tab(report)
        mock_warning.assert_called_once()
        assert "一部銘柄フォールバック中" in mock_warning.call_args[0][0]
        assert "03311187" in mock_warning.call_args[0][0]
        caption_calls = [c[0][0] for c in mock_caption.call_args_list]
        assert any("基準価額取得日時" in c and "2026-10-23 11:35:00" in c for c in caption_calls)


def test_render_app_sidebar_refresh_feedback_variants(tmp_path: Path) -> None:
    """サイドバーの refresh_feedback で warning および error が正しく表示されることを検証する。"""
    # Warning パターン
    session_warning: dict[str, object] = {"refresh_feedback": ("warning", "一部銘柄フォールバック")}
    with (
        patch("streamlit.sidebar"),
        patch("streamlit.header"),
        patch("streamlit.button", return_value=False),
        patch("streamlit.session_state", session_warning),
        patch("streamlit.file_uploader", return_value=None),
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.form"),
        patch("src.ui.sidebar.get_backup_dir", return_value=Path("C:/dir")),
        patch("streamlit.caption"),
        patch("streamlit.warning") as mock_warn,
    ):
        render_app_sidebar(project_root=tmp_path)
        mock_warn.assert_called_once_with("一部銘柄フォールバック")

    # Error パターン
    session_error: dict[str, object] = {"refresh_feedback": ("error", "外部通信失敗")}
    with (
        patch("streamlit.sidebar"),
        patch("streamlit.header"),
        patch("streamlit.button", return_value=False),
        patch("streamlit.session_state", session_error),
        patch("streamlit.file_uploader", return_value=None),
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.form"),
        patch("src.ui.sidebar.get_backup_dir", return_value=Path("C:/dir")),
        patch("streamlit.caption"),
        patch("streamlit.error") as mock_err,
    ):
        render_app_sidebar(project_root=tmp_path)
        mock_err.assert_called_once_with("外部通信失敗")


def test_render_dashboard_tab_with_history_repo(tmp_path: Path) -> None:
    """ダッシュボードタブにおける積み上げ棒グラフの履歴連携（空時およびデータ存在時）を検証する。"""
    repo = HistoryRepository(tmp_path / "test_hist.db")
    item = PortfolioItem(
        holder="個人",
        account="NISA",
        code="0331418A",
        isin="JP90C000H1T1",
        name="オルカン",
        units=1000.0,
        cost_basis=10000,
    )
    holding = HoldingEvaluation(
        item=item,
        nav=12000.0,
        valuation=1200,
        profit_loss=200,
        effective_units=1000.0,
    )
    report = PortfolioReport(
        as_of_date="2026-10-23",
        holdings=[holding],
        tank_summaries=[],
        total_valuation=1200,
        total_profit_loss=200,
    )

    # 1. 履歴が空の場合
    with (
        patch("streamlit.radio", return_value="銘柄別"),
        patch("streamlit.info") as mock_info,
        patch("streamlit.altair_chart") as mock_chart,
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.metric"),
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.dataframe"),
    ):
        render_dashboard_tab(report, history_repo=repo)
        mock_info.assert_called_once()
        assert "過去の履歴データがまだ記録されていません" in mock_info.call_args[0][0]
        # ドーナツチャートのみ呼ばれる（積み上げ棒グラフは描画されない）
        assert mock_chart.call_count == 1

    # 2. 履歴が存在する場合
    from src.models import FundSnapshotRecord

    repo.upsert_snapshots(
        [
            FundSnapshotRecord(
                recorded_date="2026-10-23",
                recorded_at="2026-10-23T12:00:00+00:00",
                holder="個人",
                account="NISA",
                code="0331418A",
                isin="JP90C000H1T1",
                name="オルカン",
                units=1000.0,
                cost_basis=10000,
                nav=12000.0,
                valuation=1200,
                profit_loss=200,
            )
        ]
    )

    with (
        patch("streamlit.radio", side_effect=["全期間", "銘柄別"]),
        patch("streamlit.info"),
        patch("streamlit.altair_chart") as mock_chart,
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.metric"),
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.dataframe"),
    ):
        render_dashboard_tab(report, history_repo=repo)
        # 積み上げ面グラフとドーナツチャートの計2回描画
        assert mock_chart.call_count == 2

    # 3. 履歴は存在するが指定期間で空になる場合
    with (
        patch("streamlit.radio", side_effect=["3ヵ月", "銘柄別"]),
        patch.object(
            repo, "get_stacked_asset_df", return_value=repo.get_all_snapshots_df().iloc[0:0]
        ),
        patch("streamlit.info") as mock_info_period,
        patch("streamlit.altair_chart"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.metric"),
        patch("streamlit.divider"),
        patch("streamlit.subheader"),
        patch("streamlit.dataframe"),
    ):
        render_dashboard_tab(report, history_repo=repo)
        mock_info_period.assert_called_once()
        assert "指定された期間内の履歴データが存在しません" in mock_info_period.call_args[0][0]


def test_render_history_tab_empty(tmp_path: Path) -> None:
    """履歴データが空の場合の案内メッセージ表示を検証する。"""
    repo = HistoryRepository(tmp_path / "empty_hist.db")
    with (
        patch("streamlit.subheader"),
        patch("streamlit.info") as mock_info,
    ):
        render_history_tab(history_repo=repo)
        mock_info.assert_called_once()
        assert "過去のファンド履歴スナップショットが記録されていません" in mock_info.call_args[0][0]


def test_render_history_tab_populated(tmp_path: Path) -> None:
    """履歴データが存在する場合の各種UIコンポーネント（セレクタ、メトリクス、3チャートタブ、テーブル）の描画を検証する。"""
    repo = HistoryRepository(tmp_path / "pop_hist.db")
    from src.models import FundSnapshotRecord

    # 2日分登録
    repo.upsert_snapshots(
        [
            FundSnapshotRecord(
                recorded_date="2026-10-21",
                recorded_at="2026-10-21T12:00:00+00:00",
                holder="個人",
                account="NISA",
                code="0331418A",
                isin="JP90C000H1T1",
                name="オルカン",
                units=1000.0,
                cost_basis=10000,
                nav=10000.0,
                valuation=1000,
                profit_loss=0,
            ),
            FundSnapshotRecord(
                recorded_date="2026-10-23",
                recorded_at="2026-10-23T12:00:00+00:00",
                holder="個人",
                account="NISA",
                code="0331418A",
                isin="JP90C000H1T1",
                name="オルカン",
                units=1500.0,
                cost_basis=15000,
                nav=12000.0,
                valuation=1800,
                profit_loss=300,
            ),
        ]
    )

    with (
        patch("streamlit.subheader"),
        patch("streamlit.selectbox", return_value="[個人] NISA - オルカン (0331418A)"),
        patch("streamlit.columns", side_effect=mock_columns),
        patch("streamlit.metric") as mock_metric,
        patch("streamlit.divider"),
        patch("streamlit.tabs", return_value=[MagicMock(), MagicMock(), MagicMock()]),
        patch("streamlit.altair_chart") as mock_chart,
        patch("streamlit.dataframe") as mock_df,
        patch("streamlit.download_button") as mock_dl,
    ):
        render_history_tab(history_repo=repo)
        assert mock_metric.call_count == 4
        # 評価額チャート、NAVチャート、簿価チャート、口数チャートの計4回
        assert mock_chart.call_count == 4
        mock_df.assert_called_once()
        mock_dl.assert_called_once()


def test_render_history_tab_none_selection_and_empty_df(tmp_path: Path) -> None:
    """セレクタ未選択、または抽出データが空の場合の分岐を検証する。"""
    repo = HistoryRepository(tmp_path / "edge_hist.db")
    from src.models import FundSnapshotRecord

    repo.upsert_snapshots(
        [
            FundSnapshotRecord(
                recorded_date="2026-10-21",
                recorded_at="2026-10-21T12:00:00+00:00",
                holder="個人",
                account="NISA",
                code="0331418A",
                isin="JP90C000H1T1",
                name="オルカン",
                units=1000.0,
                cost_basis=10000,
                nav=10000.0,
                valuation=1000,
                profit_loss=0,
            )
        ]
    )

    # 1. 選択が空文字列
    with (
        patch("streamlit.subheader"),
        patch("streamlit.selectbox", return_value=None),
        patch("streamlit.metric") as mock_metric,
    ):
        render_history_tab(history_repo=repo)
        mock_metric.assert_not_called()

    # 2. 抽出されたDataFrameが空（モックによる異常系）
    with (
        patch("streamlit.subheader"),
        patch("streamlit.selectbox", return_value="[個人] NISA - オルカン (0331418A)"),
        patch.object(
            repo, "get_fund_history_df", return_value=repo.get_all_snapshots_df().iloc[0:0]
        ),
        patch("streamlit.warning") as mock_warn,
    ):
        render_history_tab(history_repo=repo)
        mock_warn.assert_called_once()
