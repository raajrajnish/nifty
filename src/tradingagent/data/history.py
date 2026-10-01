"""Historical candle downloader → MarketStore (DuckDB). READ-ONLY; resumable; never refetches stored days.

Facts it relies on (verified live 2026-09-30, docs/DATA_FEASIBILITY.md):
  * max window per request: 1/5-min 30 days, 15-min 90 days, 1-day 180 days (we stay under)
  * option history exists back to ~Dec 2023; symbols NSE-NIFTY-06Oct26-22700-CE; index NSE-NIFTY (CASH)
  * option candles include flat post-close 15:35/15:40 rows → dropped (keep 09:15..15:30)
  * Groww sometimes answers "400 Bad Request" transiently → retried
Options: for each weekly expiry, fetch every strike the ATM could have visited that week
(from daily index high/low) ± `strikes_each_side`, for the days that contract was the nearest expiry.
"""

import math
import time as _time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Protocol

from tradingagent.data.store import MarketStore

MAX_WINDOW_DAYS = {"1minute": 28, "5minute": 28, "15minute": 85, "1day": 170}
SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)


class HistorySource(Protocol):
    def historical_candles(self, segment: str, groww_symbol: str, start: datetime, end: datetime,
                           interval: str) -> list[list[Any]]: ...
    def expiries(self, underlying: str, year: int, month: int) -> list[str]: ...


class FetchAborted(RuntimeError):
    """Raised when continuing is pointless (token expired, network down). Rerun resumes safely."""


FATAL_MARKERS = ("Authentication", "expired or is invalid")      # token gone → stop now
NETWORK_MARKERS = ("ConnectionError", "Max retries exceeded", "NameResolution", "timed out")


@dataclass
class FetchStats:
    requests: int = 0
    candles: int = 0
    skipped_days: int = 0
    errors: int = 0
    contracts: int = 0


