"""cli.py の統合テストモジュール。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cli import main


def test_cli_main_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLIの正常実行とダッシュボード出力を検証する。"""
    csv_file = tmp_path / "portfolio.csv"
    csv_file.write_text(
        "account,code,name,units,cost_basis\n法人,03311181,全世界株,10000.0,15000\n",
        encoding="utf-8",
    )

    test_args = ["cli.py", "--csv", str(csv_file), "--dc-base-date", "2025-01-01"]
    with patch.object(sys, "argv", test_args):
        ret = main()

    assert ret == 0
    captured = capsys.readouterr()
    assert "投資信託 ポートフォリオ評価ダッシュボード" in captured.out
    assert "全世界株" in captured.out


def test_cli_main_invalid_date(capsys: pytest.CaptureFixture[str]) -> None:
    """不正な日付引数でCLIが終了コード1を返すことを検証する。"""
    test_args = ["cli.py", "--dc-base-date", "invalid-date"]
    with patch.object(sys, "argv", test_args):
        ret = main()

    assert ret == 1
    captured = capsys.readouterr()
    assert "エラー: --dc-base-date の日付形式が不正です" in captured.err


def test_cli_main_csv_load_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CSV読み込みエラー時にCLIが終了コード1を返すことを検証する。"""
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("invalid,header\n", encoding="utf-8")

    test_args = ["cli.py", "--csv", str(bad_csv)]
    with patch.object(sys, "argv", test_args):
        ret = main()

    assert ret == 1
    captured = capsys.readouterr()
    assert "エラー: 保有資産CSVの読み込みに失敗しました" in captured.err
