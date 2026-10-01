from datetime import date, datetime, timedelta

import pandas as pd

from tradingagent.sim.exit_study import Entry, rule_none, simulate
from tradingagent.sim.followthrough_study import rule_follow_through, verdict_ft

T0 = datetime(2026, 9, 28, 10, 0)
CE = Entry(date(2026, 9, 28), T0, "CE", 22700, date(2026, 10, 6), 22720.0, 22650.0)
PE = Entry(date(2026, 9, 28), T0, "PE", 22700, date(2026, 10, 6), 22720.0, 22650.0)


def bars(vals, start=T0):
    return pd.DataFrame([{"ts": start + timedelta(minutes=k), "open": v, "high": v, "low": v, "close": v}
                         for k, v in enumerate(vals)])


def test_cuts_call_when_index_has_not_risen_by_minute_15():
    idx = bars([22700] * 10 + [22695] * 30)  # flat then slightly down
    t = simulate(CE, bars([100] * 40), idx, rule_follow_through(15, rule_none), stop_pct=0.3)
    assert t["reason"] == "NO_FOLLOW_THROUGH" and t["exit_ts"] == T0 + timedelta(minutes=16)


def test_keeps_call_with_follow_through_and_checks_only_once():
    idx = bars([22700] * 10 + [22720] * 10 + [22690] * 30)  # up at minute 15, falls afterwards
    t = simulate(CE, bars([100] * 50), idx, rule_follow_through(15, rule_none), stop_pct=0.3)
    assert t["reason"] == "DATA_END"  # not cut later — the check is one-off


def test_put_direction_is_mirrored():
    idx = bars([22700] * 10 + [22710] * 30)  # index UP → put has no follow-through
    t = simulate(PE, bars([100] * 40), idx, rule_follow_through(15, rule_none), stop_pct=0.3)
    assert t["reason"] == "NO_FOLLOW_THROUGH"


def test_adopt_requires_both_setups_and_neighbours():
    rows = []
    for setup in ("S1", "S2"):
        for v, net, dev, vt in (("base", 100, 100, 100), ("FT10", 150, 150, 150), ("FT15", 200, 200, 200),
                                ("FT20", 150, 150, 150)):
            rows.append({"variant": f"{setup}-{v}", "net": net, "dev": dev, "val+test": vt, "ROBUST": False})
    s = pd.DataFrame(rows)
    assert verdict_ft(s).attrs["ADOPT_FT15"] is True
    s.loc[s["variant"] == "S2-FT20", "net"] = 50  # a neighbour fails → treat FT-15 as a lucky number
    assert verdict_ft(s).attrs["ADOPT_FT15"] is False
