from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from tradingagent.sim.scorecard import scorecard, trade_metrics

T0 = datetime(2026, 9, 28, 10, 0)


def bars(closes, lows=None, highs=None, start=T0):
    return pd.DataFrame({"close": closes, "low": lows or closes, "high": highs or closes},
                        index=pd.DatetimeIndex([start + timedelta(minutes=k) for k in range(len(closes))]))


def test_capture_heat_and_follow_through():
    # option: dips to 90 (−10%), peaks at 150 (+50%) at minute 20, exits at 130 (+30%) at minute 30
    closes = [100] * 5 + [90] + [100 + 2.5 * k for k in range(1, 21)] + [140, 135, 132, 131, 130]
    opt = bars(closes, lows=[c - 0 for c in closes])
    idx = bars([22700 + k for k in range(len(closes))], start=T0)
    r = pd.Series({"entry_ts": T0, "exit_ts": T0 + timedelta(minutes=30), "entry_px": 100.0, "exit_px": 130.0,
                   "side": "CE", "reason": "OR_OPPOSITE_SIDE", "net_inr": 1800.0})
    m = trade_metrics(r, opt, idx, atr_pts=100.0)
    assert m["heat10"] == pytest.approx(-10.0)
    assert m["mfe_pct"] == pytest.approx(50.0) and m["t_peak_min"] == 25
    assert m["capture"] == pytest.approx(30.0 / 50.0)
    assert m["follow_15"] == pytest.approx(0.15)  # index +15 pts in 15 min / ATR 100
    assert m["heat_before_peak"] == pytest.approx(-10.0)
    assert not m["won_then_lost"] and not m["shaken_out"]


def test_won_then_lost_and_shaken_out_flags():
    closes = [100, 120, 135, 110, 90, 70]  # reached +35% then fell below entry
    opt = bars(closes + [80] * 300)          # recovers a bit later in the day (still below entry)
    idx = bars([22700] * 306)
    r = pd.Series({"entry_ts": T0, "exit_ts": T0 + timedelta(minutes=5), "entry_px": 100.0, "exit_px": 70.0,
                   "side": "CE", "reason": "STOP", "net_inr": -2000.0})
    m = trade_metrics(r, opt, idx, atr_pts=100.0)
    assert m["won_then_lost"] and not m["shaken_out"]


def test_scorecard_compares_variants():
    rows = []
    for v, net in (("S1", 300.0), ("RANDOM", -50.0)):
        for i in range(30):
            rows.append({"variant": v, "net_inr": net + (i % 3 - 1) * 1000, "win": (net + (i % 3 - 1) * 1000) > 0,
                         "follow_15": 0.1, "follow_60": 0.2, "follow_eod": 0.3, "heat10": -8.0, "gain10": 12.0,
                         "entry_eff": 0.4, "heat_before_peak": -9.0, "mfe_pct": 40.0, "capture": 0.5,
                         "t_peak_min": 30.0, "won_then_lost": False, "shaken_out": False, "runner_missed": False,
                         "stuck_min": 20})
    sc = scorecard(pd.DataFrame(rows)).set_index("variant")
    assert sc.loc["S1", "edge_ratio10"] == pytest.approx(1.5)
    assert sc.loc["S1", "net/trade"] > sc.loc["RANDOM", "net/trade"]
    assert not np.isnan(sc.loc["S1", "capture_med"])
