"""Bank Nifty heavyweight lead (step B5). Spec: docs/reports/2026-10-02_banknifty_search.md ("Step B5").

D = mean(HDFCBANK, ICICIBANK 30-min % return) − BANKNIFTY 30-min % return, on 5-min marks 09:45–13:30.
D ≥ +0.25% → Bank Nifty CE, D ≤ −0.25% → PE (follow the heavyweights). First signal of the day.
"""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.banknifty_search import LOT, STEP, expiries, option_symbol
from tradingagent.sim.banknifty_validation import restrike
from tradingagent.sim.costs import CostModel
from tradingagent.sim.discovery_study import follow
from tradingagent.sim.entry_study import e_random
from tradingagent.sim.exit_study import Entry, rule_none, rule_time, simulate
from tradingagent.sim.stock_study import adjust_splits, clean_bad_prints

HEAVY = ("HDFCBANK", "ICICIBANK")
THRESH = 0.0025
MARKS = [time(9, 45)] + [(datetime(2000, 1, 1, 9, 45) + timedelta(minutes=5 * k)).time() for k in range(1, 46)]
EXITS = {"HL1": (rule_none, 0.50), "HL2": (rule_time(60), 0.50)}


def price_at(g: pd.DataFrame, t: time) -> float | None:
    """Last 1-min close strictly before t; the day's first open at 09:15."""
    if t == time(9, 15):
        return float(g["open"].iloc[0])
    s = g[g["ts"].dt.time < t]
    return float(s["close"].iloc[-1]) if len(s) else None


def ret(g: pd.DataFrame, t: time) -> float | None:
    t0 = (datetime.combine(date(2000, 1, 1), t) - timedelta(minutes=30)).time()
    a, b = price_at(g, t0), price_at(g, t)
    return None if a is None or b is None or a == 0 else b / a - 1


def heavy_signal(day: date, bn: pd.DataFrame, stocks: list[pd.DataFrame], expiry: date) -> Entry | None:
    for t in MARKS:
        if t > time(13, 30):
            break
        rb = ret(bn, t)
        rs = [ret(s, t) for s in stocks]
        if rb is None or any(r is None for r in rs):
            continue
        d = float(np.mean([r for r in rs if r is not None])) - rb
        if abs(d) >= THRESH:
            px = price_at(bn, t)
            assert px is not None
            return Entry(day, datetime.combine(day, t), "CE" if d > 0 else "PE", int(round(px / STEP) * STEP),
                         expiry, np.nan, np.nan)
    return None


def contexts(store: MarketStore, start: date, end: date) -> Iterator[tuple[date, pd.DataFrame, list[pd.DataFrame],
                                                                          date, float]]:
    exps = expiries(store)
    es = set(exps)
    bn = store.candles("NSE-BANKNIFTY", "1minute")
    bn["day"] = bn["ts"].dt.date
    daily = bn.groupby("day").agg(high=("high", "max"), low=("low", "min"))
    atr = (daily["high"] - daily["low"]).shift(1).rolling(14).mean()
    skip: set[date] = set()
    by_stock = []
    for s in HEAVY:
        m, bad = clean_bad_prints(store.candles(f"NSE-{s}", "1minute"))
        _, _, ex = adjust_splits(m)
        skip |= bad | ex
        m["day"] = m["ts"].dt.date
        by_stock.append({k: v.reset_index(drop=True) for k, v in m.groupby("day")})
    for d, g in bn.groupby("day"):
        if not (start <= d <= end) or d in es or d in skip or any(d not in st for st in by_stock):
            continue
        nxt = [e for e in exps if e > d]
        if not nxt or pd.isna(atr.get(d)):
            continue
        yield d, g.reset_index(drop=True), [st[d] for st in by_stock], nxt[0], float(atr[d])


def run(store: MarketStore, costs: CostModel, start: date, end: date,
        options: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (direction rows, option trades). options=False → index-only (for the 2021–23 lock box)."""
    exps = expiries(store)
    drows: list[dict[str, Any]] = []
    trows: list[dict[str, Any]] = []
    for d, g, stocks, exp, atr in contexts(store, start, end):
        sigs = {"HEAVY": heavy_signal(d, g, stocks, exp)}
        r = e_random(g, {"day": d}, exps)
        sigs["RANDOM"] = restrike(r, g, STEP) if r is not None else None
        for name, e in sigs.items():
            if e is None:
                continue
            drows.append({"setup": name, "day": d, "side": e.side, "entry_ts": e.signal_ts,
                          "follow_60": follow(g, e.signal_ts, e.side, 60, atr),
                          "follow_eod": follow(g, e.signal_ts, e.side, None, atr)})
            if not options:
                continue
            opt = store.candles(option_symbol(e.expiry, e.strike, e.side), "1minute",
                                datetime.combine(d, time(9, 15)), datetime.combine(d, time(15, 30)))
            if opt.empty:
                continue
            exits = EXITS if name == "HEAVY" else {"RANDOM": (rule_none, 0.50)}
            for xname, (rule, stop) in exits.items():
                tr = simulate(e, opt, g, rule, stop_pct=stop)
                if tr is None:
                    continue
                cst = costs.round_trip(tr["entry_px"], tr["exit_px"], LOT).total
                net = tr["pts"] * LOT - cst
                trows.append({**tr, "variant": xname, "net_inr": net, "net2_inr": net - cst,
                              "r_net": net / (tr["risk_pts"] * LOT), "delay_min": np.nan,
                              "era": "weekly" if d <= date(2024, 11, 20) else "monthly"})
    return pd.DataFrame(drows), pd.DataFrame(trows)
