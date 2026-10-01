"""Discovery study (`tradingagent backtest-discovery`). Spec: docs/reports/2026-10-01_discovery_study.md.

NEW code only — G1/G2 (frozen, tag v1-hypercare-freeze) are not touched. Stage A tests DIRECTION logic on
untouched index data (Oct 2021 – Nov 2023); Stage B tests option P&L (Dec 2023 – Sep 2026) for A-passers.
"""

import csv
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.entry_study import day_features, e_orb, e_random, e_twap_pullback, five_min
from tradingagent.sim.exit_study import LOT, STEP, Entry, Rule, option_symbol, rule_none, simulate
from tradingagent.sim.logic_study import logic_features
from tradingagent.sim.stop_study import rule_or_opposite
from tradingagent.sim.timing_study import bootstrap_ci, opening_range, summarize_timing

SIGNAL_END = time(13, 30)
STAGE_A = (date(2021, 10, 1), date(2023, 11, 30))
STAGE_B = (date(2023, 12, 1), date(2026, 9, 30))

Ctx = dict[str, Any]


def _entry(d: date, ts: pd.Timestamp, side: str, close: float, exp: date, hi: float, lo: float) -> Entry:
    return Entry(d, ts.to_pydatetime(), side, int(round(close / STEP) * STEP), exp, hi, lo)


# ---------------------------------------------------------------------------- candidate setups
def h1_failed_breakout(g: pd.DataFrame, c: Ctx) -> Entry | None:
    """First 5-min close beyond one OR side, then a later 5-min close beyond the OPPOSITE side → trade it."""
    r = opening_range(g)
    if r is None:
        return None
    hi, lo = r
    first: str | None = None
    for ts, b in five_min(g).iterrows():
        if not (time(9, 30) < ts.time() <= SIGNAL_END):
            continue
        if first is None:
            first = "up" if b["close"] > hi else "down" if b["close"] < lo else None
            continue
        if first == "up" and b["close"] < lo:
            return _entry(c["day"], ts, "PE", b["close"], c["expiry"], hi, lo)   # exit if close > OR high
        if first == "down" and b["close"] > hi:
            return _entry(c["day"], ts, "CE", b["close"], c["expiry"], hi, lo)   # exit if close < OR low
    return None


def h2_prev_level_breakout(g: pd.DataFrame, c: Ctx) -> Entry | None:
    """Inside-open day: first 5-min close above PDH → CE / below PDL → PE. Exit: close back past PD midpoint."""
    if c["open_outside"] or c["pdh"] is None:
        return None
    mid = (c["pdh"] + c["pdl"]) / 2
    for ts, b in five_min(g).iterrows():
        if not (time(9, 30) < ts.time() <= SIGNAL_END):
            continue
        if b["close"] > c["pdh"]:
            return _entry(c["day"], ts, "CE", b["close"], c["expiry"], mid, mid)  # or_low=mid → exit below mid
        if b["close"] < c["pdl"]:
            return _entry(c["day"], ts, "PE", b["close"], c["expiry"], mid, mid)  # or_high=mid → exit above mid
    return None


def h3_afternoon_continuation(g: pd.DataFrame, c: Ctx) -> Entry | None:
    """At 13:00: above TWAP with the day high made after 12:00 → CE; mirror → PE."""
    upto = g[g["ts"].dt.time < time(13, 0)]
    if len(upto) < 200:
        return None
    twap = float(upto["close"].mean())
    close = float(upto["close"].iloc[-1])
    hi_t = upto.loc[upto["high"].idxmax(), "ts"].time()
    lo_t = upto.loc[upto["low"].idxmin(), "ts"].time()
    up = close > twap and hi_t >= time(12, 0)
    down = close < twap and lo_t >= time(12, 0)
    if up == down:
        return None
    ts = pd.Timestamp(datetime.combine(c["day"], time(13, 0)))
    r = opening_range(g) or (np.nan, np.nan)
    return _entry(c["day"], ts, "CE" if up else "PE", close, c["expiry"], *r)


