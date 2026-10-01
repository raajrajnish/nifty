"""Phase 0 demo feed: synthetic 5-min Nifty candles so the dashboard can be exercised without Groww.

Every event carries demo=True and the UI shows a DEMO DATA banner. Never used for decisions.
"""

import asyncio
import random
from datetime import datetime, timedelta

from tradingagent.core.clock import IST
from tradingagent.core.events import EventBus


def synthetic_candles(start_price: float, n: int, seed: int = 7) -> list[dict[str, float | int]]:
    rng = random.Random(seed)  # noqa: S311 — not security relevant
    t0 = datetime.now(IST).replace(hour=9, minute=15, second=0, microsecond=0)
    out: list[dict[str, float | int]] = []
    price = start_price
    for i in range(n):
        o = price
        c = o + rng.gauss(0, 12)
        h = max(o, c) + abs(rng.gauss(0, 6))
        low = min(o, c) - abs(rng.gauss(0, 6))
        out.append({"time": int((t0 + timedelta(minutes=5 * i)).timestamp()),
                    "open": round(o, 2), "high": round(h, 2), "low": round(low, 2), "close": round(c, 2)})
        price = c
    return out


async def run_demo_feed(bus: EventBus, interval_s: float = 3.0) -> None:
    candles = synthetic_candles(24300.0, 200)
    for i, c in enumerate(candles):
        bus.publish("CANDLE", datetime.now(IST), {"demo": True, "symbol": "NIFTY", "tf": "5m", "candle": c})
        if i == 3:
            bus.publish("DECISION", datetime.now(IST), {
                "demo": True, "action": "NO_TRADE",
                "no_trade_reason": "DEMO: no setup from 03_setups.md present (sample text)"})
        await asyncio.sleep(interval_s)
