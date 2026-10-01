from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from tradingagent.sim.exit_study import Entry, State
from tradingagent.sim.popular_study import (
    k1_cpr,
    k2_supertrend,
    k3_first_candle,
    k4_rsi,
    k5a_camarilla_breakout,
    k5b_camarilla_fade,
    rule_series_exit,
)

D = date(2022, 5, 11)
T915 = datetime(2022, 5, 11, 9, 15)
BASE = {"day": D, "expiry": date(2022, 5, 12), "tc": 16100.0, "bc": 16080.0, "cpr_narrow": True,
        "cam": {"R3": 16150.0, "S3": 16050.0, "R4": 16200.0, "S4": 16000.0},
        "st_trend": pd.Series(dtype=float), "st_prev": None, "rsi": pd.Series(dtype=float), "rsi_prev": None}


def day(closes, highs=None, lows=None):
    return pd.DataFrame([{"ts": T915 + timedelta(minutes=k), "open": c, "high": (highs or closes)[k],
                          "low": (lows or closes)[k], "close": c} for k, c in enumerate(closes)])


def labels(*hhmm):
    return [pd.Timestamp(datetime(2022, 5, 11, h, m)) for h, m in hhmm]


def test_k1_cpr_only_on_narrow_days_and_first_close_beyond():
    path = [16090.0] * 20 + [16110.0] * 300  # bars to 09:34 inside the CPR; the 09:35–09:39 bar closes above TC
    e = k1_cpr(day(path), BASE)
    assert e.side == "CE" and e.signal_ts == datetime(2022, 5, 11, 9, 40)
    assert e.or_low == 16080.0                          # thesis-wrong exit: close below BC
    assert k1_cpr(day(path), {**BASE, "cpr_narrow": False}) is None


def test_k3_first_candle_breakout_waits_for_0925_bar():
    path = [16000.0, 16010.0, 15995.0, 16005.0, 16000.0] + [16004.0] * 5 + [16020.0] * 300
    e = k3_first_candle(day(path), BASE)
    assert e.side == "CE" and e.signal_ts == datetime(2022, 5, 11, 9, 30)  # bar 09:25–09:29 closes > 16010
    assert (e.or_high, e.or_low) == (16010.0, 15995.0)


def test_k2_supertrend_first_flip_in_window():
    st = pd.Series([1.0, 1.0, -1.0, -1.0], index=labels((9, 40), (9, 45), (9, 50), (9, 55)))
    path = [16000.0] * 60
    e = k2_supertrend(day(path), {**BASE, "st_trend": st, "st_prev": 1.0})
    assert e.side == "PE" and e.signal_ts == datetime(2022, 5, 11, 9, 50)
    st_early = pd.Series([-1.0, -1.0], index=labels((9, 40), (9, 45)))  # flip at 09:40 is before 09:45 window
    assert k2_supertrend(day(path), {**BASE, "st_trend": st_early, "st_prev": 1.0}) is None


def test_k4_rsi_cross_back_above_30():
    r = pd.Series([25.0, 28.0, 33.0], index=labels((9, 45), (9, 50), (9, 55)))
    e = k4_rsi(day([16000.0] * 60), {**BASE, "rsi": r, "rsi_prev": 20.0})
    assert e.side == "CE" and e.signal_ts == datetime(2022, 5, 11, 9, 55)


def test_k5_camarilla_breakout_and_fade():
    up = [16100.0] * 20 + [16210.0] * 300               # close above R4 → CE, exit below R3
    e = k5a_camarilla_breakout(day(up), BASE)
    assert e.side == "CE" and e.or_low == 16150.0 and np.isnan(e.or_high)
    closes = [16100.0] * 20 + [16140.0] * 300
    highs = [16100.0] * 20 + [16155.0] * 300            # pokes above R3, closes back below → fade with PE
    f = k5b_camarilla_fade(day(closes, highs=highs), BASE)
    assert f.side == "PE" and f.or_high == 16200.0


def test_series_exit_fires_on_completed_bar_only():
    s = pd.Series([40.0, 72.0], index=labels((10, 0), (10, 5)))
    rule = rule_series_exit(s, lambda v, side: v >= 70, "RSI_TARGET")
    e = Entry(D, T915, "CE", 16000, date(2022, 5, 12), np.nan, np.nan)
    st = State(entry_px=100.0, risk=30.0, peak_close=100.0)
    assert rule(st, pd.Series(), pd.Series({"ts": datetime(2022, 5, 11, 10, 3)}), e) is None   # bar not complete
    assert rule(st, pd.Series(), pd.Series({"ts": datetime(2022, 5, 11, 10, 4)}), e) == "RSI_TARGET"
