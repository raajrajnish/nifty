"""Trading equity from realised P&L — the base every percentage limit applies to (risk.yaml)."""

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Equity:
    start_capital: float
    realised: float              # all realised net P&L so far
    equity: float                # start_capital + realised
    start_of_day: float          # equity before today's trades
    peak: float                  # highest end-of-day equity reached (incl. start capital)
    drawdown_pct: float          # % below peak (0 = at peak)
    today: float                 # today's realised net P&L

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def equity_from_ledger(start_capital: float, ledger: Path, today: str) -> Equity:
    rows: list[dict[str, str]] = []
    if ledger.exists():
        with ledger.open(encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    by_day: dict[str, float] = {}
    for r in rows:
        by_day[r["day"]] = by_day.get(r["day"], 0.0) + float(r.get("net_inr") or 0)
    eq, peak, before_today = start_capital, start_capital, start_capital
    for d in sorted(by_day):
        if d < today:
            before_today += by_day[d]
        eq += by_day[d]
        peak = max(peak, eq)
    dd = (peak - eq) / peak * 100 if peak > 0 else 0.0
    return Equity(start_capital=start_capital, realised=round(eq - start_capital, 1), equity=round(eq, 1),
                  start_of_day=round(before_today, 1), peak=round(peak, 1), drawdown_pct=round(dd, 2),
                  today=round(by_day.get(today, 0.0), 1))
