"""SBI証券ポートフォリオCSV解析・名寄せ・マージモジュール。

SBI証券からエクスポートされた不規則階層CSV（Shift-JIS/CP932/UTF-8）を解析し、
投資信託明細の抽出、全角・半角正規化によるコード逆引き、学習キャッシュ永続化、
および既存保有資産（PortfolioItem）との安全なマージ処理を提供する。
"""

from __future__ import annotations

import csv
import json
import re
import tempfile
import unicodedata
from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from src.models import PortfolioItem
from src.portfolio_loader import PRESET_FUNDS

# 口座セクション抽出正規表現（例: 投資信託（金額/NISA口座（成長投資枠）））
ACCOUNT_SECTION_PATTERN: Final[re.Pattern[str]] = re.compile(r"投資信託[（\(][^/]+/(.+)[）\)]")

# 標準口座名の正規化辞書
DEFAULT_ACCOUNT_MAP: Final[dict[str, str]] = {
    "NISA口座（成長投資枠）": "NISA成長",
    "NISA口座(成長投資枠)": "NISA成長",
    "NISA口座（つみたて投資枠）": "NISAつみたて",
    "NISA口座(つみたて投資枠)": "NISAつみたて",
    "旧つみたてNISA口座": "旧つみたてNISA",
    "特定口座": "特定",
    "一般口座": "一般",
}


class MergeMode(StrEnum):
    """インポート時の既存データ統合ポリシー。"""

    REPLACE_ALL = "replace_all"  # 洗い替え: 既存データを全破棄し、今回分で完全置換
    APPEND = "append"  # 追記: 既存データを保持し、同一銘柄であっても独立行として末尾追加


class SbiRawRecord(BaseModel):
    """SBI証券CSVから抽出された単一保有投資信託レコード。"""

    model_config = ConfigDict(frozen=True)

    raw_account_section: str = Field(..., description="元の口座セクション文字列")
    fund_name: str = Field(..., min_length=1, description="SBI上のファンド名")
    quantity: float = Field(..., gt=0.0, description="保有口数")
    acquisition_price: float = Field(..., ge=0.0, description="取得単価（10,000口あたり）")
    current_price: float = Field(default=0.0, ge=0.0, description="現在値")
    profit_loss: float = Field(default=0.0, description="含み損益")
    valuation: float = Field(default=0.0, ge=0.0, description="評価額")

    @property
    def calculated_cost_basis(self) -> int:
        """取得単価と保有口数から算出した簿価合計（円単位）。

        取得単価が正値の場合は『数量 × 取得単価 ÷ 10,000』で高精度算出。
        移管等で取得単価が0値・欠損の場合は『評価額 － 含み損益』からフォールバック算出する。
        """
        if self.acquisition_price > 0.0:
            return int(round(self.quantity * self.acquisition_price / 10000.0))
        if self.valuation > 0.0:
            return max(0, int(round(self.valuation - self.profit_loss)))
        return 0


class ImportCandidate(BaseModel):
    """名寄せおよびコード照合結果を保持するインポート候補モデル。"""

    model_config = ConfigDict(frozen=True)

    source_record: SbiRawRecord
    target_account: str
    resolved_code: str = ""
    resolved_isin: str = ""
    is_resolved: bool = False
    validation_error: str | None = None


def normalize_string_key(text: str) -> str:
    """全角・半角英数記号および空白を平坦化し、照合用キーを生成する。

    Args:
        text: 対象文字列。

    Returns:
        正規化済み照合キー文字列。
    """
    normalized = unicodedata.normalize("NFKC", text)
    # 英字を小文字化し、各種空白・記号・カッコを除去
    lowered = normalized.lower()
    return re.sub(r"[\s　＜＞<>()（）・･\-_]+", "", lowered)


def decode_csv_bytes(raw_bytes: bytes) -> str:
    """文字コード（CP932/Shift-JIS/UTF-8-SIG/UTF-8）を安全に自動判別してデコードする。

    Args:
        raw_bytes: CSVファイルのバイト列。

    Returns:
        デコードされた文字列。

    Raises:
        ValueError: サポート対象のいずれの文字コードでもデコードできない場合。
    """
    for encoding in ("cp932", "shift_jis", "utf-8-sig", "utf-8"):
        try:
            return raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    msg = "CSVファイルの文字コードを判別できませんでした（CP932/UTF-8対応）。"
    raise ValueError(msg)


