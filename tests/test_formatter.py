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
    HoldingEvaluation,
    PortfolioItem,
    PortfolioReport,
    TankSummary,
)


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
        virtual_units=500.0,
        effective_units=1500.0,
        valuation=4500000,
        profit_loss=None,
        profit_loss_rate=None,
    )
    summary = TankSummary(
        account="DC",
        valuation_total=4500000,
        ratio=100.0,
        profit_loss_total=None,
        bar="[██████████] 100.0%",
    )
    report = PortfolioReport(
        as_of_date="2026-10-21",
        total_valuation=4500000,
        total_profit_loss=None,
        tank_summaries=[summary],
        holdings=[holding],
    )

    output = format_cli_report(report)

    assert "投資信託 ポートフォリオ評価ダッシュボード" in output
    assert "2026-10-21" in output
    assert "¥4,500,000" in output
    assert "[██████████] 100.0%" in output
    assert "米国株S&P500" in output
    assert "*" in output  # virtual_units > 0 注釈
    assert "※ 口数末尾の '*' はDC口座の経過月数に応じた仮想積立加山口数を含みます。" in output
