"""src.rebalancer のテストモジュール。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.models import (
    AssetGenre,
    HoldingEvaluation,
    PortfolioItem,
    PortfolioReport,
    RebalanceConfig,
    TradeDirection,
)
from src.rebalancer import (
    calculate_rebalance_summary,
    infer_default_genre,
    load_rebalance_config,
    resolve_fund_genre,
    save_rebalance_config,
)


def _make_holding(
    code: str,
    name: str,
    valuation: int,
    account: str = "特定預り",
    holder: str = "個人",
) -> HoldingEvaluation:
    item = PortfolioItem(
        holder=holder,
        account=account,
        code=code,
        name=name,
        units=10000.0,
        cost_basis=valuation,
    )
    return HoldingEvaluation(
        item=item,
        nav=float(max(valuation, 1)),
        effective_units=10000.0,
        valuation=valuation,
        profit_loss=0,
        profit_loss_rate=0.0,
    )


def _make_report(holdings: list[HoldingEvaluation]) -> PortfolioReport:
    return PortfolioReport(
        as_of_date="2026-10-23",
        total_valuation=sum(h.valuation for h in holdings),
        total_profit_loss=0 if holdings else None,
        tank_summaries=[],
        holdings=holdings,
    )


@pytest.mark.parametrize(
    ("code", "name", "expected"),
    [
        ("0331A172", "eMAXIS Slim 先進国債券インデックス", AssetGenre.BOND),
        ("0331418A", "eMAXIS Slim 全世界株式", AssetGenre.EQUITY),
        ("99999999", "三井住友・先進国債券ファンド", AssetGenre.BOND),
        ("99999998", "iFree 米国国債インデックス", AssetGenre.BOND),
        ("99999997", "Global Bond Index Fund", AssetGenre.BOND),
        ("99999996", "謎の成長ファンド", AssetGenre.EQUITY),
    ],
)
def test_infer_default_genre(code: str, name: str, expected: AssetGenre) -> None:
    """プリセット・名称キーワード・未知銘柄デフォルトのジャンル推定を検証する。"""
    assert infer_default_genre(code, name) == expected


def test_resolve_fund_genre() -> None:
    """設定済み辞書が自動推定を上書きし、is_configured フラグを返すことを検証する。"""
    configured = {"0331418A": AssetGenre.BOND}
    genre_cfg, is_cfg = resolve_fund_genre("0331418a", "全世界株式", configured)
    assert genre_cfg == AssetGenre.BOND
    assert is_cfg is True

    genre_auto, is_auto = resolve_fund_genre("0331A172", "先進国債券", configured)
    assert genre_auto == AssetGenre.BOND
    assert is_auto is False


def test_load_and_save_rebalance_config_roundtrip(tmp_path: Path) -> None:
    """設定ファイルの不在時デフォルト、原子的保存、再読込、破損JSONフォールバックを検証する。"""
    cfg_path = tmp_path / "nested" / "rebalance_config.json"

    # 不在時はデフォルト 60.0% / 空辞書
    default_cfg = load_rebalance_config(cfg_path)
    assert default_cfg.target_equity_ratio == 60.0
    assert default_cfg.target_bond_ratio == 40.0
    assert default_cfg.fund_genres == {}

    # 保存と再読込
    saved_cfg = RebalanceConfig(
        target_equity_ratio=70.0,
        fund_genres={"0331418A": AssetGenre.EQUITY, "0331A172": AssetGenre.BOND},
    )
    save_rebalance_config(cfg_path, saved_cfg)
    assert cfg_path.exists()

    reloaded = load_rebalance_config(cfg_path)
    assert reloaded == saved_cfg

    # 破損JSON・非dictJSON・不正値JSONはいずれもデフォルトへ安全フォールバック
    cfg_path.write_text("{broken json", encoding="utf-8")
    assert load_rebalance_config(cfg_path) == RebalanceConfig()

    cfg_path.write_text("[]", encoding="utf-8")
    assert load_rebalance_config(cfg_path) == RebalanceConfig()

    cfg_path.write_text('{"target_equity_ratio": 150.0}', encoding="utf-8")
    assert load_rebalance_config(cfg_path) == RebalanceConfig()

    # 一時ファイル置換失敗時の一時ファイルクリーンアップ検証
    with (
        patch.object(Path, "replace", side_effect=OSError("replace failed")),
        pytest.raises(OSError, match="replace failed"),
    ):
        save_rebalance_config(cfg_path, saved_cfg)
    assert not list(cfg_path.parent.glob("rebalance_tmp_*"))


def test_calculate_rebalance_summary_equity_excess() -> None:
    """株式超過（800万/200万、目標60/40）の売買提案およびノーセル買い増し額を検証する。"""
    holdings = [
        _make_holding("0331418A", "全世界株", 8_000_000),
        _make_holding("0331A172", "先進国債券", 2_000_000),
    ]
    report = _make_report(holdings)
    cfg = RebalanceConfig(
        target_equity_ratio=60.0,
        fund_genres={"0331418A": AssetGenre.EQUITY, "0331A172": AssetGenre.BOND},
    )

    summary = calculate_rebalance_summary(report, cfg)

    assert summary.total_valuation == 10_000_000
    assert summary.equity.current_ratio == 80.0
    assert summary.bond.current_ratio == 20.0
    assert summary.equity.target_valuation == 6_000_000
    assert summary.bond.target_valuation == 4_000_000
    assert summary.equity.trade_amount == -2_000_000
    assert summary.equity.direction == TradeDirection.SELL
    assert summary.bond.trade_amount == 2_000_000
    assert summary.bond.direction == TradeDirection.BUY
    assert summary.equity.ratio_diff == 20.0
    assert summary.bond.ratio_diff == -20.0

    # ノーセル: 8,000,000 / 0.6 - 10,000,000 = 3,333,333
    assert summary.no_sell_achievable is True
    assert summary.no_sell_buy_genre == AssetGenre.BOND
    assert summary.no_sell_buy_amount == 3_333_333
    assert summary.no_sell_post_total == 13_333_333


def test_calculate_rebalance_summary_bond_excess() -> None:
    """債券超過（200万/800万、目標80/20）の売買提案およびノーセル株式買い増し額を検証する。"""
    holdings = [
        _make_holding("0331418A", "全世界株", 2_000_000),
        _make_holding("0331A172", "先進国債券", 8_000_000),
    ]
    report = _make_report(holdings)
    cfg = RebalanceConfig(target_equity_ratio=80.0)

    summary = calculate_rebalance_summary(report, cfg)

    assert summary.equity.trade_amount == 6_000_000
    assert summary.equity.direction == TradeDirection.BUY
    assert summary.bond.trade_amount == -6_000_000
    assert summary.bond.direction == TradeDirection.SELL

    # ノーセル: 8,000,000 / 0.2 - 10,000,000 = 30,000,000
    assert summary.no_sell_achievable is True
    assert summary.no_sell_buy_genre == AssetGenre.EQUITY
    assert summary.no_sell_buy_amount == 30_000_000
    assert summary.no_sell_post_total == 40_000_000


def test_calculate_rebalance_summary_exact_match() -> None:
    """現在比率と基準比率が完全一致する場合に売買不要・HOLDになることを検証する。"""
    holdings = [
        _make_holding("0331418A", "全世界株", 6_000_000),
        _make_holding("0331A172", "先進国債券", 4_000_000),
    ]
    summary = calculate_rebalance_summary(
        _make_report(holdings), RebalanceConfig(target_equity_ratio=60.0)
    )

    assert summary.equity.trade_amount == 0
    assert summary.bond.trade_amount == 0
    assert summary.equity.direction == TradeDirection.HOLD
    assert summary.bond.direction == TradeDirection.HOLD
    assert summary.no_sell_achievable is True
    assert summary.no_sell_buy_genre is None
    assert summary.no_sell_buy_amount == 0
    assert summary.no_sell_post_total == 10_000_000


@pytest.mark.parametrize(
    ("target_equity", "expected_buy_genre"),
    [
        (0.0, AssetGenre.BOND),
        (100.0, AssetGenre.EQUITY),
    ],
)
def test_calculate_rebalance_summary_zero_target_no_sell_unachievable(
    target_equity: float,
    expected_buy_genre: AssetGenre,
) -> None:
    """目標比率0%の資産を保有している場合、ゼロ除算せずノーセル達成不可となることを検証する。"""
    holdings = [
        _make_holding("0331418A", "全世界株", 5_000_000),
        _make_holding("0331A172", "先進国債券", 5_000_000),
    ]
    summary = calculate_rebalance_summary(
        _make_report(holdings),
        RebalanceConfig(target_equity_ratio=target_equity),
    )

    assert summary.no_sell_achievable is False
    assert summary.no_sell_buy_genre == expected_buy_genre
    assert summary.no_sell_buy_amount is None
    assert summary.no_sell_post_total is None


def test_calculate_rebalance_summary_multi_account_aggregation_and_invariants() -> None:
    """同一銘柄コードの複数口座合算、設定済フラグ混在、および端数丸め不変条件を検証する。"""
    holdings = [
        _make_holding("0331418A", "", 1, account="一般預り", holder="法人"),
        _make_holding("0331418A", "オルカン", 0, account="iDeCo", holder="個人"),
        _make_holding("0331A172", "先進国債券", 2, account="特定預り", holder="個人"),
    ]
    cfg = RebalanceConfig(
        target_equity_ratio=60.0,
        fund_genres={"0331418A": AssetGenre.EQUITY},
    )

    summary = calculate_rebalance_summary(_make_report(holdings), cfg)

    assert summary.total_valuation == 3
    assert summary.equity.current_ratio + summary.bond.current_ratio == pytest.approx(100.0)
    assert (
        summary.equity.target_valuation + summary.bond.target_valuation == summary.total_valuation
    )
    assert summary.equity.trade_amount + summary.bond.trade_amount == 0

    assert len(summary.fund_summaries) == 2
    eq_fund = summary.fund_summaries[0]
    assert eq_fund.code == "0331418A"
    assert eq_fund.name == "オルカン"
    assert eq_fund.holding_count == 2
    assert eq_fund.valuation_total == 1
    assert eq_fund.is_configured is True

    bd_fund = summary.fund_summaries[1]
    assert bd_fund.code == "0331A172"
    assert bd_fund.holding_count == 1
    assert bd_fund.is_configured is False


def test_calculate_rebalance_summary_empty_portfolio() -> None:
    """保有銘柄0件（総資産0円）の境界条件を検証する。"""
    summary = calculate_rebalance_summary(_make_report([]), RebalanceConfig())

    assert summary.total_valuation == 0
    assert summary.equity.current_ratio == 0.0
    assert summary.bond.current_ratio == 0.0
    assert summary.equity.trade_amount == 0
    assert summary.bond.trade_amount == 0
    assert summary.fund_summaries == []
    assert summary.no_sell_achievable is True
    assert summary.no_sell_buy_amount == 0
