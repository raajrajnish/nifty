from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from tradingagent.sim.exit_study import (
    HALF_SPREAD_PCT,
    Entry,
    orb_signal,
    rule_breakeven,
    rule_giveback,
    rule_none,
    rule_thesis,
    simulate,
)

D = date(2026, 9, 28)
T0 = datetime(2026, 9, 28, 10, 0)
E = Entry(D, T0, "CE", 22700, date(2026, 10, 6), or_high=22720.0, or_low=22650.0)


def bars(prices, start=T0, lows=None, highs=None):
    rows = []
    for k, p in enumerate(prices):
        lo = lows[k] if lows else p
        hi = highs[k] if highs else p
        rows.append({"ts": start + timedelta(minutes=k), "open": p, "high": max(p, hi), "low": min(p, lo), "close": p})
    return pd.DataFrame(rows)


def idx_bars(n, close=22730.0):
    return bars([close] * n)


def test_hard_stop_fires_on_low_and_is_pessimistic():
    opt = bars([100, 100, 100, 100], lows=[100, 100, 60, 100])  # dips through the 30% stop in minute 2
    t = simulate(E, opt, idx_bars(4), rule_none)
    entry = 100 * (1 + HALF_SPREAD_PCT)
    assert t["reason"] == "STOP"
    assert t["exit_px"] == pytest.approx((entry - 0.3 * entry) * (1 - HALF_SPREAD_PCT))
    assert t["r"] < -1.0  # spread on the exit makes a stop slightly worse than −1R


def test_gap_through_stop_fills_at_open_not_at_stop():
    opt = bars([100, 100, 50, 50])  # opens at 50, far below the stop
    t = simulate(E, opt, idx_bars(4), rule_none)
    assert t["exit_px"] == pytest.approx(50 * (1 - HALF_SPREAD_PCT))


def test_close_based_rule_fills_next_open():
    path = [100, 120, 140, 110, 105, 104]  # peak close 140 → lock70 triggers when close ≤ 100.1+0.7*39.9
    t = simulate(E, bars(path), idx_bars(len(path)), rule_giveback(0.7, activate_r=1.0))
    assert t["reason"] == "LOCK70"
    assert t["exit_ts"] == T0 + timedelta(minutes=4)  # fired on 110 close (min 3), filled at min-4 open
    assert t["exit_px"] == pytest.approx(105 * (1 - HALF_SPREAD_PCT))


def test_breakeven_raises_stop_after_1r():
    path = [100, 135, 101, 100]
    lows = [100, 135, 99, 100]
    t = simulate(E, bars(path, lows=lows), idx_bars(4), rule_breakeven(1.0))
    assert t["reason"] == "BREAKEVEN_STOP" and t["r"] > -0.1


def test_thesis_exit_on_index_back_below_or_mid():
    idx = bars([22730, 22730, 22600, 22600])  # OR mid = 22685
    t = simulate(E, bars([100, 101, 102, 103]), idx, rule_thesis)
    assert t["reason"] == "THESIS" and t["exit_ts"] == T0 + timedelta(minutes=3)


def test_orb_signal_and_expiry_day_skip():
    start = datetime(2026, 9, 28, 9, 15)
    closes = [22700 + (k % 3) for k in range(15)] + [22701] * 10 + [22760] * 30  # OR 22700–22702; breaks 09:40+
    idx = bars(closes, start=start)
    e = orb_signal(idx, [date(2026, 9, 29), date(2026, 10, 6)])
    assert e and e.side == "CE" and e.expiry == date(2026, 9, 29) and e.strike == 22750
    assert e.signal_ts == datetime(2026, 9, 28, 9, 45)  # 5-min bar 09:40–09:44 closes above → label 09:45
    assert orb_signal(idx, [date(2026, 9, 28)]) is None  # today is an expiry → no trade
