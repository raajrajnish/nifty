"""Local market-data database (DuckDB, single file: data/market.duckdb). DESIGN.md §4.3 / §7.

Tables
  candles   (symbol, interval, ts) primary key — timestamps are naive IST exchange times.
  coverage  (symbol, interval, day) — every day we asked Groww for, including empty days (holidays),
            so a rerun never refetches. status: 'ok' | 'empty' | 'error' (errors are retried next run).
  contracts (symbol) — option/future contract metadata for the backtester.
Upserts are idempotent: re-inserting the same candle replaces it.
"""

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol   VARCHAR  NOT NULL,
    interval VARCHAR  NOT NULL,
    ts       TIMESTAMP NOT NULL,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    volume BIGINT, oi BIGINT,
    PRIMARY KEY (symbol, interval, ts)
);
CREATE TABLE IF NOT EXISTS coverage (
    symbol   VARCHAR NOT NULL,
    interval VARCHAR NOT NULL,
    day      DATE    NOT NULL,
    n        INTEGER NOT NULL,
    status   VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (symbol, interval, day)
);
CREATE TABLE IF NOT EXISTS contracts (
    symbol     VARCHAR PRIMARY KEY,
    underlying VARCHAR NOT NULL,
    kind       VARCHAR NOT NULL,          -- CE | PE | FUT | IDX
    expiry     DATE,
    strike     DOUBLE
);
"""

Candle = Sequence[Any]  # Groww format: [iso_ts, open, high, low, close, volume, oi]


class MarketStore:
    def __init__(self, path: Path, read_only: bool = False) -> None:
        self.path = path
        if read_only:
            self.con = duckdb.connect(str(path), read_only=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        self.con.execute(SCHEMA)

    def close(self) -> None:
        self.con.close()

    # ---- writes ----------------------------------------------------------------------------------
    def upsert_candles(self, symbol: str, interval: str, candles: Iterable[Candle]) -> int:
        rows = [(symbol, interval, pd.Timestamp(c[0]).tz_localize(None).to_pydatetime(), c[1], c[2], c[3], c[4],
                 c[5] if len(c) > 5 else None, c[6] if len(c) > 6 else None) for c in candles]
        if not rows:
            return 0
        df = pd.DataFrame(rows, columns=["symbol", "interval", "ts", "open", "high", "low", "close", "volume", "oi"])
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").astype("Int64")
        df["oi"] = pd.to_numeric(df["oi"], errors="coerce").astype("Int64")
        self.con.register("_new", df)
        self.con.execute("INSERT OR REPLACE INTO candles SELECT * FROM _new")
        self.con.unregister("_new")
        return len(rows)

    def mark(self, symbol: str, interval: str, days: Iterable[date], counts: dict[date, int], status: str) -> None:
        now = datetime.now()
        rows = [(symbol, interval, d, counts.get(d, 0), status if status == "error" else
                 ("ok" if counts.get(d, 0) else "empty"), now) for d in days]
        if rows:
            self.con.executemany("INSERT OR REPLACE INTO coverage VALUES (?, ?, ?, ?, ?, ?)", rows)

    def upsert_contract(self, symbol: str, underlying: str, kind: str, expiry: date | None,
                        strike: float | None) -> None:
        self.con.execute("INSERT OR REPLACE INTO contracts VALUES (?, ?, ?, ?, ?)",
                         [symbol, underlying, kind, expiry, strike])

    # ---- reads -----------------------------------------------------------------------------------
    def covered_days(self, symbol: str, interval: str) -> set[date]:
        """Days already fetched successfully (ok or genuinely empty). Errors are NOT covered → retried."""
        rows = self.con.execute("SELECT day FROM coverage WHERE symbol=? AND interval=? AND status IN ('ok','empty')",
                                [symbol, interval]).fetchall()
        return {r[0] for r in rows}

    def candles(self, symbol: str, interval: str, start: datetime | None = None,
                end: datetime | None = None) -> pd.DataFrame:
        q = "SELECT ts, open, high, low, close, volume, oi FROM candles WHERE symbol=? AND interval=?"
        params: list[Any] = [symbol, interval]
        if start is not None:
            q += " AND ts >= ?"
            params.append(start)
        if end is not None:
            q += " AND ts <= ?"
            params.append(end)
        return self.con.execute(q + " ORDER BY ts", params).df()

    def daily_closes(self, symbol: str) -> dict[date, tuple[float, float, float]]:
        """{day: (high, low, close)} from stored 1-day candles."""
        rows = self.con.execute("SELECT CAST(ts AS DATE), high, low, close FROM candles WHERE symbol=? "
                                "AND interval='1day' ORDER BY ts", [symbol]).fetchall()
        return {r[0]: (r[1], r[2], r[3]) for r in rows}

    def summary(self) -> pd.DataFrame:
        return self.con.execute("""
            SELECT c.interval, count(DISTINCT c.symbol) AS symbols, count(*) AS candles,
                   min(c.ts) AS first_ts, max(c.ts) AS last_ts
            FROM candles c GROUP BY c.interval ORDER BY c.interval""").df()

    def coverage_summary(self) -> pd.DataFrame:
        return self.con.execute("SELECT status, count(*) AS days FROM coverage GROUP BY status").df()