def weekdays(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def chunks(days: list[date], max_span: int) -> list[list[date]]:
    """Group sorted days into runs that fit inside one request window."""
    out: list[list[date]] = []
    for d in days:
        if out and (d - out[-1][0]).days < max_span:
            out[-1].append(d)
        else:
            out.append([d])
    return out


def in_session(c: list[Any], interval: str) -> bool:
    if interval == "1day":
        return True
    t = datetime.fromisoformat(str(c[0])[:19]).time()
    return SESSION_OPEN <= t <= SESSION_CLOSE


def option_symbol(underlying: str, expiry: date, strike: int, side: str) -> str:
    return f"NSE-{underlying}-{expiry.strftime('%d%b%y')}-{strike}-{side}"


def strike_range(highs_lows: list[tuple[float, float]], step: int, each_side: int) -> list[int]:
    lo = min(low for _, low in highs_lows)
    hi = max(high for high, _ in highs_lows)
    first = int(math.floor(lo / step) * step) - each_side * step
    last = int(math.ceil(hi / step) * step) + each_side * step
    return list(range(first, last + step, step))


class HistoryDownloader:
    def __init__(self, src: HistorySource, store: MarketStore, last_complete_day: date,
                 log: Callable[[str], None] = print, sleep: Callable[[float], None] = _time.sleep,
                 retries: int = 3) -> None:
        self.src = src
        self.store = store
        self.last_day = last_complete_day
        self.log = log
        self.sleep = sleep
        self.retries = retries
        self.stats = FetchStats()
        self._network_failures = 0  # consecutive symbols that failed with network errors

    def _fetch(self, segment: str, symbol: str, start: datetime, end: datetime,
               interval: str) -> tuple[list[list[Any]], str | None]:
        err = None
        for attempt in range(self.retries):
            self.stats.requests += 1
            try:
                candles = self.src.historical_candles(segment, symbol, start, end, interval)
                self._network_failures = 0
                return candles, None
            except Exception as e:  # transient 400s happen; retry with backoff
                err = f"{type(e).__name__}: {str(e)[:160]}"
                if any(m in err for m in FATAL_MARKERS):
                    msg = f"Groww token expired/invalid — refresh it, then rerun to resume. ({err})"
                    raise FetchAborted(msg) from e
                self.sleep(1.0 * (attempt + 1))
        if err and any(m in err for m in NETWORK_MARKERS):
            self._network_failures += 1
            if self._network_failures >= 3:
                raise FetchAborted(f"network to Groww is down (3 symbols in a row) — rerun to resume. ({err})")
        return [], err

    def download_range(self, segment: str, symbol: str, interval: str, start: date, end: date) -> int:
        end = min(end, self.last_day)
        wanted = weekdays(start, end)
        done = self.store.covered_days(symbol, interval)
        missing = [d for d in wanted if d not in done]
        self.stats.skipped_days += len(wanted) - len(missing)
        added = 0
        for run in chunks(missing, MAX_WINDOW_DAYS[interval]):
            s = datetime.combine(run[0], SESSION_OPEN)
            e = datetime.combine(run[-1], SESSION_CLOSE)
            candles, err = self._fetch(segment, symbol, s, e, interval)
            if err:
                self.stats.errors += 1
                self.store.mark(symbol, interval, run, {}, "error")
                self.log(f"  ERROR {symbol} {interval} {run[0]}..{run[-1]}: {err}")
                continue
            kept = [c for c in candles if in_session(c, interval)]
            added += self.store.upsert_candles(symbol, interval, kept)
            counts: dict[date, int] = {}
            for c in kept:
                d = datetime.fromisoformat(str(c[0])[:19]).date()
                counts[d] = counts.get(d, 0) + 1
            self.store.mark(symbol, interval, run, counts, "ok")
        self.stats.candles += added
        return added

    # ---- index -----------------------------------------------------------------------------------
    def download_index(self, underlying: str, start: date, end: date, interval: str = "1minute") -> None:
        sym = f"NSE-{underlying}"
        self.store.upsert_contract(sym, underlying, "IDX", None, None)
        n1 = self.download_range("CASH", sym, "1day", start - timedelta(days=10), end)
        n2 = self.download_range("CASH", sym, interval, start, end)
        self.log(f"index {sym}: +{n1} daily, +{n2} {interval} candles")

    # ---- options ---------------------------------------------------------------------------------
    def expiry_list(self, underlying: str, start: date, end: date) -> list[date]:
        out: set[date] = set()
        y, m = start.year, start.month
        while (y, m) <= (end.year, end.month):
            self.stats.requests += 1
            for e in self.src.expiries(underlying, y, m):
                out.add(date.fromisoformat(e))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return sorted(e for e in out if start <= e)

    def download_options(self, underlying: str, start: date, end: date, strikes_each_side: int = 5,
                         step: int = 50, interval: str = "1minute") -> None:
        daily = self.store.daily_closes(f"NSE-{underlying}")
        if not daily:
            raise RuntimeError("download the index first (daily candles are needed to choose strikes)")
        exps = self.expiry_list(underlying, start, end + timedelta(days=10))
        prev: date | None = None
        for exp in exps:
            win_start = max(start, (prev + timedelta(days=1)) if prev else exp - timedelta(days=6))
            win_end = min(exp, self.last_day, end)
            prev = exp
            if win_start > win_end:
                continue
            hl = [(v[0], v[1]) for d, v in daily.items() if win_start <= d <= win_end]
            if not hl:
                continue
            strikes = strike_range(hl, step, strikes_each_side)
            before, errors_before = self.stats.candles, self.stats.errors
            for k in strikes:
                for side in ("CE", "PE"):
                    sym = option_symbol(underlying, exp, k, side)
                    self.store.upsert_contract(sym, underlying, side, exp, float(k))
                    self.download_range("FNO", sym, interval, win_start, win_end)
                    self.stats.contracts += 1
            if self.stats.candles > before or self.stats.errors > errors_before:  # quiet for already-stored weeks
                self.log(f"expiry {exp} ({win_start}..{win_end}): {len(strikes)} strikes x2, "
                         f"+{self.stats.candles - before} candles | total req={self.stats.requests} "
                         f"errors={self.stats.errors}")
