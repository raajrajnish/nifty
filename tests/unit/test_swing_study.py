from datetime import date, timedelta

import pandas as pd
import pytest

from tradingagent.sim.swing_study import DeliveryCosts, run_signal_setup, sw1_exit


def test_delivery_costs_by_hand():
    c = DeliveryCosts()
    # ₹1L buy: brokerage 20, STT 100, stamp 15, exch 2.97, SEBI 0.1, GST 18% of 23.07
    assert c.buy(100_000) == pytest.approx(20 + 100 + 15 + 2.97 + 0.1 + 0.18 * 23.07)
    # ₹1L sell: brokerage 20, STT 100, exch 2.97, SEBI 0.1, DP 20, GST 18% of (23.07 + 20)
    assert c.sell(100_000) == pytest.approx(20 + 100 + 2.97 + 0.1 + 20 + 0.18 * 43.07)


def test_sw1_exit_rules():
    r = pd.Series({"close": 101.0, "sma5": 100.0})
    assert sw1_exit(r, 100.0, 2.0, 1) == "ABOVE_SMA5"
    r = pd.Series({"close": 93.0, "sma5": 99.0})
    assert sw1_exit(r, 100.0, 2.0, 3) == "STOP_3ATR"
    r = pd.Series({"close": 99.0, "sma5": 99.5})
    assert sw1_exit(r, 100.0, 2.0, 10) == "TIME_10D" and sw1_exit(r, 100.0, 2.0, 9) is None


def test_sw1_trade_enters_next_open_and_exits_next_open_after_signal():
    days = [date(2023, 1, 2) + timedelta(days=k) for k in range(6)]
    d = pd.DataFrame({"open": [100, 100, 98, 99, 103, 104.0], "high": 110.0, "low": 90.0,
                      "close": [100, 97, 99, 102, 104, 104.0], "sma200": 90.0, "sma5": [100, 100, 100, 100, 101, 101.0],
                      "rsi2": [50, 5, 30, 60, 70, 70.0], "atr14": 2.0, "hh55": 200.0, "ll20": 1.0, "vol20": 1.0,
                      "volume": 1.0}, index=days)
    t = run_signal_setup("X", d, set(), "SW1", DeliveryCosts())
    # signal day 2 (rsi2 5) → buy day-3 open 98; day-4 close 102 > SMA5 → sell day-5 open 103
    assert len(t) == 1 and t[0]["entry_day"] == days[2] and t[0]["exit_day"] == days[4]
    assert t[0]["reason"] == "ABOVE_SMA5" and t[0]["hold"] == 2


def test_2025_daily_bars_rebuilt_from_intraday():
    from tradingagent.sim.swing_study import rebuild_from_intraday
    daily = pd.DataFrame({"ts": pd.to_datetime(["2024-12-31", "2025-11-03", "2025-11-04"]),
                          "open": [100.0, 101.0, float("nan")], "high": 105.0, "low": 95.0, "close": 101.0,
                          "volume": 9})
    intra = pd.DataFrame({"ts": pd.to_datetime(["2024-12-31 09:15", "2025-11-03 09:15", "2025-11-03 09:30",
                                                "2025-11-04 09:15"]),
                          "open": [100.02, 101.5, 102.0, 102.0], "high": [101, 103, 104, 103.0],
                          "low": [99, 101, 100, 101.0], "close": [100, 102, 103, 102.5], "volume": [1, 2, 3, 4]})
    out, st = rebuild_from_intraday(daily, intra)
    assert out["open"].tolist() == [100.0, 101.5, 102.0]              # 2024 kept; 2025 = first trade
    assert out.iloc[1][["high", "low", "close", "volume"]].tolist() == [104.0, 100.0, 103.0, 5]
    assert st == {"rebuilt": 2, "dropped": 0, "checked_pre2025": 1, "pre2025_open_match_0.05%": 100.0}
