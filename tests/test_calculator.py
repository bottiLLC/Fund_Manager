"""src.calculator のテストモジュール。"""

from __future__ import annotations

import pytest

from src.calculator import evaluate_portfolio, render_text_bar
from src.models import PortfolioItem


def test_render_text_bar() -> None:
    """テキストプログレスバーの描画およびクランプ動作を検証する。"""
    bar_0 = render_text_bar(0.0, width=10)
    assert bar_0 == "[░░░░░░░░░░]   0.0%"

    bar_100 = render_text_bar(100.0, width=10)
    assert bar_100 == "[██████████] 100.0%"

    bar_half = render_text_bar(50.0, width=10)
    assert bar_half == "[█████░░░░░]  50.0%"

    # 負数クランプ (0.0%へ)
    bar_neg = render_text_bar(-10.0, width=10)
    assert bar_neg == "[░░░░░░░░░░]   0.0%"

    # 100超クランプ (100.0%へ)
    bar_over = render_text_bar(150.0, width=10)
    assert bar_over == "[██████████] 100.0%"


def test_evaluate_portfolio_comprehensive() -> None:
    """ポートフォリオ評価の全体ロジック（登録口数直接評価、含み損益、タンク集計）を検証する。"""
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
        # 法人: 同一口座の追加銘柄（簿価なし）
        PortfolioItem(
            account="法人",
            code="03314187",
            name="米国株",
            units=5_000.0,
            cost_basis=0,
        ),
        # iDeCo: 簿価なし (cost_basis=0)
        PortfolioItem(
            account="iDeCo",
            code="03312184",
            name="先進国株",
            units=10_000.0,
            cost_basis=0,
        ),
        # DC: 登録口数で直接計算 (10,000口)
        PortfolioItem(
            account="DC",
            code="0331418A",
            name="オルカン",
            units=10_000.0,
            cost_basis=18_000,
        ),
    ]

    nav_map = {
        "03311181": 20_000.0,  # 評価額 = 10,000 * 2.0 = 20,000円
        "03314187": 30_000.0,  # 評価額 = 5,000 * 3.0 = 15,000円
        "03312184": 15_000.0,  # 評価額 = 10,000 * 1.5 = 15,000円
        "0331418A": 25_000.0,  # 評価額 = 10,000 * 2.5 = 25,000円
    }

    # Act
    report = evaluate_portfolio(
        items=items,
        nav_map=nav_map,
        as_of_date="2026-10-21",
    )

    # Assert
    # 法人評価 (全世界株)
    corp_h1 = next(h for h in report.holdings if h.item.code == "03311181")
    assert corp_h1.valuation == 20_000
    assert corp_h1.profit_loss == 5_000  # 20,000 - 15,000
    assert corp_h1.profit_loss_rate == pytest.approx(33.333, 0.01)
    assert corp_h1.effective_units == 10_000.0

    # iDeCo評価 (簿価なし)
    ideco_h = next(h for h in report.holdings if h.item.account == "iDeCo")
    assert ideco_h.valuation == 15_000
    assert ideco_h.profit_loss is None
    assert ideco_h.profit_loss_rate is None

    # DC評価 (登録口数10,000口で直接評価)
    dc_h = next(h for h in report.holdings if h.item.account == "DC")
    assert dc_h.effective_units == 10_000.0
    assert dc_h.valuation == 25_000
    assert dc_h.profit_loss == 7_000  # 25,000 - 18,000
    assert dc_h.profit_loss_rate == pytest.approx(38.888, 0.01)

    # 全体集計
    total_expected = 20_000 + 15_000 + 15_000 + 25_000  # 75,000
    assert report.total_valuation == total_expected
    assert report.total_profit_loss == 5_000 + 7_000  # 12,000 (簿価のある銘柄のみ)

    # タンク別サマリー確認
    assert len(report.tank_summaries) == 3
    corp_tank = next(t for t in report.tank_summaries if t.account == "法人")
    assert corp_tank.valuation_total == 35_000  # 20,000 + 15,000
    assert corp_tank.profit_loss_total == 5_000  # 簿価のある銘柄のみ
    assert corp_tank.ratio == round((35_000 / total_expected) * 100.0, 1)

    ideco_tank = next(t for t in report.tank_summaries if t.account == "iDeCo")
    assert ideco_tank.profit_loss_total is None  # 簿価なし


def test_evaluate_portfolio_with_zero_cost_and_zero_valuation() -> None:
    """全銘柄簿価なし(total_cost_basis == 0)および総評価額0の境界動作を検証する。"""
    # 1. 全銘柄簿価なし
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
    )

    assert report.total_profit_loss is None
    item1 = next(h for h in report.holdings if h.item.code == "03314187")
    assert item1.effective_units == 1000.0
    assert item1.valuation == 2000

    # 2. 保有銘柄が空の場合（総評価額0）
    report_zero = evaluate_portfolio(items=[], nav_map={}, as_of_date="2026-10-21")
    assert report_zero.total_valuation == 0
    assert len(report_zero.tank_summaries) == 0
