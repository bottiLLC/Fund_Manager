"""src.portfolio_loader のテストモジュール。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.portfolio_loader import load_portfolio_csv, parse_portfolio_csv_content


def test_parse_portfolio_csv_content_success() -> None:
    """正常なCSV文字列からPortfolioItemリストが生成されることを検証する。"""
    # Arrange
    csv_data = (
        "account,code,name,units,cost_basis\n"
        "法人,03311181,eMAXIS Slim 全世界株式,10000.0,15000\n"
        "   ,   ,   ,100,0\n"  # account/code/name 全て空文字の行 (スキップ)
        "iDeCo,03314187,eMAXIS Slim 米国株式,20000.0,\n"  # cost_basis空文字
        "DC,03312184,eMAXIS Slim 先進国株式,30000.0,0\n"  # cost_basis 0
        "\n"  # 空行
    )

    # Act
    items = parse_portfolio_csv_content(csv_data)

    # Assert
    assert len(items) == 3
    assert items[0].account == "法人"
    assert items[0].code == "03311181"
    assert items[0].cost_basis == 15000
    assert items[1].cost_basis == 0
    assert items[2].cost_basis == 0


def test_parse_portfolio_csv_content_empty_row_dict() -> None:
    """CSV読み込み中に空の辞書行がスキップされることを検証する。"""
    from unittest.mock import MagicMock, patch

    with patch("csv.DictReader") as mock_reader_cls:
        mock_inst = MagicMock()
        mock_inst.fieldnames = ["account", "code", "name", "units", "cost_basis"]
        mock_inst.__iter__.return_value = [
            {},
            {
                "account": "法人",
                "code": "03311181",
                "name": "全世界",
                "units": "1000",
                "cost_basis": "1000",
            },
        ]
        mock_reader_cls.return_value = mock_inst
        items = parse_portfolio_csv_content("dummy_content")

        assert len(items) == 1
        assert items[0].account == "法人"


def test_parse_portfolio_csv_content_empty_error() -> None:
    """空のCSVでValueErrorが発生することを検証する。"""
    with pytest.raises(ValueError, match="CSVファイルが空か"):
        parse_portfolio_csv_content("")


def test_parse_portfolio_csv_missing_header_error() -> None:
    """必須ヘッダが欠損している場合にValueErrorが発生することを検証する。"""
    csv_data = "account,name,units\n法人,テスト,100\n"
    with pytest.raises(ValueError, match="必須ヘッダ列が不足しています"):
        parse_portfolio_csv_content(csv_data)


def test_parse_portfolio_csv_invalid_units_error() -> None:
    """unitsが数値に変換できない場合にValueErrorが発生することを検証する。"""
    csv_data = "account,code,name,units,cost_basis\n法人,03311181,テスト,invalid_units,1000\n"
    with pytest.raises(ValueError, match="units は有効な数値である必要があります"):
        parse_portfolio_csv_content(csv_data)


def test_parse_portfolio_csv_invalid_cost_basis_error() -> None:
    """cost_basisが数値に変換できない場合にValueErrorが発生することを検証する。"""
    csv_data = "account,code,name,units,cost_basis\n法人,03311181,テスト,1000.0,invalid_cost\n"
    with pytest.raises(ValueError, match="cost_basis は有効な数値である必要があります"):
        parse_portfolio_csv_content(csv_data)


def test_parse_portfolio_csv_no_valid_data_error() -> None:
    """有効行が存在しない場合にValueErrorが発生することを検証する。"""
    csv_data = "account,code,name,units,cost_basis\n   ,   ,   ,   ,   \n"
    with pytest.raises(ValueError, match="有効な保有銘柄データが1件も存在しません"):
        parse_portfolio_csv_content(csv_data)


def test_load_portfolio_csv_creates_default_if_not_exists(tmp_path: Path) -> None:
    """指定パスが存在しない場合、デフォルトファイルを作成して読み込むことを検証する。"""
    # Arrange
    target_file = tmp_path / "sub" / "portfolio.csv"

    # Act
    items = load_portfolio_csv(target_file)

    # Assert
    assert target_file.exists()
    assert len(items) >= 1
    assert items[0].code == "03311181"
