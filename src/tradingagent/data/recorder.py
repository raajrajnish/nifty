"""Market-data recorder (DESIGN.md §4.3, lessons L8/L9). READ-ONLY: no order capability anywhere.

Records what Groww history does not provide, from the first Phase 1 day:
  ltp.jsonl     every ltp_interval_s: NIFTY index, India VIX, nearest future, tracked options (LTP)
  quotes.jsonl  every quote_interval_s: 5-level bid/ask depth + OI/volume for future and ATM±N CE/PE
  chain.jsonl   every chain_interval_s: option chain (LTP/OI/volume/IV/greeks) for ATM±chain_strikes
  master.csv + master.manifest.json  once per day: NIFTY instruments + SHA-256 of the full master
Files: data/raw/date=YYYY-MM-DD/<stream>.jsonl (append-only, flushed per record, crash-safe).
Every record carries recv_ts (IST). The tracked strike set re-centres on ATM at each chain refresh.
"""

import hashlib
import json
import os
import threading
import time as _time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from tradingagent.core.clock import Clock
from tradingagent.core.errors import BrokerRateLimited


class MarketDataSource(Protocol):
    def ltp(self, symbols: tuple[str, ...], segment: str) -> dict[str, float]: ...
    def quote_fno(self, trading_symbol: str) -> dict[str, Any]: ...
    def option_chain(self, underlying: str, expiry: str) -> dict[str, Any]: ...
    def expiries(self, underlying: str, year: int, month: int) -> list[str]: ...
    def instruments(self) -> pd.DataFrame: ...


@dataclass(frozen=True)
class RecorderConfig:
    underlying: str = "NIFTY"
    index_symbols: tuple[str, ...] = ("NSE_NIFTY", "NSE_INDIAVIX")
    # Forward tournament (2026-10-04): extra CASH symbols for P4/HL1 (Bank Nifty, HDFC Bank, ICICI Bank) and the
    # BSE candidate. Requested SEPARATELY so a bad symbol can never break the NIFTY/VIX stream G1/G2 depend on.
    extra_cash_symbols: tuple[str, ...] = ("NSE_BANKNIFTY", "NSE_HDFCBANK", "NSE_ICICIBANK", "NSE_BSE")
    strike_step: int = 50
    strikes_each_side: int = 5          # quoted with full depth (2 × (2N+1) contracts)
    chain_strikes_each_side: int = 20   # kept from each chain snapshot
    ltp_interval_s: float = 2.0
    quote_interval_s: float = 10.0
    chain_interval_s: float = 60.0
    start: time = time(9, 14)
    stop: time = time(15, 31)


@dataclass
class RecorderStatus:
    running: bool = False
    session_date: str = ""
    started_at: str = ""
    last_write_at: str = ""
    counts: dict[str, int] = field(default_factory=dict)
    bytes: int = 0
    errors: int = 0
    last_error: str = ""
    expiry: str = ""
    future: str = ""
    atm: int = 0
    tracked_contracts: int = 0
    note: str = "read-only recorder; no order capability"


