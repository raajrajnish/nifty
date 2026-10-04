from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tradingagent.sim.exit_study import Entry, State, rule_none, simulate
from tradingagent.sim.round2 import short_straddle_path
from tradingagent.tournament.exits import straddle_variant, swing_reexit, wrap_option

D = date(2025, 3, 5)


def bars(prices, t0=datetime(2025, 3, 5, 10, 0)):
    return pd.DataFrame([{"ts": pd.Timestamp(t0 + timedelta(minutes=k)), "open": p, "high": p, "low": p, "close": p}
                         for k, p in enumerate(prices)])


def test_option_x1_x2_arm_only_after_plus_50pct():
    st = State(entry_px=100.0, risk=30.0, peak_close=140.0, stop=50.0)
    e = Entry(D, datetime(2025, 3, 5, 10), "CE", 22000, date(2025, 3, 6), np.nan, np.nan)
    wrap_option(rule_none, "X1")(st, pd.Series(), pd.Series({"close": 1.0}), e)
    assert st.stop == 50.0                                   # +40%: not armed, frozen rule unchanged
    st.peak_close = 160.0
    wrap_option(rule_none, "X1")(st, pd.Series(), pd.Series({"close": 1.0}), e)
    assert st.stop == 100.0                                  # breakeven
    wrap_option(rule_none, "X2")(st, pd.Series(), pd.Series({"close": 1.0}), e)
    assert st.stop == 130.0                                  # keep half of +60


def test_option_x1_exits_at_breakeven_after_spike_and_fade():
    path = [100.0] * 3 + [160.0] * 3 + [90.0] * 200          # +60% then collapses below entry
    opt, idx = bars(path), bars([22000.0] * len(path))
    e = Entry(D, datetime(2025, 3, 5, 10), "CE", 22000, date(2025, 3, 6), np.nan, np.nan)
    base = simulate(e, opt, idx, wrap_option(rule_none, "BASE"), stop_pct=0.5)
    x1 = simulate(e, opt, idx, wrap_option(rule_none, "X1"), stop_pct=0.5)
    assert base["reason"] in ("EOD", "DATA_END") and base["pts"] < 0
    assert x1["reason"] == "BREAKEVEN_STOP" and x1["exit_px"] == pytest.approx(90.0 * (1 - 0.0011))  # gap: open < stop


def test_straddle_base_matches_round2_and_x1_locks():
    t0 = datetime(2025, 3, 6, 13, 30)
    n = 100
    ce = bars([50.0] * 10 + [10.0] * 10 + [70.0] * (n - 20), t0)    # value 100 → 40 (≤ 50%: armed) → 110
    pe = bars([50.0] * 10 + [30.0] * 10 + [40.0] * (n - 20), t0)
    assert straddle_variant(ce, pe, "BASE") == short_straddle_path(ce, pe) == (100.0, 110.0, "EOD_1510")
    credit, back, reason = straddle_variant(ce, pe, "X1")            # 110 ≥ credit 100 → buy back next open
    assert (credit, back, reason) == (100.0, 110.0, "LOCK_X1")
    credit, back, reason = straddle_variant(ce, pe, "X2")            # low 40 → trigger 40 + 30 = 70 → hit at 110
    assert reason == "LOCK_X2"
    calm = bars([50.0] * 10 + [20.0] * (n - 10), t0)                 # value 70 at worst: never armed
    assert straddle_variant(calm, pe, "X1")[2] == "EOD_1510"


def test_swing_reexit_x1_and_x2():
    closes = [100.0, 104.0, 102.0, 99.0, 99.0, 99.0]           # +4% then below entry
    d = pd.DataFrame({"open": [100.0] * 6, "close": closes, "high": closes, "low": closes})
    never = lambda r, e, a, h: None  # noqa: E731
    assert swing_reexit(d, 0, 2.0, never, "BASE") == (5, "DATA_END")
    assert swing_reexit(d, 0, 2.0, never, "X1") == (3, "LOCK_X1")      # armed at +3%, close < entry on day 3
    assert swing_reexit(d, 0, 2.0, never, "X2") == (5, "DATA_END")     # never reached +5%: not armed