def parse_numeric_cell(cell: str) -> float:
    """カンマや符号が含まれる数値文字列を float に安全変換する。

    Args:
        cell: 表セル文字列。

    Returns:
        数値（float）。変換不可または空欄は 0.0。
    """
    cleaned = cell.strip().replace(",", "").replace("+", "")
    if not cleaned or cleaned in ("-", "--", "----/--/--"):
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def extract_account_name(section_title: str) -> str:
    """セクション見出しから口座名を抽出・正規化する。

    Args:
        section_title: CSV内のセクション行（例: 投資信託（金額/NISA口座（成長投資枠）））。

    Returns:
        正規化された口座名（例: NISA成長）。
    """
    match = ACCOUNT_SECTION_PATTERN.search(section_title)
    if match:
        inner = match.group(1).strip()
        return DEFAULT_ACCOUNT_MAP.get(inner, inner)
    clean_title = section_title.strip().strip('"')
    return DEFAULT_ACCOUNT_MAP.get(clean_title, clean_title)


def parse_sbi_portfolio_csv(csv_text: str) -> list[SbiRawRecord]:
    """SBI証券のポートフォリオCSVテキストを解析し、投資信託レコードを抽出する。

    Args:
        csv_text: CSV全体のテキスト文字列。

    Returns:
        抽出された SbiRawRecord のリスト。
    """
    lines = csv_text.splitlines()
    records: list[SbiRawRecord] = []

    current_section: str = ""
    is_in_fund_table: bool = False
    header_indices: dict[str, int] = {}

    reader = csv.reader(lines)
    for row in reader:
        if not row:
            continue

        first_col = row[0].strip()

        # 総合計または終了ブロックの検知
        if first_col in ("総合計", "合　計", "合計"):
            is_in_fund_table = False
            continue

        # セクション見出しの検知（「投資信託（金額/...）」で始まる行）
        if "投資信託" in first_col and ("(" in first_col or "（" in first_col):
            if "合計" in first_col or "小計" in first_col:
                # セクション末尾の合計行
                is_in_fund_table = False
                continue
            current_section = first_col
            is_in_fund_table = False
            header_indices = {}
            continue

        # ヘッダ行の検知（「ファンド名」と「数量」を含む行）
        if "ファンド名" in row and any("数量" in col for col in row):
            is_in_fund_table = True
            header_indices = {col.strip(): idx for idx, col in enumerate(row)}
            continue

        # 明細データ行のパース
        if is_in_fund_table and current_section:
            fund_name_idx = header_indices["ファンド名"]
            quantity_idx = header_indices["数量"]
            acq_price_idx = header_indices.get("取得単価")
            current_price_idx = header_indices.get("現在値")
            pl_idx = header_indices.get("損益")
            val_idx = header_indices.get("評価額")

            if len(row) <= max(fund_name_idx, quantity_idx):
                continue

            fund_name = row[fund_name_idx].strip()
            # 合計行や無効行のガード
            if not fund_name or "合計" in fund_name or "小計" in fund_name:
                continue

            quantity = parse_numeric_cell(row[quantity_idx])
            # 売却済み・残高ゼロは除外
            if quantity <= 0.0:
                continue

            acq_price = (
                parse_numeric_cell(row[acq_price_idx])
                if acq_price_idx is not None and len(row) > acq_price_idx
                else 0.0
            )
            current_price = (
                parse_numeric_cell(row[current_price_idx])
                if current_price_idx is not None and len(row) > current_price_idx
                else 0.0
            )
            profit_loss = (
                parse_numeric_cell(row[pl_idx]) if pl_idx is not None and len(row) > pl_idx else 0.0
            )
            valuation = (
                parse_numeric_cell(row[val_idx])
                if val_idx is not None and len(row) > val_idx
                else 0.0
            )

            records.append(
                SbiRawRecord(
                    raw_account_section=current_section,
                    fund_name=fund_name,
                    quantity=quantity,
                    acquisition_price=acq_price,
                    current_price=current_price,
                    profit_loss=profit_loss,
                    valuation=valuation,
                )
            )

    return records


def load_custom_aliases(file_path: Path) -> dict[str, tuple[str, str]]:
    """永続化されたカスタム名寄せ辞書（./data/custom_fund_aliases.json）を読み込む。

    Args:
        file_path: 辞書ファイルのパス。

    Returns:
        正規化名称 -> (8桁コード, 12桁ISIN) のマッピング。
    """
    resolved_path = file_path.resolve()
    if not resolved_path.exists():
        return {}
    try:
        content = resolved_path.read_text(encoding="utf-8")
        data = json.loads(content)
        if isinstance(data, dict):
            res: dict[str, tuple[str, str]] = {}
            for k, v in data.items():
                if isinstance(v, (list, tuple)) and len(v) >= 2:
                    res[str(k)] = (str(v[0]), str(v[1]))
            return res
    except OSError, json.JSONDecodeError:
        pass
    return {}


