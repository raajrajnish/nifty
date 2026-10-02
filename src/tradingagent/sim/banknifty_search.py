"""Bank Nifty setup search (`tradingagent bn-search`). Spec: docs/reports/2026-10-02_banknifty_search.md.

Search window ONLY (Dec 2023 – Sep 2025). Lock boxes (Oct 2025 – Sep 2026 options; Nov 2021 – Nov 2023 index)
are refused here on purpose — they are opened once, by a separate pre-declared final test.
"""

from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.banknifty_validation import restrike
from tradingagent.sim.costs import CostModel
from tradingagent.sim.entry_study import ENTRIES, EXITS, day_features, summarize
from tradingagent.sim.exit_study import simulate

UNDERLYING = "BANKNIFTY"
STEP = 100
LOT = 30
SEARCH_START, SEARCH_END = date(2023, 12, 1), date(2025, 9, 30)


class LockBoxError(ValueError):
    """Raised when a search step asks for data inside a lock box."""


def check_window(start: date, end: date) -> None:
    if start < SEARCH_START or end > SEARCH_END:
        raise LockBoxError(f"{start}..{end} is outside the search window {SEARCH_START}..{SEARCH_END}")


def expiries(store: MarketStore) -> list[date]:
    return [r[0] for r in store.con.execute(
        "SELECT DISTINCT expiry FROM contracts WHERE kind='CE' AND underlying=? ORDER BY expiry",
        [UNDERLYING]).fetchall()]


def option_symbol(expiry: date, strike: int, side: str) -> str:
    return f"NSE-{UNDERLYING}-{expiry.strftime('%d%b%y')}-{strike}-{side}"


def run_entry_study(store: MarketStore, costs: CostModel, start: date = SEARCH_START,
                    end: date = SEARCH_END) -> tuple[pd.DataFrame, pd.DataFrame]:
    check_window(start, end)
    exps = expiries(store)
    exp_set = set(exps)
    idx = store.candles(f"NSE-{UNDERLYING}", "1minute")
    idx["day"] = idx["ts"].dt.date
    feats = day_features(idx)
    c5 = idx.set_index("ts")["close"].resample("5min", label="right", closed="left").last().dropna()
    ema5 = pd.DataFrame({"close": c5, "e9": c5.ewm(span=9, adjust=False).mean(),
                         "e21": c5.ewm(span=21, adjust=False).mean()})
    days = sorted(idx["day"].unique())
    next_day = {d: days[i + 1] for i, d in enumerate(days[:-1])}
    rows: list[dict[str, Any]] = []
    for d, g in idx.groupby("day"):
        if d in exp_set or not (start <= d <= end):
            continue
        g = g.reset_index(drop=True)
        ctx = {"day": d, "gap_pct": None if pd.isna(feats.at[d, "gap_pct"]) else float(feats.at[d, "gap_pct"]),
               "ema5": ema5}
        cache: dict[str, pd.DataFrame] = {}
        for ename, efn in ENTRIES.items():
            e = efn(g, ctx, exps)
            if e is None:
                continue
            e = restrike(e, g, STEP)
            sym = option_symbol(e.expiry, e.strike, e.side)
            if sym not in cache:
                cache[sym] = store.candles(sym, "1minute", datetime.combine(d, time(9, 15)),
                                           datetime.combine(d, time(15, 30)))
            opt = cache[sym]
            if opt.empty:
                rows.append({"day": d, "entry": ename, "missing": sym})
                continue
            for xname, xrule in EXITS.items():
                tr = simulate(e, opt, g, xrule)
                if tr is None:
                    continue
                c1 = costs.round_trip(tr["entry_px"], tr["exit_px"], LOT).total
                tr.update(entry=ename, exit=xname, cost_inr=c1, gross_inr=tr["pts"] * LOT,
                          net_inr=tr["pts"] * LOT - c1, net2_inr=tr["pts"] * LOT - 2 * c1,
                          r_net=(tr["pts"] * LOT - c1) / (tr["risk_pts"] * LOT),
                          gap_pct=feats.at[d, "gap_pct"], high_vol=feats.at[d, "high_vol"],
                          narrow_or=feats.at[d, "narrow_or"], pre_expiry=next_day.get(d) in exp_set,
                          trend20_up=feats.at[d, "trend20_up"], trend50_up=feats.at[d, "trend50_up"],
                          era="weekly" if d <= date(2024, 11, 20) else "monthly")
                rows.append(tr)
    allrows = pd.DataFrame(rows)
    if allrows.empty or "net_inr" not in allrows:
        return allrows, pd.DataFrame()
    trades = allrows.dropna(subset=["net_inr"]).copy()
    all_days = sorted(trades["day"].unique())
    n = len(all_days)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(all_days)}
    trades["split"] = trades["day"].map(split)
    trades["half"] = np.where(trades["day"] <= all_days[n // 2], "H1", "H2")
    missing = allrows[allrows["net_inr"].isna()] if "missing" in allrows else allrows.iloc[0:0]
    return pd.concat([trades, missing], ignore_index=True), summarize(trades)
