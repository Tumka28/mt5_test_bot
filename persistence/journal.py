"""Trade Journal — SQLite-д order/fill/pnl бичнэ.

Live, paper, replay бүгд адил schema-тай бичнэ — хожим аналитик нэг код-оор
хийгдэх боломжтой.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_order_id TEXT UNIQUE NOT NULL,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    lots            REAL NOT NULL,
    entry           REAL NOT NULL,
    stop_loss       REAL,
    take_profit     REAL,
    submitted_ts    INTEGER NOT NULL,
    status          TEXT NOT NULL,            -- submitted/filled/rejected/cancelled
    reject_reason   TEXT,
    fill_price      REAL,
    fill_ts         INTEGER,
    mode            TEXT NOT NULL              -- live/paper/backtest
);

CREATE TABLE IF NOT EXISTS pnl_daily (
    date    TEXT PRIMARY KEY,
    realized REAL NOT NULL DEFAULT 0,
    unrealized REAL NOT NULL DEFAULT 0,
    equity_close REAL
);

CREATE INDEX IF NOT EXISTS idx_orders_symbol_ts ON orders(symbol, submitted_ts);
"""


class Journal:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as conn:
            conn.executescript(_SCHEMA)
            conn.commit()

    def record_submission(
        self,
        *, client_order_id: str, symbol: str, side: str, lots: float,
        entry: float, stop_loss: float | None, take_profit: float | None,
        submitted_ts: int, mode: str,
    ) -> None:
        with closing(sqlite3.connect(self._path)) as conn:
            conn.execute(
                """INSERT INTO orders(client_order_id, symbol, side, lots, entry,
                       stop_loss, take_profit, submitted_ts, status, mode)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (client_order_id, symbol, side, lots, entry,
                 stop_loss, take_profit, submitted_ts, "submitted", mode),
            )
            conn.commit()

    def record_fill(self, client_order_id: str, fill_price: float, fill_ts: int) -> None:
        with closing(sqlite3.connect(self._path)) as conn:
            conn.execute(
                """UPDATE orders SET status='filled', fill_price=?, fill_ts=?
                   WHERE client_order_id=?""",
                (fill_price, fill_ts, client_order_id),
            )
            conn.commit()

    def record_reject(self, client_order_id: str, reason: str) -> None:
        with closing(sqlite3.connect(self._path)) as conn:
            conn.execute(
                """UPDATE orders SET status='rejected', reject_reason=?
                   WHERE client_order_id=?""",
                (reason, client_order_id),
            )
            conn.commit()

    def count_orders(self) -> int:
        with closing(sqlite3.connect(self._path)) as conn:
            cur = conn.execute("SELECT COUNT(*) FROM orders")
            return int(cur.fetchone()[0])
