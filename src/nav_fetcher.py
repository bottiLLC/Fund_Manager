"""投資信託協会の基準価額CSV取得・解析モジュール。"""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import requests

DEFAULT_TOUSHIN_NAV_URL: Final[str] = (
    "https://toushin-lib.fwg.ne.jp/FdsWeb/view/download/LST0000001.csv"
)

FALLBACK_NAV_MAPPING: Final[dict[str, float]] = {
    "03311181": 25842.0,  # eMAXIS Slim 全世界株式(オール・カントリー)
    "0331118A": 25842.0,  # eMAXIS Slim 全世界株式(オール・カントリー) 協会コード
    "0331418A": 25842.0,  # eMAXIS Slim 全世界株式(オール・カントリー) 投信コード
    "03314187": 31250.0,  # eMAXIS Slim 米国株式(S&P500)
    "03312184": 26900.0,  # eMAXIS Slim 先進国株式インデックス
}


def parse_nav_csv_content(
    csv_bytes: bytes,
    target_codes: set[str],
) -> tuple[str, dict[str, float]]:
    """Shift-JISエンコードされた基準価額CSVバイナリを解析し、対象銘柄の基準価額を抽出する。

    Args:
        csv_bytes: CSVバイナリデータ。
        target_codes: 抽出対象の8桁ファンドコード集合。

    Returns:
        基準日 (YYYY-MM-DD) と、ファンドコード -> 基準価額(10,000口あたり)の辞書。

    Raises:
        ValueError: CSVが空、またはヘッダ解析に失敗した場合。
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
        # ヘッダで「基準価額」が見つからない場合、2列目(インデックス1)をデフォルト基準価額列とみなす
        nav_col_idx = 1 if len(header) > 1 else 0

    as_of_date = datetime.now(UTC).astimezone().strftime("%Y-%m-%d")
    date_found = False

    # ヘッダ文字列内に日付が含まれる場合の検出 (例: 2025/01/15, 2025-01-15, 20250115)
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


def fetch_latest_nav(
    target_codes: set[str],
    url: str = DEFAULT_TOUSHIN_NAV_URL,
    cache_dir: Path | None = None,
    timeout: float = 8.0,
) -> tuple[str, dict[str, float]]:
    """投信協会から最新基準価額CSVを取得する。失敗時はキャッシュまたはフォールバックを使用。

    Args:
        target_codes: 抽出対象の8桁ファンドコード集合。
        url: 投信協会のCSVダウンロードURL。
        cache_dir: キャッシュ保存・参照ディレクトリ（None時は./data/cache）。
        timeout: HTTPタイムアウト秒数。

    Returns:
        基準日 (YYYY-MM-DD) と、ファンドコード -> 基準価額の辞書。
    """
    effective_cache_dir = cache_dir or Path("./data/cache")
    effective_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = effective_cache_dir / "latest_nav.csv"

    # 1. ネットワークからの取得試行
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200 and resp.content:
            as_of_date, nav_map = parse_nav_csv_content(resp.content, target_codes)
            if nav_map:
                # 正常取得時はローカルキャッシュに保存
                cache_file.write_bytes(resp.content)
                return as_of_date, nav_map
    except (requests.RequestException, OSError):
        pass

    # 2. ローカルキャッシュからの復元試行
    if cache_file.exists():
        try:
            cached_bytes = cache_file.read_bytes()
            as_of_date, cached_map = parse_nav_csv_content(cached_bytes, target_codes)
            if cached_map:
                return f"{as_of_date} (Cached)", cached_map
        except (OSError, ValueError):
            pass

    # 3. 内蔵フォールバックマップの適用
    today_str = datetime.now(UTC).astimezone().strftime("%Y-%m-%d")
    fallback_result = {code: FALLBACK_NAV_MAPPING.get(code, 10000.0) for code in target_codes}
    return f"{today_str} (Fallback)", fallback_result
