"""資産ジャンル分類・設定永続化・リバランス計算エンジン。"""

from __future__ import annotations

import json
import tempfile
import unicodedata
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

from pydantic import ValidationError

from src.calculator import render_text_bar
from src.models import (
    AssetGenre,
    FundGenreSummary,
    GenreAllocation,
    PortfolioReport,
    RebalanceConfig,
    RebalanceSummary,
    TradeDirection,
)

DEFAULT_REBALANCE_CONFIG_FILE: Final[str] = "rebalance_config.json"

PRESET_FUND_GENRES: Final[Mapping[str, AssetGenre]] = MappingProxyType(
    {
        "03311187": AssetGenre.EQUITY,
        "0331124A": AssetGenre.EQUITY,
        "0331A172": AssetGenre.BOND,
        "8931217C": AssetGenre.EQUITY,
        "03319172": AssetGenre.EQUITY,
        "2931113C": AssetGenre.EQUITY,
        "0331418A": AssetGenre.EQUITY,
        "89311221": AssetGenre.EQUITY,
        "89311199": AssetGenre.EQUITY,
        # 旧サンプルコード互換
        "03311181": AssetGenre.EQUITY,
        "03314187": AssetGenre.EQUITY,
        "03312184": AssetGenre.EQUITY,
    }
)

_BOND_KEYWORDS: Final[tuple[str, ...]] = (
    "債券",
    "国債",
    "社債",
    "公社債",
    "ボンド",
    "bond",
)


def infer_default_genre(code: str, name: str = "") -> AssetGenre:
    """ファンドコードおよび銘柄名から資産ジャンル（株式/債券）の初期値を推定する。"""
    normalized_code = code.strip().upper()
    if normalized_code in PRESET_FUND_GENRES:
        return PRESET_FUND_GENRES[normalized_code]

    normalized_name = unicodedata.normalize("NFKC", name).lower()
    if any(keyword in normalized_name for keyword in _BOND_KEYWORDS):
        return AssetGenre.BOND

    return AssetGenre.EQUITY


def resolve_fund_genre(
    code: str,
    name: str,
    fund_genres: Mapping[str, AssetGenre],
) -> tuple[AssetGenre, bool]:
    """設定辞書または推定ロジックから銘柄のジャンルと設定済みフラグを解決する。"""
    normalized_code = code.strip().upper()
    if normalized_code in fund_genres:
        return fund_genres[normalized_code], True
    return infer_default_genre(normalized_code, name), False


def load_rebalance_config(file_path: Path) -> RebalanceConfig:
    """リバランス設定JSONを読み込む。不在・破損時はデフォルト設定へフォールバックする。"""
    resolved_path = file_path.resolve()
    if not resolved_path.exists():
        return RebalanceConfig()

    try:
        raw_text = resolved_path.read_text(encoding="utf-8")
        data = json.loads(raw_text)
        if isinstance(data, dict):
            return RebalanceConfig.model_validate(data)
    except OSError, json.JSONDecodeError, ValidationError, ValueError:
        pass
    return RebalanceConfig()


