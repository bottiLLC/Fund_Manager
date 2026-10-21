"""評価額・含み損益・DC仮想積立口数計算エンジン。"""

from __future__ import annotations

from datetime import date

from src.models import HoldingEvaluation, PortfolioItem, PortfolioReport, TankSummary


def calculate_elapsed_months(base_date: date, current_date: date) -> int:
    """基準日から現在日までの経過月数を計算する。

    Args:
        base_date: 積立開始基準日。
        current_date: 評価基準日。

    Returns:
        経過月数（0以上の整数）。
    """
    diff_months = (current_date.year - base_date.year) * 12 + (current_date.month - base_date.month)
    return max(0, diff_months)


def calculate_dc_virtual_units(
    base_date: date,
    current_date: date,
    nav: float,
    monthly_amount: int = 20_000,
) -> float:
    """DC口座における基準日からの経過月数と毎月積立額に応じた仮想購入口数を算出する。

    Args:
        base_date: DC積立基準日（例: 2025-01-01）。
        current_date: 現在または評価基準日。
        nav: 基準価額（10,000口あたり）。
        monthly_amount: 月次拠出金額（デフォルト: 20,000円）。

    Returns:
        仮想購入口数 (float)。navが0以下の場合は0.0。
    """
    if nav <= 0.0:
        return 0.0

    elapsed_months = calculate_elapsed_months(base_date, current_date)
    total_contribution = elapsed_months * monthly_amount
    # 口数換算 = (金額 / (nav / 10000)) = (金額 * 10000) / nav
    return (total_contribution * 10_000.0) / nav


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
    dc_base_date: date = date(2025, 1, 1),
    current_date: date | None = None,
    dc_target_code: str | None = None,
) -> PortfolioReport:
    """保有資産リストと基準価額マップから全体の評価レポートを算出する。

    Args:
        items: 保有銘柄リスト。
        nav_map: ファンドコード -> 基準価額マップ。
        as_of_date: 基準価額の取得日付文字列。
        dc_base_date: DC仮想積立の基準日。
        current_date: 経過月数算出用の現在日（None時はdc_base_date同等または本日）。
        dc_target_code: DC仮想積立を適用するファンドコード（None時はDC口座の先頭銘柄）。

    Returns:
        評価レポート（PortfolioReport）。
    """
    effective_current_date = current_date or date.today()

    # DC口座で仮想積立を適用する対象コードの確定
    target_dc_code = dc_target_code
    if target_dc_code is None:
        for item in items:
            if item.account.upper() == "DC":
                target_dc_code = item.code
                break

    evaluations: list[HoldingEvaluation] = []
    account_valuation_map: dict[str, int] = {}
    account_cost_map: dict[str, int] = {}
    account_has_cost_map: dict[str, bool] = {}

    for item in items:
        nav = nav_map.get(item.code, 10_000.0)
        virtual_units = 0.0

        if item.account.upper() == "DC" and (target_dc_code is None or item.code == target_dc_code):
            virtual_units = calculate_dc_virtual_units(
                base_date=dc_base_date,
                current_date=effective_current_date,
                nav=nav,
            )

        effective_units = item.units + virtual_units
        valuation = int(round(effective_units * (nav / 10_000.0)))

        profit_loss: int | None = None
        profit_loss_rate: float | None = None

        if item.cost_basis > 0:
            profit_loss = valuation - item.cost_basis
            profit_loss_rate = (profit_loss / item.cost_basis) * 100.0

        eval_item = HoldingEvaluation(
            item=item,
            nav=nav,
            virtual_units=virtual_units,
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
        total_valuation=total_valuation,
        total_profit_loss=total_profit_loss,
        tank_summaries=tank_summaries,
        holdings=evaluations,
    )