def h4_opening_drive(g: pd.DataFrame, c: Ctx) -> Entry | None:
    """Open outside + OR NOT narrow: if |09:29 close − 09:15 open| ≥ 0.5×OR width, trade that direction at 09:30."""
    if not c["open_outside"] or c["narrow_or"]:
        return None
    r = opening_range(g)
    if r is None:
        return None
    hi, lo = r
    o = g[g["ts"].dt.time < time(9, 30)]
    move = float(o["close"].iloc[-1] - o["open"].iloc[0])
    if abs(move) < 0.5 * (hi - lo):
        return None
    ts = pd.Timestamp(datetime.combine(c["day"], time(9, 30)))
    return _entry(c["day"], ts, "CE" if move > 0 else "PE", float(o["close"].iloc[-1]), c["expiry"], hi, lo)


def random_entry(g: pd.DataFrame, c: Ctx) -> Entry | None:
    return e_random(g, {"day": c["day"]}, [c["expiry"]])


# Out-of-sample MEASUREMENT of the frozen G1/G2 direction logic (same entry code as the playbook setups).
def g1_signal(g: pd.DataFrame, c: Ctx) -> Entry | None:
    if not (c["open_outside"] and c["narrow_or"]):
        return None
    return e_orb(15)(g, {"day": c["day"]}, [c["expiry"]])


def g2_signal(g: pd.DataFrame, c: Ctx) -> Entry | None:
    if not (c["open_outside"] and c["low_vol"]):
        return None
    return e_twap_pullback(g, {"day": c["day"]}, [c["expiry"]])


VALIDATION = {"G1_oos": (g1_signal, rule_or_opposite, 0.50), "G2_oos": (g2_signal, rule_none, 0.30),
              "RANDOM": (random_entry, rule_none, 0.30)}


CANDIDATES: dict[str, tuple[Callable[[pd.DataFrame, Ctx], Entry | None], Rule, float]] = {
    "H1_failed_breakout": (h1_failed_breakout, rule_or_opposite, 0.50),
    "H2_prev_level_breakout": (h2_prev_level_breakout, rule_or_opposite, 0.50),
    "H3_afternoon_continuation": (h3_afternoon_continuation, rule_none, 0.30),
    "H4_opening_drive": (h4_opening_drive, rule_or_opposite, 0.50),
    "RANDOM": (random_entry, rule_none, 0.30),
}


# ---------------------------------------------------------------------------- shared day loop
def load_expiries(path: Path) -> list[date]:
    with path.open(encoding="utf-8") as f:
        return sorted(date.fromisoformat(r["expiry"]) for r in csv.DictReader(f))


def day_contexts(store: MarketStore, expiries: list[date], start: date, end: date):  # type: ignore[no-untyped-def]
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    vixd = store.candles("NSE-INDIAVIX", "1day")
    vixd["day"] = vixd["ts"].dt.date
    feats, lf = day_features(idx), logic_features(idx, vixd)
    daily = idx.groupby("day").agg(high=("high", "max"), low=("low", "min"))
    exp_set = set(expiries)
    for d, g in idx.groupby("day"):
        if not (start <= d <= end) or d in exp_set:
            continue
        nxt = [e for e in expiries if e > d]
        prev = daily.index[daily.index < d]
        if not nxt or not len(prev):
            continue
        p = prev[-1]
        yield d, g.reset_index(drop=True), {
            "day": d, "expiry": nxt[0], "pdh": float(daily.at[p, "high"]), "pdl": float(daily.at[p, "low"]),
            "open_outside": bool(lf.at[d, "open_outside"]), "narrow_or": bool(feats.at[d, "narrow_or"]),
            "low_vol": feats.at[d, "high_vol"] == False,  # noqa: E712
            "atr_pts": float(lf.at[d, "atr_pts"]) if pd.notna(lf.at[d, "atr_pts"]) else np.nan,
        }


