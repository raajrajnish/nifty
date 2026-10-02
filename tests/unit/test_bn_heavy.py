from datetime import date, datetime, time, timedelta

import pandas as pd

from tradingagent.sim.bn_heavy import heavy_signal, price_at, ret

D = date(2025, 3, 5)


def bars(closes):
    t0 = datetime(2025, 3, 5, 9, 15)
    return pd.DataFrame([{"ts": pd.Timestamp(t0 + timedelta(minutes=k)), "open": c, "high": c, "low": c, "close": c}
                         for k, c in enumerate(closes)])


def test_price_and_30min_return():
    g = bars([100.0] * 30 + [101.0] * 300)            # 09:45 onward = 101
    assert price_at(g, time(9, 15)) == 100.0 and price_at(g, time(9, 46)) == 101.0
    assert ret(g, time(9, 45)) == 0.0                 # close before 09:45 is still 100 (09:44 bar)
    assert abs(ret(g, time(9, 50)) - 0.01) < 1e-12    # 09:20→09:50: 100 → 101


def test_heavyweights_ahead_gives_call_first_mark_only():
    bn = bars([48000.0] * 400)                        # Bank Nifty flat
    h = bars([1000.0] * 30 + [1003.0] * 400)          # +0.30% from 09:45
    i = bars([500.0] * 30 + [501.5] * 400)            # +0.30%  → basket +0.30% ≥ 0.25%
    e = heavy_signal(D, bn, [h, i], date(2025, 3, 27))
    assert e.side == "CE" and e.signal_ts == datetime(2025, 3, 5, 9, 50) and e.strike == 48000
    weak = bars([500.0] * 30 + [500.5] * 400)         # +0.10% → basket +0.20% < 0.25% → no signal
    assert heavy_signal(D, bn, [h, weak], date(2025, 3, 27)) is None
