"""backup_manager のテストモジュール。"""

from __future__ import annotations

from pathlib import Path

from backup_manager import get_backup_dir, run_backup, set_backup_dir


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
