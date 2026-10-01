"""Single injectable clock (MASTER_PLAN §8: all timers use one clock, real or replay)."""

import asyncio
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


class Clock(Protocol):
    def now(self) -> datetime: ...
    async def sleep_until(self, t: datetime) -> None: ...


class WallClock:
    def now(self) -> datetime:
        return datetime.now(IST)

    async def sleep_until(self, t: datetime) -> None:
        delay = (t - self.now()).total_seconds()
        if delay > 0:
            await asyncio.sleep(delay)


class SimClock:
    """Manually advanced clock for BACKTEST/REPLAY and tests. Never reads the wall clock."""

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("SimClock requires a tz-aware datetime")
        self._now = start.astimezone(IST)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("clock cannot go backwards")
        self._now += delta

    async def sleep_until(self, t: datetime) -> None:
        if t > self._now:
            self._now = t.astimezone(IST)
