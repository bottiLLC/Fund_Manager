"""src.nav_fetcher のテストモジュール。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.nav_fetcher import (
    FALLBACK_NAV_MAPPING,
    fetch_latest_nav,
    parse_nav_csv_content,
)


def test_parse_nav_csv_content_success() -> None:
    """Shift-JISエンコードのCSVから目的の基準価額と日付が正しく抽出されることを検証する。"""
    # Arrange
    csv_text = (
        "ファンドコード,ファンド名,基準価額,年月日\n"
        '03311181,全世界株式,"25,842",2026/10/20\n'
        "03314187,米国株式,31250,2026/10/20\n"
        "99999999,対象外,10000,2026/10/20\n"
    )
    csv_bytes = csv_text.encode("cp932")
    target_codes = {"03311181", "03314187"}

    # Act
    as_of_date, nav_map = parse_nav_csv_content(csv_bytes, target_codes)

    # Assert
    assert as_of_date == "2026-10-20"
    assert nav_map["03311181"] == 25842.0
    assert nav_map["03314187"] == 31250.0
    assert "99999999" not in nav_map


def test_parse_nav_csv_content_date_in_header() -> None:
    """ヘッダに日付が含まれる場合の日付抽出を検証する。"""
    csv_text = "コード,基準価額(2026-10-19)\n03311181,25000\n"
    csv_bytes = csv_text.encode("cp932")
    as_of_date, nav_map = parse_nav_csv_content(csv_bytes, {"03311181"})

    assert as_of_date == "2026-10-19"
    assert nav_map["03311181"] == 25000.0


def test_parse_nav_csv_content_empty_error() -> None:
    """空のCSVデータでValueErrorが発生することを検証する。"""
    with pytest.raises(ValueError, match="CSVデータが空です"):
        parse_nav_csv_content(b"", {"03311181"})


def test_fetch_latest_nav_network_success(tmp_path: Path) -> None:
    """ネットワーク通信が成功した場合のキャッシュ保存と戻り値を検証する。"""
    csv_text = "コード,基準価額\n03311181,25000\n"
    csv_bytes = csv_text.encode("cp932")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = csv_bytes

    cache_dir = tmp_path / "cache"

    with patch("requests.get", return_value=mock_resp):
        as_of_date, nav_map = fetch_latest_nav(
            target_codes={"03311181"},
            cache_dir=cache_dir,
        )

    assert nav_map["03311181"] == 25000.0
    assert (cache_dir / "latest_nav.csv").exists()


def test_fetch_latest_nav_fallback_to_cache(tmp_path: Path) -> None:
    """ネットワーク失敗時にローカルキャッシュから復元することを検証する。"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "latest_nav.csv"
    cached_content = "コード,基準価額,日付\n03311181,24500,2026-10-15\n".encode("cp932")
    cache_file.write_bytes(cached_content)

    with patch("requests.get", side_effect=requests.RequestException("Network down")):
        as_of_date, nav_map = fetch_latest_nav(
            target_codes={"03311181"},
            cache_dir=cache_dir,
        )

    assert "(Cached)" in as_of_date
    assert nav_map["03311181"] == 24500.0


def test_fetch_latest_nav_fallback_to_builtin_mapping(tmp_path: Path) -> None:
    """ネットワーク失敗かつキャッシュ不在時に内蔵フォールバックを適用することを検証する。"""
    cache_dir = tmp_path / "cache"

    with patch("requests.get", side_effect=requests.RequestException("Network down")):
        as_of_date, nav_map = fetch_latest_nav(
            target_codes={"03311181", "03314187"},
            cache_dir=cache_dir,
        )

    assert "(Fallback)" in as_of_date
    assert nav_map["03311181"] == FALLBACK_NAV_MAPPING["03311181"]
    assert nav_map["03314187"] == FALLBACK_NAV_MAPPING["03314187"]


def test_parse_nav_csv_content_header_without_nav_keyword_and_invalid_rows() -> None:
    """ヘッダに'基準価額'文字列がない場合のインデックス1採用と、不正行スキップを検証する。"""
    csv_text = (
        "コード,価格,予備\n"  # '基準価額' なし -> インデックス1を採用
        "03311181,invalid_price,x\n"  # float変換失敗でスキップ
        "03311181\n"  # 列不足でスキップ
        "03311181,25000,x\n"  # 正常
    )
    as_of_date, nav_map = parse_nav_csv_content(csv_text.encode("cp932"), {"03311181"})
    assert nav_map["03311181"] == 25000.0


def test_fetch_latest_nav_corrupted_cache(tmp_path: Path) -> None:
    """キャッシュファイルが破損している場合にフォールバックへ移行することを検証する。"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "latest_nav.csv"
    cache_file.write_bytes(b"")  # 空ファイル (ValueError: CSVデータが空です)

    with patch("requests.get", side_effect=requests.RequestException("Network down")):
        as_of_date, nav_map = fetch_latest_nav(
            target_codes={"03311181"},
            cache_dir=cache_dir,
        )

    assert "(Fallback)" in as_of_date
    assert nav_map["03311181"] == FALLBACK_NAV_MAPPING["03311181"]


def test_parse_nav_csv_content_unmatched_date_format() -> None:
    """日付列が存在するが正規表現にマッチしない場合のブランチを検証する。"""
    csv_text = "ファンドコード,ファンド名,基準価額,年月日\n03311181,全世界株,25000,日付不明\n"
    as_of_date, nav_map = parse_nav_csv_content(csv_text.encode("cp932"), {"03311181"})
    assert nav_map["03311181"] == 25000.0


def test_fetch_latest_nav_network_no_target_codes_falls_back(tmp_path: Path) -> None:
    """ネットワーク取得成功でも対象コードが0件の場合にキャッシュまたはフォールバックへ移行することを検証する。"""
    csv_text = "コード,基準価額\n99999999,25000\n"
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = csv_text.encode("cp932")

    cache_dir = tmp_path / "cache"

    with patch("requests.get", return_value=mock_resp):
        as_of_date, nav_map = fetch_latest_nav(
            target_codes={"03311181"},
            cache_dir=cache_dir,
        )

    assert "(Fallback)" in as_of_date
    assert nav_map["03311181"] == FALLBACK_NAV_MAPPING["03311181"]


def test_fetch_latest_nav_cache_no_target_codes_falls_back(tmp_path: Path) -> None:
    """キャッシュが存在しても対象コードが0件の場合に内蔵フォールバックへ移行することを検証する。"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "latest_nav.csv"
    cached_content = "コード,基準価額,日付\n99999999,24500,2026-10-15\n".encode("cp932")
    cache_file.write_bytes(cached_content)

    with patch("requests.get", side_effect=requests.RequestException("Network down")):
        as_of_date, nav_map = fetch_latest_nav(
            target_codes={"03311181"},
            cache_dir=cache_dir,
        )

    assert "(Fallback)" in as_of_date
    assert nav_map["03311181"] == FALLBACK_NAV_MAPPING["03311181"]


def test_fetch_latest_nav_fallback_alphanumeric_codes(tmp_path: Path) -> None:
    """英字を含むファンドコードでも内蔵フォールバックから正しく基準価額が取得されることを検証する。"""
    cache_dir = tmp_path / "cache"
    with patch("requests.get", side_effect=requests.RequestException("Network down")):
        as_of_date, nav_map = fetch_latest_nav(
            target_codes={"0331118A", "0331418A"},
            cache_dir=cache_dir,
        )

    assert "(Fallback)" in as_of_date
    assert nav_map["0331118A"] == 25842.0
    assert nav_map["0331418A"] == 25842.0
