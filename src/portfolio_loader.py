"""保有資産データ (portfolio.csv) の読み込み・検証・保存モジュール。"""

from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path
from typing import Final

from src.models import PortfolioItem

CANONICAL_PRESET_FUNDS: Final[dict[str, dict[str, str]]] = {
    "03311187": {"isin": "JP90C000GKC6", "name": "eMAXIS Slim 米国株式(S&P500)"},
    "0331124A": {
        "isin": "JP90C000R9Z9",
        "name": "eMAXIS Slim 先進国株式(含む日本)<オール先進国>",
    },
    "0331A172": {
        "isin": "JP90C000END3",
        "name": "eMAXIS Slim 先進国債券インデックス(除く日本)",
    },
    "8931217C": {
        "isin": "JP90C000FQR3",
        "name": "SBI･全世界株式インデックス･ファンド（雪だるま）",
    },
    "03319172": {
        "isin": "JP90C000ENC5",
        "name": "eMAXIS Slim 先進国株式インデックス(除く日本)",
    },
    "2931113C": {
        "isin": "JP90C0009VE0",
        "name": "ニッセイ外国株式インデックスファンド<購入・換金手数料なし>",
    },
    "0331418A": {
        "isin": "JP90C000H1T1",
        "name": "eMAXIS Slim 全世界株式(オール・カントリー)",
    },
    "89311221": {
        "isin": "JP90C000MWH8",
        "name": "SBI･V･全世界株式インデックス・ファンド",
    },
    "89311199": {
        "isin": "JP90C000J569",
        "name": "SBI･V･S&P500インデックス・ファンド",
    },
}

LEGACY_CODE_TO_REAL_CODE: Final[dict[str, str]] = {
    "03311181": "0331418A",
    "03314187": "03311187",
    "03312184": "03319172",
}

PRESET_FUNDS: Final[dict[str, dict[str, str]]] = {
    **CANONICAL_PRESET_FUNDS,
    # 旧サンプルコードの後方互換マッピング
    "03311181": {
        "isin": "JP90C000H1T1",
        "name": "eMAXIS Slim 全世界株式(オール・カントリー)",
    },
    "03314187": {
        "isin": "JP90C000GKC6",
        "name": "eMAXIS Slim 米国株式(S&P500)",
    },
    "03312184": {
        "isin": "JP90C000ENC5",
        "name": "eMAXIS Slim 先進国株式インデックス(除く日本)",
    },
}

DEFAULT_PORTFOLIO_HEADER: Final[tuple[str, ...]] = (
    "holder",
    "account",
    "code",
    "isin",
    "units",
    "cost_basis",
)

COLUMN_ALIASES: Final[dict[str, str]] = {
    "holder": "holder",
    "法人/個人": "holder",
    "法人・個人": "holder",
    "区分": "holder",
    "名義": "holder",
    "所有者": "holder",
    "保有者": "holder",
    "account": "account",
    "口座": "account",
    "口座名": "account",
    "口座種別": "account",
    "格納口座": "account",
    "code": "code",
    "協会コード": "code",
    "ファンドコード": "code",
    "isin": "isin",
    "isinコード": "isin",
    "isin_code": "isin",
    "国際証券コード": "isin",
    "name": "name",
    "銘柄名": "name",
    "銘柄略称": "name",
    "ファンド名": "name",
    "units": "units",
    "保有口数": "units",
    "口数": "units",
    "cost_basis": "cost_basis",
    "取得簿価": "cost_basis",
    "簿価": "cost_basis",
}

DEFAULT_SAMPLE_PORTFOLIO: Final[str] = (
    "holder,account,code,isin,units,cost_basis\n"
    "法人,一般預り,0331418A,JP90C000H1T1,5000000.0,7500000\n"
    "個人,NISA預り（成長投資枠）,03311187,JP90C000GKC6,3000000.0,6000000\n"
    "個人,特定預り,03319172,JP90C000ENC5,2000000.0,4500000\n"
    "個人,iDeCo,0331418A,JP90C000H1T1,1500000.0,0\n"
    "個人,DC,03311187,JP90C000GKC6,1000000.0,\n"
)


