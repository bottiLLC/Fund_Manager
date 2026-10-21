"""backup_manager の包括的テストモジュール。"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from backup_manager import _DEFAULT_BACKUP_DIR, get_backup_dir, run_backup, set_backup_dir


def test_backup_manager_lifecycle(tmp_path: Path) -> None:
    """バックアップ設定変更およびZIP圧縮・整合性検証のライフサイクルをテストする。"""
    source_dir = tmp_path / "data"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "sample.txt").write_text("hello backup", encoding="utf-8")

    backup_dest = tmp_path / "dest_backups"

    # 1. バックアップ先設定
    set_res = set_backup_dir(str(backup_dest))
    assert set_res["success"] is True

    # 2. 設定取得
    current_dest = get_backup_dir()
    assert current_dest == backup_dest.resolve()

    # 3. バックアップ実行
    backup_res = run_backup(app_name="test_app", source_dir=str(source_dir))
    assert backup_res["success"] is True
    assert "バックアップ完了" in str(backup_res["message"])

    # 4. バックアップファイル存在確認
    dest_path = Path(str(backup_res["destination"]))
    assert dest_path.exists()
    assert dest_path.suffix == ".zip"


def test_backup_manager_empty_source(tmp_path: Path) -> None:
    """空のディレクトリに対するバックアップがインターロックで拒否されることを検証する。"""
    empty_dir = tmp_path / "empty_data"
    empty_dir.mkdir(parents=True, exist_ok=True)

    res = run_backup(app_name="test_app", source_dir=str(empty_dir))
    assert res["success"] is False
    assert "存在しないか空欄" in str(res["message"])


def test_backup_manager_non_existent_source(tmp_path: Path) -> None:
    """存在しないディレクトリに対するバックアップがインターロックで拒否されることを検証する。"""
    res = run_backup(app_name="test_app", source_dir=str(tmp_path / "non_existent"))
    assert res["success"] is False
    assert "存在しないか空欄" in str(res["message"])


def test_get_backup_dir_fallback_to_env(tmp_path: Path) -> None:
    """設定ファイル不在時に環境変数BACKUP_DIRからパスを取得することを検証する。"""
    env_target = tmp_path / "env_backup"
    non_existent_cfg = tmp_path / "missing_config.json"
    with (
        patch("backup_manager._CONFIG_FILE", non_existent_cfg),
        patch.dict(os.environ, {"BACKUP_DIR": str(env_target)}),
    ):
        dest = get_backup_dir()
        assert dest == env_target.resolve()


def test_get_backup_dir_fallback_to_default(tmp_path: Path) -> None:
    """設定ファイルも環境変数も不在時にデフォルトパスを取得することを検証する。"""
    non_existent_cfg = tmp_path / "missing_config.json"
    with (
        patch("backup_manager._CONFIG_FILE", non_existent_cfg),
        patch.dict(os.environ, {}, clear=True),
    ):
        dest = get_backup_dir()
        assert dest == _DEFAULT_BACKUP_DIR.resolve()


def test_get_backup_dir_config_read_error(tmp_path: Path) -> None:
    """設定ファイル読み込み時にJSONDecodeErrorやOSErrorが発生した場合にフォールバックすることを検証する。"""
    corrupt_cfg = tmp_path / "corrupt_config.json"
    corrupt_cfg.write_text("{not valid json", encoding="utf-8")
    with patch("backup_manager._CONFIG_FILE", corrupt_cfg):
        dest = get_backup_dir()
        assert dest == _DEFAULT_BACKUP_DIR.resolve()


def test_set_backup_dir_oserror() -> None:
    """保存先フォルダの作成に失敗した場合のエラーハンドリングを検証する。"""
    with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
        res = set_backup_dir("/invalid/path")
        assert res["success"] is False
        assert "保存先パスが無効、または書き込み権限がありません" in str(res["message"])


def test_run_backup_destination_mkdir_oserror(tmp_path: Path) -> None:
    """保存先フォルダの作成に失敗した場合のrun_backupのエラーハンドリングを検証する。"""
    source_dir = tmp_path / "data"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "file.txt").write_text("content", encoding="utf-8")

    mock_dest = MagicMock(spec=Path)
    mock_dest.mkdir.side_effect = OSError("Disk read-only")

    with patch("backup_manager.get_backup_dir", return_value=mock_dest):
        res = run_backup(source_dir=str(source_dir))
        assert res["success"] is False
        assert "保存先フォルダの作成に失敗しました" in str(res["message"])


def test_run_backup_corrupt_zip_detected(tmp_path: Path) -> None:
    """ZIP整合性チェック(testzip)で破損が検知された場合のエラーハンドリングを検証する。"""
    source_dir = tmp_path / "data"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "file.txt").write_text("content", encoding="utf-8")

    with patch.object(zipfile.ZipFile, "testzip", return_value="bad_entry.txt"):
        res = run_backup(source_dir=str(source_dir))
        assert res["success"] is False
        assert "整合性チェック失敗（破損検知）" in str(res["message"])


def test_run_backup_move_oserror(tmp_path: Path) -> None:
    """shutil.move に失敗した場合のエラーハンドリングを検証する。"""
    source_dir = tmp_path / "data"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "file.txt").write_text("content", encoding="utf-8")

    with patch("shutil.move", side_effect=OSError("Cross-device link failure")):
        res = run_backup(source_dir=str(source_dir))
        assert res["success"] is False
        assert "バックアップファイルの確定移動に失敗しました" in str(res["message"])


def test_run_backup_skips_config_file_and_formats_mb(tmp_path: Path) -> None:
    """_CONFIG_FILE がsource_dir内にあってもスキップされること、および1MB以上のサイズ表記を検証する。"""
    source_dir = tmp_path / "data"
    source_dir.mkdir(parents=True, exist_ok=True)
    # 1MB超の非圧縮ダミーファイル（ランダムバイト列）を作成して ZIP サイズを1MB以上にし MB 表記ブランチを通過
    dummy_file = source_dir / "large_dummy.bin"
    dummy_file.write_bytes(os.urandom(1_100_000))

    # 設定ファイルと同等のパスを配置
    config_in_source = source_dir / "backup_config.json"
    config_in_source.write_text(json.dumps({"backup_dir": str(tmp_path)}), encoding="utf-8")

    backup_dest = tmp_path / "backups"
    set_backup_dir(str(backup_dest))

    with patch("backup_manager._CONFIG_FILE", config_in_source):
        res = run_backup(source_dir=str(source_dir))
        assert res["success"] is True
        assert "MB" in str(res["size"])