def save_rebalance_config(file_path: Path, config: RebalanceConfig) -> None:
    """リバランス設定をJSONファイルへ原子的に保存する。"""
    resolved_path = file_path.resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "target_equity_ratio": config.target_equity_ratio,
        "fund_genres": {code: genre.value for code, genre in sorted(config.fund_genres.items())},
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)

    temp_fd, temp_path_str = tempfile.mkstemp(
        dir=resolved_path.parent,
        prefix="rebalance_tmp_",
    )
    temp_path = Path(temp_path_str)
    try:
        with open(temp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        temp_path.replace(resolved_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _determine_direction(trade_amount: int) -> TradeDirection:
    if trade_amount > 0:
        return TradeDirection.BUY
    if trade_amount < 0:
        return TradeDirection.SELL
    return TradeDirection.HOLD


def calculate_rebalance_summary(
    report: PortfolioReport,
    config: RebalanceConfig,
) -> RebalanceSummary:
    """評価レポートとリバランス設定からジャンル別配分と売買提案額を算出する。"""
    code_order: list[str] = []
    code_name: dict[str, str] = {}
    code_valuation: dict[str, int] = {}
    code_count: dict[str, int] = {}

    for holding in report.holdings:
        code = holding.item.code
        if code not in code_valuation:
            code_order.append(code)
            code_name[code] = holding.item.name
            code_valuation[code] = 0
            code_count[code] = 0
        elif not code_name[code] and holding.item.name:
            code_name[code] = holding.item.name

        code_valuation[code] += holding.valuation
        code_count[code] += 1

    resolved_meta: dict[str, tuple[AssetGenre, bool]] = {
        code: resolve_fund_genre(code, code_name[code], config.fund_genres) for code in code_order
    }

    equity_total = sum(
        code_valuation[c] for c in code_order if resolved_meta[c][0] == AssetGenre.EQUITY
    )
    bond_total = sum(
        code_valuation[c] for c in code_order if resolved_meta[c][0] == AssetGenre.BOND
    )
    total_valuation = equity_total + bond_total

    if total_valuation > 0:
        current_equity_ratio = round((equity_total / total_valuation) * 100.0, 1)
        current_bond_ratio = round(100.0 - current_equity_ratio, 1)
    else:
        current_equity_ratio = 0.0
        current_bond_ratio = 0.0

    target_eq_ratio = config.target_equity_ratio
    target_bd_ratio = config.target_bond_ratio

    target_equity_amount = int(round(total_valuation * (target_eq_ratio / 100.0)))
    target_bond_amount = total_valuation - target_equity_amount

    equity_trade = target_equity_amount - equity_total
    bond_trade = target_bond_amount - bond_total

    no_sell_buy_genre: AssetGenre | None = None
    no_sell_buy_amount: int | None = 0
    no_sell_achievable = True
    no_sell_post_total: int | None = total_valuation

    if total_valuation > 0 and equity_trade != 0:
        if equity_trade < 0:
            no_sell_buy_genre = AssetGenre.BOND
            r_e = target_eq_ratio / 100.0
            if r_e <= 0.0:
                no_sell_achievable = False
                no_sell_buy_amount = None
                no_sell_post_total = None
            else:
                buy_amt = max(0, int(round((equity_total / r_e) - total_valuation)))
                no_sell_buy_amount = buy_amt
                no_sell_post_total = total_valuation + buy_amt
        else:
            no_sell_buy_genre = AssetGenre.EQUITY
            r_b = target_bd_ratio / 100.0
            if r_b <= 0.0:
                no_sell_achievable = False
                no_sell_buy_amount = None
                no_sell_post_total = None
            else:
                buy_amt = max(0, int(round((bond_total / r_b) - total_valuation)))
                no_sell_buy_amount = buy_amt
                no_sell_post_total = total_valuation + buy_amt

    equity_alloc = GenreAllocation(
        genre=AssetGenre.EQUITY,
        valuation_total=equity_total,
        current_ratio=current_equity_ratio,
        target_ratio=target_eq_ratio,
        target_valuation=target_equity_amount,
        ratio_diff=round(current_equity_ratio - target_eq_ratio, 1),
        trade_amount=equity_trade,
        direction=_determine_direction(equity_trade),
        bar=render_text_bar(current_equity_ratio),
    )

    bond_alloc = GenreAllocation(
        genre=AssetGenre.BOND,
        valuation_total=bond_total,
        current_ratio=current_bond_ratio,
        target_ratio=target_bd_ratio,
        target_valuation=target_bond_amount,
        ratio_diff=round(current_bond_ratio - target_bd_ratio, 1),
        trade_amount=bond_trade,
        direction=_determine_direction(bond_trade),
        bar=render_text_bar(current_bond_ratio),
    )

    fund_summaries = [
        FundGenreSummary(
            code=code,
            name=code_name[code] or f"ファンド {code}",
            genre=resolved_meta[code][0],
            is_configured=resolved_meta[code][1],
            valuation_total=code_valuation[code],
            ratio=round((code_valuation[code] / total_valuation) * 100.0, 1)
            if total_valuation > 0
            else 0.0,
            holding_count=code_count[code],
        )
        for code in code_order
    ]

    return RebalanceSummary(
        total_valuation=total_valuation,
        target_equity_ratio=target_eq_ratio,
        target_bond_ratio=target_bd_ratio,
        equity=equity_alloc,
        bond=bond_alloc,
        fund_summaries=fund_summaries,
        no_sell_buy_genre=no_sell_buy_genre,
        no_sell_buy_amount=no_sell_buy_amount,
        no_sell_achievable=no_sell_achievable,
        no_sell_post_total=no_sell_post_total,
    )
