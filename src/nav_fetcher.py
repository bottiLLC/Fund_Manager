"""投資信託協会の直結エンドポイントを用いた基準価額・銘柄名取得・解析モジュール。"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Self

import requests

from src.portfolio_loader import (
    CANONICAL_PRESET_FUNDS,
    LEGACY_CODE_TO_REAL_CODE,
    PRESET_FUNDS,
)

ISIN_TO_CANONICAL_CODE: Final[dict[str, str]] = {
    meta["isin"]: code for code, meta in CANONICAL_PRESET_FUNDS.items() if "isin" in meta
}


class NavFetchResult(tuple[str, dict[str, float], dict[str, str]]):
    """基準価額および銘柄名フェッチ結果コンテナ。

    従来の (as_of_date, nav_map, name_map) 3要素タプルと多重代入互換であり、
    かつ fetched_at および fallback_funds 属性を保持する。
    """

    as_of_date: str
    nav_map: dict[str, float]
    name_map: dict[str, str]
    fetched_at: str
    fallback_funds: list[str]

    def __new__(
        cls,
        as_of_date: str,
        nav_map: dict[str, float],
        name_map: dict[str, str],
        fetched_at: str,
        fallback_funds: list[str] | None = None,
    ) -> Self:
        instance = super().__new__(cls, (as_of_date, nav_map, name_map))
        instance.as_of_date = as_of_date
        instance.nav_map = nav_map
        instance.name_map = name_map
        instance.fetched_at = fetched_at
        instance.fallback_funds = fallback_funds or []
        return instance

    def __reduce__(
        self,
    ) -> tuple[
        type[Self],
        tuple[str, dict[str, float], dict[str, str], str, list[str]],
    ]:
        return (
            self.__class__,
            (
                self.as_of_date,
                self.nav_map,
                self.name_map,
                self.fetched_at,
                self.fallback_funds,
            ),
        )


DIRECT_CSV_URL_TEMPLATE: Final[str] = (
    "https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000/csv-file-download?isinCd={isin}&associFundCd={code}"
)
DIRECT_DETAIL_URL_TEMPLATE: Final[str] = (
    "https://toushin-lib.fwg.ne.jp/FdsWeb/FDST030000?isinCd={isin}&associFundCd={code}"
)

# ネットワーク完全不通時用の内蔵基準価額・銘柄名フォールバック
FALLBACK_FUNDS: Final[dict[str, dict[str, Any]]] = {
    "03311187": {
        "isin": "JP90C000GKC6",
        "name": "eMAXIS Slim 米国株式(S&P500)",
        "nav": 44943.0,
    },
    "0331124A": {
        "isin": "JP90C000R9Z9",
        "name": "eMAXIS Slim 先進国株式(含む日本)<オール先進国>",
        "nav": 14137.0,
    },
    "0331A172": {
        "isin": "JP90C000END3",
        "name": "eMAXIS Slim 先進国債券インデックス(除く日本)",
        "nav": 15120.0,
    },
    "8931217C": {
        "isin": "JP90C000FQR3",
        "name": "SBI･全世界株式インデックス･ファンド（雪だるま）",
        "nav": 35039.0,
    },
    "03319172": {
        "isin": "JP90C000ENC5",
        "name": "eMAXIS Slim 先進国株式インデックス(除く日本)",
        "nav": 45368.0,
    },
    "2931113C": {
        "isin": "JP90C0009VE0",
        "name": "ニッセイ外国株式インデックスファンド<購入・換金手数料なし>",
        "nav": 59920.0,
    },
    "0331418A": {
        "isin": "JP90C000H1T1",
        "name": "eMAXIS Slim 全世界株式(オール・カントリー)",
        "nav": 37859.0,
    },
    "89311221": {
        "isin": "JP90C000MWH8",
        "name": "SBI･V･全世界株式インデックス・ファンド",
        "nav": 22683.0,
    },
    "89311199": {
        "isin": "JP90C000J569",
        "name": "SBI･V･S&P500インデックス・ファンド",
        "nav": 41070.0,
    },
    # 旧コードとの互換
    "03311181": {
        "isin": "JP90C000H1T1",
        "name": "eMAXIS Slim 全世界株式(オール・カントリー)",
        "nav": 37859.0,
    },
    "03314187": {
        "isin": "JP90C000GKC6",
        "name": "eMAXIS Slim 米国株式(S&P500)",
        "nav": 44943.0,
    },
    "03312184": {
        "isin": "JP90C000ENC5",
        "name": "eMAXIS Slim 先進国株式インデックス(除く日本)",
        "nav": 45368.0,
    },
}

FALLBACK_NAV_MAPPING: Final[dict[str, float]] = {
    code: float(info["nav"]) for code, info in FALLBACK_FUNDS.items()
}


def parse_single_fund_csv_content(csv_bytes: bytes) -> tuple[str, float]:
    """直結エンドポイントから取得した単一銘柄CSVバイナリを解析し、最新日と最新基準価額を返す。

    Args:
        csv_bytes: Shift-JISエンコードされた単一銘柄CSV。

    Returns:
        最新基準日 (YYYY-MM-DD) と最新基準価額 (float)。

    Raises:
        ValueError: CSVが空、または行データが存在しない場合。
    """
    text = csv_bytes.decode("cp932", errors="replace")
    reader = csv.reader(io.StringIO(text))

    try:
        header = next(reader)
    except StopIteration as e:
        msg = "CSVデータが空です。"
        raise ValueError(msg) from e

    nav_col_idx = 1
    date_col_idx = 0

    for idx, col in enumerate(header):
        normalized = col.strip()
        if "基準価額" in normalized:
            nav_col_idx = idx
        elif "年月日" in normalized or "基準日" in normalized or "日付" in normalized:
            date_col_idx = idx

    last_row: list[str] | None = None
    for row in reader:
        if row and len(row) > max(date_col_idx, nav_col_idx):
            val_str = row[nav_col_idx].replace(",", "").strip()
            if val_str:
                last_row = row

    if not last_row:
        msg = "有効な基準価額レコードが存在しません。"
        raise ValueError(msg)

    raw_date = last_row[date_col_idx].strip()
    m = re.search(r"(\d{4})[^\d]+(\d{1,2})[^\d]+(\d{1,2})", raw_date)
    as_of_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else raw_date

    try:
        nav = float(last_row[nav_col_idx].replace(",", "").strip())
    except ValueError as e:
        msg = f"基準価額の数値変換に失敗しました: {last_row[nav_col_idx]}"
        raise ValueError(msg) from e

    return as_of_date, nav


def parse_nav_csv_content(
    csv_bytes: bytes,
    target_codes: set[str],
) -> tuple[str, dict[str, float]]:
    """複数銘柄一括CSVバイナリ（従来形式・キャッシュ用）を解析する。

    Args:
        csv_bytes: CSVバイナリデータ。
        target_codes: 抽出対象のファンドコード集合。

    Returns:
        基準日 (YYYY-MM-DD) と、ファンドコード -> 基準価額(10,000口あたり)の辞書。
    """
    text = csv_bytes.decode("cp932", errors="replace")
    reader = csv.reader(io.StringIO(text))

    try:
        header = next(reader)
    except StopIteration as e:
        msg = "CSVデータが空です。"
        raise ValueError(msg) from e

    code_col_idx = 0
    nav_col_idx: int | None = None
    date_col_idx: int | None = None

    for idx, col in enumerate(header):
        normalized = col.strip()
        if "基準価額" in normalized:
            nav_col_idx = idx
        elif "年月日" in normalized or "基準日" in normalized or "日付" in normalized:
            date_col_idx = idx

    if nav_col_idx is None:
        nav_col_idx = 1 if len(header) > 1 else 0

    as_of_date = datetime.now(UTC).astimezone().strftime("%Y-%m-%d")
    date_found = False

    for col in header:
        m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", col)
        if m:
            as_of_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            date_found = True
            break

    nav_map: dict[str, float] = {}
    for row in reader:
        if not row or len(row) <= max(code_col_idx, nav_col_idx):
            continue

        raw_code = row[code_col_idx].strip()
        if raw_code in target_codes:
            raw_nav = row[nav_col_idx].replace(",", "").strip()
            try:
                nav_value = float(raw_nav)
                nav_map[raw_code] = nav_value
            except ValueError:
                continue

            if not date_found and date_col_idx is not None and len(row) > date_col_idx:
                raw_date = row[date_col_idx].strip()
                m = re.search(r"(\d{4})[/-]?(\d{1,2})[/-]?(\d{1,2})", raw_date)
                if m:
                    as_of_date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
                    date_found = True

    return as_of_date, nav_map


def _fetch_single_fund_live(
    code: str,
    isin: str,
    timeout: float = 8.0,
) -> tuple[str, float, str, bytes]:
    """単一ファンドのCSVと銘柄詳細HTMLをHTTPで取得する。"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    canonical_code = LEGACY_CODE_TO_REAL_CODE.get(code.upper(), code.upper())
    if isin in ISIN_TO_CANONICAL_CODE:
        canonical_code = ISIN_TO_CANONICAL_CODE[isin]

    csv_url = DIRECT_CSV_URL_TEMPLATE.format(isin=isin, code=canonical_code)
    r_csv = requests.get(csv_url, headers=headers, timeout=timeout)
    r_csv.raise_for_status()

    as_of_date, nav = parse_single_fund_csv_content(r_csv.content)

    # 銘柄名のHTML取得
    name = ""
    try:
        detail_url = DIRECT_DETAIL_URL_TEMPLATE.format(isin=isin, code=canonical_code)
        r_html = requests.get(detail_url, headers=headers, timeout=timeout)
        if r_html.status_code == 200:
            titles = re.findall(r"<title>(.*?)</title>", r_html.content.decode("utf-8", "replace"))
            if titles:
                name = unicodedata.normalize("NFKC", titles[0]).strip()
    except Exception:
        pass

    if not name:
        preset = CANONICAL_PRESET_FUNDS.get(canonical_code) or PRESET_FUNDS.get(code)
        name = preset["name"] if preset else f"ファンド {code}"

    return as_of_date, nav, name, r_csv.content


