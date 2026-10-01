"""Internet strategies study, batch 2 (`tradingagent backtest-internet`).
Spec: docs/reports/2026-10-01_internet_strategies_study.md (pre-declared). NEW code only; G1/G2 untouched.
"""

import math
from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.discovery_study import day_contexts, follow, random_entry
from tradingagent.sim.exit_study import LOT, STEP, Entry, Rule, State, option_symbol, rule_none, simulate
from tradingagent.sim.stop_study import rule_or_opposite
from tradingagent.sim.timing_study import summarize_timing

NAN = float("nan")
BN = 0.45                       # Bank Nifty points → Nifty points
GAP_MAX = 150.0                 # skip if |open − previous close| ≥ this (300–400 BN pts)
P4_MIN_SL = 35.0                # 70–80 BN pts
P6_WINDOW = 15.0                # 30 BN pts, on Nifty's 50-pt grid
P6_SL = 40.0                    # 90 BN pts
Ctx = dict[str, Any]
Strategy = Callable[[pd.DataFrame, Ctx], Entry | None]


def _e(c: Ctx, ts: pd.Timestamp, side: str, close: float, hi: float = NAN, lo: float = NAN) -> Entry:
    return Entry(c["day"], ts.to_pydatetime(), side, int(round(close / STEP) * STEP), c["expiry"], hi, lo)


def _between(g: pd.DataFrame, start: time, end: time) -> pd.DataFrame:
    t = g["ts"].dt.time
    return g[(t >= start) & (t < end)]


def _gap_ok(g: pd.DataFrame, c: Ctx) -> bool:
    return c["prev_close"] is not None and abs(float(g["open"].iloc[0]) - c["prev_close"]) < GAP_MAX


def _first_close_break(g: pd.DataFrame, c: Ctx, hi: float, lo: float, start: time, end: time) -> Entry | None:
    """First 1-min close beyond hi/lo with the bar starting in [start, end). Signal = bar end → fill next open."""
    for _, b in _between(g, start, end).iterrows():
        ts = pd.Timestamp(b["ts"]) + timedelta(minutes=1)
        if b["close"] > hi:
            return _e(c, ts, "CE", float(b["close"]), hi=hi, lo=lo)
        if b["close"] < lo:
            return _e(c, ts, "PE", float(b["close"]), hi=hi, lo=lo)
    return None


def _first_candle(g: pd.DataFrame, end: time, min_bars: int) -> tuple[float, float] | None:
    first = g[g["ts"].dt.time < end]
    if len(first) < min_bars:
        return None
    return float(first["high"].max()), float(first["low"].min())


# ---------------------------------------------------------------------------- strategies
def p1_inside_15m(g: pd.DataFrame, c: Ctx) -> Entry | None:
    r = _first_candle(g, time(9, 30), 12)
    if r is None or not _gap_ok(g, c):
        return None
    hi, lo = r
    inside = _between(g, time(9, 30), time(10, 45))
    if len(inside) < 60 or not (inside["high"].max() < hi and inside["low"].min() > lo):
        return None
    return _first_close_break(g, c, hi, lo, time(10, 45), time(13, 30))


def p2_first5_30min(g: pd.DataFrame, c: Ctx) -> Entry | None:
    r = _first_candle(g, time(9, 20), 4)
    return None if r is None else _first_close_break(g, c, *r, time(9, 20), time(9, 45))


def p4_bn920(g: pd.DataFrame, c: Ctx) -> Entry | None:
    if not _gap_ok(g, c):
        return None
    e = p2_first5_30min(g, c)
    if e is None:
        return None
    px = float(g.loc[g["ts"] == pd.Timestamp(e.signal_ts) - timedelta(minutes=1), "close"].iloc[0])
    if e.side == "CE":
        return Entry(e.day, e.signal_ts, e.side, e.strike, e.expiry, NAN, min(e.or_low, px - P4_MIN_SL))
    return Entry(e.day, e.signal_ts, e.side, e.strike, e.expiry, max(e.or_high, px + P4_MIN_SL), NAN)


