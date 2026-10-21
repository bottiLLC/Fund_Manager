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


def test_app_sbi_file_uploader_rendered() -> None:
    """マスター管理タブにSBI証券CSVアップローダーが存在することを検証する。"""
    at = AppTest.from_file(_APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception
    # 全体のファイルアップローダー（サイドバーの基準価額CSV + マスター管理のSBI証券CSV）
    uploaders = at.file_uploader
    assert len(uploaders) >= 2
    assert any("SBI" in u.label for u in uploaders)


def test_app_master_tab_controls() -> None:
    """マスター管理タブ内のデータエディタ削除コントロールおよび標準CSVアップローダーの存在を検証する。"""
    at = AppTest.from_file(_APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception

    # 旧マルチセレクト選択削除UIが撤去されていることの確認
    multiselects = at.multiselect
    assert not any("削除対象の銘柄を選択" in m.label for m in multiselects)

    # データエディタの保存ボタンおよび削除ボタンの存在確認
    buttons = at.button
    assert any("保存して再計算" in b.label for b in buttons)
    assert any("チェックした銘柄" in b.label for b in buttons)

    # 標準 portfolio.csv アップローダーの存在確認
    uploaders = at.file_uploader
    assert any("portfolio.csv を選択" in u.label for u in uploaders)

    # 反映方式のラジオボタン存在確認
    radios = at.radio
    assert any("反映方式" in r.label for r in radios)


def test_app_empty_portfolio_renders_safely() -> None:
    """全レコード削除等で保有資産が0件の場合にエラーなく描画され、マスター管理UIが稼働することを検証する。"""
    with patch("src.portfolio_loader.load_portfolio_csv", return_value=[]):
        at = AppTest.from_file(_APP_PATH, default_timeout=30)
        at.run()

        assert not at.exception
        # エラーバナーが出現しないこと
        assert len(at.error) == 0

        # 保有銘柄なしの案内情報が表示されること
        infos = [i.value for i in at.info]
        assert any("現在、保有銘柄が登録されていません" in info for info in infos)

        # マスター管理タブの追加フォームおよびアップローダーが存在すること
        uploaders = at.file_uploader
        assert any("portfolio.csv を選択" in u.label for u in uploaders)
        assert any("SBI" in u.label for u in uploaders)
