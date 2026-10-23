"""src.history_db の包括的テストモジュール。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.history_db import PERIOD_OPTIONS, HistoryRepository, calculate_start_date
from src.models import FundSnapshotRecord


@pytest.fixture
def repo(tmp_path: Path) -> HistoryRepository:
    """テスト用の一時 SQLite データベースリポジトリを提供する。"""
    db_file = tmp_path / "test_history.db"
    return HistoryRepository(db_path=db_file)


def _make_record(
    recorded_date: str = "2026-10-21",
    holder: str = "個人",
    account: str = "NISA",
    code: str = "0331418A",
    isin: str = "JP90C000H1T1",
    name: str = "オルカン",
    units: float = 10000.0,
    cost_basis: int = 20000,
    nav: float = 25000.0,
    valuation: int = 25000,
    profit_loss: int | None = 5000,
) -> FundSnapshotRecord:
    """テスト用 FundSnapshotRecord 生成ヘルパー。"""
    return FundSnapshotRecord(
        recorded_date=recorded_date,
        recorded_at=f"{recorded_date}T12:00:00+00:00",
        holder=holder,
        account=account,
        code=code,
        isin=isin,
        name=name,
        units=units,
        cost_basis=cost_basis,
        nav=nav,
        valuation=valuation,
        profit_loss=profit_loss,
    )


def test_init_schema_idempotent(repo: HistoryRepository) -> None:
    """スキーマ初期化が冪等であり、複数回実行してもエラーにならないことを検証する。"""
    repo.init_schema()
    repo.init_schema()
    assert repo.db_path.exists()


def test_upsert_snapshots_empty(repo: HistoryRepository) -> None:
    """空のスナップショットリストを渡した場合に 0 が返り、DBに影響がないことを検証する。"""
    count = repo.upsert_snapshots([])
    assert count == 0
    assert repo.get_all_snapshots_df().empty


def test_upsert_and_on_conflict_update(repo: HistoryRepository) -> None:
    """スナップショットの登録および同一キー時の上書き更新（ON CONFLICT REPLACE）を検証する。"""
    # Arrange: 初回登録
    rec1 = _make_record(recorded_date="2026-10-21", valuation=25000)
    count1 = repo.upsert_snapshots([rec1])
    assert count1 == 1

    df_init = repo.get_all_snapshots_df()
    assert len(df_init) == 1
    assert df_init.iloc[0]["valuation"] == 25000

    # Act: 同一日付・同一ファンドで異なる評価額で更新
    rec1_updated = _make_record(recorded_date="2026-10-21", valuation=28000, nav=28000.0)
    count2 = repo.upsert_snapshots([rec1_updated])

    # Assert: レコード数は増えず、値が更新されている
    assert count2 == 1
    df_updated = repo.get_all_snapshots_df()
    assert len(df_updated) == 1
    assert df_updated.iloc[0]["valuation"] == 28000
    assert df_updated.iloc[0]["nav"] == 28000.0


def test_get_distinct_funds(repo: HistoryRepository) -> None:
    """一意なファンド一覧の取得およびプロパティ動作を検証する。"""
    rec_a1 = _make_record(
        recorded_date="2026-10-21", holder="個人", account="NISA", code="0331418A"
    )
    rec_a2 = _make_record(
        recorded_date="2026-10-22", holder="個人", account="NISA", code="0331418A"
    )
    rec_b = _make_record(
        recorded_date="2026-10-21",
        holder="法人",
        account="一般預り",
        code="03311187",
        isin="JP90C000GKC6",
        name="先進国株式",
    )

    repo.upsert_snapshots([rec_a1, rec_a2, rec_b])

    funds = repo.get_distinct_funds()
    assert len(funds) == 2

    keys = {f.identity_key for f in funds}
    assert "個人__NISA__0331418A__JP90C000H1T1" in keys
    assert "法人__一般預り__03311187__JP90C000GKC6" in keys

    target_fund = next(f for f in funds if f.code == "0331418A")
    assert target_fund.display_label == "[個人] NISA - オルカン (0331418A)"


def test_get_fund_history_df(repo: HistoryRepository) -> None:
    """指定ファンドの時系列推移抽出を検証する。"""
    rec1 = _make_record(recorded_date="2026-10-20", valuation=24000)
    rec2 = _make_record(recorded_date="2026-10-22", valuation=26000)
    rec_other = _make_record(
        recorded_date="2026-10-21",
        holder="法人",
        account="一般預り",
        code="03311187",
        isin="JP90C000GKC6",
    )

    repo.upsert_snapshots([rec1, rec2, rec_other])

    # 存在するファンド
    df_fund = repo.get_fund_history_df(
        holder="個人",
        account="NISA",
        code="0331418A",
        isin="JP90C000H1T1",
    )
    assert len(df_fund) == 2
    assert list(df_fund["recorded_date"]) == ["2026-10-20", "2026-10-22"]
    assert list(df_fund["valuation"]) == [24000, 26000]

    # 存在しないファンド
    df_none = repo.get_fund_history_df(
        holder="個人",
        account="特定預り",
        code="99999999",
        isin="JP9999999999",
    )
    assert df_none.empty


def test_get_stacked_asset_df(repo: HistoryRepository) -> None:
    """積み上げ集計（銘柄別、口座別、法人個人別、不正引数フォールバック）を検証する。"""
    rec_a = _make_record(
        recorded_date="2026-10-21",
        holder="個人",
        account="NISA",
        code="0331418A",
        name="オルカン",
        valuation=30000,
    )
    rec_b = _make_record(
        recorded_date="2026-10-21",
        holder="法人",
        account="一般預り",
        code="03311187",
        isin="JP90C000GKC6",
        name="先進国",
        valuation=50000,
    )

    repo.upsert_snapshots([rec_a, rec_b])

    # 1. 銘柄別集計
    df_name = repo.get_stacked_asset_df(group_by="name")
    assert len(df_name) == 2
    assert set(df_name["group_key"]) == {"オルカン", "先進国"}
    assert df_name["valuation"].sum() == 80000

    # 2. 口座別集計
    df_acc = repo.get_stacked_asset_df(group_by="account")
    assert len(df_acc) == 2
    assert set(df_acc["group_key"]) == {"NISA", "一般預り"}

    # 3. 法人個人別集計
    df_holder = repo.get_stacked_asset_df(group_by="holder")
    assert len(df_holder) == 2
    assert set(df_holder["group_key"]) == {"個人", "法人"}

    # 4. 不正な group_by 引数時のフォールバック (name)
    df_invalid = repo.get_stacked_asset_df(group_by="invalid_column")
    assert set(df_invalid["group_key"]) == {"オルカン", "先進国"}


def test_get_latest_recorded_date_and_delete(repo: HistoryRepository) -> None:
    """最新記録日の取得および日付指定削除の動作を検証する。"""
    # 空の時は None
    assert repo.get_latest_recorded_date() is None

    # 2日分登録
    rec1 = _make_record(recorded_date="2026-10-20")
    rec2 = _make_record(recorded_date="2026-10-23")
    repo.upsert_snapshots([rec1, rec2])

    assert repo.get_latest_recorded_date() == "2026-10-23"

    # 指定日削除
    deleted_count = repo.delete_snapshot_by_date("2026-10-20")
    assert deleted_count == 1
    assert repo.get_latest_recorded_date() == "2026-10-23"

    # 存在しない日の削除は 0 件
    deleted_zero = repo.delete_snapshot_by_date("2020-01-01")
    assert deleted_zero == 0


def test_calculate_start_date() -> None:
    """期間区分に応じた開始日算出ロジックを検証する。"""
    # 正常系
    assert calculate_start_date("2026-10-23", "全期間") is None
    assert calculate_start_date("2026-10-23", "3ヵ月") == "2026-07-23"
    assert calculate_start_date("2026-10-23", "1年") == "2025-10-23"
    assert calculate_start_date("2026-10-23", "3年") == "2023-10-24"
    assert "全期間" in PERIOD_OPTIONS

    # 異常系・境界値
    assert calculate_start_date("invalid-date", "1年") is None
    assert calculate_start_date("2026-10-23", "10年") is None


def test_get_total_asset_history_df(repo: HistoryRepository) -> None:
    """全ファンド合算の資産推移集計および期間フィルタリングを検証する。"""
    # 空DB時
    df_empty = repo.get_total_asset_history_df()
    assert df_empty.empty

    # 複数日付・複数ファンド登録
    rec1_a = _make_record(
        recorded_date="2026-01-01", valuation=10000, cost_basis=8000, profit_loss=2000
    )
    rec1_b = _make_record(
        recorded_date="2026-01-01",
        holder="法人",
        code="03311187",
        isin="JP90C000GKC6",
        valuation=20000,
        cost_basis=15000,
        profit_loss=5000,
    )
    rec2 = _make_record(
        recorded_date="2026-06-01", valuation=35000, cost_basis=25000, profit_loss=10000
    )
    rec3 = _make_record(
        recorded_date="2026-10-23", valuation=40000, cost_basis=30000, profit_loss=10000
    )

    repo.upsert_snapshots([rec1_a, rec1_b, rec2, rec3])

    # 全期間
    df_all = repo.get_total_asset_history_df()
    assert len(df_all) == 3
    row0 = df_all.iloc[0]
    assert row0["recorded_date"] == "2026-01-01"
    assert row0["total_valuation"] == 30000
    assert row0["total_cost_basis"] == 23000
    assert row0["total_profit_loss"] == 7000

    # 期間指定（2026-06-01以降）
    df_filtered = repo.get_total_asset_history_df(start_date="2026-06-01")
    assert len(df_filtered) == 2
    assert list(df_filtered["recorded_date"]) == ["2026-06-01", "2026-10-23"]

    # 積み上げ集計の期間指定
    df_stacked_filtered = repo.get_stacked_asset_df(group_by="name", start_date="2026-06-01")
    assert len(df_stacked_filtered) == 2
    assert "2026-01-01" not in set(df_stacked_filtered["recorded_date"])

    # 個別ファンド推移の期間指定
    df_fund_filtered = repo.get_fund_history_df(
        holder="個人", account="NISA", code="0331418A", isin="JP90C000H1T1", start_date="2026-06-01"
    )
    assert len(df_fund_filtered) == 2
    assert list(df_fund_filtered["recorded_date"]) == ["2026-06-01", "2026-10-23"]
