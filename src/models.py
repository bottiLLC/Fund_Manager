"""ドメインモデルおよびデータバリデーションスキーマ定義。"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

FUND_CODE_REGEX: Final[re.Pattern[str]] = re.compile(r"^[0-9A-Z]{8}$")
ISIN_CODE_REGEX: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}\d$")
HOLDER_OPTIONS: Final[tuple[str, ...]] = ("個人", "法人", "個人(DC)")


class PortfolioItem(BaseModel):
    """ローカル保有資産CSV (portfolio.csv) の1行を表すデータモデル。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    holder: str = Field(
        default="個人",
        description="所有者区分（個人 / 法人 / 個人(DC)。手入力指定）",
    )
    account: str = Field(
        ...,
        min_length=1,
        description="格納口座種別（NISA預り（成長投資枠）, 一般預り, 特定預り など）",
    )
    code: str = Field(..., description="投信協会の8桁ファンドコード（半角英大文字・数字）")
    isin: str = Field(default="", description="国際証券識別番号（12桁ISINコード）")
    name: str = Field(default="", description="銘柄略称（Webから自動補完可能）")
    units: float = Field(..., gt=0.0, description="保有口数")
    cost_basis: int = Field(
        default=0, ge=0, description="取得簿価の合計金額（0または空欄は簿価管理不要）"
    )

    @field_validator("code")
    @classmethod
    def validate_fund_code(cls, v: str) -> str:
        cleaned = v.strip()
        if not FUND_CODE_REGEX.match(cleaned):
            msg = f"ファンドコードは8桁の半角英数字（大文字）である必要があります: {v}"
            raise ValueError(msg)
        return cleaned

    @field_validator("isin")
    @classmethod
    def validate_isin_code(cls, v: str) -> str:
        cleaned = v.strip()
        if cleaned and not ISIN_CODE_REGEX.match(cleaned):
            msg = f"ISINコードは12桁の半角英数字である必要があります: {v}"
            raise ValueError(msg)
        return cleaned

    @field_validator("holder")
    @classmethod
    def validate_holder(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            return "個人"
        if cleaned not in HOLDER_OPTIONS:
            msg = f"所有者区分は {HOLDER_OPTIONS} のいずれかである必要があります: {v}"
            raise ValueError(msg)
        return cleaned


class FundInfo(BaseModel):
    """Webから取得した投資信託の基準情報。"""

    model_config = ConfigDict(frozen=True)

    code: str = Field(..., description="投信協会コード")
    isin: str = Field(..., description="ISINコード")
    name: str = Field(..., description="銘柄正式名称または略称")
    nav: float = Field(..., gt=0.0, description="最新基準価額（10,000口あたり）")
    as_of_date: str = Field(..., description="基準日（YYYY-MM-DD）")


class HoldingEvaluation(BaseModel):
    """各銘柄の基準価額突合後の評価結果。"""

    model_config = ConfigDict(frozen=True)

    item: PortfolioItem
    nav: float = Field(..., gt=0.0, description="基準価額（10,000口あたり）")
    virtual_units: float = Field(default=0.0, ge=0.0, description="DC仮想購入口数")
    effective_units: float = Field(..., gt=0.0, description="実質口数（保有口数 + 仮想口数）")
    valuation: int = Field(..., description="評価額（円）")
    profit_loss: int | None = Field(default=None, description="含み損益（円、簿価なし時はNone）")
    profit_loss_rate: float | None = Field(
        default=None, description="損益率（%、簿価なし時はNone）"
    )


class TankSummary(BaseModel):
    """口座（タンク）ごとの集計サマリー。"""

    model_config = ConfigDict(frozen=True)

    account: str
    valuation_total: int = Field(..., ge=0, description="口座別評価額合計")
    ratio: float = Field(..., ge=0.0, le=100.0, description="総資産に占める構成比率（%）")
    profit_loss_total: int | None = Field(default=None, description="口座別含み損益合計")
    bar: str = Field(..., description="テキストプログレスバー [████████░░] 45.2%")


class PortfolioReport(BaseModel):
    """CLIおよびGUIに渡される集計結果レポート全体。"""

    model_config = ConfigDict(frozen=True)

    as_of_date: str = Field(..., description="基準価額データの取得日付 (YYYY-MM-DD)")
    fetched_at: str | None = Field(
        default=None, description="基準価額データの取得実行日時 (YYYY/MM/DD HH:MM:SS)"
    )
    fallback_funds: list[str] = Field(
        default_factory=list, description="フォールバック値が適用された銘柄コード一覧"
    )
    total_valuation: int = Field(..., ge=0, description="総資産評価額（円）")
    total_profit_loss: int | None = Field(default=None, description="総含み損益（円）")
    tank_summaries: list[TankSummary] = Field(default_factory=list)
    holdings: list[HoldingEvaluation] = Field(default_factory=list)


class FundSnapshotRecord(BaseModel):
    """日次ポートフォリオ履歴スナップショット1行を表す不変モデル。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recorded_date: str = Field(..., description="記録基準日 (YYYY-MM-DD)")
    recorded_at: str = Field(..., description="記録タイムスタンプ (ISO8601)")
    holder: str = Field(..., description="所有者区分 (個人 / 法人 / 個人(DC))")
    account: str = Field(..., description="格納口座種別")
    code: str = Field(..., min_length=8, max_length=8, description="投信協会コード (8桁)")
    isin: str = Field(default="", description="ISINコード")
    name: str = Field(..., description="銘柄名")
    units: float = Field(..., gt=0.0, description="保有口数")
    cost_basis: int = Field(default=0, ge=0, description="取得簿価 (円)")
    nav: float = Field(..., ge=0.0, description="基準価額 (円/1万口)")
    valuation: int = Field(..., ge=0, description="現在値 / 評価額 (円)")
    profit_loss: int | None = Field(default=None, description="含み損益 (円)")

    @property
    def identity_key(self) -> str:
        """4要素完全一致による同一ファンド識別キー。"""
        return f"{self.holder}__{self.account}__{self.code}__{self.isin}"


class AssetGenre(StrEnum):
    """リバランス計算用の資産ジャンル区分。"""

    EQUITY = "株式"
    BOND = "債券"


ASSET_GENRE_OPTIONS: Final[tuple[AssetGenre, ...]] = (
    AssetGenre.EQUITY,
    AssetGenre.BOND,
)


class TradeDirection(StrEnum):
    """リバランス時の売買方向区分。"""

    BUY = "購入"
    SELL = "売却"
    HOLD = "維持"


class RebalanceConfig(BaseModel):
    """リバランス基準比率および銘柄別ジャンル設定モデル。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_equity_ratio: float = Field(
        default=60.0,
        ge=0.0,
        le=100.0,
        description="株式の基準比率（%）",
    )
    fund_genres: dict[str, AssetGenre] = Field(
        default_factory=dict,
        description="銘柄コード -> 資産ジャンルマッピング",
    )

    @field_validator("target_equity_ratio")
    @classmethod
    def round_target_equity_ratio(cls, v: float) -> float:
        return round(float(v), 1)

    @field_validator("fund_genres")
    @classmethod
    def validate_fund_genres(cls, v: dict[str, AssetGenre]) -> dict[str, AssetGenre]:
        normalized: dict[str, AssetGenre] = {}
        for code, genre in v.items():
            cleaned_code = code.strip().upper()
            if not FUND_CODE_REGEX.match(cleaned_code):
                msg = f"ファンドコードは8桁の半角英数字（大文字）である必要があります: {code}"
                raise ValueError(msg)
            normalized[cleaned_code] = AssetGenre(genre)
        return normalized

    @property
    def target_bond_ratio(self) -> float:
        """債券の基準比率（%）。"""
        return round(100.0 - self.target_equity_ratio, 1)


class GenreAllocation(BaseModel):
    """ジャンル（株式・債券）ごとの評価額・比率・売買提案。"""

    model_config = ConfigDict(frozen=True)

    genre: AssetGenre
    valuation_total: int = Field(..., ge=0, description="ジャンル別評価額合計（円）")
    current_ratio: float = Field(..., ge=0.0, le=100.0, description="現在の構成比率（%）")
    target_ratio: float = Field(..., ge=0.0, le=100.0, description="基準構成比率（%）")
    target_valuation: int = Field(..., ge=0, description="目標評価額（円）")
    ratio_diff: float = Field(..., description="基準比率との乖離（現在比率 - 基準比率, pt）")
    trade_amount: int = Field(
        ..., description="総額不変時の売買金額（正: 購入, 負: 売却, 0: 維持）"
    )
    direction: TradeDirection
    bar: str = Field(..., description="テキストプログレスバー")


class FundGenreSummary(BaseModel):
    """銘柄コード単位のジャンル分類および評価額サマリー。"""

    model_config = ConfigDict(frozen=True)

    code: str
    name: str
    genre: AssetGenre
    is_configured: bool
    valuation_total: int = Field(..., ge=0)
    ratio: float = Field(..., ge=0.0, le=100.0)
    holding_count: int = Field(..., ge=1)


class RebalanceSummary(BaseModel):
    """ポートフォリオ全体のリバランス集計および売買提案結果。"""

    model_config = ConfigDict(frozen=True)

    total_valuation: int = Field(..., ge=0)
    target_equity_ratio: float = Field(..., ge=0.0, le=100.0)
    target_bond_ratio: float = Field(..., ge=0.0, le=100.0)
    equity: GenreAllocation
    bond: GenreAllocation
    fund_summaries: list[FundGenreSummary] = Field(default_factory=list)
    no_sell_buy_genre: AssetGenre | None = Field(
        default=None, description="売却なし買い増し時の購入対象ジャンル"
    )
    no_sell_buy_amount: int | None = Field(
        default=None, description="売却なし買い増し時の必要金額（円、達成不可時はNone）"
    )
    no_sell_achievable: bool = Field(
        default=True, description="売却なしの買い増しのみで基準比率へ到達可能か"
    )
    no_sell_post_total: int | None = Field(
        default=None, description="買い増し後の総資産評価額（円、達成不可時はNone）"
    )
