"""Entry-timing study (`tradingagent backtest-timing`). Spec: docs/reports/2026-10-01_entry_timing_study.md.

Exits are held fixed from the stop study; only the ENTRY moment changes. A 1-min bar stamped t closes at
t+1min, so a 1-min signal on bar t enters at the open of bar t+1 (signal_ts = t + 1 minute).
"""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.entry_study import day_features, e_orb, e_twap_pullback
from tradingagent.sim.exit_study import LOT, STEP, Entry, metrics, option_symbol, rule_none, simulate
from tradingagent.sim.stop_study import rule_or_opposite

SIGNAL_END = time(13, 30)
RETEST_ZONE = 0.10      # × OR width
RETEST_WINDOW_MIN = 30
CHASE_LIMIT = 0.50      # × OR width


def _next_expiry(d: date, expiries: list[date]) -> date | None:
    nxt = [e for e in expiries if e > d]
    return nxt[0] if nxt else None


def _mk(d: date, ts: pd.Timestamp, side: str, close: float, exp: date, hi: float, lo: float) -> Entry:
    return Entry(d, ts.to_pydatetime(), side, int(round(close / STEP) * STEP), exp, hi, lo)


def opening_range(g: pd.DataFrame) -> tuple[float, float] | None:
    o = g[g["ts"].dt.time < time(9, 30)]
    if len(o) < 10:
        return None
    return float(o["high"].max()), float(o["low"].min())


def first_1min_break(g: pd.DataFrame, hi: float, lo: float) -> tuple[pd.Timestamp, str, float] | None:
    """First 1-min CLOSE beyond the range (bar time, side, close), within 09:30–13:30."""
    w = g[(g["ts"].dt.time >= time(9, 30)) & (g["ts"].dt.time < SIGNAL_END)]
    for _, b in w.iterrows():
        if b["close"] > hi:
            return b["ts"], "CE", float(b["close"])
        if b["close"] < lo:
            return b["ts"], "PE", float(b["close"])
    return None


def extension(close: float, side: str, hi: float, lo: float) -> float:
    w = hi - lo
    return (close - hi) / w if side == "CE" else (lo - close) / w


def s1_variants(g: pd.DataFrame, d: date, expiries: list[date]) -> dict[str, Entry | None]:
    out: dict[str, Entry | None] = {k: None for k in ("S1-A", "S1-B", "S1-C", "S1-D(A)", "S1-D(B)")}
    exp = _next_expiry(d, expiries)
    r = opening_range(g)
    if exp is None or r is None:
        return out
    hi, lo = r
    w = hi - lo
    # A: current 5-min rule (reuses the study-#2 implementation)
    a = e_orb(15)(g, {"day": d}, expiries)
    out["S1-A"] = a
    if a is not None:
        sig_close = float(g[g["ts"] < a.signal_ts]["close"].iloc[-1])
        out["S1-D(A)"] = a if extension(sig_close, a.side, hi, lo) <= CHASE_LIMIT else None
    # B: first 1-min close beyond the range
    fb = first_1min_break(g, hi, lo)
    if fb is None:
        return out
    tb, side, cb = fb
    b = _mk(d, tb + timedelta(minutes=1), side, cb, exp, hi, lo)
    out["S1-B"] = b
    out["S1-D(B)"] = b if extension(cb, side, hi, lo) <= CHASE_LIMIT else None
    # C: retest after the first 1-min break
    later = g[(g["ts"] > tb) & (g["ts"] <= tb + timedelta(minutes=RETEST_WINDOW_MIN))
              & (g["ts"].dt.time < SIGNAL_END)]
    for _, bar in later.iterrows():
        if (side == "CE" and bar["close"] < lo) or (side == "PE" and bar["close"] > hi):
            break  # full failure before any retest → cancel
        touched = bar["low"] <= hi + RETEST_ZONE * w if side == "CE" else bar["high"] >= lo - RETEST_ZONE * w
        held = bar["close"] > hi if side == "CE" else bar["close"] < lo
        if touched and held:
            out["S1-C"] = _mk(d, bar["ts"] + timedelta(minutes=1), side, float(bar["close"]), exp, hi, lo)
            break
    return out


def s2_fast(g: pd.DataFrame, d: date, expiries: list[date]) -> Entry | None:
    """S2-B: the S2 pullback condition on a 1-min bar."""
    exp = _next_expiry(d, expiries)
    if exp is None:
        return None
    s = g.set_index("ts")["close"]
    twap = s.expanding().mean()  # value at bar t includes bar t's close (known at t+1min)
    r = opening_range(g) or (np.nan, np.nan)
    for ts, b in g.set_index("ts").iterrows():
        if not (time(10, 0) <= ts.time() < SIGNAL_END):
            continue
        tw = twap.loc[ts]
        then = twap[:ts - timedelta(minutes=30)]
        if then.empty:
            continue
        slope = tw - then.iloc[-1]
        if slope > 0 and b["low"] <= tw * 1.0005 and b["close"] > tw:
            return _mk(d, ts + timedelta(minutes=1), "CE", float(b["close"]), exp, *r)
        if slope < 0 and b["high"] >= tw * 0.9995 and b["close"] < tw:
            return _mk(d, ts + timedelta(minutes=1), "PE", float(b["close"]), exp, *r)
    return None


