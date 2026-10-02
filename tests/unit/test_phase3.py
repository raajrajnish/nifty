from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd
import pytest

from tradingagent.sim.phase3 import (
    Leg,
    close_before,
    hold_leg,
    p1_ratio,
    p1_signals,
    p2_breakout,
    p3_signal,
    p4_rel,
    p4_signals,
    passes,
    weekdays_incl,
)

D = date(2025, 1, 6)


def bars(prices, start=time(9, 15), d=D):
    t0 = datetime.combine(d, start)
    p = list(prices)
    return pd.DataFrame({"ts": [pd.Timestamp(t0 + timedelta(minutes=i)) for i in range(len(p))],
                         "open": p, "high": [x + 0.5 for x in p], "low": [x - 0.5 for x in p], "close": p})


def test_close_before_uses_the_bar_that_ends_at_the_label():
    g = bars(range(100, 400))           # 09:15 → 100, so 09:59 → 144
    assert close_before(g, time(10, 0)) == 144
    assert close_before(g, time(9, 15)) is None


def test_hold_leg_entry_open_exit_1510_close_and_late_fill_rejected():
    opt = bars(range(10, 400))
    leg = hold_leg(opt, datetime.combine(D, time(9, 30)))
    assert leg == Leg(25, 10 + 355)     # 09:30 is bar 15; 15:10 is bar 355
    assert hold_leg(opt[opt["ts"].dt.time >= time(9, 40)], datetime.combine(D, time(9, 30))) is None


def test_p1_ratio_and_signal_is_past_only():
    assert p1_ratio(100, 200, 4) == pytest.approx(1.0)      # IDM = 200/√4 = 100
    assert weekdays_incl(date(2025, 1, 3), date(2025, 1, 7)) == 3  # Fri, Mon, Tue
    r = pd.Series(np.r_[np.ones(40), 5.0, 1.0])
    s = p1_signals(r)
    assert not s.iloc[:40].any() and bool(s.iloc[40]) and not bool(s.iloc[41])
    assert not p1_signals(pd.Series(np.r_[np.ones(10), 5.0])).any()   # < 30 days of history → no signal


def test_p2_breakout_first_bar_after_1300():
    p = [100.0] * 225 + [100.0] * 10 + [110.0] * 50     # 09:15–12:59 flat, 13:10 jumps above range
    g = bars(p)
    ts, side, c, hi, lo = p2_breakout(g)
    assert side == "CE" and c == 110.0 and hi == 100.5 and ts.time() == time(13, 15)


def test_p3_signal_needs_vix_up_and_index_flat():
    n = bars([100.0] * 300)
    v = bars([10.0] * 60 + [10.4] * 240)        # +4% from 10:15 on
    assert p3_signal(n, v) == time(10, 20)       # first label whose previous minute (10:19) shows it
    n_moving = bars([100.0] * 60 + [101.0] * 240)  # index +1% → not "flat"
    assert p3_signal(n_moving, v) is None


def test_p4_rel_and_signal():
    n, b = bars([100.0] * 300), bars([200.0] * 44 + [202.0] * 256)  # 09:59 bar already 202
    rel = p4_rel(n, b)
    assert rel[time(10, 0)] == pytest.approx(np.log(1.01))
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(41)]
    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(0, 0.001, (41, 2)), index=days, columns=[time(10, 0), time(10, 5)])
    df.iloc[40] = [0.0, -0.01]              # 10× SD on the last day, at 10:05
    sig = p4_signals(df)
    assert days[40] in sig and sig[days[40]][:2] == (time(10, 5), -1)
    assert all(d not in sig for d in days[:30])   # warm-up: < 30 past days → no signal


def test_passes_requires_every_condition():
    s = {"n": 80, "net": 100.0, "net_2x": 10.0, "P(<=0)": 0.01, "control_net": 50.0}
    assert passes(s, 60, 0.05)
    assert not passes({**s, "net_2x": -1.0}, 60, 0.05)
    assert not passes({**s, "control_net": 150.0}, 60, 0.05)
    assert not passes(s, 60, 0.005)
    assert not passes({**s, "n": 10}, 60, 0.05)