def parse_portfolio_csv_content(
    csv_content: str,
    *,
    allow_empty: bool = False,
) -> list[PortfolioItem]:
    """CSV文字列を解析し、PortfolioItemのリストを返す。

    Args:
        csv_content: CSV形式の生テキスト文字列。
        allow_empty: 有効銘柄データが0件の場合に空リストを許容するかどうか。

    Returns:
        検証済みのPortfolioItemインスタンスのリスト。

    Raises:
        ValueError: ヘッダ不正や必須フィールドの欠損・型変換エラー時。
    """
    reader = csv.DictReader(io.StringIO(csv_content))
    if not reader.fieldnames:
        msg = "CSVファイルが空か、有効なヘッダ行が存在しません。"
        raise ValueError(msg)

    # ヘッダのエイリアス正規化
    normalized_header_map: dict[str, str] = {}
    for raw_fn in reader.fieldnames:
        clean_fn = raw_fn.strip()
        normalized_name = COLUMN_ALIASES.get(clean_fn.lower()) or COLUMN_ALIASES.get(clean_fn)
        if normalized_name:
            normalized_header_map[raw_fn] = normalized_name

    fieldnames_canonical = set(normalized_header_map.values())

    # 必須列の検証（account, code, units, cost_basis は常に必須）
    base_required = {"account", "code", "units", "cost_basis"}
    missing_fields = base_required - fieldnames_canonical
    if missing_fields:
        msg = f"必須ヘッダ列が不足しています: {', '.join(sorted(missing_fields))}"
        raise ValueError(msg)

    items: list[PortfolioItem] = []
    for line_num, raw_row in enumerate(reader, start=2):
        if not raw_row:
            continue

        row: dict[str, str] = {}
        for k, v in raw_row.items():
            norm_k = normalized_header_map.get(k)
            if norm_k:
                row[norm_k] = (v or "").strip()

        holder = row.get("holder", "")
        account = row.get("account", "")
        code = row.get("code", "")
        isin = row.get("isin", "")
        name = row.get("name", "")
        raw_units = row.get("units", "")
        raw_cost = row.get("cost_basis", "")

        if not account and not code and not name and not isin:
            continue

        # 旧フォーマットCSV（holder列なし）の後方互換フォールバック
        if not holder:
            if account == "法人":
                holder = "法人"
                account = "一般預り"
            else:
                holder = "個人"

        # 既知主要銘柄からの自動補完
        preset = PRESET_FUNDS.get(code.upper())
        if preset:
            if not isin:
                isin = preset["isin"]
            if not name:
                name = preset["name"]

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
            holder=holder,
            account=account,
            code=code,
            isin=isin,
            name=name,
            units=units,
            cost_basis=cost_basis,
        )
        items.append(item)

    if not items and not allow_empty:
        msg = "有効な保有銘柄データが1件も存在しません。"
        raise ValueError(msg)

    return items


def load_portfolio_csv(
    file_path: Path,
    *,
    allow_empty: bool = True,
) -> list[PortfolioItem]:
    """ファイルパスから保有資産CSVを読み込む。不在時はデフォルトサンプルを生成する。

    Args:
        file_path: 読み込み対象のCSVパス。
        allow_empty: 有効銘柄データが0件の場合に空リストを許容するかどうか。

    Returns:
        検証済みのPortfolioItemインスタンスのリスト。
    """
    resolved_path = file_path.resolve()
    if not resolved_path.exists():
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(DEFAULT_SAMPLE_PORTFOLIO, encoding="utf-8")

    content = resolved_path.read_text(encoding="utf-8")
    items = parse_portfolio_csv_content(content, allow_empty=allow_empty)

    # 旧コードが検出された場合は正規コードへ自動マイグレーションして再保存
    migrated = False
    migrated_items: list[PortfolioItem] = []
    for item in items:
        if item.code in LEGACY_CODE_TO_REAL_CODE:
            new_code = LEGACY_CODE_TO_REAL_CODE[item.code]
            migrated_items.append(item.model_copy(update={"code": new_code}))
            migrated = True
        else:
            migrated_items.append(item)

    if migrated:
        save_portfolio_csv(resolved_path, migrated_items)
        return migrated_items

    return items


def save_portfolio_csv(file_path: Path, items: list[PortfolioItem]) -> None:
    """PortfolioItemリストをCSVファイルへ原子的に保存する。

    Args:
        file_path: 保存先ファイルパス。
        items: 保存するPortfolioItemインスタンスのリスト。
    """
    resolved_path = file_path.resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    header = ["holder", "account", "code", "isin", "units", "cost_basis"]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)

    for item in items:
        writer.writerow(
            [
                item.holder,
                item.account,
                item.code,
                item.isin,
                f"{item.units:f}".rstrip("0").rstrip(".")
                if "." in f"{item.units:f}"
                else f"{item.units}",
                str(item.cost_basis) if item.cost_basis > 0 else "",
            ]
        )

    temp_fd, temp_path_str = tempfile.mkstemp(dir=resolved_path.parent, prefix="portfolio_tmp_")
    temp_path = Path(temp_path_str)
    try:
        with open(temp_fd, "w", encoding="utf-8", newline="") as f:
            f.write(buf.getvalue())
        temp_path.replace(resolved_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def delete_portfolio_items_by_indices(
    existing_items: list[PortfolioItem],
    indices_to_delete: set[int] | list[int],
) -> list[PortfolioItem]:
    """指定された行インデックスの銘柄を除外した新規リストを生成する。

    Args:
        existing_items: 現在登録済みのPortfolioItemリスト。
        indices_to_delete: 削除対象の0始まりインデックス集合。

    Returns:
        削除対象が除外されたPortfolioItemリスト。
    """
    delete_set = set(indices_to_delete)
    return [item for idx, item in enumerate(existing_items) if idx not in delete_set]
