from datetime import date

import numpy as np
import pandas as pd

from tradingagent.sim.risk_study import apply_cap, longest_losing_streak, max_drawdown, monte_carlo


def _t(rows):
    t = pd.DataFrame(rows, columns=["day", "entry_ts", "exit_ts", "net_inr"])
    t["entry_ts"] = pd.to_datetime(t["entry_ts"])
    t["exit_ts"] = pd.to_datetime(t["exit_ts"])
    return t


def test_cap_skips_new_entry_only_after_realised_loss():
    d = date(2025, 1, 2)
    t = _t([(d, "2025-01-02 09:40", "2025-01-02 10:30", -4500),   # S1 stopped out
            (d, "2025-01-02 11:00", "2025-01-02 15:10", 3000)])   # S2 later the same day
    assert len(apply_cap(t, 4000)) == 1          # −4,500 realised before 11:00 → skip
    assert len(apply_cap(t, 5000)) == 2          # cap not reached → take it
    assert len(apply_cap(t, None)) == 2


def test_cap_ignores_trades_still_open():
    d = date(2025, 1, 2)
    t = _t([(d, "2025-01-02 09:40", "2025-01-02 14:00", -4500),   # still open at 11:00
            (d, "2025-01-02 11:00", "2025-01-02 15:10", 3000)])
    assert len(apply_cap(t, 4000)) == 2


def test_streak_and_drawdown():
    assert longest_losing_streak(pd.Series([1, -1, -2, 3, -1, -1, -1, 2])) == 3
    assert max_drawdown(np.array([100.0, -300.0, 50.0, -100.0, 400.0])) == -350.0
    assert max_drawdown(np.array([-200.0, 100.0])) == -200.0  # drawdown from the starting balance


def test_monte_carlo_is_reproducible():
    s = pd.Series([500.0, -300.0, -200.0, 800.0, -400.0] * 20)
    assert monte_carlo(s, runs=200) == monte_carlo(s, runs=200)
