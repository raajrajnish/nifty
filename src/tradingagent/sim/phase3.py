"""Phase 3 of the independent review: hypotheses P1–P4 (pre-declared in docs/reports/2026-10-02_p{1..4}_*.md).

RESEARCH ONLY — paper only, no order code. Rules here are copied from the pre-declarations and must not be
tuned after a window is opened. Windows: DESIGN = 2023-12-01 → 2025-06-30, TEST = 2025-07-01 → 2026-09-30
(opened once, only after a design pass). Prices: 1-min Groww candles; fills at bar open/close ± half-spread.
"""

import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.exit_study import Entry, rule_none, simulate
from tradingagent.sim.timing_study import bootstrap_ci

LOT = 65
STEP = 50
HS = 0.0011
EXIT_T = time(15, 10)
DESIGN = (date(2023, 12, 1), date(2025, 6, 30))
TEST = (date(2025, 7, 1), date(2026, 9, 30))
LABELS = [(datetime(2000, 1, 1, 10, 0) + timedelta(minutes=5 * i)).time() for i in range(43)]  # 10:00 … 13:30


# ---------------------------------------------------------------------------- costs & stats
@dataclass(frozen=True)
class Leg:
    entry_raw: float   # traded price before spread
    exit_raw: float


def leg_net(costs: CostModel, leg: Leg, mult: float = 1.0) -> float:
    """Net ₹ for 1 lot: half-spread on both sides and Groww charges, both scaled by `mult` (2.0 = 2× costs)."""
    e = leg.entry_raw * (1 + HS * mult)
    x = leg.exit_raw * (1 - HS * mult)
    return (x - e) * LOT - costs.round_trip(e, x, LOT).total * mult


def legs_from_sim(tr: dict[str, Any]) -> Leg:
    """Undo exit_study.simulate's 1× half-spread so costs can be re-applied at any multiple."""
    return Leg(tr["entry_px"] / (1 + HS), tr["exit_px"] / (1 - HS))


def stats(net: "pd.Series[float]", net2: "pd.Series[float]",
          control: "pd.Series[float] | None" = None) -> dict[str, Any]:
    v = net.dropna().to_numpy()
    if len(v) < 5:
        return {"n": len(v)}
    lo, hi, p0 = bootstrap_ci(v)
    out = {"n": len(v), "net": round(float(v.mean()), 1), "net_2x": round(float(net2.mean()), 1),
           "win": round(float((v > 0).mean()), 3), "ci95": f"[{lo:.0f}, {hi:.0f}]", "P(<=0)": round(p0, 4),
           "ex_top5": round(float(np.sort(v)[::-1][5:].mean()), 1) if len(v) > 5 else None}
    if control is not None:
        out["control_n"] = int(control.notna().sum())
        out["control_net"] = round(float(control.mean()), 1)
    return out


def passes(s: dict[str, Any], min_n: int, p_max: float, need_control: bool = True) -> bool:
    if s.get("n", 0) < min_n:
        return False
    ok = s["net"] > 0 and s["net_2x"] > 0 and s["P(<=0)"] <= p_max
    if need_control:
        ok = ok and s["net"] > s.get("control_net", math.inf)
    return bool(ok)


# ---------------------------------------------------------------------------- data access
class Data:
    def __init__(self, store: MarketStore) -> None:
        self.store = store
        self.expiries = [r[0] for r in store.con.execute(
            "SELECT DISTINCT expiry FROM contracts WHERE kind='CE' AND underlying='NIFTY' ORDER BY expiry").fetchall()]
        self.exp_set = set(self.expiries)
        self.idx = self._by_day("NSE-NIFTY")

    def _by_day(self, sym: str) -> dict[date, pd.DataFrame]:
        df = self.store.candles(sym, "1minute")
        df["day"] = df["ts"].dt.date
        return {d: g.drop(columns="day").reset_index(drop=True) for d, g in df.groupby("day")}

    def next_expiry(self, d: date) -> date | None:
        return next((e for e in self.expiries if e > d), None)

    def option(self, d: date, expiry: date, strike: int, side: str) -> pd.DataFrame:
        sym = f"NSE-NIFTY-{expiry.strftime('%d%b%y')}-{strike}-{side}"
        return self.store.candles(sym, "1minute", datetime.combine(d, time(9, 15)), datetime.combine(d, time(15, 30)))

    def days(self, window: tuple[date, date]) -> Iterator[date]:
        return (d for d in sorted(self.idx) if window[0] <= d <= window[1])


