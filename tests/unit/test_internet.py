from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from tradingagent.sim.exit_study import Entry, State
from tradingagent.sim.internet_study import (
    fib_outcome,
    p1_inside_15m,
    p2_first5_30min,
    p3_fib44,
    p4_bn920,
    p6_window,
    rule_fib,
    rule_p4,
    rule_p6,
)

D = date(2022, 5, 11)
T915 = datetime(2022, 5, 11, 9, 15)
C = {"day": D, "expiry": date(2022, 5, 12), "prev_close": 16040.0}


def at(h, m):
    return datetime(2022, 5, 11, h, m)


def day(closes, highs=None, lows=None):
    return pd.DataFrame([{"ts": pd.Timestamp(T915 + timedelta(minutes=k)), "open": c, "high": (highs or closes)[k],
                          "low": (lows or closes)[k], "close": c} for k, c in enumerate(closes)])


def test_p1_inside_15m_needs_five_inside_candles_then_close_break():
    closes = [16050.0] * 90 + [16110.0] * 200               # 09:15–10:44 inside, 10:45 bar closes above
    highs = [16100.0] + [16050.0] * 89 + [16110.0] * 200
    lows = [16000.0] + [16050.0] * 89 + [16110.0] * 200
    e = p1_inside_15m(day(closes, highs, lows), C)
    assert e.side == "CE" and e.signal_ts == at(10, 46) and (e.or_high, e.or_low) == (16100.0, 16000.0)
    touched = list(highs)
    touched[50] = 16100.0                                     # 10:05 touches the high → not strictly inside
    assert p1_inside_15m(day(closes, touched, lows), C) is None
    assert p1_inside_15m(day(closes, highs, lows), {**C, "prev_close": 15880.0}) is None   # 170-pt gap


def test_p2_first_5min_break_only_in_first_30_minutes():
    closes = [16050.0] * 5 + [16055.0, 16061.0] + [16061.0] * 100
    highs = [16060.0] + [16050.0] * 4 + [16055.0, 16061.0] + [16061.0] * 100
    lows = [16040.0] + [16050.0] * 4 + [16055.0, 16061.0] + [16061.0] * 100
    e = p2_first5_30min(day(closes, highs, lows), C)
    assert e.side == "CE" and e.signal_ts == at(9, 22)       # 09:21 bar closes 16061 > 16060
    late = [16050.0] * 31 + [16061.0] * 100                   # first close beyond at 09:46 → outside window
    assert p2_first5_30min(day(late, highs[:5] + late[5:], lows[:5] + late[5:]), C) is None


def test_p4_stop_is_opposite_side_but_at_least_35_points():
    closes = [16050.0] * 5 + [16055.0, 16061.0] + [16061.0] * 100
    highs = [16060.0] + [16050.0] * 4 + [16055.0, 16061.0] + [16061.0] * 100
    lows = [16040.0] + [16050.0] * 4 + [16055.0, 16061.0] + [16061.0] * 100
    e = p4_bn920(day(closes, highs, lows), C)
    assert e.side == "CE" and e.or_low == 16061.0 - 35.0    # candle low 16040 is only 21 pts away
    assert p4_bn920(day(closes, highs, lows), {**C, "prev_close": 16250.0}) is None   # gap filter


def test_p3_fib44_entry_and_frozen_levels():
    path = [16050.0] * 5 + [16100.0] + [16000.0] * 19 + [16030.0] * 5 + [16050.0] * 100
    e = p3_fib44(day(path), C)
    assert e.side == "CE" and e.signal_ts == at(9, 50)       # 09:49 close 16050 crosses 16044
    assert e.or_low == pytest.approx(16022.0) and e.or_high == pytest.approx(16077.0)   # 0.22 / 0.77
    shallow = [16050.0] * 5 + [16100.0] + [16030.0] * 19 + [16060.0] * 100   # only 70-pt fall
    assert p3_fib44(day(shallow), C) is None


def test_p6_window_buy_setup():
    closes = [16100.0, 16105.0] + [16105.0] * 50
    highs = [16110.0, 16111.0] + [16105.0] * 50             # 16110 is 10 pts above 16100 → buy setup
    lows = [16080.0, 16100.0] + [16105.0] * 50              # 16080 is 30 below 16100 → no sell setup
    e = p6_window(day(closes, highs, lows), C)
    assert e.side == "CE" and e.signal_ts == at(9, 17) and e.or_low == 16111.0 - 40.0
    highs2 = [16120.0, 16125.0] + [16105.0] * 50            # 20 pts above round → outside 15-pt window
    assert p6_window(day(closes, highs2, lows), C) is None


def _st():
    return State(entry_px=100.0, risk=30.0, peak_close=100.0)


def _ce(lo=16000.0, hi=float("nan")):
    return Entry(D, T915, "CE", 16000, date(2022, 5, 12), hi, lo)


def test_exit_rules():
    s = _st()
    s.minutes = 20
    i = pd.Series({"ts": at(10, 0), "close": 16050.0, "high": 16051.0, "low": 16049.0})
    assert rule_p4(s, pd.Series({"close": 99.0}), i, _ce()) == "STAGNANT"
    assert rule_p4(s, pd.Series({"close": 99.0}), i, _ce()) is None          # checked once only
    assert rule_fib(_st(), pd.Series(), pd.Series({"close": 16000.0}), _ce(16000.0, 16100.0)) == "FIB_SL"
    assert rule_fib(_st(), pd.Series(), pd.Series({"close": 16100.0}), _ce(16000.0, 16100.0)) == "FIB_T1"
    s6 = _st()
    assert rule_p6(s6, pd.Series(), i, _ce()) is None                         # stores previous bar
    assert rule_p6(s6, pd.Series(), pd.Series({"close": 16048.0, "high": 16049.0, "low": 16047.0}), _ce()) == "TRAIL"


def test_fib_outcome_first_touch():
    g = day([16050.0, 16080.0, 16010.0, 16200.0])
    e = Entry(D, T915, "CE", 16050, date(2022, 5, 12), 16077.0, 16020.0)
    assert fib_outcome(g, e, {"T1": 16077.0, "T2": 16100.0}) == {"T1": "HIT", "T2": "SL"}