def run_timing_study(store: MarketStore, costs: CostModel) -> tuple[pd.DataFrame, pd.DataFrame]:
    expiries = [r[0] for r in store.con.execute(
        "SELECT DISTINCT expiry FROM contracts WHERE kind='CE' ORDER BY expiry").fetchall()]
    exp_set = set(expiries)
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    feats = day_features(idx)
    rows: list[dict[str, Any]] = []
    for d, g in idx.groupby("day"):
        if d in exp_set:
            continue
        g = g.reset_index(drop=True)
        r = opening_range(g)
        fb = first_1min_break(g, *r) if r else None
        variants: dict[str, tuple[Entry | None, Callable[..., Any], float]] = {}
        if bool(feats.at[d, "narrow_or"]):
            for k, e in s1_variants(g, d, expiries).items():
                variants[k] = (e, rule_or_opposite, 0.50)
        if feats.at[d, "high_vol"] == False:  # noqa: E712 — NaN (warm-up) days excluded, as in the stop study
            variants["S2-A"] = (e_twap_pullback(g, {"day": d}, expiries), rule_none, 0.30)
            variants["S2-B"] = (s2_fast(g, d, expiries), rule_none, 0.30)
        cache: dict[str, pd.DataFrame] = {}
        for name, (e, rule, stop) in variants.items():
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
            c = costs.round_trip(tr["entry_px"], tr["exit_px"], LOT).total
            delay = None
            if name.startswith("S1") and fb is not None:
                delay = (pd.Timestamp(tr["entry_ts"]) - (fb[0] + timedelta(minutes=1))).total_seconds() / 60
            rows.append({**tr, "variant": name, "net_inr": tr["pts"] * LOT - c, "net2_inr": tr["pts"] * LOT - 2 * c,
                         "r_net": (tr["pts"] * LOT - c) / (tr["risk_pts"] * LOT), "delay_min": delay})
    trades = pd.DataFrame(rows)
    days = sorted(trades["day"].unique())
    n = len(days)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(days)}
    trades["split"] = trades["day"].map(split)
    trades["half"] = np.where(trades["day"] <= days[n // 2], "H1", "H2")
    return trades, summarize_timing(trades)


def bootstrap_ci(v: np.ndarray, runs: int = 5000, seed: int = 1) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    bs = np.array([rng.choice(v, len(v)).mean() for _ in range(runs)])
    return float(np.quantile(bs, 0.025)), float(np.quantile(bs, 0.975)), float((bs <= 0).mean())


def summarize_timing(trades: pd.DataFrame) -> pd.DataFrame:
    out = []
    for name, g in trades.groupby("variant"):
        m = metrics(g)
        parts = {p: metrics(g[g["split"] == p]).get("exp_inr") for p in ("dev", "validate", "test")}
        halves = {h: metrics(g[g["half"] == h]).get("exp_inr") for h in ("H1", "H2")}
        sides = {s: metrics(g[g["side"] == s]).get("exp_inr") for s in ("CE", "PE")}
        top = g.sort_values("net_inr", ascending=False)["net_inr"]
        ex_top5 = float(top.iloc[5:].mean()) if len(top) > 5 else None
        exp2 = float(g["net2_inr"].mean())
        lo, hi, p0 = bootstrap_ci(g["net_inr"].to_numpy())
        ok = (m["n"] >= 100 and all(v is not None and v > 0 for v in parts.values()) and exp2 > 0
              and (m.get("pf") or 0) >= 1.10 and all(v is not None and v > 0 for v in halves.values()))
        robust = ok and all(v is not None and v > 0 for v in sides.values()) and (ex_top5 or 0) > 0
        failed = g["reason"].isin(["STOP", "OR_OPPOSITE_SIDE"]).mean()
        valtest = g[g["split"].isin(["validate", "test"])]["net_inr"].mean()
        out.append({"variant": name, "n": m["n"], "win": m["win_rate"], "net": m["exp_inr"], "net_2x": round(exp2, 1),
                    "pf": m.get("pf"), "dev": parts["dev"], "val": parts["validate"], "test": parts["test"],
                    "val+test": round(float(valtest), 1), "CE": sides["CE"], "PE": sides["PE"],
                    "ex_top5": None if ex_top5 is None else round(ex_top5, 1),
                    "ci95": f"[{lo:.0f}, {hi:.0f}]", "P(<=0)": round(p0, 2), "failed_share": round(float(failed), 3),
                    "median_delay_min": None if g["delay_min"].isna().all() else float(g["delay_min"].median()),
                    "PASS": ok, "ROBUST": robust})
    return pd.DataFrame(out)


def verdict(summary: pd.DataFrame) -> pd.DataFrame:
    """Pre-declared decision: beats its setup's A on dev AND on validate+test combined."""
    rows = []
    for setup in ("S1", "S2"):
        base = summary[summary["variant"] == f"{setup}-A"]
        if base.empty:
            continue
        b = base.iloc[0]
        for _, v in summary[summary["variant"].str.startswith(setup) & (summary["variant"] != f"{setup}-A")].iterrows():
            better = (v["dev"] or -1e9) > (b["dev"] or -1e9) and v["val+test"] > b["val+test"]
            rows.append({"variant": v["variant"], "dev_vs_A": round((v["dev"] or 0) - (b["dev"] or 0), 1),
                         "valtest_vs_A": round(v["val+test"] - b["val+test"], 1), "BEATS_A": bool(better),
                         "ROBUST": bool(v["ROBUST"])})
    return pd.DataFrame(rows)
