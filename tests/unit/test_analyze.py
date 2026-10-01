from datetime import datetime, timedelta

import pandas as pd

from tradingagent.core.clock import IST
from tradingagent.data.analyze import cadence, clean_index, entry_test, frozen_index_episodes, index_anomalies

T0 = datetime(2026, 9, 30, 9, 30, tzinfo=IST)


def _ts(seconds):
    return pd.Series(pd.to_datetime([T0 + timedelta(seconds=s) for s in seconds]))


def test_cadence_counts_gaps():
    c = cadence(_ts([0, 2, 4, 6, 20, 22]), expected_s=2.0)
    assert c["median_gap_s"] == 2.0 and c["gaps_over_3x"] == 1 and c["max_gap_s"] == 14.0
    assert c["gap_seconds_lost"] == 12.0


def _ltp(nifty, fut, step_s=2):
    return pd.DataFrame({"ts": _ts([i * step_s for i in range(len(nifty))]), "nifty": nifty, "fut": fut,
                         "vix": 13.0})


def test_bad_index_print_detected_and_cleaned():
    # 2026-09-30 pattern: index jumps ~100 pts while the future is quiet
    ltp = _ltp([22600, 22601, 22500, 22598, 22600], [22700, 22701, 22700, 22701, 22700])
    a = index_anomalies(ltp)
    assert a["bad_index_ticks"] == 2  # the drop and the recovery
    assert 22500 not in clean_index(ltp)["nifty"].tolist()


def test_frozen_index_while_future_moves():
    n = 40  # 80 s of samples
    ltp = _ltp([22600.0] * n, [22700 + i for i in range(n)])
    assert frozen_index_episodes(ltp, window_s=60, fut_move_pts=5) == 1
    moving = _ltp([22600 + i for i in range(n)], [22700 + i for i in range(n)])
    assert frozen_index_episodes(moving) == 0


def test_entry_test_uses_ask_to_enter_and_bid_to_exit():
    chain = pd.DataFrame([{"symbol": "N22600CE", "strike": 22600.0, "type": "CE"},
                          {"symbol": "N22600PE", "strike": 22600.0, "type": "PE"}])
    ltp = _ltp([22601.0] * 400, [22700.0] * 400)
    rows = []
    for s in range(0, 800, 10):
        t, up, down = T0 + timedelta(seconds=s), 100 + s / 100, 100 - s / 100
        rows.append({"ts": t, "symbol": "N22600CE", "bid": up, "ask": up + 0.5})
        rows.append({"ts": t, "symbol": "N22600PE", "bid": down, "ask": down + 0.5})
    q = pd.DataFrame(rows)
    q["ts"] = pd.to_datetime(q["ts"])
    e = entry_test(q, ltp, chain, lot=65, end=T0.time(), horizons=(10,))
    ce = e[e["side"] == "CE"].iloc[0]
    pe = e[e["side"] == "PE"].iloc[0]
    assert ce["entry_ask"] == 100.5 and round(ce["spread_inr"], 2) == 32.5
    # CE: bid rises 0.1/10s → best bid at t+600s = 106.0; minus entry ask 100.5 → 5.5 pts × 65
    assert round(ce["mfe_10"], 1) == round(5.5 * 65, 1)
    # PE: bid falls → best bid right after entry (99.9) → MFE is negative (never profitable)
    assert pe["mfe_10"] < 0
