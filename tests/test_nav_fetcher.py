"""src.nav_fetcher のテストモジュール。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.nav_fetcher import (
    FALLBACK_FUNDS,
    FALLBACK_NAV_MAPPING,
    _fetch_single_fund_live,
    fetch_latest_nav,
    fetch_latest_nav_and_names,
    parse_nav_csv_content,
    parse_single_fund_csv_content,
)


def test_parse_single_fund_csv_content_success() -> None:
    """単一銘柄CSVから最新日付と基準価額が正常に抽出されることを検証する。"""
    csv_text = (
        "年月日,基準価額(円),純資産総額(百万円),分配金,決算日\n"
        "2026年10月18日,37000,10000,,\n"
        "2026年10月19日,37500,10100,,\n"
        "2026年10月20日,37859,10200,,\n"
    )
    as_of_date, nav = parse_single_fund_csv_content(csv_text.encode("cp932"))
    assert as_of_date == "2026-10-20"
    assert nav == 37859.0


def test_parse_single_fund_csv_content_date_fallback_and_invalid_number() -> None:
    """日付フォーマットが非標準の場合および数値エラーの例外を検証する。"""
    csv_text = "年月日,基準価額\n2026-10-20,35000\n"
    as_of, nav = parse_single_fund_csv_content(csv_text.encode("cp932"))
    assert as_of == "2026-10-20"
    assert nav == 35000.0

    empty_csv = b""
    with pytest.raises(ValueError, match="CSVデータが空です"):
        parse_single_fund_csv_content(empty_csv)

    no_records = "年月日,基準価額\n".encode("cp932")
    with pytest.raises(ValueError, match="有効な基準価額レコードが存在しません"):
        parse_single_fund_csv_content(no_records)

    bad_nav = "年月日,基準価額\n2026-10-20,not_a_number\n".encode("cp932")
    with pytest.raises(ValueError, match="基準価額の数値変換に失敗しました"):
        parse_single_fund_csv_content(bad_nav)


def test_parse_nav_csv_content_success() -> None:
    """複数銘柄一括CSVから目的の基準価額と日付が正しく抽出されることを検証する。"""
    csv_text = (
        "ファンドコード,ファンド名,基準価額,年月日\n"
        '0331418A,全世界株式,"25,842",2026/10/20\n'
        "03311187,米国株式,31250,2026/10/20\n"
        "99999999,対象外,10000,2026/10/20\n"
    )
    csv_bytes = csv_text.encode("cp932")
    target_codes = {"0331418A", "03311187"}

    as_of_date, nav_map = parse_nav_csv_content(csv_bytes, target_codes)
    assert as_of_date == "2026-10-20"
    assert nav_map["0331418A"] == 25842.0
    assert nav_map["03311187"] == 31250.0
    assert "99999999" not in nav_map


def test_parse_nav_csv_content_date_in_header() -> None:
    """ヘッダに日付が含まれる場合の日付抽出を検証する。"""
    csv_text = "コード,基準価額(2026-10-19)\n0331418A,25000\n"
    csv_bytes = csv_text.encode("cp932")
    as_of_date, nav_map = parse_nav_csv_content(csv_bytes, {"0331418A"})

    assert as_of_date == "2026-10-19"
    assert nav_map["0331418A"] == 25000.0


def test_parse_nav_csv_content_empty_error() -> None:
    """空のCSVデータでValueErrorが発生することを検証する。"""
    with pytest.raises(ValueError, match="CSVデータが空です"):
        parse_nav_csv_content(b"", {"0331418A"})


def test_parse_nav_csv_content_header_without_nav_keyword_and_invalid_rows() -> None:
    """ヘッダに基準価額キーワードがない場合および不正行スキップを検証する。"""
    csv_text = "コード,第2列\n\n0331418A,invalid_number\n0331418A,26000\n"
    as_of_date, nav_map = parse_nav_csv_content(csv_text.encode("cp932"), {"0331418A"})
    assert nav_map["0331418A"] == 26000.0


def test_parse_nav_csv_content_unmatched_date_format() -> None:
    """日付列が存在するが正規表現にマッチしない場合のブランチを検証する。"""
    csv_text = "ファンドコード,ファンド名,基準価額,年月日\n0331418A,全世界株,25000,日付不明\n"
    as_of_date, nav_map = parse_nav_csv_content(csv_text.encode("cp932"), {"0331418A"})
    assert nav_map["0331418A"] == 25000.0


def test_fetch_single_fund_live_success() -> None:
    """単一銘柄のライブフェッチ（CSVおよびHTMLタイトル抽出）を検証する。"""
    csv_resp = MagicMock()
    csv_resp.status_code = 200
    csv_resp.content = (
        "年月日,基準価額(円),純資産総額(百万円),分配金,決算日\n2026年10月20日,37859,10200,,\n"
    ).encode("cp932")

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.content = "<html><title>ｅＭＡＸＩＳ　Ｓｌｉｍ全世界株式</title></html>".encode()

    def side_effect(url: str, **_kwargs: object) -> MagicMock:
        if "csv-file-download" in url:
            return csv_resp
        return html_resp

    with patch("requests.get", side_effect=side_effect):
        as_of, nav, name, content = _fetch_single_fund_live("0331418A", "JP90C000H1T1")

    assert as_of == "2026-10-20"
    assert nav == 37859.0
    assert "eMAXIS Slim全世界株式" in name
    assert content == csv_resp.content


def test_fetch_latest_nav_and_names_caching_and_fallback(tmp_path: Path) -> None:
    """並列フェッチ、キャッシュ保存、キャッシュ復元、内蔵フォールバックを網羅検証する。"""
    cache_dir = tmp_path / "cache"

    csv_resp = MagicMock()
    csv_resp.status_code = 200
    csv_resp.content = "年月日,基準価額\n2026年10月20日,37859\n".encode("cp932")

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.content = "<title>テストファンド</title>".encode()

    def mock_get(url: str, **_kwargs: object) -> MagicMock:
        if "csv-file-download" in url:
            return csv_resp
        return html_resp

    # 1. ネットワーク成功時（キャッシュ保存とメタ更新）
    with patch("requests.get", side_effect=mock_get):
        as_of, navs, names = fetch_latest_nav_and_names(
            targets={"0331418A": "JP90C000H1T1"},
            cache_dir=cache_dir,
        )
    assert as_of == "2026-10-20"
    assert navs["0331418A"] == 37859.0
    assert names["0331418A"] == "テストファンド"
    assert (cache_dir / "0331418A_JP90C000H1T1.csv").exists()
    assert (cache_dir / "fund_meta.json").exists()

    # 2. ネットワーク失敗時、ローカルキャッシュからの復元
    with patch("requests.get", side_effect=requests.RequestException("Offline")):
        as_of2, navs2, names2 = fetch_latest_nav_and_names(
            targets={"0331418A": "JP90C000H1T1"},
            cache_dir=cache_dir,
        )
    assert "(Cached)" in as_of2
    assert navs2["0331418A"] == 37859.0
    assert names2["0331418A"] == "テストファンド"

    # 3. キャッシュ不在銘柄の内蔵フォールバック
    with patch("requests.get", side_effect=requests.RequestException("Offline")):
        as_of3, navs3, names3 = fetch_latest_nav_and_names(
            targets={"8931217C": "JP90C000FQR3", "UNKNOWN9": ""},
            cache_dir=tmp_path / "empty_cache",
        )
    assert "(Fallback)" in as_of3
    assert navs3["8931217C"] == FALLBACK_FUNDS["8931217C"]["nav"]
    assert navs3["UNKNOWN9"] == 10000.0


def test_fetch_latest_nav_backward_compatibility(tmp_path: Path) -> None:
    """fetch_latest_nav ラッパーの後方互換性を検証する。"""
    cache_dir = tmp_path / "cache"
    with patch("requests.get", side_effect=requests.RequestException("Offline")):
        as_of, nav_map = fetch_latest_nav(
            target_codes={"0331418A", "03311187"},
            cache_dir=cache_dir,
        )

    assert "(Fallback)" in as_of
    assert nav_map["0331418A"] == FALLBACK_NAV_MAPPING["0331418A"]
    assert nav_map["03311187"] == FALLBACK_NAV_MAPPING["03311187"]

    # dict入力での呼び出し
    with patch("requests.get", side_effect=requests.RequestException("Offline")):
        as_of2, nav_map2 = fetch_latest_nav(
            target_codes={"0331418A": "JP90C000H1T1"},
            cache_dir=cache_dir,
        )
    assert "(Fallback)" in as_of2
    assert nav_map2["0331418A"] == FALLBACK_NAV_MAPPING["0331418A"]


def test_fetch_single_fund_live_html_failure_and_preset_name() -> None:
    """銘柄詳細HTML取得が失敗した場合にプリセット名へフォールバックすることを検証する。"""
    csv_resp = MagicMock()
    csv_resp.status_code = 200
    csv_resp.content = "年月日,基準価額\n2026年10月20日,37859\n".encode("cp932")

    def side_effect(url: str, **_kwargs: object) -> MagicMock:
        if "csv-file-download" in url:
            return csv_resp
        raise requests.RequestException("HTML error")

    with patch("requests.get", side_effect=side_effect):
        as_of, nav, name, content = _fetch_single_fund_live("0331418A", "JP90C000H1T1")

    assert as_of == "2026-10-20"
    assert nav == 37859.0
    assert name == "eMAXIS Slim 全世界株式(オール・カントリー)"

    # 未知のコードの場合
    with patch("requests.get", side_effect=side_effect):
        _, _, name_unknown, _ = _fetch_single_fund_live("99999999", "JP9999999999")
    assert name_unknown == "ファンド 99999999"


def test_fetch_latest_nav_and_names_corrupt_cache_and_empty_targets(tmp_path: Path) -> None:
    """破損キャッシュおよび空ターゲット時の安全な動作を検証する。"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 破損したメタキャッシュJSON
    (cache_dir / "fund_meta.json").write_text("{broken json", encoding="utf-8")

    # 破損した単一CSVキャッシュ
    (cache_dir / "0331418A_JP90C000H1T1.csv").write_bytes(b"broken,csv,data\n")

    with patch("requests.get", side_effect=requests.RequestException("Offline")):
        as_of, navs, names = fetch_latest_nav_and_names(
            targets={"0331418A": "JP90C000H1T1"},
            cache_dir=cache_dir,
        )

    assert "(Fallback)" in as_of
    assert navs["0331418A"] == 37859.0

    # targetsが空の場合
    as_of_empty, navs_empty, names_empty = fetch_latest_nav_and_names(
        targets={},
        cache_dir=cache_dir,
    )
    assert len(navs_empty) == 0


