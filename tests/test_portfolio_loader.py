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
    assert items[0].holder == "法人"
    assert items[0].account == "一般預り"
    assert items[0].code == "03311181"
    assert items[0].cost_basis == 15000
    assert items[1].holder == "個人"
    assert items[1].account == "iDeCo"
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
        assert items[0].holder == "法人"
        assert items[0].account == "一般預り"


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


def test_parse_portfolio_csv_allow_empty() -> None:
    """allow_empty=True指定時に有効データ行が0件でも空リストが返却されることを検証する。"""
    # Arrange
    csv_data = "account,code,isin,units,cost_basis\n"

    # Act
    items = parse_portfolio_csv_content(csv_data, allow_empty=True)

    # Assert
    assert items == []


def test_load_portfolio_csv_empty_header_only(tmp_path: Path) -> None:
    """全削除後のヘッダのみCSVをエラーなく空リストとして読み込めることを検証する。"""
    # Arrange
    target_file = tmp_path / "empty_portfolio.csv"
    target_file.write_text("account,code,isin,units,cost_basis\n", encoding="utf-8")

    # Act
    items = load_portfolio_csv(target_file)

    # Assert
    assert items == []


def test_load_portfolio_csv_creates_default_if_not_exists(tmp_path: Path) -> None:
    """指定パスが存在しない場合、デフォルトファイルを作成して読み込むことを検証する。"""
    # Arrange
    target_file = tmp_path / "sub" / "portfolio.csv"

    # Act
    items = load_portfolio_csv(target_file)

    # Assert
    assert target_file.exists()
    assert len(items) >= 1
    assert items[0].code == "0331418A"


def test_save_and_load_portfolio_csv_roundtrip(tmp_path: Path) -> None:
    """save_portfolio_csvによる保存とload_portfolio_csvによる復元を検証する。"""
    from src.models import PortfolioItem
    from src.portfolio_loader import save_portfolio_csv

    target_file = tmp_path / "saved.csv"
    items = [
        PortfolioItem(
            holder="法人",
            account="一般預り",
            code="0331418A",
            isin="JP90C000H1T1",
            name="全世界株式",
            units=1000.5,
            cost_basis=20000,
        ),
        PortfolioItem(
            holder="個人",
            account="DC",
            code="03311187",
            isin="JP90C000GKC6",
            name="S&P500",
            units=500.0,
            cost_basis=0,
        ),
    ]

    save_portfolio_csv(target_file, items)
    assert target_file.exists()

    loaded = load_portfolio_csv(target_file)
    assert len(loaded) == 2
    assert loaded[0].holder == "法人"
    assert loaded[0].account == "一般預り"
    assert loaded[0].code == "0331418A"
    assert loaded[0].isin == "JP90C000H1T1"
    assert loaded[0].units == 1000.5
    assert loaded[0].cost_basis == 20000
    assert loaded[1].holder == "個人"
    assert loaded[1].account == "DC"
    assert loaded[1].cost_basis == 0


def test_parse_portfolio_csv_japanese_aliases() -> None:
    """日本語ヘッダ（法人/個人, 口座, 協会コード, ISINコード, units, cost_basis等）の解析を検証する。"""
    csv_data = "法人/個人,口座,協会コード,ISINコード,口数,取得簿価\n法人,一般預り,0331418A,JP90C000H1T1,1234.5,5678\n"
    items = parse_portfolio_csv_content(csv_data)
    assert len(items) == 1
    assert items[0].holder == "法人"
    assert items[0].account == "一般預り"
    assert items[0].code == "0331418A"
    assert items[0].isin == "JP90C000H1T1"
    assert items[0].units == 1234.5
    assert items[0].cost_basis == 5678


def test_parse_portfolio_csv_with_explicit_holder() -> None:
    """holder列が明示されたCSVから各銘柄の所有者区分が正確に解析されることを検証する。"""
    csv_data = (
        "holder,account,code,isin,units,cost_basis\n"
        "法人,一般預り,0331418A,JP90C000H1T1,500.0,10000\n"
        "個人,NISA預り（成長投資枠）,03311187,JP90C000GKC6,300.0,5000\n"
        "個人(DC),DC,03312187,JP90C000GKC7,200.0,4000\n"
    )
    items = parse_portfolio_csv_content(csv_data)
    assert len(items) == 3
    assert items[0].holder == "法人"
    assert items[0].account == "一般預り"
    assert items[1].holder == "個人"
    assert items[1].account == "NISA預り（成長投資枠）"
    assert items[2].holder == "個人(DC)"
    assert items[2].account == "DC"


