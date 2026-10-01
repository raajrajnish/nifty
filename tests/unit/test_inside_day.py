from datetime import date, datetime, timedelta

import pandas as pd

from tradingagent.sim.exit_study import Entry, State
from tradingagent.sim.inside_day_study import (
    n1_rejection,
    n2_acceptance,
    n3_quiet_expansion,
    n4_gap_fill,
    rule_gap_fill,
    rule_level_back,
)

T915 = datetime(2022, 5, 11, 9, 15)
C = {"day": date(2022, 5, 11), "expiry": date(2022, 5, 12), "pdh": 16100.0, "pdl": 16000.0,
     "prev_close": 16050.0, "atr_pts": 200.0, "step": 50}


def at(h, m):
    return datetime(2022, 5, 11, h, m)


def day(closes, highs=None, lows=None, opens=None):
    return pd.DataFrame([{"ts": pd.Timestamp(T915 + timedelta(minutes=k)), "open": (opens or closes)[k],
                          "high": (highs or closes)[k], "low": (lows or closes)[k], "close": c}
                         for k, c in enumerate(closes)])


def test_n1_rejection_at_pdh_gives_put():
    closes = [16080.0] * 20 + [16090.0] * 300
    highs = [16080.0] * 20 + [16102.0] + [16090.0] * 299        # 09:35 minute pokes above PDH, closes below
    e = n1_rejection(day(closes, highs), C)
    assert e.side == "PE" and e.signal_ts == at(9, 40) and e.or_high == 16100.0


def test_n2_needs_three_closes_beyond():
    closes = [16080.0] * 15 + [16110.0] * 300                   # first close above PDH: bar ending 09:35
    e = n2_acceptance(day(closes), C)
    assert e.side == "CE" and e.signal_ts == at(9, 45) and e.or_low == 16100.0   # 09:35, 09:40, 09:45
    blip = [16080.0] * 15 + [16110.0] * 10 + [16090.0] * 300   # only two closes above
    assert n2_acceptance(day(blip), C) is None


def test_n3_quiet_first_hour_then_break():
    closes = [16050.0] * 60 + [16070.0] * 200
    highs = [16060.0] + [16050.0] * 59 + [16070.0] * 200        # first-hour range 20 pts < 0.25 × 200
    lows = [16040.0] + [16050.0] * 59 + [16070.0] * 200
    e = n3_quiet_expansion(day(closes, highs, lows), C)
    assert e.side == "CE" and e.signal_ts == at(10, 20)
    assert n3_quiet_expansion(day(closes, highs, lows), {**C, "atr_pts": 60.0}) is None   # 20 ≥ 15 → not quiet


def test_n4_gap_up_fill_and_wrong_way_break():
    opens = [16095.0] + [16085.0] * 400                         # +0.28% gap from 16050 (≥ 0.25%), inside range
    closes = [16085.0] * 15 + [16070.0] * 300                   # 09:30–09:34 bar closes below OR low 16080
    highs = [16095.0] + [16085.0] * 14 + [16070.0] * 300
    lows = [16080.0] + [16085.0] * 14 + [16070.0] * 300
    e = n4_gap_fill(day(closes, highs, lows, opens), C)
    assert e.side == "PE" and e.signal_ts == at(9, 35) and e.or_low == 16050.0 and e.or_high == 16095.0
    up = [16085.0] * 15 + [16100.0] * 300                       # breaks above the OR first → no setup
    assert n4_gap_fill(day(up, highs[:15] + up[15:], lows[:15] + up[15:], opens), C) is None
    small = [16080.0] + [16085.0] * 400                         # +0.19% gap → too small
    assert n4_gap_fill(day(closes, highs, lows, small), C) is None


def test_exit_rules():
    st = State(entry_px=100.0, risk=30.0, peak_close=100.0)
    pe = Entry(C["day"], T915, "PE", 16050, C["expiry"], 16100.0, 16050.0)
    assert rule_gap_fill(st, pd.Series(), pd.Series({"ts": at(10, 1), "close": 16049.0}), pe) == "GAP_FILLED"
    assert rule_gap_fill(st, pd.Series(), pd.Series({"ts": at(10, 1), "close": 16120.0}), pe) is None   # not 5-min
    assert rule_gap_fill(st, pd.Series(), pd.Series({"ts": at(10, 4), "close": 16120.0}), pe) == "OR_OPPOSITE_SIDE"
    lv = Entry(C["day"], T915, "PE", 16050, C["expiry"], 16100.0, float("nan"))
    assert rule_level_back(st, pd.Series(), pd.Series({"ts": at(10, 4), "close": 16101.0}), lv) == "LEVEL_BACK"
