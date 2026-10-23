"""SQLiteによる投資信託ポートフォリオ履歴永続化および時系列集計リポジトリ。"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from src.models import FundSnapshotRecord

DEFAULT_DB_FILE: Final[str] = "fund_history.db"


@dataclass(frozen=True)
class DistinctFund:
    """履歴に登録されている一意なファンドの表現。"""

    holder: str
    account: str
    code: str
    isin: str
    name: str

    @property
    def identity_key(self) -> str:
        """4要素完全一致の識別キー。"""
        return f"{self.holder}__{self.account}__{self.code}__{self.isin}"

    @property
    def display_label(self) -> str:
        """UIドロップダウン用の表示文字列。"""
        return f"[{self.holder}] {self.account} - {self.name} ({self.code})"


class HistoryRepository:
    """投資信託ポートフォリオのスナップショットを SQLite に記録・集計するリポジトリ。"""

    def __init__(self, db_path: Path) -> None:
        """リポジトリを初期化し、スキーマを保証する。

        Args:
            db_path: SQLiteデータベースファイルのパス。
        """
        self._db_path = db_path.resolve()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @property
    def db_path(self) -> Path:
        """データベースファイルの絶対パスを取得する。"""
        return self._db_path

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection]:
        """SQLite データベースへの接続を生成し、確実にクローズするコンテキストマネージャ。"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_schema(self) -> None:
        """スナップショット履歴テーブルおよび検索インデックスを初期化する。"""
        with self._connect() as conn, conn:
            conn.execute(
                """
                    CREATE TABLE IF NOT EXISTS fund_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        recorded_date TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        holder TEXT NOT NULL,
                        account TEXT NOT NULL,
                        code TEXT NOT NULL,
                        isin TEXT NOT NULL,
                        name TEXT NOT NULL,
                        units REAL NOT NULL,
                        cost_basis INTEGER NOT NULL,
                        nav REAL NOT NULL,
                        valuation INTEGER NOT NULL,
                        profit_loss INTEGER,
                        UNIQUE(recorded_date, holder, account, code, isin) ON CONFLICT REPLACE
                    );
                    """
            )
            conn.execute(
                """
                    CREATE INDEX IF NOT EXISTS idx_fund_snapshots_fund 
                    ON fund_snapshots (holder, account, code, isin, recorded_date);
                    """
            )
            conn.execute(
                """
                    CREATE INDEX IF NOT EXISTS idx_fund_snapshots_date 
                    ON fund_snapshots (recorded_date);
                    """
            )

    def upsert_snapshots(self, snapshots: Sequence[FundSnapshotRecord]) -> int:
        """スナップショット群をデータベースにアトミックに登録・更新する。

        同一日付・同一ファンド（holder, account, code, isin）のレコードが存在する場合は上書き更新する。

        Args:
            snapshots: 登録対象のスナップショットリスト。

        Returns:
            登録・更新された件数。
        """
        if not snapshots:
            return 0

        with self._connect() as conn, conn:
            conn.executemany(
                """
                    INSERT INTO fund_snapshots (
                        recorded_date, recorded_at, holder, account, code, isin,
                        name, units, cost_basis, nav, valuation, profit_loss
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(recorded_date, holder, account, code, isin) DO UPDATE SET
                        recorded_at=excluded.recorded_at,
                        name=excluded.name,
                        units=excluded.units,
                        cost_basis=excluded.cost_basis,
                        nav=excluded.nav,
                        valuation=excluded.valuation,
                        profit_loss=excluded.profit_loss;
                    """,
                [
                    (
                        s.recorded_date,
                        s.recorded_at,
                        s.holder,
                        s.account,
                        s.code,
                        s.isin,
                        s.name,
                        s.units,
                        s.cost_basis,
                        s.nav,
                        s.valuation,
                        s.profit_loss,
                    )
                    for s in snapshots
                ],
            )
            return len(snapshots)

    def get_all_snapshots_df(self) -> pd.DataFrame:
        """全スナップショットを時系列昇順の DataFrame として取得する。

        Returns:
            全スナップショットの DataFrame。
        """
        query = """
            SELECT 
                recorded_date, recorded_at, holder, account, code, isin,
                name, units, cost_basis, nav, valuation, profit_loss
            FROM fund_snapshots
            ORDER BY recorded_date ASC, holder ASC, account ASC, code ASC;
        """
        with self._connect() as conn:
            return pd.read_sql_query(query, conn)

    def get_distinct_funds(self) -> list[DistinctFund]:
        """履歴に存在する一意なファンド（最新の銘柄名を含む）一覧を取得する。

        Returns:
            一意なファンド一覧（DistinctFund）。
        """
        query = """
            SELECT 
                holder, account, code, isin, name
            FROM fund_snapshots
            GROUP BY holder, account, code, isin
            ORDER BY holder ASC, account ASC, name ASC;
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            rows = cursor.execute(query).fetchall()
            return [
                DistinctFund(
                    holder=row["holder"],
                    account=row["account"],
                    code=row["code"],
                    isin=row["isin"],
                    name=row["name"],
                )
                for row in rows
            ]

    def get_fund_history_df(
        self,
        holder: str,
        account: str,
        code: str,
        isin: str,
    ) -> pd.DataFrame:
        """指定ファンド（4要素完全一致）の時系列推移を DataFrame として取得する。

        Args:
            holder: 法人/個人区分。
            account: 格納口座。
            code: 投信協会コード。
            isin: ISINコード。

        Returns:
            該当ファンドの時系列 DataFrame（recorded_date 昇順）。
        """
        query = """
            SELECT 
                recorded_date, recorded_at, holder, account, code, isin,
                name, units, cost_basis, nav, valuation, profit_loss
            FROM fund_snapshots
            WHERE holder = ? AND account = ? AND code = ? AND isin = ?
            ORDER BY recorded_date ASC;
        """
        with self._connect() as conn:
            return pd.read_sql_query(
                query,
                conn,
                params=(holder, account, code, isin),
            )

    def get_stacked_asset_df(self, group_by: str = "name") -> pd.DataFrame:
        """ダッシュボード積み上げ棒グラフ用集計データを取得する。

        Args:
            group_by: 積み上げ集計のグループキー（'name', 'account', 'holder' のいずれか）。

        Returns:
            ['recorded_date', 'group_key', 'valuation'] を持つ DataFrame。
        """
        allowed_columns = {"name", "account", "holder"}
        target_col = group_by if group_by in allowed_columns else "name"

        query = f"""
            SELECT 
                recorded_date,
                {target_col} AS group_key,
                SUM(valuation) AS valuation
            FROM fund_snapshots
            GROUP BY recorded_date, {target_col}
            ORDER BY recorded_date ASC, {target_col} ASC;
        """
        with self._connect() as conn:
            return pd.read_sql_query(query, conn)

    def get_latest_recorded_date(self) -> str | None:
        """直近でスナップショットが記録された最新日付（YYYY-MM-DD）を取得する。

        Returns:
            最新日付文字列。記録が存在しない場合は None。
        """
        query = "SELECT MAX(recorded_date) AS max_date FROM fund_snapshots;"
        with self._connect() as conn:
            cursor = conn.cursor()
            row = cursor.execute(query).fetchone()
            if row and row["max_date"]:
                return str(row["max_date"])
            return None

    def delete_snapshot_by_date(self, recorded_date: str) -> int:
        """指定日のスナップショットレコードを全件削除する。

        Args:
            recorded_date: 削除対象の基準日 (YYYY-MM-DD)。

        Returns:
            削除された件数。
        """
        with self._connect() as conn, conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM fund_snapshots WHERE recorded_date = ?;",
                (recorded_date,),
            )
            return cursor.rowcount