def test_save_portfolio_csv_cleanup_on_error(tmp_path: Path) -> None:
    """保存処理中に例外が発生した場合に一時ファイルがクリーンアップされることを検証する。"""
    from unittest.mock import patch

    from src.models import PortfolioItem
    from src.portfolio_loader import save_portfolio_csv

    target_file = tmp_path / "saved.csv"
    items = [PortfolioItem(account="NISA", code="0331418A", units=10.0)]

    with (
        patch("pathlib.Path.replace", side_effect=OSError("Replace error")),
        pytest.raises(OSError, match="Replace error"),
    ):
        save_portfolio_csv(target_file, items)

    # 一時ファイルが残存していないことを検証
    temp_files = list(tmp_path.glob("portfolio_tmp_*"))
    assert len(temp_files) == 0


def test_parse_portfolio_csv_unknown_columns_and_full_preset() -> None:
    """未知のカラムが存在する場合やプリセット銘柄に全情報が明示指定されているケース、非プリセット銘柄を検証する。"""
    csv_data = (
        "account,code,isin,name,units,cost_basis,unknown_col\n"
        "特定,03311181,JP90C000H1T1,カスタム名称,500.0,12000,dummy\n"
        "一般,99999999,JP9999999999,非プリセット銘柄,100.0,10000,dummy\n"
    )
    items = parse_portfolio_csv_content(csv_data)
    assert len(items) == 2
    assert items[0].code == "03311181"
    assert items[0].isin == "JP90C000H1T1"
    assert items[0].name == "カスタム名称"
    assert items[1].code == "99999999"
    assert items[1].name == "非プリセット銘柄"


def test_delete_portfolio_items_by_indices() -> None:
    """行インデックスによる選択削除ロジックを検証する。"""
    from src.models import PortfolioItem
    from src.portfolio_loader import delete_portfolio_items_by_indices

    items = [
        PortfolioItem(account="法人", code="03311187", units=100.0),
        PortfolioItem(account="NISA", code="0331418A", units=200.0),
        PortfolioItem(account="特定", code="03319172", units=300.0),
    ]

    # 1. 複数インデックスの削除 (0, 2)
    remaining = delete_portfolio_items_by_indices(items, {0, 2})
    assert len(remaining) == 1
    assert remaining[0].account == "NISA"
    assert remaining[0].code == "0331418A"

    # 2. 空集合の削除（変更なし）
    remaining_none = delete_portfolio_items_by_indices(items, set())
    assert len(remaining_none) == 3

    # 3. 範囲外インデックス（無視される）
    remaining_out_of_range = delete_portfolio_items_by_indices(items, [99])
    assert len(remaining_out_of_range) == 3


def test_load_portfolio_csv_migrates_legacy_codes(tmp_path: Path) -> None:
    """旧コードが含まれるCSVを読み込んだ際、正規コードへ自動置換および再保存されることを検証する。"""
    csv_file = tmp_path / "legacy_portfolio.csv"
    csv_file.write_text(
        "holder,account,code,isin,units,cost_basis\n"
        "個人,NISA預り（成長投資枠）,03314187,JP90C000GKC6,100,1000\n"
        "個人,特定預り,03311181,JP90C000H1T1,200,2000\n",
        encoding="utf-8",
    )

    loaded = load_portfolio_csv(csv_file)
    assert len(loaded) == 2
    assert loaded[0].code == "03311187"  # 03314187 -> 03311187
    assert loaded[1].code == "0331418A"  # 03311181 -> 0331418A

    # 再保存されたファイル内容の確認
    saved_text = csv_file.read_text(encoding="utf-8")
    assert "03311187" in saved_text
    assert "0331418A" in saved_text
    assert "03314187" not in saved_text
    assert "03311181" not in saved_text
