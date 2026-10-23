"""src.models のテストモジュール。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models import (
    FundSnapshotRecord,
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
    assert item.holder == "個人"
    assert item.account == "NISA"
    assert item.code == valid_code
    assert item.name == "eMAXIS Slim 全世界株式"
    assert item.units == 10000.5
    assert item.cost_basis == 20000


def test_portfolio_item_holder_custom() -> None:
    """holder の明示指定および空白正規化の動作を検証する。"""
    item_corp = PortfolioItem(
        holder="法人",
        account="一般預り",
        code="0331418A",
        units=100.0,
    )
    assert item_corp.holder == "法人"

    # 個人(DC)
    item_dc = PortfolioItem(
        holder="個人(DC)",
        account="DC",
        code="0331418A",
        units=100.0,
    )
    assert item_dc.holder == "個人(DC)"

    # 空文字渡しの場合はデフォルト "個人" にフォールバック
    item_empty = PortfolioItem(
        holder="   ",
        account="一般預り",
        code="0331418A",
        units=100.0,
    )
    assert item_empty.holder == "個人"

    # 許可されていない値は ValidationError
    with pytest.raises(ValidationError, match="所有者区分は"):
        PortfolioItem(
            holder="投資信託組合",
            account="特定預り",
            code="0331418A",
            units=100.0,
        )


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


def test_fund_snapshot_record_valid() -> None:
    """FundSnapshotRecord の正常系生成と identity_key プロパティの挙動を検証する。"""
    # Arrange & Act
    record = FundSnapshotRecord(
        recorded_date="2026-10-23",
        recorded_at="2026-10-23T12:00:00+00:00",
        holder="個人",
        account="NISA預り（成長投資枠）",
        code="0331418A",
        isin="JP90C000H1T1",
        name="eMAXIS Slim 全世界株式(オール・カントリー)",
        units=500000.0,
        cost_basis=1000000,
        nav=25000.0,
        valuation=1250000,
        profit_loss=250000,
    )

    # Assert
    assert record.recorded_date == "2026-10-23"
    assert record.holder == "個人"
    assert record.account == "NISA預り（成長投資枠）"
    assert record.code == "0331418A"
    assert record.isin == "JP90C000H1T1"
    assert record.units == 500000.0
    assert record.cost_basis == 1000000
    assert record.nav == 25000.0
    assert record.valuation == 1250000
    assert record.profit_loss == 250000
    assert record.identity_key == "個人__NISA預り（成長投資枠）__0331418A__JP90C000H1T1"


def test_fund_snapshot_record_validation_error() -> None:
    """不正な値（無効なコード桁数や負の口数）で ValidationError が送出されることを検証する。"""
    with pytest.raises(ValidationError):
        FundSnapshotRecord(
            recorded_date="2026-10-23",
            recorded_at="2026-10-23T12:00:00+00:00",
            holder="個人",
            account="特定預り",
            code="INVALID",  # 7桁でバリデーション失敗
            isin="JP90C000H1T1",
            name="テスト投信",
            units=100.0,
            cost_basis=100,
            nav=10000.0,
            valuation=100,
        )
