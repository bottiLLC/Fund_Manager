"""src.models のテストモジュール。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import (
    HoldingEvaluation,
    PortfolioItem,
    PortfolioReport,
    TankSummary,
)


def test_portfolio_item_valid() -> None:
    """正常なPortfolioItemの生成を検証する。"""
    # Arrange & Act
    item = PortfolioItem(
        account="NISA",
        code="03311181",
        name="eMAXIS Slim 全世界株式",
        units=10000.5,
        cost_basis=20000,
    )

    # Assert
    assert item.account == "NISA"
    assert item.code == "03311181"
    assert item.name == "eMAXIS Slim 全世界株式"
    assert item.units == 10000.5
    assert item.cost_basis == 20000


@pytest.mark.parametrize(
    "invalid_code",
    ["1234567", "123456789", "abcdefgh", "0331118A", ""],
)
def test_portfolio_item_invalid_code(invalid_code: str) -> None:
    """不正なファンドコードでValidationErrorが発生することを検証する。"""
    # Arrange, Act & Assert
    with pytest.raises(ValidationError, match="ファンドコードは8桁の半角数字である必要があります"):
        PortfolioItem(
            account="特定",
            code=invalid_code,
            name="テスト",
            units=100.0,
            cost_basis=0,
        )


def test_portfolio_item_invalid_units_or_cost() -> None:
    """units <= 0 や cost_basis < 0 でValidationErrorが発生することを検証する。"""
    with pytest.raises(ValidationError):
        PortfolioItem(
            account="特定",
            code="03311181",
            name="テスト",
            units=0.0,  # gt=0.0
            cost_basis=0,
        )

    with pytest.raises(ValidationError):
        PortfolioItem(
            account="特定",
            code="03311181",
            name="テスト",
            units=100.0,
            cost_basis=-10,  # ge=0
        )


def test_holding_evaluation_and_report_creation() -> None:
    """HoldingEvaluation, TankSummary, PortfolioReport の正常生成を検証する。"""
    # Arrange
    item = PortfolioItem(
        account="法人",
        code="03311181",
        name="テスト投信",
        units=10000.0,
        cost_basis=10000,
    )

    # Act
    eval_item = HoldingEvaluation(
        item=item,
        nav=12000.0,
        virtual_units=0.0,
        effective_units=10000.0,
        valuation=12000,
        profit_loss=2000,
        profit_loss_rate=20.0,
    )
    summary = TankSummary(
        account="法人",
        valuation_total=12000,
        ratio=100.0,
        profit_loss_total=2000,
        bar="[██████████] 100.0%",
    )
    report = PortfolioReport(
        as_of_date="2026-10-21",
        total_valuation=12000,
        total_profit_loss=2000,
        tank_summaries=[summary],
        holdings=[eval_item],
    )

    # Assert
    assert report.total_valuation == 12000
    assert len(report.tank_summaries) == 1
    assert len(report.holdings) == 1
    assert report.holdings[0].valuation == 12000
