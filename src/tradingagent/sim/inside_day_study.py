"""Inside-day setups study (`tradingagent backtest-inside`). Spec: docs/reports/2026-10-02_inside_day_study.md
(pre-declared). NEW code only; G1/G2 untouched. Works on any underlying (Nifty / Bank Nifty).
"""

from collections.abc import Callable, Iterator
from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.discovery_study import follow, random_entry
from tradingagent.sim.entry_study import five_min
from tradingagent.sim.exit_study import LOT, Entry, Rule, State, rule_none, simulate
from tradingagent.sim.stop_study import _five_min_close, rule_or_opposite
from tradingagent.sim.timing_study import opening_range

NAN = float("nan")
SIGNAL_END = time(13, 30)
Ctx = dict[str, Any]
Strategy = Callable[[pd.DataFrame, Ctx], Entry | None]


def _e(c: Ctx, ts: pd.Timestamp, side: str, close: float, hi: float = NAN, lo: float = NAN) -> Entry:
    step = c["step"]
    return Entry(c["day"], ts.to_pydatetime(), side, int(round(close / step) * step), c["expiry"], hi, lo)


def _bars(g: pd.DataFrame, start: time = time(9, 30), end: time = SIGNAL_END) -> pd.DataFrame:
    b = five_min(g)
    return b[(b.index.time > start) & (b.index.time <= end)]


# ---------------------------------------------------------------------------- candidates
def n1_rejection(g: pd.DataFrame, c: Ctx) -> Entry | None:
    """Trades at/through PDH but closes back below → PE (exit: close back above PDH). Mirror at PDL."""
    for ts, b in _bars(g).iterrows():
        if b["high"] >= c["pdh"] and b["close"] < c["pdh"]:
            return _e(c, ts, "PE", b["close"], hi=c["pdh"])
        if b["low"] <= c["pdl"] and b["close"] > c["pdl"]:
            return _e(c, ts, "CE", b["close"], lo=c["pdl"])
    return None


def n2_acceptance(g: pd.DataFrame, c: Ctx) -> Entry | None:
    """Three consecutive 5-min closes beyond PDH → CE (exit: close back below PDH). Mirror at PDL."""
    run_up = run_dn = 0
    for ts, b in _bars(g, time(9, 15)).iterrows():
        run_up = run_up + 1 if b["close"] > c["pdh"] else 0
        run_dn = run_dn + 1 if b["close"] < c["pdl"] else 0
        if ts.time() <= time(9, 30):
            continue
        if run_up >= 3:
            return _e(c, ts, "CE", b["close"], lo=c["pdh"])
        if run_dn >= 3:
            return _e(c, ts, "PE", b["close"], hi=c["pdl"])
    return None


def n3_quiet_expansion(g: pd.DataFrame, c: Ctx) -> Entry | None:
    first = g[g["ts"].dt.time < time(10, 15)]
    atr = c["atr_pts"]
    if len(first) < 50 or not atr or np.isnan(atr):
        return None
    hi, lo = float(first["high"].max()), float(first["low"].min())
    if hi - lo >= 0.25 * atr:
        return None
    for ts, b in _bars(g, time(10, 15)).iterrows():
        if b["close"] > hi:
            return _e(c, ts, "CE", b["close"], hi=hi, lo=lo)
        if b["close"] < lo:
            return _e(c, ts, "PE", b["close"], hi=hi, lo=lo)
    return None


def n4_gap_fill(g: pd.DataFrame, c: Ctx) -> Entry | None:
    """Gap ≥ 0.25% (open still inside yesterday's range); first 5-min close beyond the 15-min OR towards
    yesterday's close → trade the fill. Entry carries target = prev close, stop side = the other OR side."""
    gap = (float(g["open"].iloc[0]) - c["prev_close"]) / c["prev_close"]
    r = opening_range(g)
    if abs(gap) < 0.0025 or r is None:
        return None
    hi, lo = r
    for ts, b in _bars(g).iterrows():
        if gap > 0 and b["close"] < lo:     # gap up → fill is down
            return _e(c, ts, "PE", b["close"], hi=hi, lo=c["prev_close"])
        if gap < 0 and b["close"] > hi:     # gap down → fill is up
            return _e(c, ts, "CE", b["close"], hi=c["prev_close"], lo=lo)
        if (gap > 0 and b["close"] > hi) or (gap < 0 and b["close"] < lo):
            return None                     # OR broke the other way first: no fill setup today
    return None


