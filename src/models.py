"""ドメインモデルおよびデータバリデーションスキーマ定義。"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

FUND_CODE_REGEX: Final[re.Pattern[str]] = re.compile(r"^[0-9A-Z]{8}$")


class PortfolioItem(BaseModel):
    """ローカル保有資産CSV (portfolio.csv) の1行を表すデータモデル。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account: str = Field(
        ..., min_length=1, description="口座種別（法人, NISA, 特定, iDeCo, DCなど）"
    )
    code: str = Field(..., description="投信協会の8桁ファンドコード（半角英大文字・数字）")
    name: str = Field(..., min_length=1, description="銘柄略称")
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
    total_valuation: int = Field(..., ge=0, description="総資産評価額（円）")
    total_profit_loss: int | None = Field(default=None, description="総含み損益（円）")
    tank_summaries: list[TankSummary] = Field(default_factory=list)
    holdings: list[HoldingEvaluation] = Field(default_factory=list)
