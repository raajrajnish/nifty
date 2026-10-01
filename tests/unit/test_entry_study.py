from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from tradingagent.sim.entry_study import ENTRIES, FILTERS, day_features, e_random, summarize

D = date(2026, 9, 28)
EXP = [date(2026, 9, 29), date(2026, 10, 6)]


def day_bars(closes, day=D):
    t0 = datetime(day.year, day.month, day.day, 9, 15)
    return pd.DataFrame([{"ts": t0 + timedelta(minutes=k), "open": c, "high": c, "low": c, "close": c}
                         for k, c in enumerate(closes)])


def test_orb30_waits_for_30_minute_range():
    closes = [22700 + (k % 5) for k in range(30)] + [22750] * 60  # range 22700–22704, breakout at 09:45
    e = ENTRIES["orb30"](day_bars(closes), {"day": D}, EXP)
    assert e.side == "CE" and e.signal_ts == datetime(2026, 9, 28, 9, 50)  # first 5-min bar after 09:45


def test_gap_and_go_vs_fade():
    closes_up = [22800 + k for k in range(20)]  # first 15 min rising
    ctx = {"day": D, "gap_pct": 0.006}  # +0.6% gap up
    go = ENTRIES["gap_and_go"](day_bars(closes_up), ctx, EXP)
    fade = ENTRIES["gap_fade"](day_bars(closes_up), ctx, EXP)
    assert go.side == "CE" and go.signal_ts == datetime(2026, 9, 28, 9, 30) and fade is None
    closes_down = [22800 - k for k in range(20)]
    assert ENTRIES["gap_fade"](day_bars(closes_down), ctx, EXP).side == "PE"
    assert ENTRIES["gap_and_go"](day_bars(closes_up), {"day": D, "gap_pct": 0.001}, EXP) is None  # small gap


def test_random_control_is_reproducible():
    bars = day_bars([22700] * 300)
    a = e_random(bars, {"day": D}, EXP)
    b = e_random(bars, {"day": D}, EXP)
    assert a == b


def test_with_trend_filter_matches_side_to_trend():
    t = pd.DataFrame({"side": ["CE", "PE", "CE", "PE"], "trend20_up": [True, True, False, False]})
    assert FILTERS["with_trend20"](t).tolist() == [True, False, False, True]
    assert FILTERS["against_trend20"](t).tolist() == [False, True, True, False]


def test_day_features_use_only_past_for_volatility():
    rows = []
    for i in range(30):
        d = date(2026, 1, 1) + timedelta(days=i)
        for k in range(20):
            c = 22000 + i * 10 + k
            rows.append({"ts": datetime(d.year, d.month, d.day, 9, 15) + timedelta(minutes=k), "open": c,
                         "high": c + 1, "low": c - 1, "close": c, "day": d})
    idx = pd.DataFrame(rows)
    f1 = day_features(idx)
    idx2 = idx.copy()
    last = idx2["day"] == idx2["day"].max()
    idx2.loc[last, "high"] += 500  # change ONLY the last day's prices
    f2 = day_features(idx2)
    d_last = idx["day"].max()
    assert f1.at[d_last, "atr14_pct"] == f2.at[d_last, "atr14_pct"]  # today's range can't leak into today's ATR


def test_summary_pass_requires_all_conditions():
    rng = np.random.default_rng(0)
    n = 300
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(n)]
    base = {"entry": "x", "exit": "y", "side": "CE", "gap_pct": 0.0, "high_vol": True, "narrow_or": True,
            "pre_expiry": False, "entry_ts": "2024-01-01 10:00:00", "trend20_up": True, "trend50_up": True}
    good = pd.DataFrame([{**base, "day": d, "net_inr": v, "net2_inr": v - 70, "gross_inr": v + 70, "r_net": 0.1,
                          "split": "dev" if i < 180 else "validate" if i < 240 else "test",
                          "half": "H1" if i < 150 else "H2"}
                         for i, (d, v) in enumerate(zip(days, rng.normal(400, 1000, n), strict=True))])
    s = summarize(good)
    assert bool(s[s["filter"] == "all"]["PASS"].iloc[0]) is True
    assert bool(s[s["filter"] == "all"]["ROBUST"].iloc[0]) is False  # only CE trades → PE side unproven
    mixed = good.assign(side=["CE" if i % 2 else "PE" for i in range(n)])
    assert bool(summarize(mixed)[lambda x: x["filter"] == "all"]["ROBUST"].iloc[0]) is True
    one_day_wonder = good.assign(net_inr=-50.0, net2_inr=-120.0)
    one_day_wonder.loc[:4, "net_inr"] = 20000.0  # five huge days carry everything
    r = summarize(one_day_wonder)[lambda x: x["filter"] == "all"].iloc[0]
    assert r["ex_top5"] < 0 and not r["ROBUST"]
    bad = good.assign(net2_inr=good["net_inr"] - 2000)  # dies at 2× costs
    assert bool(summarize(bad)[lambda x: x["filter"] == "all"]["PASS"].iloc[0]) is False
    assert set(FILTERS) >= {"all", "high_vol", "gap_day", "before_11"}