class DayWriter:
    def __init__(self, root: Path, day: date) -> None:
        self.dir = root / f"date={day.isoformat()}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.bytes = sum(p.stat().st_size for p in self.dir.glob("*") if p.is_file())

    def write(self, stream: str, record: dict[str, Any]) -> None:
        line = json.dumps(record, default=str, separators=(",", ":")) + "\n"
        with (self.dir / f"{stream}.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)
        self.bytes += len(line.encode("utf-8"))


def nearest_expiry(expiries: list[str], today: date) -> str:
    upcoming = sorted(e for e in expiries if e >= today.isoformat())
    if not upcoming:
        raise ValueError("no upcoming expiry returned by broker")
    return upcoming[0]


def atm_strike(underlying_ltp: float, step: int) -> int:
    return int(round(underlying_ltp / step) * step)


class Recorder:
    def __init__(self, src: MarketDataSource, cfg: RecorderConfig, clock: Clock, data_root: Path,
                 status_path: Path, sleep: Callable[[float], None] = _time.sleep) -> None:
        self._src = src
        self._cfg = cfg
        self._clock = clock
        self._root = data_root
        self._status_path = status_path
        self._sleep = sleep
        self.status = RecorderStatus()
        self._writer: DayWriter | None = None
        self._expiry = ""
        self._future = ""
        self._tracked: list[str] = []  # option trading symbols, e.g. NIFTY26O0622700CE
        self._backoff_until = 0.0
        self._lock = threading.Lock()  # guards writer + status across stream threads
        self._stop = threading.Event()

    # ---- helpers ---------------------------------------------------------------------------------
    def _now(self) -> datetime:
        return self._clock.now()

    def _write(self, stream: str, payload: dict[str, Any]) -> None:
        assert self._writer is not None
        with self._lock:
            now = self._now()
            self._writer.write(stream, {"recv_ts": now.isoformat(), **payload})
            self.status.counts[stream] = self.status.counts.get(stream, 0) + 1
            self.status.last_write_at = now.isoformat()
            self.status.bytes = self._writer.bytes

    def _error(self, where: str, e: Exception) -> None:
        with self._lock:
            self.status.errors += 1
            self.status.last_error = f"{self._now():%H:%M:%S} {where}: {type(e).__name__}: {str(e)[:160]}"
            if isinstance(e, BrokerRateLimited):
                self._backoff_until = _time.monotonic() + 10  # back off all polling for 10 s

    def _save_status(self, payload: str | None = None) -> None:
        """Atomic status write. On Windows, os.replace fails while another process (the dashboard) has the file open,
        so retry briefly; the status is display-only and must NEVER stop recording (2026-10-07: an unhandled
        PermissionError here ended the recorder at 12:07)."""
        self._status_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._status_path.with_suffix(f".{os.getpid()}.tmp")
        if payload is None:
            payload = json.dumps(self.status.__dict__, default=str)
        tmp.write_text(payload, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, self._status_path)
                return
            except OSError:
                if attempt == 4:
                    raise
                _time.sleep(0.05 * (attempt + 1))

    # ---- setup -----------------------------------------------------------------------------------
    def setup(self) -> None:
        today = self._now().date()
        self._writer = DayWriter(self._root, today)
        self.status = RecorderStatus(running=True, session_date=today.isoformat(), started_at=self._now().isoformat(),
                                     bytes=self._writer.bytes)
        self._snapshot_master(today)
        exps: list[str] = []
        for y, m in ((today.year, today.month), (today.year + (today.month == 12), today.month % 12 + 1)):
            exps += self._src.expiries(self._cfg.underlying, y, m)
        self._expiry = nearest_expiry(exps, today)
        self.status.expiry = self._expiry
        self._refresh_chain()
        self._save_status()

    def _snapshot_master(self, today: date) -> None:
        manifest = self._writer.dir / "master.manifest.json"  # type: ignore[union-attr]
        if manifest.exists():  # restart on the same day: keep the first snapshot, reload the future symbol
            self._future = json.loads(manifest.read_text(encoding="utf-8"))["nearest_future"]
            self.status.future = self._future
            return
        df = self._src.instruments()
        full_sha = hashlib.sha256(df.to_csv(index=False).encode("utf-8")).hexdigest()
        sub = df[df["underlying_symbol"] == self._cfg.underlying]
        sub.to_csv(self._writer.dir / "master.csv", index=False)  # type: ignore[union-attr]
        futs = sub[sub["instrument_type"] == "FUT"].sort_values("expiry_date")
        futs = futs[futs["expiry_date"].astype(str) >= today.isoformat()]
        self._future = str(futs.iloc[0]["trading_symbol"]) if len(futs) else ""
        self.status.future = self._future
        lot_sizes = sorted({str(x) for x in sub.loc[sub["instrument_type"].isin(["CE", "PE"]), "lot_size"]})
        manifest.write_text(json.dumps({
            "fetched_at": self._now().isoformat(), "full_master_sha256": full_sha, "full_rows": len(df),
            "underlying": self._cfg.underlying, "rows": len(sub), "nearest_future": self._future,
            "option_lot_sizes": lot_sizes,
        }, indent=2), encoding="utf-8")

    # ---- polling tasks ---------------------------------------------------------------------------
    def _refresh_chain(self) -> None:
        chain = self._src.option_chain(self._cfg.underlying, self._expiry)
        u = float(chain.get("underlying_ltp") or 0)
        atm = atm_strike(u, self._cfg.strike_step)
        strikes: dict[str, Any] = chain.get("strikes") or {}
        keep_lo = atm - self._cfg.chain_strikes_each_side * self._cfg.strike_step
        keep_hi = atm + self._cfg.chain_strikes_each_side * self._cfg.strike_step
        kept = {k: v for k, v in strikes.items() if keep_lo <= float(k) <= keep_hi}
        self._write("chain", {"expiry": self._expiry, "underlying_ltp": u, "atm": atm, "strikes": kept})
        lo = atm - self._cfg.strikes_each_side * self._cfg.strike_step
        hi = atm + self._cfg.strikes_each_side * self._cfg.strike_step
        tracked = []
        for k in sorted(kept, key=float):
            if lo <= float(k) <= hi:
                for side in ("CE", "PE"):
                    sym = (kept[k].get(side) or {}).get("trading_symbol")
                    if sym:
                        tracked.append(str(sym))
        self._tracked = tracked
        self.status.atm = atm
        self.status.tracked_contracts = len(tracked)

    def _poll_ltp(self) -> None:
        idx = self._src.ltp(self._cfg.index_symbols, "CASH")
        if self._cfg.extra_cash_symbols:
            try:
                idx = {**self._src.ltp(self._cfg.extra_cash_symbols, "CASH"), **idx}
            except Exception as e:  # extras are optional; NIFTY/VIX are still written
                self._error("ltp extras", e)
        fno_syms = tuple(f"NSE_{s}" for s in ([self._future] if self._future else []) + self._tracked)
        fno = self._src.ltp(fno_syms, "FNO") if fno_syms else {}
        self._write("ltp", {"index": idx, "fno": fno})

    def _poll_quotes(self) -> None:
        for sym in ([self._future] if self._future else []) + self._tracked:
            if _time.monotonic() < self._backoff_until:
                return
            try:
                q = self._src.quote_fno(sym)
            except Exception as e:  # one bad contract must not stop the others
                self._error(f"quote {sym}", e)
                continue
            depth = q.get("depth") or {}
            buy, sell = depth.get("buy") or [], depth.get("sell") or []
            self._write("quotes", {
                "symbol": sym, "ltp": q.get("last_price"),
                "bid": buy[0]["price"] if buy else None, "bid_qty": buy[0]["quantity"] if buy else None,
                "ask": sell[0]["price"] if sell else None, "ask_qty": sell[0]["quantity"] if sell else None,
                "depth": {"buy": buy, "sell": sell}, "oi": q.get("open_interest"), "volume": q.get("volume"),
                "last_trade_time": q.get("last_trade_time"), "total_buy_qty": q.get("total_buy_quantity"),
                "total_sell_qty": q.get("total_sell_quantity"),
            })

    # ---- main loop -------------------------------------------------------------------------------
    def _stream_loop(self, name: str, every: float, fn: Callable[[], None], first_delay: float) -> None:
        """One thread per stream so slow depth quotes never delay the 2-second LTP stream."""
        if self._stop.wait(first_delay):
            return
        while not self._stop.is_set():
            t0 = _time.monotonic()
            if t0 >= self._backoff_until:
                try:
                    fn()
                except Exception as e:  # recorder must survive any single failure
                    self._error(name, e)
            self._stop.wait(max(0.0, every - (_time.monotonic() - t0)))

    def run(self, duration_s: float | None = None) -> RecorderStatus:
        """Runs until the configured stop time (or duration_s, for tests)."""
        start_dt = self._now().replace(hour=self._cfg.start.hour, minute=self._cfg.start.minute, second=0)
        if self._now() < start_dt:
            self._sleep((start_dt - self._now()).total_seconds())
        self.setup()
        self._stop.clear()
        c = self._cfg
        threads = [threading.Thread(target=self._stream_loop, args=a, name=f"rec-{a[0]}", daemon=True) for a in (
            ("ltp", c.ltp_interval_s, self._poll_ltp, 0.0),
            ("quotes", c.quote_interval_s, self._poll_quotes, 0.0),
            ("chain", c.chain_interval_s, self._refresh_chain, c.chain_interval_s),  # setup() just fetched it
        )]
        for t in threads:
            t.start()
        t_end = None if duration_s is None else _time.monotonic() + duration_s
        try:
            while self._now().time() < c.stop and (t_end is None or _time.monotonic() < t_end):
                try:
                    with self._lock:  # snapshot under the lock; the file write (and any retries) happen outside it
                        payload = json.dumps(self.status.__dict__, default=str)
                    self._save_status(payload)
                except Exception as e:  # a failed status write is logged, never fatal: data keeps flowing
                    self._error("status write", e)
                self._sleep(1.0)
        finally:
            self._stop.set()
            for t in threads:
                t.join(timeout=15)
            self.status.running = False
            try:
                with self._lock:
                    payload = json.dumps(self.status.__dict__, default=str)
                self._save_status(payload)
            except Exception as e:  # never let the final status write turn a normal stop into a crash
                self._error("status write", e)
        return self.status
