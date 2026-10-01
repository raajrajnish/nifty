from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from tradingagent.sim.timing_study import (
    extension,
    first_1min_break,
    s1_variants,
    s2_fast,
    summarize_timing,
    verdict,
)


def test_summary_and_verdict_run_on_trade_rows():
    rng = np.random.default_rng(0)
    rows = []
    for v, shift in (("S1-A", 0), ("S1-B", 300)):
        for i in range(150):
            net = float(rng.normal(100 + shift, 800))
            rows.append({"variant": v, "net_inr": net, "net2_inr": net - 70, "r_net": net / 2000,
                         "split": "dev" if i < 90 else "validate" if i < 120 else "test",
                         "half": "H1" if i < 75 else "H2", "side": "CE" if i % 2 else "PE",
                         "reason": "EOD", "delay_min": float(i % 5)})
    s = summarize_timing(pd.DataFrame(rows))
    assert set(s["variant"]) == {"S1-A", "S1-B"}
    v = verdict(s)
    assert v.iloc[0]["variant"] == "S1-B" and bool(v.iloc[0]["BEATS_A"]) is True

D = date(2026, 9, 28)
EXP = [date(2026, 9, 29), date(2026, 10, 6)]
T915 = datetime(2026, 9, 28, 9, 15)


def day(closes, lows=None, highs=None):
    return pd.DataFrame([{"ts": T915 + timedelta(minutes=k), "open": c,
                          "high": highs[k] if highs else c, "low": lows[k] if lows else c, "close": c}
                         for k, c in enumerate(closes)])


# opening range 09:15–09:29: 22700..22740 (width 40)
OR = [22700, 22740] + [22720] * 13


def test_fast_confirm_enters_one_minute_after_first_1min_close():
    closes = OR + [22730, 22745, 22750, 22752, 22760] + [22770] * 60  # 09:31 closes above 22740
    g = day(closes)
    v = s1_variants(g, D, EXP)
    assert first_1min_break(g, 22740, 22700)[0] == T915 + timedelta(minutes=16)
    assert v["S1-B"].signal_ts == T915 + timedelta(minutes=17)  # 09:32 open
    assert v["S1-A"].signal_ts == datetime(2026, 9, 28, 9, 35)  # 5-min bar 09:30–09:34 closes above
    assert v["S1-B"].side == v["S1-A"].side == "CE"


def test_retest_requires_dip_into_zone_and_close_back_beyond():
    closes = OR + [22745, 22760, 22770, 22760, 22745, 22750] + [22780] * 60
    lows = OR + [22745, 22760, 22770, 22760, 22742, 22750] + [22780] * 60  # 09:34 low 22742 ≤ 22740+4
    v = s1_variants(day(closes, lows=lows), D, EXP)
    assert v["S1-C"] is not None and v["S1-C"].signal_ts == T915 + timedelta(minutes=20)


def test_retest_cancelled_by_full_failure():
    closes = OR + [22745, 22690] + [22760] * 60  # breaks up then closes below the range low
    lows = OR + [22745, 22690] + [22760] * 60
    v = s1_variants(day(closes, lows=lows), D, EXP)
    assert v["S1-C"] is None


def test_dont_chase_skips_extended_breakouts():
    assert extension(22770, "CE", 22740, 22700) == 0.75
    closes = OR + [22770] + [22790] * 60  # first break already 0.75 × width past the level
    v = s1_variants(day(closes), D, EXP)
    assert v["S1-B"] is not None and v["S1-D(B)"] is None


def test_s2_fast_uses_1min_touch_of_rising_twap():
    closes = [22600 + k for k in range(60)] + [22640] + [22700] * 60  # rising, then 10:15 dips to TWAP area
    lows = [c for c in closes]
    g = day(closes, lows=lows)
    e = s2_fast(g, D, EXP)
    assert e is not None and e.side == "CE" and e.signal_ts.time() >= datetime(2026, 9, 28, 10, 0).time()
