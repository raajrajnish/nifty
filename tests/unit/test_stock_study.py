import math
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from tradingagent.sim.stock_study import (
    EquityIntradayCosts,
    Signal,
    adjust_splits,
    simulate,
    st3_intraday_momentum,
)

D = date(2025, 3, 5)


def bars(day, closes, t0=(9, 15)):
    start = datetime(day.year, day.month, day.day, *t0)
    return pd.DataFrame([{"ts": pd.Timestamp(start + timedelta(minutes=k)), "open": c, "high": c, "low": c,
                          "close": c, "volume": 1} for k, c in enumerate(closes)])


def test_costs_by_hand():
    c = EquityIntradayCosts()
    # ₹1L buy and sell: brokerage capped 20+20; STT 25; exch 5.94; SEBI 0.2; stamp 3; GST 18% of 46.14
    assert c.round_trip(100_000, 100_000) == pytest.approx(40 + 25 + 5.94 + 0.2 + 3 + 0.18 * 46.14, abs=1e-6)
    assert c.round_trip(10_000, 10_000) == pytest.approx(20 + 2.5 + 0.594 + 0.02 + 0.3 + 0.18 * 20.614, abs=1e-6)


def test_split_is_detected_and_back_adjusted():
    d1, d2 = date(2025, 6, 13), date(2025, 6, 16)
    m1 = pd.concat([bars(d1, [1000.0] * 5), bars(d2, [502.0] * 5)], ignore_index=True)   # 1:1 bonus → ratio 2
    adj, events, excl = adjust_splits(m1)
    assert events == [{"day": d2, "ratio": 2.0, "raw_ratio": 1.992}]
    assert excl == {d2} and adj[adj["day"] == d1]["close"].iloc[0] == 500.0


def test_st3_long_at_1415_with_half_atr_stop():
    g = bars(D, [101.0] * 400)                       # +1% vs previous close 100 at 09:45
    row = pd.Series({"prev_close": 100.0, "atr": 4.0}, name=D)
    s = st3_intraday_momentum(g, row, None)
    assert s.side == 1 and s.ts == datetime(2025, 3, 5, 14, 15) and s.lo == 99.0 and s.hi == math.inf
    flat = bars(D, [100.3] * 400)                    # +0.3% → no trade
    assert st3_intraday_momentum(flat, row, None) is None


def test_simulate_short_range_exit_and_costs():
    closes = [100.0] * 20 + [99.0] * 10 + [101.5] * 400   # short at 09:35 open; 5-min close above hi at 09:49
    g = bars(D, closes)
    sig = Signal(D, datetime(2025, 3, 5, 9, 35), -1, 101.0, 99.5, "range")
    tr = simulate(sig, g, EquityIntradayCosts())
    assert tr["reason"] == "OPPOSITE_SIDE" and tr["side"] == "SHORT"
    assert tr["entry_ts"] == pd.Timestamp(2025, 3, 5, 9, 35)
    assert tr["gross"] == pytest.approx((tr["entry"] - tr["exit"]) * tr["qty"])
    assert tr["net"] == pytest.approx(tr["gross"] - tr["cost"])


def test_bad_x100_prints_are_repaired_and_day_flagged():
    from tradingagent.sim.stock_study import clean_bad_prints
    g = bars(D, [794.0, 794.2, 79415.0, 79360.0, 794.1])
    out, bad = clean_bad_prints(g)
    assert bad == {D} and out["close"].tolist() == pytest.approx([794.0, 794.2, 794.15, 793.6, 794.1])
    ok, none = clean_bad_prints(bars(D, [794.0, 830.0, 790.0]))     # a real 4.5% move is untouched
    assert none == set() and ok["close"].tolist() == [794.0, 830.0, 790.0]
