from datetime import date, datetime, timedelta

import pandas as pd

from tradingagent.agent.shadow import Ledger, ShadowConfig
from tradingagent.tournament import live
from tradingagent.tournament.candidates import BY_ID, CANDIDATES
from tradingagent.tournament.live import MemStore, Watcher

DAY = date(2026, 10, 6)


def test_ten_frozen_candidates_with_descriptions():
    assert [c.id for c in CANDIDATES] == ["G1", "G2", "P4", "SW2", "FIB71", "R6", "CPR", "HL1", "BSE", "SW1"]
    assert all(c.description and c.weakness and c.backtest for c in CANDIDATES)
    assert {c.id for c in CANDIDATES if not c.live} == {"SW1", "SW2"}


def test_memstore_appends_today_and_filters_window():
    h = pd.DataFrame({"ts": pd.to_datetime(["2026-10-05 15:29"]), "open": 1.0, "high": 1.0, "low": 1.0,
                      "close": 1.0})
    m = MemStore({("NSE-NIFTY", "1minute"): h})
    m.today["NSE-NIFTY"] = pd.DataFrame({"ts": pd.to_datetime(["2026-10-06 09:15"]), "open": 2.0, "high": 2.0,
                                         "low": 2.0, "close": 2.0})
    assert len(m.candles("NSE-NIFTY", "1minute")) == 2
    assert m.candles("NSE-NIFTY", "1minute", start=datetime(2026, 10, 6))["close"].tolist() == [2.0]
    assert m.candles("NSE-INDIAVIX", "1day").empty


def make_watcher(tmp_path, monkeypatch, check_result):
    monkeypatch.setattr(live, "CHECKS", {"FIB71": lambda w, now: check_result(now)})
    monkeypatch.setattr(live, "load_events", lambda d: [])
    asked = []
    monkeypatch.setattr(live, "decide", lambda *a, **k: asked.append(a))
    w = Watcher(DAY, {}, [date(2026, 10, 13)], [], ShadowConfig(), Ledger(tmp_path / "l.jsonl"),
                now=lambda: datetime(2026, 10, 6, 12, 0), log=lambda m: None, start_thread=lambda fn: fn(),
                signals_log=tmp_path / "sig.jsonl")
    return w, asked


def feed_minutes(w, start, n, px=25000.0):
    for k in range(n):
        ts = start + timedelta(minutes=k, seconds=5)
        w.on_ltp(ts, {"NSE_NIFTY": px, "NSE_INDIAVIX": 13.0})


def test_signal_accepted_only_when_not_in_future_and_only_once(tmp_path, monkeypatch):
    sig_t = datetime(2026, 10, 6, 12, 5)
    w, asked = make_watcher(tmp_path, monkeypatch, lambda now: (sig_t, "CE"))
    feed_minutes(w, datetime(2026, 10, 6, 11, 58), 6)        # only the 12:00 check runs; 12:05 is still the future
    assert w.fired == set() and asked == []
    feed_minutes(w, datetime(2026, 10, 6, 12, 4), 8)         # crosses 12:05 and 12:10 boundaries
    assert w.fired == {"FIB71"} and len(asked) == 1
    lines = (tmp_path / "sig.jsonl").read_text().splitlines()
    assert len(lines) == 1 and '"side": "CE"' in lines[0]


def test_future_signal_is_rejected(tmp_path, monkeypatch):
    w, asked = make_watcher(tmp_path, monkeypatch, lambda now: (now + timedelta(minutes=5), "PE"))
    feed_minutes(w, datetime(2026, 10, 6, 9, 15), 20)
    assert w.fired == set() and asked == []


def test_check_error_never_stops_watcher(tmp_path, monkeypatch):
    def boom(now):
        raise RuntimeError("bad data")
    w, asked = make_watcher(tmp_path, monkeypatch, boom)
    feed_minutes(w, datetime(2026, 10, 6, 9, 15), 20)
    assert w.fired == set() and asked == []
    assert BY_ID["FIB71"].live