def test_fetch_latest_nav_and_names_oserror_suppressed(tmp_path: Path) -> None:
    """キャッシュ書き込み時のOSErrorが抑制されて正常に値が返却されることを検証する。"""
    cache_dir = tmp_path / "cache"

    csv_resp = MagicMock()
    csv_resp.status_code = 200
    csv_resp.content = "年月日,基準価額\n2026年10月20日,37859\n".encode("cp932")

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.content = "<title>テストファンド</title>".encode()

    def mock_get(url: str, **_kwargs: object) -> MagicMock:
        if "csv-file-download" in url:
            return csv_resp
        return html_resp

    with (
        patch("requests.get", side_effect=mock_get),
        patch("pathlib.Path.write_bytes", side_effect=OSError("Write error")),
        patch("pathlib.Path.write_text", side_effect=OSError("Write error")),
    ):
        as_of, navs, names = fetch_latest_nav_and_names(
            targets={"0331418A": "JP90C000H1T1"},
            cache_dir=cache_dir,
        )

    assert as_of == "2026-10-20"
    assert navs["0331418A"] == 37859.0


def test_parse_single_fund_csv_content_edge_cases() -> None:
    """空行、不完全行、空白値、日付正規表現不一致の網羅分岐を検証する。"""
    # 1. 不完全行や空文字基準価額を含むCSV
    csv_text = "年月日,基準価額\n\n2026/10/18\n2026/10/19,   \n2026年10月20日,37859\n"
    as_of, nav = parse_single_fund_csv_content(csv_text.encode("cp932"))
    assert as_of == "2026-10-20"
    assert nav == 37859.0

    # 2. 日付が正規表現にマッチしないケース
    csv_text_nodate = "年月日,基準価額\nINVALID_DATE,12345\n"
    as_of_nodate, nav_nodate = parse_single_fund_csv_content(csv_text_nodate.encode("cp932"))
    assert as_of_nodate == "INVALID_DATE"
    assert nav_nodate == 12345.0


