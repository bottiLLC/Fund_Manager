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

    test_args = ["cli.py", "--csv", str(csv_file)]
    with patch.object(sys, "argv", test_args):
        ret = main()

    assert ret == 0
    captured = capsys.readouterr()
    assert "投資信託 ポートフォリオ評価ダッシュボード" in captured.out
    assert "全世界株" in captured.out


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


def test_cli_name_main_execution() -> None:
    """__main__ 経由での実行を検証する。"""
    import runpy

    with patch("sys.argv", ["cli.py", "--help"]):
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_path("cli.py", run_name="__main__")
        assert exc_info.value.code == 0


def test_cli_main_import_sbi_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLIでのSBI CSVインポート成功とポートフォリオ更新を検証する。"""
    csv_file = tmp_path / "portfolio.csv"
    csv_file.write_text("account,code,isin,units,cost_basis\n", encoding="utf-8")

    sbi_csv = tmp_path / "sbi.csv"
    sbi_content = """\
"投資信託（金額/NISA口座（成長投資枠））"
"ファンド名","買付日","数量","取得単価","現在値","損益","評価額"
"ｅＭＡＸＩＳ Ｓｌｉｍ 米国株式（Ｓ＆Ｐ５００）","----/--/--",1000,28420,44943,0,0
"""
    sbi_csv.write_text(sbi_content, encoding="cp932")

    test_args = ["cli.py", "--csv", str(csv_file), "--import-sbi", str(sbi_csv)]
    with patch.object(sys, "argv", test_args):
        ret = main()

    assert ret == 0
    captured = capsys.readouterr()
    assert "SBI証券CSVを正常にインポートしました" in captured.out


def test_cli_main_import_sbi_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLIでの各種エラー（ファイル不在、空明細、未解決銘柄、例外）を検証する。"""
    csv_file = tmp_path / "portfolio.csv"
    csv_file.write_text("account,code,isin,units,cost_basis\n", encoding="utf-8")

    # 1. ファイル不在
    with patch.object(
        sys,
        "argv",
        ["cli.py", "--csv", str(csv_file), "--import-sbi", str(tmp_path / "non_existent.csv")],
    ):
        assert main() == 1
    assert "指定されたSBI CSVファイルが存在しません" in capsys.readouterr().err

    # 2. 空明細
    empty_sbi = tmp_path / "empty_sbi.csv"
    empty_sbi.write_text('"ポートフォリオ一覧"\n', encoding="utf-8")
    with patch.object(
        sys, "argv", ["cli.py", "--csv", str(csv_file), "--import-sbi", str(empty_sbi)]
    ):
        assert main() == 1
    assert "有効な投資信託明細が検出されませんでした" in capsys.readouterr().err

    # 3. 未解決銘柄
    unresolved_sbi = tmp_path / "unresolved_sbi.csv"
    unresolved_content = """\
"投資信託（金額/特定口座）"
"ファンド名","数量"
"架空の未解決銘柄999",1000
"""
    unresolved_sbi.write_text(unresolved_content, encoding="utf-8")
    with patch.object(
        sys, "argv", ["cli.py", "--csv", str(csv_file), "--import-sbi", str(unresolved_sbi)]
    ):
        assert main() == 1
    assert "件の銘柄コードが未解決です" in capsys.readouterr().err

    # 4. 例外発生
    with (
        patch("cli.parse_sbi_portfolio_csv", side_effect=RuntimeError("パース致命的エラー")),
        patch.object(
            sys, "argv", ["cli.py", "--csv", str(csv_file), "--import-sbi", str(unresolved_sbi)]
        ),
    ):
        assert main() == 1
    assert "SBI CSVインポートに失敗しました: パース致命的エラー" in capsys.readouterr().err
