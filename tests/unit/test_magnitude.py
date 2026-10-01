from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from tradingagent.sim.magnitude_study import day_table, evaluate


def _bars(n_days: int, range_fn, start=date(2022, 1, 3)):
    rows, vix1, vixd = [], [], []
    d, made = start, 0
    days = []
    while made < n_days:
        if d.weekday() < 5:
            r = range_fn(made)
            for k in range(375):
                t = datetime(d.year, d.month, d.day, 9, 15) + timedelta(minutes=k)
                px = 17000 + r * ((k % 50) / 49)
                rows.append({"ts": t, "open": px, "high": px, "low": px, "close": px})
                vix1.append({"ts": t, "open": 15.0, "high": 15.0, "low": 15.0, "close": 15.0 + made * 0.01})
            vixd.append({"ts": datetime(d.year, d.month, d.day), "close": 15.0 + made * 0.01})
            days.append(d)
            made += 1
        d += timedelta(days=1)
    return pd.DataFrame(rows), pd.DataFrame(vix1), pd.DataFrame(vixd), days


def test_targets_and_predictors_are_past_only():
    idx, v1, vd, days = _bars(40, lambda i: 100.0)
    t1 = day_table(idx, v1, vd, [days[-1]])
    idx2 = idx.copy()
    last = idx2["ts"].dt.date == days[-1]
    afternoon = last & (idx2["ts"].dt.hour >= 12)
    idx2.loc[afternoon, ["high", "close"]] += 500  # change ONLY today's afternoon
    t2 = day_table(idx2, v1, vd, [days[-1]])
    for p in ("P1_squeeze", "P2_vix_level", "P4_gap_atr", "P5_or_width_atr", "P6_open_outside"):
        a, b = t1.at[days[-1], p], t2.at[days[-1], p]
        assert (a == b) or (np.isnan(a) and np.isnan(b)), p
    assert t2.at[days[-1], "range_after_atr"] > t1.at[days[-1], "range_after_atr"]  # target does see it


def test_days_to_expiry():
    idx, v1, vd, days = _bars(10, lambda i: 100.0)
    t = day_table(idx, v1, vd, [days[4], days[9]])
    assert t.at[days[3], "P7_days_to_expiry"] == 1 and t.at[days[4], "P7_days_to_expiry"] == 0
    assert t.at[days[5], "P7_days_to_expiry"] == 4


def test_evaluate_detects_a_real_predictor():
    rng = np.random.default_rng(0)
    n = 300
    x = rng.normal(size=n)
    tbl = pd.DataFrame({p: rng.normal(size=n) for p in ("P1_squeeze", "P2_vix_level", "P3_vix_change_open",
                                                        "P4_gap_atr", "P6_open_outside", "P7_days_to_expiry")})
    tbl["P5_or_width_atr"] = x
    tbl["range_after_atr"] = 2 + x + rng.normal(scale=0.7, size=n)  # P5 truly predicts the size
    r = evaluate(tbl, tbl).set_index("predictor")
    assert bool(r.loc["P5_or_width_atr", "PASS"]) is True
    assert r.loc["P5_or_width_atr", "rho_untouched"] > 0.5