def test_fetch_single_fund_live_status_code_not_200_and_no_title() -> None:
    """詳細HTMLのステータスコードが200以外、またはtitleタグが存在しないケースを検証する。"""
    csv_resp = MagicMock()
    csv_resp.status_code = 200
    csv_resp.content = "年月日,基準価額\n2026年10月20日,37859\n".encode("cp932")

    # 1. status_code = 500
    html_resp_500 = MagicMock()
    html_resp_500.status_code = 500
    html_resp_500.content = b"Error"

    def mock_get_500(url: str, **_kwargs: object) -> MagicMock:
        if "csv-file-download" in url:
            return csv_resp
        return html_resp_500

    with patch("requests.get", side_effect=mock_get_500):
        _, _, name_500, _ = _fetch_single_fund_live("0331418A", "JP90C000H1T1")
    assert name_500 == "eMAXIS Slim 全世界株式(オール・カントリー)"

    # 2. status_code = 200 だが <title> なし
    html_resp_notitle = MagicMock()
    html_resp_notitle.status_code = 200
    html_resp_notitle.content = b"<html><body>No title here</body></html>"

    def mock_get_notitle(url: str, **_kwargs: object) -> MagicMock:
        if "csv-file-download" in url:
            return csv_resp
        return html_resp_notitle

    with patch("requests.get", side_effect=mock_get_notitle):
        _, _, name_notitle, _ = _fetch_single_fund_live("0331418A", "JP90C000H1T1")
    assert name_notitle == "eMAXIS Slim 全世界株式(オール・カントリー)"


