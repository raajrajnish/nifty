"""Groww adapter — the only module (with auth.py) that imports growwapi.

Phase 1 scope: READ-ONLY market data. There is deliberately no order method here yet.
Symbol formats and response shapes below were verified live on 2026-09-30:
  get_ltp(("NSE_NIFTY","NSE_INDIAVIX"), CASH) -> {"NSE_NIFTY": 22703.45, ...}
  get_ltp(("NSE_NIFTY26O0622700CE","NSE_NIFTY26OCTFUT"), FNO) -> {...}
  get_quote("NIFTY26O0622700CE", NSE, FNO) -> {..., "depth": {"buy":[{price,quantity}]*5, "sell":[...]}, ...}
  get_option_chain(NSE, "NIFTY", "2026-10-06") -> {"underlying_ltp": x, "strikes": {"22700": {"CE": {..}, "PE": {..}}}}
    (chain has LTP/OI/volume/IV/greeks per strike but NO bid/ask — depth needs get_quote per contract)
  get_expiries(NSE, "NIFTY", year, month) -> {"expiries": ["2026-10-06", ...]}
"""

import threading
import time
from datetime import datetime
from typing import Any

import pandas as pd

from tradingagent.core.errors import BrokerRateLimited, BrokerUnavailable


class _RateLimiter:
    """Simple token bucket shared by all calls (Groww limits not yet documented here — keep conservative)."""

    def __init__(self, per_second: float) -> None:
        self._interval = 1.0 / per_second
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next - now
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            time.sleep(delay)


class GrowwMarketData:
    """Read-only market data. Construct with a verified access token from broker.auth.GrowwAuth."""

    def __init__(self, token: str, max_requests_per_second: float = 4.0, timeout_s: int = 5) -> None:
        from growwapi import GrowwAPI

        self._g = GrowwAPI(token)
        self._limit = _RateLimiter(max_requests_per_second)
        self._timeout = timeout_s

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        self._limit.wait()
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            name = type(e).__name__
            if "RateLimit" in name or "429" in str(e):
                raise BrokerRateLimited(f"{name}: {str(e)[:200]}") from e
            raise BrokerUnavailable(f"{name}: {str(e)[:200]}") from e

    def ltp(self, symbols: tuple[str, ...], segment: str) -> dict[str, float]:
        seg = self._g.SEGMENT_CASH if segment == "CASH" else self._g.SEGMENT_FNO
        return dict(self._call(self._g.get_ltp, exchange_trading_symbols=symbols, segment=seg, timeout=self._timeout))

    def quote_fno(self, trading_symbol: str) -> dict[str, Any]:
        return dict(self._call(self._g.get_quote, trading_symbol=trading_symbol, exchange=self._g.EXCHANGE_NSE,
                               segment=self._g.SEGMENT_FNO, timeout=self._timeout))

    def option_chain(self, underlying: str, expiry: str) -> dict[str, Any]:
        return dict(self._call(self._g.get_option_chain, exchange=self._g.EXCHANGE_NSE, underlying=underlying,
                               expiry_date=expiry, timeout=self._timeout))

    def expiries(self, underlying: str, year: int, month: int) -> list[str]:
        r = self._call(self._g.get_expiries, exchange=self._g.EXCHANGE_NSE, underlying_symbol=underlying,
                       year=year, month=month, timeout=self._timeout)
        return list(r.get("expiries") or [])

    def historical_candles(self, segment: str, groww_symbol: str, start: datetime, end: datetime,
                           interval: str) -> list[list[Any]]:
        """[iso_ts, open, high, low, close, volume, oi] rows. Max window: 1/5-min 30d, 15-min 90d, 1-day 180d."""
        seg = self._g.SEGMENT_CASH if segment == "CASH" else self._g.SEGMENT_FNO
        r = self._call(self._g.get_historical_candles, exchange=self._g.EXCHANGE_NSE, segment=seg,
                       groww_symbol=groww_symbol, start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
                       end_time=end.strftime("%Y-%m-%d %H:%M:%S"), candle_interval=interval, timeout=30)
        return list((r or {}).get("candles") or [])

    def instruments(self) -> pd.DataFrame:
        df: pd.DataFrame = self._call(self._g.get_all_instruments)
        return df
