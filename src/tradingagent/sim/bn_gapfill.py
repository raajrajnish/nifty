"""Bank Nifty gap-fill setups (steps B2/B3). Spec: docs/reports/2026-10-02_banknifty_search.md ("Step B2").

Entry objects carry the index TARGET (yesterday's close) and STOP levels:
CE (gap down → fill is up):  or_high = target, or_low = stop
PE (gap up → fill is down):  or_low = target,  or_high = stop
"""

from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.banknifty_search import LOT, STEP, expiries, option_symbol
from tradingagent.sim.costs import CostModel
from tradingagent.sim.exit_study import Entry, Rule, State, simulate
from tradingagent.sim.stop_study import _five_min_close

Ctx = dict[str, Any]
Strategy = Callable[[pd.DataFrame, Ctx], Entry | None]


def _entry(c: Ctx, ts: datetime, side: str, px: float, target: float, stop: float) -> Entry:
    strike = int(round(px / STEP) * STEP)
    if side == "CE":
        return Entry(c["day"], ts, side, strike, c["expiry"], target, stop)
    return Entry(c["day"], ts, side, strike, c["expiry"], stop, target)


def _last_close_before(g: pd.DataFrame, t: time) -> float | None:
    s = g[g["ts"].dt.time < t]
    return float(s["close"].iloc[-1]) if len(s) else None


def _gap(g: pd.DataFrame, c: Ctx) -> tuple[float, float, float]:
    o = float(g["open"].iloc[0])
    return o, o - c["prev_close"], (o - c["prev_close"]) / c["prev_close"]


def open_fade(lo_pct: float, hi_pct: float) -> Strategy:
    def f(g: pd.DataFrame, c: Ctx) -> Entry | None:
        o, dist, gap = _gap(g, c)
        if not (lo_pct <= abs(gap) * 100 <= hi_pct):
            return None
        px = _last_close_before(g, time(9, 20))
        pc = c["prev_close"]
        if px is None:
            return None
        early = g[g["ts"].dt.time < time(9, 20)]
        if (gap > 0 and early["low"].min() <= pc) or (gap < 0 and early["high"].max() >= pc):
            return None                                   # already filled before entry
        ts = datetime.combine(c["day"], time(9, 20))
        if gap > 0:
            return _entry(c, ts, "PE", px, target=pc, stop=o + dist)
        return _entry(c, ts, "CE", px, target=pc, stop=o + dist)   # dist < 0 → stop below the open
    return f


def confirmed_fade(g: pd.DataFrame, c: Ctx) -> Entry | None:
    o, _dist, gap = _gap(g, c)
    if not (0.2 <= abs(gap) * 100 <= 1.0):
        return None
    first = g[g["ts"].dt.time < time(9, 30)]
    if len(first) < 10:
        return None
    pc, cl = c["prev_close"], float(first["close"].iloc[-1])
    if (gap > 0 and first["low"].min() <= pc) or (gap < 0 and first["high"].max() >= pc):
        return None
    ts = datetime.combine(c["day"], time(9, 30))
    if gap > 0 and cl < o:
        return _entry(c, ts, "PE", cl, target=pc, stop=float(first["high"].max()))
    if gap < 0 and cl > o:
        return _entry(c, ts, "CE", cl, target=pc, stop=float(first["low"].min()))
    return None


def random_gap(g: pd.DataFrame, c: Ctx) -> Entry | None:
    _o, _d, gap = _gap(g, c)
    if not (0.2 <= abs(gap) * 100 <= 1.0):
        return None
    px = _last_close_before(g, time(9, 20))
    if px is None:
        return None
    side = "CE" if np.random.default_rng(c["day"].toordinal()).random() < 0.5 else "PE"
    return _entry(c, datetime.combine(c["day"], time(9, 20)), side, px, target=np.nan, stop=np.nan)


# ---------------------------------------------------------------------------- exits
def _target_hit(i: pd.Series, e: Entry) -> bool:
    return bool(i["close"] >= e.or_high) if e.side == "CE" else bool(i["close"] <= e.or_low)


def _stop_hit(i: pd.Series, e: Entry) -> bool:
    return bool(i["close"] <= e.or_low) if e.side == "CE" else bool(i["close"] >= e.or_high)


def rule_fill_1m(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    if _target_hit(i, e):
        return "GAP_FILLED"
    return "INDEX_SL" if _stop_hit(i, e) else None


def rule_fill_5m(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    if _target_hit(i, e):
        return "GAP_FILLED"
    return "INDEX_SL" if _five_min_close(i) and _stop_hit(i, e) else None


def rule_hold(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    return None


VARIANTS: dict[str, tuple[Strategy, Rule, float]] = {
    "GF1_open_fade": (open_fade(0.2, 1.0), rule_fill_1m, 0.50),
    "GF2_confirmed_fade": (confirmed_fade, rule_fill_5m, 0.50),
    "GF3_open_fade_0.2-0.5": (open_fade(0.2, 0.5), rule_fill_1m, 0.50),
    "RANDOM_gap": (random_gap, rule_hold, 0.50),
}


def contexts(store: MarketStore, start: date, end: date) -> Iterator[tuple[date, pd.DataFrame, Ctx]]:
    exps = expiries(store)
    es = set(exps)
    idx = store.candles("NSE-BANKNIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    closes = idx.groupby("day")["close"].last()
    days = list(closes.index)
    for k, (d, g) in enumerate(idx.groupby("day")):
        if k == 0 or not (start <= d <= end) or d in es:
            continue
        nxt = [e for e in exps if e > d]
        if not nxt:
            continue
        yield d, g.reset_index(drop=True), {"day": d, "expiry": nxt[0], "prev_close": float(closes[days[k - 1]])}


def run(store: MarketStore, costs: CostModel, start: date, end: date) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for d, g, c in contexts(store, start, end):
        for name, (fn, rule, stop) in VARIANTS.items():
            e = fn(g, c)
            if e is None:
                continue
            opt = store.candles(option_symbol(e.expiry, e.strike, e.side), "1minute",
                                datetime.combine(d, time(9, 15)), datetime.combine(d, time(15, 30)))
            if opt.empty:
                continue
            tr = simulate(e, opt, g, rule, stop_pct=stop)
            if tr is None:
                continue
            cst = costs.round_trip(tr["entry_px"], tr["exit_px"], LOT).total
            net = tr["pts"] * LOT - cst
            rows.append({**tr, "variant": name, "net_inr": net, "net2_inr": net - cst,
                         "r_net": net / (tr["risk_pts"] * LOT), "delay_min": np.nan,
                         "era": "weekly" if d <= date(2024, 11, 20) else "monthly",
                         "hold_min": (tr["exit_ts"] - tr["entry_ts"]) / timedelta(minutes=1)})
    return pd.DataFrame(rows)
