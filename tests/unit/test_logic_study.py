from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from tradingagent.sim.logic_study import decide, gap_group, logic_features


def _days(n, rng_fn, start=date(2026, 1, 1)):
    rows, vix = [], []
    for i in range(n):
        d = start + timedelta(days=i)
        lo, hi = 22000.0, 22000.0 + rng_fn(i)
        for k, px in enumerate((lo + (hi - lo) / 2, hi, lo, lo + 10)):
            rows.append({"ts": datetime(d.year, d.month, d.day, 9, 15 + k), "open": px, "high": px, "low": px,
                         "close": px, "day": d})
        vix.append({"day": d, "close": 12.0 + i * 0.01})
    return pd.DataFrame(rows), pd.DataFrame(vix)


def test_features_do_not_use_today():
    idx, vix = _days(40, lambda i: 100.0)
    f1 = logic_features(idx, vix)
    idx2 = idx.copy()
    last = idx2["day"] == idx2["day"].max()
    idx2.loc[last, ["high", "close"]] += 900  # change ONLY today
    f2 = logic_features(idx2, vix)
    d = idx["day"].max()
    for col in ("squeeze", "after_big_day", "atr_pts", "vix_cheap"):
        assert (f1.at[d, col] == f2.at[d, col]) or (pd.isna(f1.at[d, col]) and pd.isna(f2.at[d, col]))


def test_squeeze_and_big_day_detection():
    idx, vix = _days(40, lambda i: 300.0 if i < 30 else 60.0)   # ranges shrink in the last 10 days
    f = logic_features(idx, vix)
    assert bool(f.iloc[-1]["squeeze"]) is True
    idx2, vix2 = _days(40, lambda i: 400.0 if i == 38 else 100.0)  # yesterday (day 38) was big
    assert bool(logic_features(idx2, vix2).iloc[-1]["after_big_day"]) is True


def test_gap_group():
    assert gap_group(0.003, "CE") == "aligned" and gap_group(0.003, "PE") == "opposed"
    assert gap_group(-0.003, "PE") == "aligned" and gap_group(0.0005, "CE") == "no_gap"
    assert gap_group(np.nan, "CE") == "no_gap"


def test_decide_requires_both_setups():
    rows = []
    for s in ("S1", "S2", "RANDOM"):
        rows.append({"setup": s, "feature": "ALL", "value": "-", "n": 300, "right_dir_60%": 50.0, "dev": 100.0,
                     "val+test": 100.0})
    for s, good in (("S1", True), ("S2", True), ("RANDOM", False)):
        rows.append({"setup": s, "feature": "F1_squeeze", "value": "True", "n": 100,
                     "right_dir_60%": 55.0 if good else 45.0, "dev": 200.0 if good else 0.0,
                     "val+test": 200.0 if good else 0.0})
    for s, good in (("S1", True), ("S2", False), ("RANDOM", True)):
        rows.append({"setup": s, "feature": "F2_vix_cheap", "value": "True", "n": 100,
                     "right_dir_60%": 55.0 if good else 45.0, "dev": 200.0, "val+test": 200.0})
    v = decide(pd.DataFrame(rows)).set_index(["feature", "value"])
    assert bool(v.loc[("F1_squeeze", "True"), "LOGIC_IMPROVEMENT"]) is True
    assert v.loc[("F1_squeeze", "True"), "kind"] == "setup-specific"
    assert bool(v.loc[("F2_vix_cheap", "True"), "LOGIC_IMPROVEMENT"]) is False
