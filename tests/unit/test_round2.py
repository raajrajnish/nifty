from datetime import date, datetime, timedelta

import pandas as pd

from tradingagent.sim.round2 import r2_turn_of_month, short_straddle_path
from tradingagent.sim.swing_study import DeliveryCosts


def legs(ce_closes, pe_closes, t0=datetime(2025, 3, 6, 13, 30)):
    mk = lambda xs: pd.DataFrame([{"ts": pd.Timestamp(t0 + timedelta(minutes=k)), "open": x, "close": x}  # noqa: E731
                                  for k, x in enumerate(xs)])
    return mk(ce_closes), mk(pe_closes)


def test_short_straddle_holds_to_1510_when_no_stop():
    n = 100                                                     # 13:30 … 15:09
    ce, pe = legs([50.0] * n, [50.0] * n)
    assert short_straddle_path(ce, pe) == (100.0, 100.0, "EOD_1510")


def test_short_straddle_stops_at_next_open_after_1_5x():
    ce_c = [50.0, 60.0, 110.0, 120.0] + [120.0] * 96            # summed close 160 ≥ 150 at 13:32
    ce, pe = legs(ce_c, [50.0] * 100)
    credit, back, reason = short_straddle_path(ce, pe)
    assert (credit, reason) == (100.0, "STOP_1.5x") and back == 120.0 + 50.0   # next minute's opens


def test_turn_of_month_window_and_control_exclusion():
    cal = [date(2024, 1, 29), date(2024, 1, 30), date(2024, 1, 31), date(2024, 2, 1), date(2024, 2, 2),
           date(2024, 2, 5), date(2024, 2, 6), date(2024, 2, 7), date(2024, 2, 8)]
    d = pd.DataFrame({"open": 100.0, "close": 100.0}, index=cal)
    d.loc[date(2024, 2, 5), "close"] = 110.0
    t = r2_turn_of_month({f"S{i}": d for i in range(30)}, cal, DeliveryCosts())
    tom = t[t.strategy == "R2"]
    # last trading day of Jan = 31 Jan (open 100) → 3rd trading day of Feb = 5 Feb (close 110) → ≈ +10% − costs
    assert list(tom.day) == [date(2024, 1, 31)] and 9.4 < tom.net_pct.iloc[0] < 9.8
    assert date(2024, 1, 30) not in set(t[t.strategy == "R2_control"].day)   # overlaps the TOM window
