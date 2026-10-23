"""評価額・含み損益・アセットアロケーション計算エンジン。"""

from __future__ import annotations

from src.models import HoldingEvaluation, PortfolioItem, PortfolioReport, TankSummary


def render_text_bar(ratio: float, width: int = 10) -> str:
    """比率(%)からテキストプログレスバー [████████░░] 45.2% を生成する。

    Args:
        ratio: 構成比率パーセント (0.0 - 100.0)。
        width: バーの合計文字数。

    Returns:
        テキストバー文字列。
    """
    clamped_ratio = max(0.0, min(100.0, ratio))
    filled_len = int(round((clamped_ratio / 100.0) * width))
    empty_len = width - filled_len
    bar_str = "█" * filled_len + "░" * empty_len
    return f"[{bar_str}] {clamped_ratio:5.1f}%"


def evaluate_portfolio(
    items: list[PortfolioItem],
    nav_map: dict[str, float],
    as_of_date: str,
    fetched_at: str | None = None,
    fallback_funds: list[str] | None = None,
) -> PortfolioReport:
    """保有資産リストと基準価額マップから全体の評価レポートを算出する。

    各銘柄の保有口数（units）に基づいて評価額（units * nav / 10,000）を算出する。

    Args:
        items: 保有銘柄リスト。
        nav_map: ファンドコード -> 基準価額マップ。
        as_of_date: 基準価額の取得日付文字列。
        fetched_at: 基準価額データの取得実行日時。
        fallback_funds: フォールバック値が適用された銘柄コード一覧。

    Returns:
        評価レポート（PortfolioReport）。
    """
    evaluations: list[HoldingEvaluation] = []
    account_valuation_map: dict[str, int] = {}
    account_cost_map: dict[str, int] = {}
    account_has_cost_map: dict[str, bool] = {}

    for item in items:
        nav = nav_map.get(item.code, 10_000.0)
        effective_units = item.units
        valuation = int(round(effective_units * (nav / 10_000.0)))

        profit_loss: int | None = None
        profit_loss_rate: float | None = None

        if item.cost_basis > 0:
            profit_loss = valuation - item.cost_basis
            profit_loss_rate = (profit_loss / item.cost_basis) * 100.0

        eval_item = HoldingEvaluation(
            item=item,
            nav=nav,
            virtual_units=0.0,
            effective_units=effective_units,
            valuation=valuation,
            profit_loss=profit_loss,
            profit_loss_rate=profit_loss_rate,
        )
        evaluations.append(eval_item)

        # 口座別集計加算
        acc = item.account
        account_valuation_map[acc] = account_valuation_map.get(acc, 0) + valuation
        if item.cost_basis > 0:
            account_cost_map[acc] = account_cost_map.get(acc, 0) + item.cost_basis
            account_has_cost_map[acc] = True
        elif acc not in account_has_cost_map:
            account_has_cost_map[acc] = False

    total_valuation = sum(account_valuation_map.values())

    # 総含み損益（簿価が存在する銘柄のみの合計）
    total_cost_basis = sum(item.cost_basis for item in items if item.cost_basis > 0)
    total_profit_loss: int | None = None
    if total_cost_basis > 0:
        total_profit_loss = sum(ev.profit_loss for ev in evaluations if ev.profit_loss is not None)

    # タンク別サマリー構築
    tank_summaries: list[TankSummary] = []
    # 登録順を維持
    seen_accounts: list[str] = []
    for item in items:
        if item.account not in seen_accounts:
            seen_accounts.append(item.account)

    for acc in seen_accounts:
        acc_val = account_valuation_map.get(acc, 0)
        ratio = (acc_val / total_valuation * 100.0) if total_valuation > 0 else 0.0
        acc_pl: int | None = None
        if account_has_cost_map.get(acc, False):
            acc_cost = account_cost_map.get(acc, 0)
            # 簿価のある銘柄のみの評価額と簿価の差分
            acc_val_with_cost = sum(
                ev.valuation
                for ev in evaluations
                if ev.item.account == acc and ev.item.cost_basis > 0
            )
            acc_pl = acc_val_with_cost - acc_cost

        summary = TankSummary(
            account=acc,
            valuation_total=acc_val,
            ratio=round(ratio, 1),
            profit_loss_total=acc_pl,
            bar=render_text_bar(ratio),
        )
        tank_summaries.append(summary)

    return PortfolioReport(
        as_of_date=as_of_date,
        fetched_at=fetched_at,
        fallback_funds=fallback_funds or [],
        total_valuation=total_valuation,
        total_profit_loss=total_profit_loss,
        tank_summaries=tank_summaries,
        holdings=evaluations,
    )
