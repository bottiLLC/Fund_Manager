"""投資信託ポートフォリオ評価 CLI ダッシュボード エントリーポイント。"""

from __future__ import annotations

import argparse
import sys
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

from backup_manager import run_backup
from src.calculator import evaluate_portfolio
from src.formatter import format_cli_report
from src.models import HOLDER_OPTIONS, PortfolioItem
from src.nav_fetcher import fetch_latest_nav_and_names
from src.portfolio_loader import PRESET_FUNDS, load_portfolio_csv, save_portfolio_csv
from src.sbi_importer import (
    MergeMode,
    decode_csv_bytes,
    load_custom_aliases,
    merge_candidates_into_portfolio,
    parse_sbi_portfolio_csv,
    resolve_candidates,
)


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
        "--import-sbi",
        type=Path,
        default=None,
        help="SBI証券ポートフォリオCSVを取り込んで portfolio.csv を更新する",
    )
    parser.add_argument(
        "--mode",
        choices=["append", "replace"],
        default="append",
        help="インポート方式: append (追記・デフォルト) または replace (洗い替え)",
    )
    parser.add_argument(
        "--holder",
        type=str,
        choices=list(HOLDER_OPTIONS),
        default="個人",
        help="SBI証券CSVインポート時の所有者区分 (デフォルト: 個人)",
    )
    return parser.parse_args()


def main() -> int:
    """メイン実行処理。"""
    args = parse_arguments()

    portfolio_items: list[PortfolioItem] = []
    if args.csv.exists() or args.import_sbi is None:
        try:
            portfolio_items = load_portfolio_csv(args.csv)
        except Exception as e:
            if args.import_sbi is None:
                sys.stderr.write(f"エラー: 保有資産CSVの読み込みに失敗しました: {e}\n")
                return 1

    if args.import_sbi is not None:
        try:
            sbi_path = Path(args.import_sbi).resolve()
            if not sbi_path.exists():
                sys.stderr.write(f"エラー: 指定されたSBI CSVファイルが存在しません: {sbi_path}\n")
                return 1

            raw_text = decode_csv_bytes(sbi_path.read_bytes())
            records = parse_sbi_portfolio_csv(raw_text)
            if not records:
                sys.stderr.write("エラー: 有効な投資信託明細が検出されませんでした。\n")
                return 1

            alias_file = _PROJECT_ROOT / "data" / "custom_fund_aliases.json"
            custom_aliases = load_custom_aliases(alias_file)
            candidates = resolve_candidates(
                records=records,
                existing_items=portfolio_items,
                custom_aliases=custom_aliases,
                default_holder=args.holder,
            )

            unresolved = [c for c in candidates if not c.is_resolved]
            if unresolved:
                sys.stderr.write(
                    f"エラー: {len(unresolved)} 件の銘柄コードが未解決です (例: {unresolved[0].source_record.fund_name})\n"
                )
                return 1

            run_backup(app_name="pre_sbi_import")
            merge_mode = MergeMode.REPLACE_ALL if args.mode == "replace" else MergeMode.APPEND
            updated = merge_candidates_into_portfolio(
                existing_items=portfolio_items,
                resolved_candidates=candidates,
                merge_mode=merge_mode,
            )
            save_portfolio_csv(args.csv, updated)
            portfolio_items = updated
            print(f"SBI証券CSVを正常にインポートしました: {len(updated)} 件")
        except Exception as ex:
            sys.stderr.write(f"エラー: SBI CSVインポートに失敗しました: {ex}\n")
            return 1

    targets = {item.code: item.isin for item in portfolio_items}
    cache_dir = _PROJECT_ROOT / "data" / "cache"

    fetch_result = fetch_latest_nav_and_names(
        targets=targets,
        cache_dir=cache_dir,
    )
    as_of_date = fetch_result[0]
    nav_map = fetch_result[1]
    name_map = fetch_result[2]

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
        fetched_at=fetch_result.fetched_at,
        fallback_funds=fetch_result.fallback_funds,
    )

    output_text = format_cli_report(report)
    print(output_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
