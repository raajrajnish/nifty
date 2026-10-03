import json
from datetime import date, time

import pandas as pd
import pytest

from tradingagent.core.errors import BrokerUnavailable
from tradingagent.data.recorder import Recorder, RecorderConfig, atm_strike, nearest_expiry


class FakeSource:
    def __init__(self, underlying=22704.65, bad=()):
        self.underlying = underlying
        self.bad = set(bad)
        self.calls = []

    def ltp(self, symbols, segment):
        self.calls.append(("ltp", segment))
        return {s: 1.0 for s in symbols}

    def quote_fno(self, sym):
        self.calls.append(("quote", sym))
        if sym in self.bad:
            raise BrokerUnavailable("Bad Request")
        return {"last_price": 100.0, "depth": {"buy": [{"price": 99.5, "quantity": 65}],
                                               "sell": [{"price": 100.5, "quantity": 130}]},
                "open_interest": 10, "volume": 5}

    def option_chain(self, underlying, expiry):
        strikes = {str(k): {"CE": {"trading_symbol": f"N{k}CE", "ltp": 1}, "PE": {"trading_symbol": f"N{k}PE"}}
                   for k in range(22000, 23500, 50)}
        return {"underlying_ltp": self.underlying, "strikes": strikes}

    def expiries(self, underlying, year, month):
        return {9: ["2026-09-22", "2026-09-29"], 10: ["2026-10-06", "2026-10-13"]}.get(month, [])

    def instruments(self):
        return pd.DataFrame([
            {"underlying_symbol": "NIFTY", "instrument_type": "FUT", "trading_symbol": "NIFTY26SEPFUT",
             "expiry_date": "2026-09-29", "lot_size": 65},
            {"underlying_symbol": "NIFTY", "instrument_type": "FUT", "trading_symbol": "NIFTY26OCTFUT",
             "expiry_date": "2026-10-27", "lot_size": 65},
            {"underlying_symbol": "NIFTY", "instrument_type": "CE", "trading_symbol": "X", "expiry_date": "2026-10-06",
             "lot_size": 65},
            {"underlying_symbol": "BANKNIFTY", "instrument_type": "FUT", "trading_symbol": "BN",
             "expiry_date": "2026-10-27", "lot_size": 30},
        ])


@pytest.fixture
def make(clock, tmp_path):
    clock.advance(clock.now().replace(hour=10) - clock.now())  # fixture clock: 2026-09-29 (a Tuesday expiry) 10:00

    def _make(src, **cfg):
        c = RecorderConfig(strikes_each_side=2, chain_strikes_each_side=4, ltp_interval_s=0.01,
                           quote_interval_s=0.01, chain_interval_s=0.05, start=time(9, 14), stop=time(15, 31), **cfg)
        return Recorder(src, c, clock, tmp_path / "raw", tmp_path / "status.json", sleep=lambda s: None)

    return _make


def test_helpers():
    assert atm_strike(22704.65, 50) == 22700
    assert atm_strike(22726, 50) == 22750
    assert nearest_expiry(["2026-09-29", "2026-10-06"], date(2026, 9, 30)) == "2026-10-06"
    assert nearest_expiry(["2026-09-29", "2026-10-06"], date(2026, 9, 29)) == "2026-09-29"  # expiry day itself
    with pytest.raises(ValueError):
        nearest_expiry(["2026-09-01"], date(2026, 9, 30))


def test_setup_snapshots_master_and_tracks_atm(make, tmp_path):
    rec = make(FakeSource())
    rec.setup()
    day = tmp_path / "raw" / "date=2026-09-29"
    manifest = json.loads((day / "master.manifest.json").read_text())
    assert manifest["nearest_future"] == "NIFTY26SEPFUT"  # expiring today still counts on its own expiry day
    assert len(manifest["full_master_sha256"]) == 64 and manifest["rows"] == 3  # NIFTY only, not BANKNIFTY
    assert rec.status.expiry == "2026-09-29" and rec.status.atm == 22700
    assert rec.status.tracked_contracts == 10  # ATM±2 strikes × CE/PE
    chain = json.loads((day / "chain.jsonl").read_text().splitlines()[0])
    assert sorted(float(k) for k in chain["strikes"]) == [22500 + 50 * i for i in range(9)]  # ATM±4 kept


def test_run_writes_all_streams_and_survives_bad_contract(make, tmp_path):
    src = FakeSource(bad={"N22700CE"})
    st = make(src).run(duration_s=0.3)
    day = tmp_path / "raw" / "date=2026-09-29"
    assert st.running is False
    assert st.counts["ltp"] >= 2 and st.counts["quotes"] >= 10
    quotes = [json.loads(line) for line in (day / "quotes.jsonl").read_text().splitlines()]
    assert {q["symbol"] for q in quotes} >= {"NIFTY26SEPFUT", "N22650PE", "N22800CE"}
    assert "N22700CE" not in {q["symbol"] for q in quotes}  # failing contract skipped...
    assert st.errors >= 1 and "N22700CE" in st.last_error  # ...recorded as an error, others unaffected
    q = quotes[0]
    assert q["bid"] == 99.5 and q["ask"] == 100.5 and q["recv_ts"].endswith("+05:30")
    assert json.loads((tmp_path / "status.json").read_text())["running"] is False


def test_recentres_when_market_moves(make):
    src = FakeSource(underlying=22704.0)
    rec = make(src)
    rec.setup()
    src.underlying = 22912.0
    rec._refresh_chain()
    assert rec.status.atm == 22900


def test_same_day_restart_keeps_first_master_snapshot(make, tmp_path):
    make(FakeSource()).setup()
    manifest = tmp_path / "raw" / "date=2026-09-29" / "master.manifest.json"
    first = manifest.read_text()
    rec2 = make(FakeSource())
    rec2.setup()
    assert manifest.read_text() == first and rec2.status.future == "NIFTY26SEPFUT"


def test_adapter_has_no_order_methods():
    from tradingagent.broker import groww_adapter

    names = {n.lower() for n in dir(groww_adapter.GrowwMarketData)}
    assert not {n for n in names if any(w in n for w in ("order", "place", "cancel", "modify"))}


class ExtrasFail(FakeSource):
    def ltp(self, symbols, segment):
        if "NSE_BSE" in symbols:
            raise BrokerUnavailable("Bad Request")
        return super().ltp(symbols, segment)


def test_extra_cash_symbols_recorded_and_failure_never_breaks_nifty(make, tmp_path):
    rec = make(FakeSource())
    rec.setup()
    rec._poll_ltp()  # noqa: SLF001
    line = json.loads((tmp_path / "raw" / "date=2026-09-29" / "ltp.jsonl").read_text().splitlines()[-1])
    want = {"NSE_NIFTY", "NSE_INDIAVIX", "NSE_BANKNIFTY", "NSE_HDFCBANK", "NSE_ICICIBANK", "NSE_BSE"}
    assert want <= set(line["index"])
    bad = make(ExtrasFail())
    bad.setup()
    bad._poll_ltp()  # noqa: SLF001
    line = json.loads((tmp_path / "raw" / "date=2026-09-29" / "ltp.jsonl").read_text().splitlines()[-1])
    assert set(line["index"]) == {"NSE_NIFTY", "NSE_INDIAVIX"} and "ltp extras" in bad.status.last_error