def fib_buy(min_fall: float, entry_lvl: float, sl_lvl: float, tgt_lvl: float, start: time,
            end: time = time(13, 30)) -> Strategy:
    """Running day high H, L = lowest low since H. When H − L ≥ min_fall and a 5-min close crosses above
    L + entry_lvl·(H−L) → CE. Entry carries or_low = stop level, or_high = target level (frozen)."""
    def f(g: pd.DataFrame, c: Ctx) -> Entry | None:
        hh, ll, prev5 = -math.inf, math.inf, None
        for _, b in g.iterrows():
            if b["high"] > hh:
                hh, ll = float(b["high"]), float(b["low"])
            else:
                ll = min(ll, float(b["low"]))
            ts = pd.Timestamp(b["ts"])
            if ts.minute % 5 != 4:
                continue
            cl, sig = float(b["close"]), ts + timedelta(minutes=1)
            rng = hh - ll
            lvl = ll + entry_lvl * rng
            if rng >= min_fall and start <= sig.time() <= end and prev5 is not None and prev5 <= lvl < cl:
                return _e(c, sig, "CE", cl, hi=ll + tgt_lvl * rng, lo=ll + sl_lvl * rng)
            prev5 = cl
        return None
    return f


p3_fib44 = fib_buy(80.0, 0.44, 0.22, 0.77, time(9, 30))
p5_fib71 = fib_buy(300 * BN, 0.71, 0.38, 1.00, time(12, 0))


def p6_window(g: pd.DataFrame, c: Ctx) -> Entry | None:
    first = g[g["ts"].dt.time == time(9, 15)]
    nxt = _between(g, time(9, 16), time(9, 18))
    if first.empty or len(nxt) < 1:
        return None
    h1, l1 = float(first["high"].iloc[0]), float(first["low"].iloc[0])
    buy = (h1 % 50) <= P6_WINDOW
    sell = (l1 % 50) >= 50 - P6_WINDOW
    for _, b in nxt.iterrows():
        up, dn = buy and b["high"] >= h1 + 1, sell and b["low"] <= l1 - 1
        if up and dn:
            return None
        ts = pd.Timestamp(b["ts"]) + timedelta(minutes=1)
        if up:
            return _e(c, ts, "CE", h1 + 1, lo=h1 + 1 - P6_SL)
        if dn:
            return _e(c, ts, "PE", l1 - 1, hi=l1 - 1 + P6_SL)
    return None


