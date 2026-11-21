"""src.formatter のテストモジュール。"""

from __future__ import annotations

from src.formatter import (
    format_cli_report,
    format_rate,
    format_yen,
    get_display_width,
    pad_display,
)
from src.models import (
    AssetGenre,
    HoldingEvaluation,
    PortfolioItem,
    PortfolioReport,
    RebalanceConfig,
    TankSummary,
)
from src.rebalancer import calculate_rebalance_summary


def test_get_display_width() -> None:
    """文字幅計算の検証（全角=2, 半角=1）。"""
    assert get_display_width("abc") == 3
    assert get_display_width("あいう") == 6
    assert get_display_width("法人 (NISA)") == 11


def test_pad_display() -> None:
    """パディング位置（左、右、中央）の検証。"""
    assert pad_display("abc", 5, "left") == "abc  "
    assert pad_display("abc", 5, "right") == "  abc"
    assert pad_display("abc", 5, "center") == " abc "


def test_format_yen() -> None:
    """円フォーマットの検証。"""
    assert format_yen(None) == "-"
    assert format_yen(1234567) == "¥1,234,567"
    assert format_yen(-50000) == "-¥50,000"
    assert format_yen(50000, prefix_sign=True) == "+¥50,000"
    assert format_yen(0, prefix_sign=True) == "¥0"


def test_format_rate() -> None:
    """パーセントフォーマットの検証。"""
    assert format_rate(None) == ""
    assert format_rate(12.34) == "(+12.3%)"
    assert format_rate(-5.67) == "(-5.7%)"


def test_format_cli_report() -> None:
    """CLIダッシュボード出力文字列の構築を検証する。"""
    item = PortfolioItem(
        account="DC",
        code="03314187",
        name="米国株S&P500",
        units=1000.0,
        cost_basis=0,
    )
    holding = HoldingEvaluation(
        item=item,
        nav=30000.0,
        virtual_units=0.0,
        effective_units=1000.0,
        valuation=3000000,
        profit_loss=None,
        profit_loss_rate=None,
    )
    summary = TankSummary(
        account="DC",
        valuation_total=3000000,
        ratio=100.0,
        profit_loss_total=None,
        bar="[██████████] 100.0%",
    )
    report = PortfolioReport(
        as_of_date="2026-10-21",
        total_valuation=3000000,
        total_profit_loss=None,
        tank_summaries=[summary],
        holdings=[holding],
    )

    output = format_cli_report(report)

    assert "投資信託 ポートフォリオ評価ダッシュボード" in output
    assert "2026-10-21" in output
    assert "¥3,000,000" in output
    assert "[██████████] 100.0%" in output
    assert "米国株S&P500" in output


def test_format_cli_report_with_rebalance_summary() -> None:
    """リバランス計算サマリー付きCLIレポートの全分岐（売買・維持・ノーセル不可）を検証する。"""
    holdings = [
        HoldingEvaluation(
            item=PortfolioItem(account="特定預り", code="0331418A", name="全世界株", units=1000.0),
            nav=10000.0,
            effective_units=1000.0,
            valuation=8_000_000,
        ),
        HoldingEvaluation(
            item=PortfolioItem(
                account="特定預り", code="0331A172", name="先進国債券", units=1000.0
            ),
            nav=10000.0,
            effective_units=1000.0,
            valuation=2_000_000,
        ),
    ]
    report = PortfolioReport(
        as_of_date="2026-10-21",
        total_valuation=10_000_000,
        total_profit_loss=None,
        tank_summaries=[],
        holdings=holdings,
    )

    # 1. 売買提案あり（株式超過）
    summary_excess = calculate_rebalance_summary(report, RebalanceConfig(target_equity_ratio=60.0))
    out_excess = format_cli_report(report, rebalance_summary=summary_excess)
    assert "【資産クラス配分 & リバランス試算】" in out_excess
    assert "売却 ¥2,000,000" in out_excess
    assert "購入 ¥2,000,000" in out_excess
    assert "債券を ¥3,333,333 買い増し" in out_excess

    # 2. 維持（一致）
    summary_match = calculate_rebalance_summary(report, RebalanceConfig(target_equity_ratio=80.0))
    out_match = format_cli_report(report, rebalance_summary=summary_match)
    assert "維持 (¥0)" in out_match
    assert "売買不要（基準比率と一致）" in out_match

    # 3. ノーセル達成不可（目標債券0%なのに債券保有）
    summary_unachievable = calculate_rebalance_summary(
        report,
        RebalanceConfig(target_equity_ratio=100.0, fund_genres={"0331A172": AssetGenre.BOND}),
    )
    out_unachievable = format_cli_report(report, rebalance_summary=summary_unachievable)
    assert "買い増しのみでは達成不可" in out_unachievable
