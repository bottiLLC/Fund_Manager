"""投資信託ポートフォリオ評価 CLI ダッシュボード エントリーポイント。"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Deterministic sys.path configuration for top-level entry point
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.calculator import evaluate_portfolio
from src.formatter import format_cli_report
from src.nav_fetcher import fetch_latest_nav_and_names
from src.portfolio_loader import PRESET_FUNDS, load_portfolio_csv


def parse_arguments() -> argparse.Namespace:
    """コマンドライン引数を解析する。"""
    parser = argparse.ArgumentParser(
        description="投資信託協会基準価額を用いたポートフォリオ評価・可視化CLIツール",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=_PROJECT_ROOT / "data" / "portfolio.csv",
        help="保有資産CSVファイルへのパス (デフォルト: ./data/portfolio.csv)",
    )
    parser.add_argument(
        "--dc-base-date",
        type=str,
        default="2025-01-01",
        help="DC仮想積立の開始基準日 (YYYY-MM-DD, デフォルト: 2025-01-01)",
    )
    parser.add_argument(
        "--dc-code",
        type=str,
        default=None,
        help="DC仮想積立を適用するファンドコード (未指定時はDC口座の先頭銘柄)",
    )
    return parser.parse_args()


def main() -> int:
    """メイン実行処理。"""
    args = parse_arguments()

    try:
        dc_base = date.fromisoformat(args.dc_base_date)
    except ValueError:
        sys.stderr.write(
            f"エラー: --dc-base-date の日付形式が不正です (指定値: {args.dc_base_date}, 形式: YYYY-MM-DD)\n"
        )
        return 1

    try:
        portfolio_items = load_portfolio_csv(args.csv)
    except Exception as e:
        sys.stderr.write(f"エラー: 保有資産CSVの読み込みに失敗しました: {e}\n")
        return 1

    targets = {item.code: item.isin for item in portfolio_items}
    cache_dir = _PROJECT_ROOT / "data" / "cache"

    as_of_date, nav_map, name_map = fetch_latest_nav_and_names(
        targets=targets,
        cache_dir=cache_dir,
    )

    hydrated_items = [
        item.model_copy(
            update={
                "name": name_map.get(item.code)
                or item.name
                or PRESET_FUNDS.get(item.code, {}).get("name")
                or f"ファンド {item.code}"
            }
        )
        for item in portfolio_items
    ]

    report = evaluate_portfolio(
        items=hydrated_items,
        nav_map=nav_map,
        as_of_date=as_of_date,
        dc_base_date=dc_base,
        dc_target_code=args.dc_code,
    )

    output_text = format_cli_report(report)
    print(output_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
