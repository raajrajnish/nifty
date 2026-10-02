"""Helpers for scripts/check_paper_fidelity.py (kept here so they can be unit-tested).

The contracts table holds NIFTY and BANKNIFTY options. Bank Nifty weekly expiries (Wednesdays until
2024-11-20) fall one day before Nifty's, so an unfiltered "next expiry" picks a Bank Nifty date for a Nifty day.
"""

from datetime import date
from typing import Any


def option_expiries(con: Any, underlying: str = "NIFTY") -> list[date]:
    """Sorted option expiries of ONE underlying (con: a DuckDB connection with the `contracts` table)."""
    rows = con.execute("SELECT DISTINCT expiry FROM contracts WHERE kind='CE' AND underlying=? ORDER BY expiry",
                       [underlying]).fetchall()
    return [r[0] for r in rows]


def next_expiry(day: date, expiries: list[date]) -> date | None:
    """Nearest expiry strictly after `day` (the playbook's contract rule)."""
    return next((e for e in expiries if e > day), None)


def option_contracts(con: Any, expiry: date, underlying: str = "NIFTY") -> list[tuple[str, float, str]]:
    """(symbol, strike, CE/PE) of one underlying's options for one expiry."""
    rows = con.execute("SELECT symbol, strike, kind FROM contracts WHERE expiry=? AND underlying=? "
                       "AND kind IN ('CE','PE')", [expiry, underlying]).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]
