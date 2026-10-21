"""CLIダッシュボード向けテキスト整形・パディングモジュール。"""

from __future__ import annotations

import unicodedata
from typing import Final

from src.models import PortfolioReport

SEPARATOR_LINE: Final[str] = "═" * 86
THIN_SEPARATOR_LINE: Final[str] = "─" * 86


def get_display_width(text: str) -> int:
    """全角文字を2文字幅、半角文字を1文字幅として文字列の表示幅を計算する。

    Args:
        text: 対象文字列。

    Returns:
        表示幅（文字セル数）。
    """
    width = 0
    for char in text:
        status = unicodedata.east_asian_width(char)
        if status in ("F", "W", "A"):
            width += 2
        else:
            width += 1
    return width


def pad_display(text: str, target_width: int, align: str = "left") -> str:
    """全角文字幅を考慮して指定幅にパディングした文字列を返す。

    Args:
        text: 対象文字列。
        target_width: 目的の表示幅。
        align: 'left', 'right', 'center' のいずれか。

    Returns:
        パディング済み文字列。
    """
    current_width = get_display_width(text)
    pad_needed = max(0, target_width - current_width)

    if align == "right":
        return (" " * pad_needed) + text
    if align == "center":
        left_pad = pad_needed // 2
        right_pad = pad_needed - left_pad
        return (" " * left_pad) + text + (" " * right_pad)
    return text + (" " * pad_needed)


def format_yen(amount: int | None, prefix_sign: bool = False) -> str:
    """金額を3桁カンマ区切りの円表記に変換する。

    Args:
        amount: 金額整数値（Noneの場合は '-' を返す）。
        prefix_sign: 正の値に '+' を付与するかどうか。

    Returns:
        整形された文字列（例: ¥12,345,678, +¥123,456, -¥45,678, -）。
    """
    if amount is None:
        return "-"
    if amount < 0:
        return f"-¥{abs(amount):,}"
    if prefix_sign and amount > 0:
        return f"+¥{amount:,}"
    return f"¥{amount:,}"


def format_rate(rate: float | None) -> str:
    """損益率をパーセント表記に変換する。

    Args:
        rate: 損益率（Noneの場合は空文字を返す）。

    Returns:
        整形された文字列（例: (+12.3%), (-5.4%), 空文字）。
    """
    if rate is None:
        return ""
    if rate > 0:
        return f"(+{rate:.1f}%)"
    return f"({rate:.1f}%)"


def format_cli_report(report: PortfolioReport) -> str:
    """CLI向けダッシュボード文字列を組み立てる。

    Args:
        report: 集計済みポートフォリオレポート。

    Returns:
        ターミナル出力用の整形テキスト。
    """
    lines: list[str] = [
        SEPARATOR_LINE,
        "  投資信託 ポートフォリオ評価ダッシュボード (Fund Manager)",
        SEPARATOR_LINE,
        f"  基準価額取得日 : {report.as_of_date}",
        f"  総資産評価額   : {format_yen(report.total_valuation)}",
    ]

    if report.total_profit_loss is not None:
        lines.append(f"  総含み損益     : {format_yen(report.total_profit_loss, prefix_sign=True)}")
    else:
        lines.append("  総含み損益     : -")

    lines.append(THIN_SEPARATOR_LINE)
    lines.append("【タンク別サマリー（口座別アセットアロケーション）】")

    tank_header = (
        pad_display("口座名", 10)
        + " | "
        + pad_display("評価額合計", 16, "right")
        + " | "
        + pad_display("構成比率", 20, "left")
        + " | "
        + pad_display("含み損益合計", 16, "right")
    )
    lines.append(tank_header)
    lines.append(THIN_SEPARATOR_LINE)

    for tank in report.tank_summaries:
        pl_str = format_yen(tank.profit_loss_total, prefix_sign=True)
        tank_line = (
            pad_display(tank.account, 10)
            + " | "
            + pad_display(format_yen(tank.valuation_total), 16, "right")
            + " | "
            + pad_display(tank.bar, 20, "left")
            + " | "
            + pad_display(pl_str, 16, "right")
        )
        lines.append(tank_line)

    lines.append(THIN_SEPARATOR_LINE)
    lines.append("【保有銘柄明細テーブル】")

    detail_header = (
        pad_display("口座", 8)
        + " | "
        + pad_display("銘柄名", 28)
        + " | "
        + pad_display("基準価額", 10, "right")
        + " | "
        + pad_display("保有口数", 14, "right")
        + " | "
        + pad_display("評価額", 14, "right")
        + " | "
        + pad_display("含み損益 (損益率)", 22, "right")
    )
    lines.append(detail_header)
    lines.append(THIN_SEPARATOR_LINE)

    for h in report.holdings:
        if h.profit_loss is not None:
            pl_display = (
                f"{format_yen(h.profit_loss, prefix_sign=True)} {format_rate(h.profit_loss_rate)}"
            )
        else:
            pl_display = "-"

        units_str = f"{h.effective_units:,.1f}"
        if h.virtual_units > 0:
            units_str += "*"

        detail_line = (
            pad_display(h.item.account, 8)
            + " | "
            + pad_display(h.item.name, 28)
            + " | "
            + pad_display(f"¥{h.nav:,.0f}", 10, "right")
            + " | "
            + pad_display(units_str, 14, "right")
            + " | "
            + pad_display(format_yen(h.valuation), 14, "right")
            + " | "
            + pad_display(pl_display, 22, "right")
        )
        lines.append(detail_line)

    lines.append(SEPARATOR_LINE)
    if any(h.virtual_units > 0 for h in report.holdings):
        lines.append("  ※ 口数末尾の '*' はDC口座の経過月数に応じた仮想積立加山口数を含みます。")
        lines.append(SEPARATOR_LINE)

    return "\n".join(lines)
