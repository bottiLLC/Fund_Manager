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


@pytest.mark.parametrize(
    "valid_code",
    ["03311181", "0331118A", "9C311181", "ABCDEFGH"],
)
def test_portfolio_item_valid(valid_code: str) -> None:
    """正常なPortfolioItem（半角数字および半角英大文字コード）の生成を検証する。"""
    # Arrange & Act
    item = PortfolioItem(
        account="NISA",
        code=valid_code,
        name="eMAXIS Slim 全世界株式",
        units=10000.5,
        cost_basis=20000,
    )

    # Assert
    assert item.account == "NISA"
    assert item.code == valid_code
    assert item.name == "eMAXIS Slim 全世界株式"
    assert item.units == 10000.5
    assert item.cost_basis == 20000


@pytest.mark.parametrize(
    "invalid_code",
    ["1234567", "123456789", "abcdefgh", "0331118a", "0331-181", ""],
)
def test_portfolio_item_invalid_code(invalid_code: str) -> None:
    """不正なファンドコードでValidationErrorが発生することを検証する。"""
    # Arrange, Act & Assert
    with pytest.raises(
        ValidationError, match="ファンドコードは8桁の半角英数字（大文字）である必要があります"
    ):
        PortfolioItem(
            account="特定",
            code=invalid_code,
            name="テスト",
            units=100.0,
            cost_basis=0,
        )


def test_portfolio_item_isin_validation() -> None:
    """ISINコードの正常系および異常系バリデーションを検証する。"""
    # 正常系（空文字または12桁半角英数大文字）
    item1 = PortfolioItem(
        account="NISA",
        code="0331418A",
        isin="JP90C000H1T1",
        units=100.0,
    )
    assert item1.isin == "JP90C000H1T1"

    item2 = PortfolioItem(
        account="NISA",
        code="0331418A",
        isin="",
        units=100.0,
    )
    assert item2.isin == ""

    # 異常系
    with pytest.raises(ValidationError, match="ISINコードは12桁の半角英数字である必要があります"):
        PortfolioItem(
            account="NISA",
            code="0331418A",
            isin="invalid_isin",
            units=100.0,
        )


def test_fund_info_model() -> None:
    """FundInfoモデルの生成と属性を検証する。"""
    from src.models import FundInfo

    fund = FundInfo(
        code="0331418A",
        isin="JP90C000H1T1",
        name="eMAXIS Slim 全世界株式",
        nav=37859.0,
        as_of_date="2026-10-20",
    )
    assert fund.code == "0331418A"
    assert fund.nav == 37859.0


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
