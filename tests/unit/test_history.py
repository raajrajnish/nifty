from datetime import date, timedelta

import pytest

from tradingagent.data.history import (
    FetchAborted,
    HistoryDownloader,
    chunks,
    option_symbol,
    strike_range,
    weekdays,
)
from tradingagent.data.store import MarketStore


class FakeHist:
    """Serves 3 one-minute candles per weekday (plus a 15:40 post-close row) and 1-day candles."""

    def __init__(self, fail_times=0, holidays=()):
        self.calls = []
        self.fail_times = fail_times
        self.holidays = set(holidays)

    def historical_candles(self, segment, symbol, start, end, interval):
        self.calls.append((symbol, interval, start.date(), end.date()))
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("GrowwAPIException: Bad Request")
        out, d = [], start.date()
        while d <= end.date():
            if d.weekday() < 5 and d not in self.holidays:
                if interval == "1day":
                    out.append([f"{d}T00:00:00", 22600, 22700, 22500, 22650, None, None])
                else:
                    for hm in ("09:15", "12:00", "15:30", "15:40"):
                        out.append([f"{d}T{hm}:00", 100, 101, 99, 100.5, 65, 1000])
            d += timedelta(days=1)
        return out

    def expiries(self, underlying, year, month):
        return {(2026, 9): ["2026-09-22", "2026-09-29"], (2026, 10): ["2026-10-06"]}.get((year, month), [])


@pytest.fixture
def store(tmp_path):
    s = MarketStore(tmp_path / "m.duckdb")
    yield s
    s.close()


def _dl(src, store, last=date(2026, 9, 30)):
    return HistoryDownloader(src, store, last, log=lambda m: None, sleep=lambda s: None)


def test_helpers():
    assert weekdays(date(2026, 9, 25), date(2026, 9, 29)) == [date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29)]
    days = weekdays(date(2026, 8, 1), date(2026, 9, 30))
    assert all((c[-1] - c[0]).days < 28 for c in chunks(days, 28))
    assert option_symbol("NIFTY", date(2026, 10, 6), 22700, "CE") == "NSE-NIFTY-06Oct26-22700-CE"
    # low 22560 → 22550 − 2 strikes = 22450; high 22790 → 22800 + 2 strikes = 22900 (inclusive)
    assert strike_range([(22710, 22560), (22790, 22620)], 50, 2) == list(range(22450, 22950, 50))


def test_download_range_stores_session_candles_only_and_is_idempotent(store):
    src = FakeHist()
    dl = _dl(src, store)
    n = dl.download_range("CASH", "NSE-NIFTY", "1minute", date(2026, 9, 28), date(2026, 9, 29))
    assert n == 6  # 3 in-session candles × 2 days; the 15:40 row is dropped
    df = store.candles("NSE-NIFTY", "1minute")
    assert df["ts"].dt.strftime("%H:%M").max() == "15:30"
    calls = len(src.calls)
    assert dl.download_range("CASH", "NSE-NIFTY", "1minute", date(2026, 9, 28), date(2026, 9, 29)) == 0
    assert len(src.calls) == calls  # second run hits the database, not Groww


def test_holidays_are_recorded_as_empty_and_not_refetched(store):
    src = FakeHist(holidays={date(2026, 9, 29)})
    dl = _dl(src, store)
    dl.download_range("CASH", "NSE-NIFTY", "1minute", date(2026, 9, 28), date(2026, 9, 29))
    status = dict(store.con.execute("SELECT day, status FROM coverage").fetchall())
    assert status[date(2026, 9, 29)] == "empty" and status[date(2026, 9, 28)] == "ok"
    calls = len(src.calls)
    dl.download_range("CASH", "NSE-NIFTY", "1minute", date(2026, 9, 28), date(2026, 9, 29))
    assert len(src.calls) == calls


def test_transient_errors_retried_then_persisting_errors_refetched_next_run(store):
    dl = _dl(FakeHist(fail_times=2), store)  # fails twice, succeeds on 3rd attempt
    assert dl.download_range("CASH", "NSE-NIFTY", "1minute", date(2026, 9, 28), date(2026, 9, 28)) == 3
    dl2 = _dl(FakeHist(fail_times=99), store)
    dl2.download_range("CASH", "NSE-X", "1minute", date(2026, 9, 28), date(2026, 9, 28))
    assert dl2.stats.errors == 1 and store.covered_days("NSE-X", "1minute") == set()  # will be retried


class Raising(FakeHist):
    def __init__(self, msg):
        super().__init__()
        self.msg = msg

    def historical_candles(self, *a, **k):
        self.calls.append(a)
        raise RuntimeError(self.msg)


def test_expired_token_stops_immediately(store):
    src = Raising("GrowwAPIAuthenticationException: Authentication failed. Your API token has either expired")
    with pytest.raises(FetchAborted, match="token"):
        _dl(src, store).download_range("CASH", "NSE-NIFTY", "1minute", date(2026, 9, 28), date(2026, 9, 29))
    assert len(src.calls) == 1  # no retries on a dead token
    assert store.covered_days("NSE-NIFTY", "1minute") == set()


def test_network_outage_stops_after_three_symbols(store):
    src = Raising("ConnectionError: HTTPSConnectionPool(host='api.groww.in'): Max retries exceeded")
    dl = _dl(src, store)
    for i in range(2):
        dl.download_range("CASH", f"S{i}", "1minute", date(2026, 9, 28), date(2026, 9, 28))
    with pytest.raises(FetchAborted, match="network"):
        dl.download_range("CASH", "S2", "1minute", date(2026, 9, 28), date(2026, 9, 28))


def test_never_fetches_beyond_last_complete_day(store):
    src = FakeHist()
    _dl(src, store, last=date(2026, 9, 29)).download_range("CASH", "NSE-NIFTY", "1minute",
                                                           date(2026, 9, 28), date(2026, 10, 2))
    assert max(c[3] for c in src.calls) == date(2026, 9, 29)


def test_options_follow_each_expiry_week(store):
    src = FakeHist()
    dl = _dl(src, store)
    dl.download_index("NIFTY", date(2026, 9, 23), date(2026, 9, 30))
    dl.download_options("NIFTY", date(2026, 9, 23), date(2026, 9, 30), strikes_each_side=1)
    syms = {c[0] for c in src.calls if c[0].startswith("NSE-NIFTY-")}
    # week of 29 Sep expiry: 23..29 Sep; daily range 22500..22700 → 22450..22750 with ±1 strike
    assert "NSE-NIFTY-29Sep26-22450-CE" in syms and "NSE-NIFTY-29Sep26-22750-PE" in syms
    assert not any("22Sep26" in s for s in syms)  # expiry before the start date is not fetched
    oct_calls = [c for c in src.calls if "06Oct26" in c[0]]
    assert oct_calls and all(c[2] == date(2026, 9, 30) for c in oct_calls)  # only 30 Sep so far
    kinds = dict(store.con.execute("SELECT symbol, kind FROM contracts").fetchall())
    assert kinds["NSE-NIFTY-29Sep26-22450-CE"] == "CE" and kinds["NSE-NIFTY"] == "IDX"