# ---------------------------------------------------------------------------- exits
def rule_level_back(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    """5-min close back on the wrong side of the level (CE: below or_low; PE: above or_high)."""
    if not _five_min_close(i):
        return None
    wrong = i["close"] < e.or_low if e.side == "CE" else i["close"] > e.or_high
    return "LEVEL_BACK" if wrong else None


def rule_gap_fill(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    """Target: 1-min index close reaches prev close. Stop: 5-min close beyond the other OR side."""
    if e.side == "CE":
        if i["close"] >= e.or_high:
            return "GAP_FILLED"
        return "OR_OPPOSITE_SIDE" if _five_min_close(i) and i["close"] < e.or_low else None
    if i["close"] <= e.or_low:
        return "GAP_FILLED"
    return "OR_OPPOSITE_SIDE" if _five_min_close(i) and i["close"] > e.or_high else None


CANDIDATES: dict[str, tuple[Strategy, Rule, float]] = {
    "N1_rejection": (n1_rejection, rule_level_back, 0.30),
    "N2_acceptance": (n2_acceptance, rule_level_back, 0.50),
    "N3_quiet_expansion": (n3_quiet_expansion, rule_or_opposite, 0.50),
    "N4_gap_fill": (n4_gap_fill, rule_gap_fill, 0.50),
    "RANDOM": (random_entry, rule_none, 0.30),     # on the same inside days only
}


# ---------------------------------------------------------------------------- day loop
def contexts(store: MarketStore, underlying: str, expiries: list[date], start: date, end: date,
             step: int) -> Iterator[tuple[date, pd.DataFrame, Ctx]]:
    idx = store.candles(f"NSE-{underlying}", "1minute")
    idx["day"] = idx["ts"].dt.date
    daily = idx.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                   close=("close", "last"))
    atr = (daily["high"] - daily["low"]).shift(1).rolling(14).mean()
    days = list(daily.index)
    exp_set = set(expiries)
    for k, (d, g) in enumerate(idx.groupby("day")):
        if not (start <= d <= end) or d in exp_set or k == 0:
            continue
        nxt = [e for e in expiries if e > d]
        if not nxt:
            continue
        p = days[days.index(d) - 1]
        pdh, pdl, pc = (float(daily.at[p, x]) for x in ("high", "low", "close"))
        if not (pdl <= float(daily.at[d, "open"]) <= pdh):
            continue                                       # inside-open days only
        yield d, g.reset_index(drop=True), {"day": d, "expiry": nxt[0], "pdh": pdh, "pdl": pdl, "prev_close": pc,
                                            "atr_pts": float(atr[d]) if pd.notna(atr[d]) else NAN, "step": step}


def stage_a(store: MarketStore, underlying: str, expiries: list[date], start: date, end: date,
            step: int) -> pd.DataFrame:
    rows = []
    for d, g, c in contexts(store, underlying, expiries, start, end, step):
        for name, (fn, _, _) in CANDIDATES.items():
            e = fn(g, c)
            if e is None:
                continue
            rows.append({"setup": name, "day": d, "side": e.side, "entry_ts": e.signal_ts,
                         "follow_60": follow(g, e.signal_ts, e.side, 60, c["atr_pts"]),
                         "follow_eod": follow(g, e.signal_ts, e.side, None, c["atr_pts"])})
    return pd.DataFrame(rows)


def resplit(t: pd.DataFrame) -> pd.DataFrame:
    """60/20/20 dev/validate/test and halves by date, computed within the given trades only."""
    t = t.copy()
    if t.empty:
        return t
    days_ = sorted(t["day"].unique())
    n = len(days_)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(days_)}
    t["split"] = t["day"].map(split)
    t["half"] = np.where(t["day"] <= days_[n // 2], "H1", "H2")
    return t


def stage_b(store: MarketStore, costs: CostModel, underlying: str, expiries: list[date], setups: list[str],
            start: date, end: date, step: int = 50, lot: int = LOT) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    chosen = {k: v for k, v in CANDIDATES.items() if k in setups or k == "RANDOM"}
    for d, g, c in contexts(store, underlying, expiries, start, end, step):
        for name, (fn, rule, stop) in chosen.items():
            e = fn(g, c)
            if e is None:
                continue
            if name == "RANDOM":   # e_random rounds to Nifty's 50 grid; put it on this index's grid
                px = float(g[g["ts"] < pd.Timestamp(e.signal_ts)]["close"].iloc[-1])
                e = _e(c, pd.Timestamp(e.signal_ts), e.side, px, e.or_high, e.or_low)
            sym = f"NSE-{underlying}-{e.expiry.strftime('%d%b%y')}-{e.strike}-{e.side}"
            opt = store.candles(sym, "1minute", datetime.combine(d, time(9, 15)), datetime.combine(d, time(15, 30)))
            if opt.empty:
                continue
            tr = simulate(e, opt, g, rule, stop_pct=stop)
            if tr is None:
                continue
            cst = costs.round_trip(tr["entry_px"], tr["exit_px"], lot).total
            net = tr["pts"] * lot - cst
            rows.append({**tr, "variant": name, "net_inr": net, "net2_inr": net - cst,
                         "r_net": net / (tr["risk_pts"] * lot), "delay_min": np.nan})
    return resplit(pd.DataFrame(rows))