def close_before(g: pd.DataFrame, label: time) -> float | None:
    """Close of the 1-minute bar that ends at `label` (the bar stamped label − 1 min), or the last one before it."""
    t = (datetime.combine(date.min, label) - timedelta(minutes=1)).time()
    s = g[g["ts"].dt.time <= t]
    return None if s.empty else float(s["close"].iloc[-1])


def hold_leg(opt: pd.DataFrame, entry_ts: datetime, exit_t: time = EXIT_T) -> Leg | None:
    """Buy at the open of the first bar at/after entry_ts (≤ 3 min late), sell at the close of the last bar ≤ exit_t."""
    if opt.empty:
        return None
    a = opt[opt["ts"] >= pd.Timestamp(entry_ts)]
    if a.empty or (pd.Timestamp(a["ts"].iloc[0]) - pd.Timestamp(entry_ts)).total_seconds() > 180:
        return None
    b = opt[opt["ts"].dt.time <= exit_t]
    if b.empty or b["ts"].iloc[-1] < a["ts"].iloc[0]:
        return None
    return Leg(float(a["open"].iloc[0]), float(b["close"].iloc[-1]))


def atm(px: float) -> int:
    return int(round(px / STEP) * STEP)


# ---------------------------------------------------------------------------- P1: straddle value at 09:30
def weekdays_incl(d: date, e: date) -> int:
    return sum(1 for i in range((e - d).days + 1) if (d + timedelta(days=i)).weekday() < 5)


def p1_ratio(or_width: float, straddle: float, bdays: int) -> float:
    return or_width / (straddle / math.sqrt(max(bdays, 1)))


def p1_signals(ratio: "pd.Series[float]") -> "pd.Series[bool]":
    """R above the 67th percentile of the previous 60 eligible days (≥ 30 needed). Unknown → no signal."""
    thr = ratio.shift(1).rolling(60, min_periods=30).quantile(0.67)
    return (ratio > thr).fillna(False).astype(bool)


def p1_rows(data: Data, start: date, end: date) -> pd.DataFrame:
    """Per eligible day: ratio R (known at 09:30) and the two straddle legs (entry 09:30, exit 15:10)."""
    rows = []
    for d in data.days((start, end)):
        if d in data.exp_set:
            continue
        exp = data.next_expiry(d)
        g = data.idx[d]
        o = g[g["ts"].dt.time < time(9, 30)]
        if exp is None or len(o) < 10:
            continue
        k = atm(float(o["close"].iloc[-1]))
        t0 = datetime.combine(d, time(9, 30))
        legs = {s: hold_leg(data.option(d, exp, k, s), t0) for s in ("CE", "PE")}
        if legs["CE"] is None or legs["PE"] is None:
            continue
        straddle = legs["CE"].entry_raw + legs["PE"].entry_raw
        r = p1_ratio(float(o["high"].max() - o["low"].min()), straddle, weekdays_incl(d, exp))
        rows.append({"day": d, "expiry": exp, "strike": k, "straddle": straddle, "R": r,
                     "ce": legs["CE"], "pe": legs["PE"]})
    return pd.DataFrame(rows)


def straddle_net(costs: CostModel, ce: Leg, pe: Leg, mult: float = 1.0) -> float:
    return leg_net(costs, ce, mult) + leg_net(costs, pe, mult)


# ---------------------------------------------------------------------------- P2: expiry day (0DTE)
def p2_breakout(g: pd.DataFrame) -> tuple[pd.Timestamp, str, float, float, float] | None:
    """First 5-min bar labelled 13:05–14:30 closing beyond the 09:15–12:59 range → (label ts, side, close, hi, lo)."""
    morning = g[g["ts"].dt.time < time(13, 0)]
    if len(morning) < 100:
        return None
    hi, lo = float(morning["high"].max()), float(morning["low"].min())
    five = g.set_index("ts")["close"].resample("5min", label="right", closed="left").last().dropna()
    for ts, c in five.items():
        if time(13, 5) <= ts.time() <= time(14, 30):
            if c > hi:
                return ts, "CE", float(c), hi, lo
            if c < lo:
                return ts, "PE", float(c), hi, lo
    return None