def fetch_latest_nav_and_names(
    targets: dict[str, str],
    cache_dir: Path | None = None,
    timeout: float = 8.0,
) -> NavFetchResult:
    """直結APIおよびキャッシュを用いて、最新基準日、基準価額マップ、銘柄名マップを取得する。

    Args:
        targets: 協会コード -> ISINコードの辞書。
        cache_dir: キャッシュ保存・参照先ディレクトリ。
        timeout: 各銘柄のHTTPリクエストタイムアウト秒数。

    Returns:
        NavFetchResult (as_of_date, nav_map, name_map, fetched_at, fallback_funds)。
        従来の3要素タプルとしても多重代入可能。
    """
    effective_cache_dir = cache_dir or Path("./data/cache")
    effective_cache_dir.mkdir(parents=True, exist_ok=True)
    meta_cache_file = effective_cache_dir / "fund_meta.json"

    cached_meta: dict[str, dict[str, Any]] = {}
    if meta_cache_file.exists():
        try:
            cached_meta = json.loads(meta_cache_file.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            cached_meta = {}

    fetched_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    nav_map: dict[str, float] = {}
    name_map: dict[str, str] = {}
    dates: list[str] = []
    fallback_funds: list[str] = []
    is_cached = False

    def fetch_worker(code: str, isin: str) -> tuple[str, str, float, str, bytes | None]:
        canonical_code = LEGACY_CODE_TO_REAL_CODE.get(code.upper(), code.upper())
        if not isin:
            preset = CANONICAL_PRESET_FUNDS.get(canonical_code) or PRESET_FUNDS.get(code)
            if preset:
                isin = preset["isin"]

        if isin:
            try:
                as_of, nav, name, content = _fetch_single_fund_live(code, isin, timeout=timeout)
                return code, as_of, nav, name, content
            except Exception:
                pass

        # ローカルCSVキャッシュからの復元試行
        single_cache = effective_cache_dir / f"{code}_{isin}.csv"
        if not single_cache.exists() and canonical_code != code:
            single_cache = effective_cache_dir / f"{canonical_code}_{isin}.csv"

        if single_cache.exists():
            try:
                b = single_cache.read_bytes()
                as_of, nav = parse_single_fund_csv_content(b)
                cached_name = (
                    cached_meta.get(code, {}).get("name")
                    or cached_meta.get(canonical_code, {}).get("name")
                    or CANONICAL_PRESET_FUNDS.get(canonical_code, {}).get("name")
                    or PRESET_FUNDS.get(code, {}).get("name", f"ファンド {code}")
                )
                return code, f"{as_of} (Cached)", nav, cached_name, None
            except Exception:
                pass

        # フォールバック辞書の適用
        today_str = datetime.now(UTC).astimezone().strftime("%Y-%m-%d")
        fallback_item = FALLBACK_FUNDS.get(code) or FALLBACK_FUNDS.get(canonical_code)
        if fallback_item:
            return (
                code,
                f"{today_str} (Fallback)",
                float(fallback_item["nav"]),
                str(fallback_item["name"]),
                None,
            )

        return code, f"{today_str} (Fallback)", 10000.0, f"ファンド {code}", None

    with ThreadPoolExecutor(max_workers=min(len(targets) or 1, 8)) as executor:
        futures = [executor.submit(fetch_worker, code, isin) for code, isin in targets.items()]
        for f in as_completed(futures):
            code, as_of, nav, name, content = f.result()
            nav_map[code] = nav
            name_map[code] = name
            clean_date = as_of.replace(" (Cached)", "").replace(" (Fallback)", "")
            dates.append(clean_date)
            if "(Fallback)" in as_of:
                fallback_funds.append(code)
            elif "(Cached)" in as_of:
                is_cached = True

            if content:
                # 個別CSVキャッシュの保存
                isin_val = targets.get(code, "")
                csv_path = effective_cache_dir / f"{code}_{isin_val}.csv"
                with contextlib.suppress(OSError):
                    csv_path.write_bytes(content)

                cached_meta[code] = {
                    "isin": isin_val,
                    "name": name,
                    "nav": nav,
                    "as_of_date": as_of,
                    "fetched_at": fetched_at,
                }

    # メタ情報キャッシュの保存
    if cached_meta:
        with contextlib.suppress(OSError):
            meta_cache_file.write_text(
                json.dumps(cached_meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    overall_date = max(dates) if dates else datetime.now(UTC).astimezone().strftime("%Y-%m-%d")
    if len(fallback_funds) == len(targets) and len(targets) > 0:
        overall_date = f"{overall_date} (Fallback)"
    elif is_cached:
        overall_date = f"{overall_date} (Cached)"

    return NavFetchResult(
        as_of_date=overall_date,
        nav_map=nav_map,
        name_map=name_map,
        fetched_at=fetched_at,
        fallback_funds=fallback_funds,
    )


def fetch_latest_nav(
    target_codes: set[str] | dict[str, str],
    url: str | None = None,
    cache_dir: Path | None = None,
    timeout: float = 8.0,
) -> tuple[str, dict[str, float]]:
    """後方互換用エントリーポイント。基準日と基準価額マップを返却する。"""
    _ = url
    if isinstance(target_codes, dict):
        targets = target_codes
    else:
        targets = {code: PRESET_FUNDS.get(code, {}).get("isin", "") for code in target_codes}

    as_of_date, nav_map, _ = fetch_latest_nav_and_names(
        targets=targets,
        cache_dir=cache_dir,
        timeout=timeout,
    )
    return as_of_date, nav_map
