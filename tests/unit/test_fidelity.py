from datetime import date

from tradingagent.data.store import MarketStore
from tradingagent.sim.fidelity import next_expiry, option_contracts, option_expiries


def _store(tmp_path):
    s = MarketStore(tmp_path / "m.duckdb")
    # Bank Nifty weekly expiry (Wed) one day BEFORE Nifty's (Thu), as in Dec 2023 – Nov 2024
    s.upsert_contract("NSE-BANKNIFTY-10Jan24-47000-CE", "BANKNIFTY", "CE", date(2024, 1, 10), 47000.0)
    s.upsert_contract("NSE-BANKNIFTY-10Jan24-47000-PE", "BANKNIFTY", "PE", date(2024, 1, 10), 47000.0)
    s.upsert_contract("NSE-NIFTY-11Jan24-21700-CE", "NIFTY", "CE", date(2024, 1, 11), 21700.0)
    s.upsert_contract("NSE-NIFTY-11Jan24-21700-PE", "NIFTY", "PE", date(2024, 1, 11), 21700.0)
    return s


def test_nifty_day_never_gets_a_banknifty_expiry(tmp_path):
    s = _store(tmp_path)
    exps = option_expiries(s.con, "NIFTY")
    assert exps == [date(2024, 1, 11)]
    assert next_expiry(date(2024, 1, 8), exps) == date(2024, 1, 11)  # unfiltered list gave 2024-01-10 (Bank Nifty)
    assert next_expiry(date(2024, 1, 11), exps) is None                # strictly after today
    syms = option_contracts(s.con, date(2024, 1, 11), "NIFTY")
    assert sorted(x[0] for x in syms) == ["NSE-NIFTY-11Jan24-21700-CE", "NSE-NIFTY-11Jan24-21700-PE"]
    assert option_contracts(s.con, date(2024, 1, 10), "NIFTY") == []
    s.close()