def p2_rows(data: Data, costs: CostModel, start: date, end: date) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for d in data.days((start, end)):
        if d not in data.exp_set:
            continue
        g = data.idx[d]
        for name, t in (("M1-0930", time(9, 30)), ("M1-1100", time(11, 0)), ("M1-1330", time(13, 30))):
            px = close_before(g, t)
            if px is None:
                continue
            k, t0 = atm(px), datetime.combine(d, t)
            ce, pe = hold_leg(data.option(d, d, k, "CE"), t0), hold_leg(data.option(d, d, k, "PE"), t0)
            if ce is None or pe is None:
                continue
            rows.append({"day": d, "m": name, "net": straddle_net(costs, ce, pe),
                         "net2": straddle_net(costs, ce, pe, 2),
                         "gross": (ce.exit_raw - ce.entry_raw + pe.exit_raw - pe.entry_raw) * LOT, "control": np.nan})
        b = p2_breakout(g)
        if b is None:
            continue
        ts, side, c, hi, lo = b
        k = atm(c)
        opt = data.option(d, d, k, side)
        tr = simulate(Entry(d, ts.to_pydatetime(), side, k, d, hi, lo), opt, g, rule_none, stop_pct=0.50) \
            if not opt.empty else None
        if tr is None:
            continue
        leg = legs_from_sim(tr)
        other = hold_leg(data.option(d, d, k, "PE" if side == "CE" else "CE"), ts.to_pydatetime())
        own_hold = hold_leg(opt, ts.to_pydatetime())
        ctrl = straddle_net(costs, own_hold, other) if own_hold and other else np.nan
        rows.append({"day": d, "m": "M2", "net": leg_net(costs, leg), "net2": leg_net(costs, leg, 2),
                     "gross": (leg.exit_raw - leg.entry_raw) * LOT, "control": ctrl})
    return pd.DataFrame(rows)


def p2_pin(data: Data, start: date, end: date) -> pd.DataFrame:
    rows = []
    for d in data.days((start, end)):
        px = close_before(data.idx[d], time(15, 11))
        if px is not None:
            rows.append({"day": d, "expiry_day": d in data.exp_set, "dist100": abs(px - round(px / 100) * 100)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------- P3: VIX up, index flat → PE
def p3_signal(n: pd.DataFrame, v: pd.DataFrame, dv: float = 0.03, dn: float = 0.003) -> time | None:
    """First 5-min label 10:00–13:30 where VIX is ≥ dv above and NIFTY within ±dn of their 09:19-bar closes."""
    n0, v0 = close_before(n, time(9, 20)), close_before(v, time(9, 20))
    if not n0 or not v0:
        return None
    for lab in LABELS:
        nc, vc = close_before(n, lab), close_before(v, lab)
        if nc is None or vc is None:
            continue
        if vc / v0 - 1 >= dv and abs(nc / n0 - 1) <= dn:
            return lab
    return None


# ---------------------------------------------------------------------------- P4: Nifty vs Bank Nifty spread
def p4_rel(n: pd.DataFrame, b: pd.DataFrame) -> dict[time, float]:
    """rel at each label = ln(BN/BN_open) − ln(N/N_open), from closes of the minute before the label."""
    if n.empty or b.empty:
        return {}
    n_open, b_open = float(n["open"].iloc[0]), float(b["open"].iloc[0])
    out = {}
    for lab in LABELS:
        nc, bc = close_before(n, lab), close_before(b, lab)
        if nc is not None and bc is not None:
            out[lab] = math.log(bc / b_open) - math.log(nc / n_open)
    return out


def p4_signals(rel: pd.DataFrame, z: float = 2.0) -> dict[date, tuple[time, int, float]]:
    """rel: rows = days (sorted), columns = labels. SD per label over the previous 60 days (≥ 30). First |z| ≥ z."""
    sd = rel.rolling(60, min_periods=30).std().shift(1)
    zz = rel / sd
    out: dict[date, tuple[time, int, float]] = {}
    for d, row in zz.iterrows():
        for lab in rel.columns:
            v = row[lab]
            if pd.notna(v) and abs(v) >= z:
                out[d] = (lab, 1 if rel.at[d, lab] > 0 else -1, float(rel.at[d, lab]))
                break
    return out