# ---------------------------------------------------------------------------- exits
def rule_index_stop(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    """1-min index close beyond the stop level carried in or_low (CE) / or_high (PE)."""
    hit = i["close"] <= e.or_low if e.side == "CE" else i["close"] >= e.or_high
    return "INDEX_SL" if hit else None


def rule_p4(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    if (r := rule_index_stop(s, o, i, e)) is not None:
        return r
    if s.minutes >= 20 and not s.extra.get("checked"):
        s.extra["checked"] = True
        if float(o["close"]) <= s.entry_px:
            return "STAGNANT"
    return None


def rule_fib(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    if i["close"] <= e.or_low:
        return "FIB_SL"
    return "FIB_T1" if i["close"] >= e.or_high else None


def rule_p6(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    if (r := rule_index_stop(s, o, i, e)) is not None:
        return r
    prev = s.extra.get("prev")
    s.extra["prev"] = (float(i["high"]), float(i["low"]))
    if prev is None:
        return None
    rev = i["close"] < prev[1] if e.side == "CE" else i["close"] > prev[0]
    return "TRAIL" if rev else None


STRATEGIES: dict[str, tuple[Strategy, Rule, float]] = {
    "P1_inside_15m": (p1_inside_15m, rule_or_opposite, 0.50),
    "P2_first5_30min": (p2_first5_30min, rule_or_opposite, 0.50),
    "P3_fib44_buy": (p3_fib44, rule_fib, 0.50),
    "P4_bn920": (p4_bn920, rule_p4, 0.50),
    "P5_fib71_buy": (p5_fib71, rule_fib, 0.50),
    "P6_window": (p6_window, rule_p6, 0.50),
    "RANDOM": (random_entry, rule_none, 0.30),
}


# ---------------------------------------------------------------------------- day loop
def contexts(store: MarketStore, expiries: list[date], start: date,
             end: date) -> Iterator[tuple[date, pd.DataFrame, Ctx]]:
    d1 = store.candles("NSE-NIFTY", "1minute")
    closes = d1.groupby(d1["ts"].dt.date)["close"].last()
    for d, g, c in day_contexts(store, expiries, start, end):
        prev = closes.index[closes.index < d]
        c["prev_close"] = float(closes[prev[-1]]) if len(prev) else None
        yield d, g, c


def stage_a(store: MarketStore, expiries: list[date], start: date, end: date) -> pd.DataFrame:
    rows = []
    for d, g, c in contexts(store, expiries, start, end):
        for name, (fn, _, _) in STRATEGIES.items():
            e = fn(g, c)
            if e is None:
                continue
            rows.append({"setup": name, "day": d, "side": e.side, "entry_ts": e.signal_ts,
                         "follow_60": follow(g, e.signal_ts, e.side, 60, c["atr_pts"]),
                         "follow_eod": follow(g, e.signal_ts, e.side, None, c["atr_pts"])})
    return pd.DataFrame(rows)


def fib_outcome(g: pd.DataFrame, e: Entry, levels: dict[str, float]) -> dict[str, Any]:
    """Index-only claim check: after entry, which comes first on 1-min closes, the stop or each target."""
    after = g[(g["ts"] >= pd.Timestamp(e.signal_ts)) & (g["ts"].dt.time < time(15, 10))]
    out: dict[str, Any] = {}
    for name, lvl in levels.items():
        res = "NEITHER"
        for cl in after["close"]:
            if cl <= e.or_low:
                res = "SL"
                break
            if cl >= lvl:
                res = "HIT"
                break
        out[name] = res
    return out


def claims(store: MarketStore, expiries: list[date], start: date, end: date) -> pd.DataFrame:
    rows = []
    for d, g, c in contexts(store, expiries, start, end):
        for name, (fn, _, _) in STRATEGIES.items():
            if name == "RANDOM":
                continue
            e = fn(g, c)
            if e is None:
                continue
            row: dict[str, Any] = {"setup": name, "day": d, "month": f"{d:%Y-%m}"}
            if name.startswith(("P3", "P5")):
                lo_ = e.or_low
                span = (e.or_high - lo_) / ((0.77 - 0.22) if name.startswith("P3") else (1.00 - 0.38))
                base = lo_ - (0.22 if name.startswith("P3") else 0.38) * span   # L
                lv = {"T1": 0.77, "T2": 1.00, "T3": 1.22} if name.startswith("P3") else {"T1": 1.00, "T2": 1.27}
                row.update(fib_outcome(g, e, {k: base + v * span for k, v in lv.items()}))
            rows.append(row)
    return pd.DataFrame(rows)


def summarize_b(t: pd.DataFrame) -> pd.DataFrame:
    """Same PASS bar as every study. ROBUST: PASS + ex-top-5 > 0 + each side that is traded is positive
    (P3/P5 are call-only by design, so a missing PE side does not count against them)."""
    s = summarize_timing(t)
    sides_ok = [all(v > 0 for v in (r["CE"], r["PE"]) if v is not None and not pd.isna(v)) for _, r in s.iterrows()]
    s["ROBUST"] = s["PASS"] & pd.Series(sides_ok, index=s.index) & (s["ex_top5"].fillna(0) > 0)
    s["sample"] = np.where(s["n"] >= 100, "ok", "INSUFFICIENT")
    return s


def stage_b(store: MarketStore, costs: CostModel, expiries: list[date], start: date, end: date) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for d, g, c in contexts(store, expiries, start, end):
        cache: dict[str, pd.DataFrame] = {}
        g_day = {"G1_day": c["open_outside"] and c["narrow_or"], "G2_day": c["open_outside"] and c["low_vol"]}
        for name, (fn, rule, stop) in STRATEGIES.items():
            e = fn(g, c)
            if e is None:
                continue
            sym = option_symbol(e)
            if sym not in cache:
                cache[sym] = store.candles(sym, "1minute", datetime.combine(d, time(9, 15)),
                                           datetime.combine(d, time(15, 30)))
            if cache[sym].empty:
                continue
            tr = simulate(e, cache[sym], g, rule, stop_pct=stop)
            if tr is None:
                continue
            cst = costs.round_trip(tr["entry_px"], tr["exit_px"], LOT).total
            net = tr["pts"] * LOT - cst
            rows.append({**tr, **g_day, "variant": name, "net_inr": net, "net2_inr": net - cst,
                         "r_net": net / (tr["risk_pts"] * LOT), "delay_min": np.nan})
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    days_ = sorted(t["day"].unique())
    n = len(days_)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(days_)}
    t["split"] = t["day"].map(split)
    t["half"] = np.where(t["day"] <= days_[n // 2], "H1", "H2")
    return t
