"""保有資産データ (portfolio.csv) の読み込み・検証モジュール。"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Final

from src.models import PortfolioItem

DEFAULT_PORTFOLIO_HEADER: Final[tuple[str, ...]] = (
    "account",
    "code",
    "name",
    "units",
    "cost_basis",
)

DEFAULT_SAMPLE_PORTFOLIO: Final[str] = (
    "account,code,name,units,cost_basis\n"
    "法人,03311181,eMAXIS Slim 全世界株式(OL),5000000.0,7500000\n"
    "NISA,03314187,eMAXIS Slim 米国株式(S&P500),3000000.0,6000000\n"
    "特定,03312184,eMAXIS Slim 先進国株式,2000000.0,4500000\n"
    "iDeCo,03311181,eMAXIS Slim 全世界株式(OL),1500000.0,0\n"
    "DC,03314187,eMAXIS Slim 米国株式(S&P500),1000000.0,\n"
)


def parse_portfolio_csv_content(csv_content: str) -> list[PortfolioItem]:
    """CSV文字列を解析し、PortfolioItemのリストを返す。

    Args:
        csv_content: CSV形式の生テキスト文字列。

    Returns:
        検証済みのPortfolioItemインスタンスのリスト。

    Raises:
        ValueError: ヘッダ不正や必須フィールドの欠損・型変換エラー時。
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    if not reader.fieldnames:
        msg = "CSVファイルが空か、有効なヘッダ行が存在しません。"
        raise ValueError(msg)

    fieldnames_set = {fn.strip() for fn in reader.fieldnames}
    missing_fields = set(DEFAULT_PORTFOLIO_HEADER) - fieldnames_set
    if missing_fields:
        msg = f"必須ヘッダ列が不足しています: {', '.join(sorted(missing_fields))}"
        raise ValueError(msg)

    items: list[PortfolioItem] = []
    for line_num, row in enumerate(reader, start=2):
        if not row:
            continue
        account = (row.get("account") or "").strip()
        code = (row.get("code") or "").strip()
        name = (row.get("name") or "").strip()
        raw_units = (row.get("units") or "").strip()
        raw_cost = (row.get("cost_basis") or "").strip()

        if not account and not code and not name:
            continue

        try:
            units = float(raw_units)
        except ValueError as e:
            msg = f"{line_num}行目: units は有効な数値である必要があります (値: {raw_units})"
            raise ValueError(msg) from e

        cost_basis = 0
        if raw_cost:
            try:
                cost_basis = int(float(raw_cost.replace(",", "")))
            except ValueError as e:
                msg = (
                    f"{line_num}行目: cost_basis は有効な数値である必要があります (値: {raw_cost})"
                )
                raise ValueError(msg) from e

        item = PortfolioItem(
            account=account,
            code=code,
            name=name,
            units=units,
            cost_basis=cost_basis,
        )
        items.append(item)

    if not items:
        msg = "有効な保有銘柄データが1件も存在しません。"
        raise ValueError(msg)

    return items


def load_portfolio_csv(file_path: Path) -> list[PortfolioItem]:
    """ファイルパスから保有資産CSVを読み込む。不在時はデフォルトサンプルを生成する。

    Args:
        file_path: 読み込み対象のCSVパス。

    Returns:
        検証済みのPortfolioItemインスタンスのリスト。
    """
    resolved_path = file_path.resolve()
    if not resolved_path.exists():
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(DEFAULT_SAMPLE_PORTFOLIO, encoding="utf-8")

    content = resolved_path.read_text(encoding="utf-8")
    return parse_portfolio_csv_content(content)