def save_custom_aliases(file_path: Path, aliases: dict[str, tuple[str, str]]) -> None:
    """カスタム名寄せ辞書を原子的に保存する。

    Args:
        file_path: 保存先ファイルパス。
        aliases: 保存する名寄せ辞書。
    """
    resolved_path = file_path.resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    serialized = {k: list(v) for k, v in sorted(aliases.items())}
    content = json.dumps(serialized, ensure_ascii=False, indent=2)

    temp_fd, temp_path_str = tempfile.mkstemp(dir=resolved_path.parent, prefix="alias_tmp_")
    temp_path = Path(temp_path_str)
    try:
        with open(temp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        temp_path.replace(resolved_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def resolve_candidates(
    records: list[SbiRawRecord],
    existing_items: list[PortfolioItem],
    custom_aliases: dict[str, tuple[str, str]],
    account_override_map: dict[str, str] | None = None,
) -> list[ImportCandidate]:
    """SBIレコード群に対してカスケード名寄せを行い、インポート候補リストを生成する。

    名寄せ優先順位:
    1. 既存 portfolio_items 内の同名銘柄からコード/ISINを継承
    2. custom_aliases（学習済み辞書）との前方・正規化一致
    3. PRESET_FUNDS（内蔵マスター）との前方・正規化一致

    Args:
        records: SBI生レコードリスト。
        existing_items: 現在登録済みのPortfolioItemリスト。
        custom_aliases: 学習済みカスタム名寄せ辞書。
        account_override_map: 口座名のユーザー指定置換マップ（オプション）。

    Returns:
        解決状態フラグ付きの ImportCandidate リスト。
    """
    # 既存保有資産からの逆引き辞書構築
    existing_name_map: dict[str, tuple[str, str]] = {}
    for item in existing_items:
        if item.name:
            existing_name_map[normalize_string_key(item.name)] = (item.code, item.isin)

    # PRESET_FUNDS からの逆引き辞書構築
    preset_name_map: dict[str, tuple[str, str]] = {}
    for code, meta in PRESET_FUNDS.items():
        name = meta.get("name", "")
        isin = meta.get("isin", "")
        if name:
            preset_name_map[normalize_string_key(name)] = (code, isin)

    candidates: list[ImportCandidate] = []
    override_map = account_override_map or {}

    for record in records:
        default_account = extract_account_name(record.raw_account_section)
        target_account = override_map.get(default_account, default_account)

        norm_key = normalize_string_key(record.fund_name)
        resolved_code = ""
        resolved_isin = ""
        is_resolved = False

        # カスケード判定 1: 既存ポートフォリオ
        if norm_key in existing_name_map:
            resolved_code, resolved_isin = existing_name_map[norm_key]
            is_resolved = True
        # カスケード判定 2: カスタム辞書
        elif norm_key in custom_aliases:
            resolved_code, resolved_isin = custom_aliases[norm_key]
            is_resolved = True
        # カスケード判定 3: 内蔵プリセット
        elif norm_key in preset_name_map:
            resolved_code, resolved_isin = preset_name_map[norm_key]
            is_resolved = True
        else:
            # 部分一致フォールバック（例: プリセット名称の部分含有）
            for p_key, (p_code, p_isin) in preset_name_map.items():
                if p_key in norm_key or norm_key in p_key:
                    resolved_code, resolved_isin = p_code, p_isin
                    is_resolved = True
                    break

        candidate = ImportCandidate(
            source_record=record,
            target_account=target_account,
            resolved_code=resolved_code,
            resolved_isin=resolved_isin,
            is_resolved=is_resolved,
            validation_error=None if is_resolved else "投信協会コードが未解決です",
        )
        candidates.append(candidate)

    return candidates


def merge_candidates_into_portfolio(
    existing_items: list[PortfolioItem],
    resolved_candidates: list[ImportCandidate],
    merge_mode: MergeMode = MergeMode.APPEND,
) -> list[PortfolioItem]:
    """解決済みのインポート候補を既存ポートフォリオと統合する。

    Args:
        existing_items: 既存のPortfolioItemリスト。
        resolved_candidates: コード解決済みのImportCandidateリスト。
        merge_mode: マージ戦略（APPEND: 追記 / REPLACE_ALL: 洗い替え）。

    Returns:
        統合後のPortfolioItemリスト。

    Raises:
        ValueError: 未解決の候補が含まれている場合。
    """
    for c in resolved_candidates:
        if not c.is_resolved or not c.resolved_code:
            msg = f"未解決の銘柄が含まれています: {c.source_record.fund_name}"
            raise ValueError(msg)

    # 候補から新規 PortfolioItem を生成
    incoming_items: list[PortfolioItem] = [
        PortfolioItem(
            account=c.target_account,
            code=c.resolved_code,
            isin=c.resolved_isin,
            name=c.source_record.fund_name,
            units=c.source_record.quantity,
            cost_basis=c.source_record.calculated_cost_basis,
        )
        for c in resolved_candidates
    ]

    if merge_mode == MergeMode.REPLACE_ALL:
        return incoming_items

    # APPEND モード: 同一銘柄・同一口座であってもまとめず、末尾に追記する
    return [*existing_items, *incoming_items]
