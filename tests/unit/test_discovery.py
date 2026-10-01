from datetime import date, datetime, timedelta

import pandas as pd

from tradingagent.sim.discovery_study import (
    follow,
    h1_failed_breakout,
    h2_prev_level_breakout,
    h3_afternoon_continuation,
    h4_opening_drive,
    summarize_a,
)

D = date(2022, 3, 9)
T915 = datetime(2022, 3, 9, 9, 15)
CTX = {"day": D, "expiry": date(2022, 3, 10), "pdh": 17000.0, "pdl": 16800.0, "open_outside": False,
       "narrow_or": True, "low_vol": True, "atr_pts": 200.0}


def day(closes, opens=None):
    return pd.DataFrame([{"ts": T915 + timedelta(minutes=k), "open": (opens or closes)[k], "high": c, "low": c,
                          "close": c} for k, c in enumerate(closes)])


OR = [16900.0 + (k % 3) * 10 for k in range(15)]  # OR 16900–16920


def test_h1_trades_the_opposite_side_after_a_failed_breakout():
    # up-break (bar ending 09:35), back inside, then the 09:45–09:49 bar closes below the OR low → signal 09:50
    path = OR + [16930.0] * 5 + [16910.0] * 10 + [16890.0] * 300
    e = h1_failed_breakout(day(path), CTX)
    assert e is not None and e.side == "PE" and e.signal_ts == datetime(2022, 3, 9, 9, 50)
    assert e.or_high == 16920.0  # thesis-wrong exit: back above the original breakout side


def test_h2_needs_inside_open_and_breaks_yesterdays_high():
    path = OR + [16950.0] * 10 + [17010.0] * 300
    e = h2_prev_level_breakout(day(path), CTX)
    assert e.side == "CE" and e.or_low == 16900.0  # exit below yesterday's midpoint (16900)
    assert h2_prev_level_breakout(day(path), {**CTX, "open_outside": True}) is None


def test_h3_afternoon_continuation_requires_late_high_above_twap():
    path = [16900.0 + k * 0.5 for k in range(300)]  # steady rise → close > TWAP, high made just before 13:00
    e = h3_afternoon_continuation(day(path), CTX)
    assert e.side == "CE" and e.signal_ts == datetime(2022, 3, 9, 13, 0)
    flat_then_old_high = [17000.0] * 30 + [16950.0] * 270  # high made at 09:15 → no continuation
    assert h3_afternoon_continuation(day(flat_then_old_high), CTX) is None


def test_h4_only_on_outside_wide_days_with_a_decisive_drive():
    ctx = {**CTX, "open_outside": True, "narrow_or": False}
    drive = [16900.0 + k * 3 for k in range(15)] + [16960.0] * 50  # +42 pts vs OR width 42 → decisive
    e = h4_opening_drive(day(drive), ctx)
    assert e.side == "CE" and e.signal_ts == datetime(2022, 3, 9, 9, 30)
    assert h4_opening_drive(day(drive), {**ctx, "narrow_or": True}) is None  # G1 territory — left to G1


def test_follow_measures_from_entry_open_in_atr_units():
    g = day([100.0] * 20 + [140.0] * 400, opens=[100.0] * 420)
    assert follow(g, T915 + timedelta(minutes=10), "CE", 60, 20.0) == 2.0
    assert follow(g, T915 + timedelta(minutes=10), "PE", 60, 20.0) == -2.0


def test_stage_a_pass_rule():
    rows = [{"setup": "H9", "day": D, "side": "CE", "follow_60": 0.2 if i % 10 < 6 else -0.1,
             "follow_eod": 0.3 if i % 10 < 6 else -0.1} for i in range(100)]
    rows += [{"setup": "RANDOM", "day": D, "side": "CE", "follow_60": 0.1 if i % 2 else -0.1,
              "follow_eod": 0.0} for i in range(100)]
    s = summarize_a(pd.DataFrame(rows)).set_index("setup")
    assert bool(s.loc["H9", "PASS_A"]) is True and s.loc["H9", "right_dir_60%"] == 60.0
