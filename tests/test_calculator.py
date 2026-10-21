"""src.calculator のテストモジュール。"""

from __future__ import annotations

from datetime import date

import pytest

from src.calculator import (
    calculate_dc_virtual_units,
    calculate_elapsed_months,
    evaluate_portfolio,
    render_text_bar,
)
from src.models import PortfolioItem


def test_calculate_elapsed_months() -> None:
    """基準日からの経過月数計算を検証する。"""
    # 同一月
    assert calculate_elapsed_months(date(2025, 1, 1), date(2025, 1, 15)) == 0
    # 翌月
    assert calculate_elapsed_months(date(2025, 1, 1), date(2025, 2, 1)) == 1
    # 1年後
    assert calculate_elapsed_months(date(2025, 1, 1), date(2026, 1, 1)) == 12
    # 過去日指定（負数は0クランプ）
    assert calculate_elapsed_months(date(2025, 5, 1), date(2025, 1, 1)) == 0


def test_calculate_dc_virtual_units() -> None:
    """DC仮想購入口数の算出を検証する。"""
    # 10ヶ月経過、月20,000円、基準価額20,000円
    # 総額200,000円 / (20,000 / 10,000) = 100,000口
    units = calculate_dc_virtual_units(
        base_date=date(2025, 1, 1),
        current_date=date(2025, 11, 1),
        nav=20_000.0,
        monthly_amount=20_000,
    )
    assert units == 100_000.0

    # nav <= 0 の境界
    assert (
        calculate_dc_virtual_units(
            base_date=date(2025, 1, 1),
            current_date=date(2025, 11, 1),
            nav=0.0,
        )
        == 0.0
    )


def test_render_text_bar() -> None:
    """テキストプログレスバーの描画を検証する。"""
    bar_0 = render_text_bar(0.0, width=10)
    assert bar_0 == "[░░░░░░░░░░]   0.0%"

    bar_100 = render_text_bar(100.0, width=10)
    assert bar_100 == "[██████████] 100.0%"

    bar_half = render_text_bar(50.0, width=10)
    assert bar_half == "[█████░░░░░]  50.0%"


def test_evaluate_portfolio_comprehensive() -> None:
    """ポートフォリオ評価の全体ロジック（評価額、含み損益、DC仮想加算、タンク集計）を検証する。"""
    # Arrange
    items = [
        # 法人: 簿価あり
        PortfolioItem(
            account="法人",
            code="03311181",
            name="全世界株",
            units=10_000.0,
            cost_basis=15_000,
        ),
        # iDeCo: 簿価なし (cost_basis=0)
        PortfolioItem(
            account="iDeCo",
            code="03312184",
            name="先進国株",
            units=10_000.0,
            cost_basis=0,
        ),
        # DC: 仮想加算あり (10ヶ月経過 = 200,000円分)
        PortfolioItem(
            account="DC",
            code="03314187",
            name="米国株",
            units=10_000.0,
            cost_basis=0,
        ),
    ]

    nav_map = {
        "03311181": 20_000.0,  # 評価額 = 10,000 * (20,000/10,000) = 20,000円
        "03312184": 15_000.0,  # 評価額 = 10,000 * (15,000/10,000) = 15,000円
        "03314187": 20_000.0,  # 仮想口数 = (10 * 20,000 * 10,000) / 20,000 = 100,000口
        # 実質口数 = 110,000口, 評価額 = 110,000 * 2 = 220,000円
    }

    # Act
    report = evaluate_portfolio(
        items=items,
        nav_map=nav_map,
        as_of_date="2026-10-21",
        dc_base_date=date(2025, 1, 1),
        current_date=date(2025, 11, 1),  # 10ヶ月経過
    )

    # Assert
    # 法人評価
    corp_h = next(h for h in report.holdings if h.item.account == "法人")
    assert corp_h.valuation == 20_000
    assert corp_h.profit_loss == 5_000  # 20,000 - 15,000
    assert corp_h.profit_loss_rate == pytest.approx(33.333, 0.01)

    # iDeCo評価 (簿価なし)
    ideco_h = next(h for h in report.holdings if h.item.account == "iDeCo")
    assert ideco_h.valuation == 15_000
    assert ideco_h.profit_loss is None
    assert ideco_h.profit_loss_rate is None

    # DC評価 (仮想加算100,000口)
    dc_h = next(h for h in report.holdings if h.item.account == "DC")
    assert dc_h.virtual_units == 100_000.0
    assert dc_h.effective_units == 110_000.0
    assert dc_h.valuation == 220_000

    # 全体集計
    total_expected = 20_000 + 15_000 + 220_000
    assert report.total_valuation == total_expected
    assert report.total_profit_loss == 5_000  # 簿価のある法人分のみ

    # タンク別サマリー確認
    assert len(report.tank_summaries) == 3
    corp_tank = next(t for t in report.tank_summaries if t.account == "法人")
    assert corp_tank.valuation_total == 20_000
    assert corp_tank.profit_loss_total == 5_000
    assert corp_tank.ratio == round((20_000 / total_expected) * 100.0, 1)

    ideco_tank = next(t for t in report.tank_summaries if t.account == "iDeCo")
    assert ideco_tank.profit_loss_total is None  # 簿価なし


def test_evaluate_portfolio_with_dc_target_code_and_zero_cost() -> None:
    """dc_target_code明示指定および全銘柄簿価なし(total_cost_basis == 0)の場合の集計を検証する。"""
    items = [
        PortfolioItem(
            account="DC",
            code="03314187",
            name="米国株",
            units=1000.0,
            cost_basis=0,
        ),
        PortfolioItem(
            account="DC",
            code="03311181",
            name="全世界株",
            units=2000.0,
            cost_basis=0,
        ),
    ]
    nav_map = {"03314187": 20000.0, "03311181": 25000.0}

    report = evaluate_portfolio(
        items=items,
        nav_map=nav_map,
        as_of_date="2026-10-21",
        dc_base_date=date(2025, 1, 1),
        current_date=date(2025, 11, 1),
        dc_target_code="03314187",
    )

    assert report.total_profit_loss is None
    # 03314187 のみ仮想加算される
    item1 = next(h for h in report.holdings if h.item.code == "03314187")
    item2 = next(h for h in report.holdings if h.item.code == "03311181")
    assert item1.virtual_units > 0
    assert item2.virtual_units == 0.0
