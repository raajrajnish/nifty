from datetime import date, datetime, timedelta

import pandas as pd

from tradingagent.sim.exit_study import Entry, rule_none, simulate
from tradingagent.sim.stop_study import killed_winners, rule_or_inside, rule_or_opposite, rule_twap_cross

T0 = datetime(2026, 9, 28, 10, 0)
E = Entry(date(2026, 9, 28), T0, "CE", 22700, date(2026, 10, 6), or_high=22720.0, or_low=22650.0)


def bars(prices, lows=None, start=T0):
    return pd.DataFrame([{"ts": start + timedelta(minutes=k), "open": p, "high": p,
                          "low": lows[k] if lows else p, "close": p} for k, p in enumerate(prices)])


def test_no_stop_lets_a_dip_recover():
    path = [100, 100, 100, 100, 100, 130]
    lows = [100, 100, 55, 100, 100, 130]  # 45% dip, then recovery
    stopped = simulate(E, bars(path, lows), bars([22730] * 6), rule_none, stop_pct=0.30)
    free = simulate(E, bars(path, lows), bars([22730] * 6), rule_none, stop_pct=None)
    assert stopped["reason"] == "STOP" and stopped["pts"] < 0
    assert free["reason"] == "DATA_END" and free["pts"] > 0
    assert free["mae_r"] < -1.4  # dip recorded: 45% ≈ −1.5R with R = 30%


def test_or_rules_fire_only_on_completed_5min_bars():
    idx_start = datetime(2026, 9, 28, 10, 0)  # minute 0 → 10:00; 10:04 completes a 5-min bar
    idx = bars([22730, 22700, 22700, 22700, 22700, 22700], start=idx_start)  # back inside OR (22650–22720)
    t = simulate(E, bars([100] * 6), idx, rule_or_inside, stop_pct=None)
    assert t["reason"] == "OR_BACK_INSIDE" and t["exit_ts"] == idx_start + timedelta(minutes=5)
    t2 = simulate(E, bars([100] * 6), idx, rule_or_opposite, stop_pct=None)
    assert t2["reason"] != "OR_OPPOSITE_SIDE"  # 22700 is inside, not below 22650


def test_twap_cross_rule_uses_running_twap():
    idx = bars([22800, 22800, 22800, 22800, 22600, 22600])
    twap = idx.set_index("ts")["close"].expanding().mean()
    t = simulate(E, bars([100] * 6), idx, rule_twap_cross(twap), stop_pct=None)
    assert t["reason"] == "TWAP_CROSSED"  # 22600 < running TWAP at 10:04


def test_killed_winners_counts_recovered_dips():
    t = pd.DataFrame({"setup": "S", "exit_mode": "hold_1510", "stop": "none",
                      "mae_pct": [-10, -35, -45, -55, -65], "net_inr": [500, 800, -900, 300, -2000]})
    k = killed_winners(t).iloc[0]
    assert k["dipped_30"] == 4 and k["recovered_30"] == 2  # −35 (+800) and −55 (+300) came back
    assert k["dipped_50"] == 2 and k["recovered_50"] == 1
