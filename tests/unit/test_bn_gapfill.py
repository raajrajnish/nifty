from datetime import date, datetime, timedelta

import pandas as pd

from tradingagent.sim.bn_gapfill import confirmed_fade, open_fade, rule_fill_1m, rule_fill_5m
from tradingagent.sim.exit_study import State

T915 = datetime(2025, 3, 5, 9, 15)
C = {"day": date(2025, 3, 5), "expiry": date(2025, 3, 27), "prev_close": 48000.0}


def day(closes, highs=None, lows=None, opens=None):
    return pd.DataFrame([{"ts": pd.Timestamp(T915 + timedelta(minutes=k)), "open": (opens or closes)[k],
                          "high": (highs or closes)[k], "low": (lows or closes)[k], "close": c}
                         for k, c in enumerate(closes)])


def test_gf1_gap_up_buys_put_with_target_and_stop():
    # open 48,200 = +0.417% gap; target 48,000; stop 48,400 (gap doubles away)
    g = day([48200.0] * 5 + [48180.0] * 300)
    e = open_fade(0.2, 1.0)(g, C)
    assert e.side == "PE" and e.signal_ts == datetime(2025, 3, 5, 9, 20) and e.strike == 48200
    assert (e.or_low, e.or_high) == (48000.0, 48400.0)
    assert open_fade(0.2, 0.3)(g, C) is None                         # outside the bucket
    small = day([48050.0] * 300)                                      # +0.10% gap → no trade
    assert open_fade(0.2, 1.0)(small, C) is None


def test_gf1_skips_if_already_filled():
    g = day([48200.0, 48100.0, 47990.0, 48100.0, 48150.0] + [48150.0] * 300,
            lows=[48200.0, 48100.0, 47990.0, 48100.0, 48150.0] + [48150.0] * 300)
    assert open_fade(0.2, 1.0)(g, C) is None


def test_gf2_needs_first_15_min_turn_towards_fill():
    closes = [48200.0] * 14 + [48150.0] + [48150.0] * 300           # 09:29 close below the open
    highs = [48230.0] + [48200.0] * 13 + [48150.0] + [48150.0] * 300
    e = confirmed_fade(day(closes, highs), C)
    assert e.side == "PE" and e.signal_ts == datetime(2025, 3, 5, 9, 30) and e.or_high == 48230.0
    up = [48200.0] * 14 + [48250.0] + [48250.0] * 300                # still moving away → no trade
    assert confirmed_fade(day(up), C) is None


def test_exit_rules():
    st = State(entry_px=600.0, risk=180.0, peak_close=600.0)
    e = open_fade(0.2, 1.0)(day([48200.0] * 5 + [48180.0] * 300), C)  # PE: target 48,000, stop 48,400
    bar = lambda m, c: pd.Series({"ts": datetime(2025, 3, 5, 10, m), "close": c})  # noqa: E731
    assert rule_fill_1m(st, pd.Series(), bar(1, 48000.0), e) == "GAP_FILLED"
    assert rule_fill_1m(st, pd.Series(), bar(1, 48400.0), e) == "INDEX_SL"
    assert rule_fill_5m(st, pd.Series(), bar(1, 48400.0), e) is None    # not a 5-min close
    assert rule_fill_5m(st, pd.Series(), bar(4, 48400.0), e) == "INDEX_SL"