def follow(g: pd.DataFrame, entry_ts: datetime, side: str, minutes: int | None, atr: float) -> float:
    """Index move in the trade's direction, from the entry minute's OPEN, in ATR units."""
    s = g.set_index("ts")
    at = s[s.index >= pd.Timestamp(entry_ts)]
    if at.empty or not atr or np.isnan(atr):
        return np.nan
    i0 = float(at["open"].iloc[0])
    end = pd.Timestamp(datetime.combine(entry_ts.date(), time(15, 10))) if minutes is None \
        else pd.Timestamp(entry_ts) + timedelta(minutes=minutes)
    i1 = float(s[s.index <= end]["close"].iloc[-1])
    return (i1 - i0) / atr * (1 if side == "CE" else -1)


# ---------------------------------------------------------------------------- Stage A
def stage_a(store: MarketStore, expiries: list[date], start: date, end: date,
            setups: dict[str, Any] | None = None) -> pd.DataFrame:
    rows = []
    for d, g, c in day_contexts(store, expiries, start, end):
        for name, (fn, _, _) in (setups or CANDIDATES).items():
            e = fn(g, c)
            if e is None:
                continue
            rows.append({"setup": name, "day": d, "side": e.side, "entry_ts": e.signal_ts,
                         "follow_60": follow(g, e.signal_ts, e.side, 60, c["atr_pts"]),
                         "follow_eod": follow(g, e.signal_ts, e.side, None, c["atr_pts"])})
    return pd.DataFrame(rows)


def summarize_a(a: pd.DataFrame, min_n: int = 80) -> pd.DataFrame:
    a = a.dropna(subset=["follow_60", "follow_eod"])
    rnd = a[a["setup"] == "RANDOM"]
    rnd_right = float((rnd["follow_60"] > 0).mean() * 100) if len(rnd) else np.nan
    out = []
    for name, g in a.groupby("setup"):
        lo, hi, p0 = bootstrap_ci(g["follow_eod"].to_numpy()) if len(g) >= 10 else (np.nan, np.nan, np.nan)
        right = float((g["follow_60"] > 0).mean() * 100)
        ok = bool(len(g) >= min_n and right >= 53 and right >= rnd_right + 3
                  and g["follow_eod"].mean() > 0 and lo > 0)
        out.append({"setup": name, "n": len(g), "right_dir_60%": round(right, 1),
                    "random_right_60%": round(rnd_right, 1), "follow_60_atr": round(float(g["follow_60"].mean()), 3),
                    "follow_eod_atr": round(float(g["follow_eod"].mean()), 3), "eod_ci95": f"[{lo:.3f}, {hi:.3f}]",
                    "P(eod<=0)": round(p0, 2), "CE": int((g["side"] == "CE").sum()),
                    "PE": int((g["side"] == "PE").sum()), "PASS_A": ok if name != "RANDOM" else None})
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------- Stage B
def stage_b(store: MarketStore, costs: CostModel, expiries: list[date], setups: list[str],
            start: date = STAGE_B[0], end: date = STAGE_B[1]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    chosen = {k: v for k, v in CANDIDATES.items() if k in setups or k == "RANDOM"}
    for d, g, c in day_contexts(store, expiries, start, end):
        cache: dict[str, pd.DataFrame] = {}
        g_day = {"G1_day": c["open_outside"] and c["narrow_or"], "G2_day": c["open_outside"] and c["low_vol"]}
        for name, (fn, rule, stop) in chosen.items():
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
    days = sorted(t["day"].unique())
    n = len(days)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(days)}
    t["split"] = t["day"].map(split)
    t["half"] = np.where(t["day"] <= days[n // 2], "H1", "H2")
    return t


def summarize_b(t: pd.DataFrame) -> pd.DataFrame:
    s = summarize_timing(t)
    overlap = t.groupby("variant")[["G1_day", "G2_day"]].mean().round(3).reset_index()
    return s.merge(overlap, on="variant", how="left")


__all__ = ["CANDIDATES", "STAGE_A", "STAGE_B", "stage_a", "summarize_a", "stage_b", "summarize_b", "load_expiries"]
