from datetime import date, datetime, timedelta

import pandas as pd

from tradingagent.sim.banknifty_validation import overlap, restrike
from tradingagent.sim.exit_study import Entry


def test_restrike_uses_last_close_before_signal_on_100_grid():
    t0 = datetime(2022, 5, 11, 9, 15)
    g = pd.DataFrame({"ts": [pd.Timestamp(t0 + timedelta(minutes=k)) for k in range(3)],
                      "close": [45020.0, 45049.0, 45160.0]})
    e = Entry(date(2022, 5, 11), t0 + timedelta(minutes=2), "CE", 45050, date(2022, 5, 12), 1.0, 0.0)
    assert restrike(e, g, 100).strike == 45000          # 45049 → 45000 (the 09:17 close is not yet known)
    assert restrike(e, g, 100).signal_ts == e.signal_ts


def test_overlap_counts_same_day_and_same_side():
    bn = pd.DataFrame({"setup": ["G1", "G1", "G2"], "day": [1, 2, 3], "side": ["CE", "PE", "PE"]})
    nf = pd.DataFrame({"setup": ["G1", "G1"], "day": [1, 2], "side": ["CE", "CE"]})
    o = overlap(bn, nf).set_index("setup")
    assert o.loc["G1", "also_on_nifty%"] == 100.0 and o.loc["G1", "same_side%"] == 50.0
    assert o.loc["G2", "also_on_nifty%"] == 0.0