def test_fetch_latest_nav_and_names_preset_isin_lookup(tmp_path: Path) -> None:
    """targetsのisinが空の場合にPRESET_FUNDSからISINが自動補完されて取得できることを検証する。"""
    csv_resp = MagicMock()
    csv_resp.status_code = 200
    csv_resp.content = "年月日,基準価額\n2026年10月20日,37859\n".encode("cp932")

    html_resp = MagicMock()
    html_resp.status_code = 200
    html_resp.content = "<title>テストファンド</title>".encode()

    def mock_get(url: str, **_kwargs: object) -> MagicMock:
        if "csv-file-download" in url:
            return csv_resp
        return html_resp

    with patch("requests.get", side_effect=mock_get):
        as_of, navs, names = fetch_latest_nav_and_names(
            targets={"0331418A": ""},
            cache_dir=tmp_path / "cache",
        )

    assert as_of == "2026-10-20"
    assert navs["0331418A"] == 37859.0
    assert names["0331418A"] == "テストファンド"


def test_fetch_latest_nav_and_names_legacy_code_cache_and_partial_fallback(tmp_path: Path) -> None:
    """旧コードの正規コードキャッシュ解決および部分フォールバック判定を検証する。"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. 正規コード名のキャッシュCSVを事前配置
    csv_bytes = "年月日,基準価額\n2026-10-20,37859\n".encode("cp932")
    (cache_dir / "0331418A_JP90C000H1T1.csv").write_bytes(csv_bytes)

    # ネットワーク不通下で旧コード 03311181 と キャッシュ不在コード UNKNOWN をフェッチ
    with patch("requests.get", side_effect=requests.RequestException("Offline")):
        result = fetch_latest_nav_and_names(
            targets={"03311181": "JP90C000H1T1", "UNKNOWN": ""},
            cache_dir=cache_dir,
        )

    # 03311181 は 0331418A のキャッシュから復元され、UNKNOWN のみがフォールバックとなる
    assert "(Cached)" in result.as_of_date
    assert "(Fallback)" not in result.as_of_date
    assert result.nav_map["03311181"] == 37859.0
    assert result.nav_map["UNKNOWN"] == 10000.0
    assert result.fallback_funds == ["UNKNOWN"]
    assert result.fetched_at is not None
