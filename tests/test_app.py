"""app.py Streamlit GUI のテストモジュール。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

_APP_PATH = str(Path(__file__).resolve().parent.parent / "app.py")


def test_app_initial_render() -> None:
    """Streamlit アプリケーションがエラーなく初期描画されることを検証する。"""
    at = AppTest.from_file(_APP_PATH, default_timeout=30)
    at.run()

    assert not at.exception
    assert len(at.title) >= 1
    assert "投資信託 ポートフォリオ評価ダッシュボード" in at.title[0].value
    assert len(at.metric) >= 3


def test_app_force_refresh_button() -> None:
    """キャッシュクリアボタンのクリック動作を検証する。"""
    at = AppTest.from_file(_APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception

    refresh_buttons = [b for b in at.sidebar.button if "再取得" in b.label]
    assert len(refresh_buttons) == 1
    refresh_buttons[0].click().run()
    assert not at.exception


def test_app_backup_button() -> None:
    """サイドバーのバックアップ実行ボタンのクリック動作を検証する。"""
    at = AppTest.from_file(_APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception

    backup_buttons = [b for b in at.sidebar.button if "今すぐバックアップ" in b.label]
    assert len(backup_buttons) == 1
    backup_buttons[0].click().run()
    assert not at.exception


def test_app_csv_load_error() -> None:
    """portfolio.csv 読み込み失敗時にエラー表示と st.stop が行われることを検証する。"""
    with patch("src.portfolio_loader.load_portfolio_csv", side_effect=ValueError("テストエラー")):
        at = AppTest.from_file(_APP_PATH, default_timeout=30)
        at.run()
        assert not at.exception
        assert len(at.error) >= 1
        assert "保有資産CSVの読み込みエラー: テストエラー" in at.error[0].value


def test_app_fallback_warning_rendered() -> None:
    """フォールバックデータ使用時に警告バナーが表示されることを検証する。"""
    import streamlit as st

    st.cache_data.clear()
    with patch(
        "src.nav_fetcher.fetch_latest_nav_and_names",
        return_value=("2026-10-21 (Fallback)", {"0331418A": 37859.0}, {"0331418A": "テスト"}),
    ):
        at = AppTest.from_file(_APP_PATH, default_timeout=30)
        at.run()
        assert not at.exception
        warnings = [w.value for w in at.warning]
        assert any("内蔵フォールバック値を使用中" in w for w in warnings)


def test_app_file_uploader_rendered() -> None:
    """基準価額CSVのファイルアップローダーが存在することを検証する。"""
    at = AppTest.from_file(_APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception
    assert len(at.sidebar.file_uploader) >= 1


def test_app_tabs_rendered() -> None:
    """ダッシュボードおよびマスター管理タブが正しく描画されることを検証する。"""
    at = AppTest.from_file(_APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception
    assert len(at.tabs) == 2
