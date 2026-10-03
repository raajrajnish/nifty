"""Round 2 research-based strategies (spec: docs/reports/2026-10-03_round2_strategies.md, pre-declared).
R1 overnight drift · R2 turn of the month · R4 index intraday momentum · R5 weekly reversal · R6 VRP (research only,
selling). Rules are copied from the spec and must not be tuned. Paper research only; no order code.
"""

import math
from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.phase3 import LOT, Leg, leg_net
from tradingagent.sim.swing_study import NOTIONAL, DeliveryCosts
from tradingagent.sim.timing_study import bootstrap_ci

HALVES = {"H-A": (date(2024, 1, 1), date(2025, 6, 30)), "H-B": (date(2025, 7, 1), date(2026, 9, 30))}
STOCK_SLIP = 0.0005


def half_of(d: date, halves: dict[str, tuple[date, date]] | None = None) -> str | None:
    return next((h for h, (a, b) in (halves or HALVES).items() if a <= d <= b), None)


def opt_sym(exp: date, strike: int, side: str) -> str:
    return f"NSE-NIFTY-{exp:%d%b%y}-{strike}-{side}"


def bar_at(df: pd.DataFrame, t: time, field: str, within_min: int = 3) -> float | None:
    """`field` of the first 1-min bar at or after t (within `within_min` minutes)."""
    if df.empty:
        return None
    s = df[df["ts"].dt.time >= t]
    if s.empty:
        return None
    first = s.iloc[0]
    lag = (datetime.combine(date.min, first["ts"].time()) - datetime.combine(date.min, t)).total_seconds() / 60
    return float(first[field]) if lag <= within_min else None


def close_before(df: pd.DataFrame, t: time) -> float | None:
    s = df[df["ts"].dt.time < t]
    return float(s["close"].iloc[-1]) if len(s) else None


# ---------------------------------------------------------------------------- option strategies
def r1_overnight(store: MarketStore, idx: pd.DataFrame, expiries: list[date], costs: CostModel) -> pd.DataFrame:
    es = set(expiries)
    days = sorted(idx["day"].unique())
    by = {d: g.reset_index(drop=True) for d, g in idx.groupby("day")}
    rows = []
    for d, nd in zip(days[:-1], days[1:], strict=True):
        h = half_of(d)
        if h is None or d in es:
            continue
        nxt = [e for e in expiries if e > d]
        px = close_before(by[d], time(15, 20))
        if not nxt or px is None:
            continue
        k = int(round(px / 50) * 50)
        idx_move = float(by[nd]["open"].iloc[0] - by[d]["close"].iloc[-1])
        for side in ("CE", "PE"):
            sym = opt_sym(nxt[0], k, side)
            o1 = store.candles(sym, "1minute", datetime.combine(d, time(15, 15)), datetime.combine(d, time(15, 30)))
            o2 = store.candles(sym, "1minute", datetime.combine(nd, time(9, 15)), datetime.combine(nd, time(9, 30)))
            e, x = bar_at(o1, time(15, 20), "open"), bar_at(o2, time(9, 20), "open")
            if e is None or x is None:
                continue
            leg = Leg(e, x)
            rows.append({"strategy": "R1", "half": h, "day": d, "side": side, "net": leg_net(costs, leg),
                         "net2": leg_net(costs, leg, 2.0), "idx_overnight_pts": idx_move})
    return pd.DataFrame(rows)


def r4_index_momentum(store: MarketStore, idx: pd.DataFrame, expiries: list[date], costs: CostModel) -> pd.DataFrame:
    es = set(expiries)
    closes = idx.groupby("day")["close"].last()
    days = list(closes.index)
    rows = []
    for i, (d, g) in enumerate(idx.groupby("day")):
        h = half_of(d)
        if h is None or d in es or i == 0:
            continue
        nxt = [e for e in expiries if e > d]
        g = g.reset_index(drop=True)
        p945, px = close_before(g, time(9, 45)), close_before(g, time(14, 40))
        if not nxt or p945 is None or px is None:
            continue
        r = p945 / float(closes[days[i - 1]]) - 1
        k = int(round(px / 50) * 50)
        rnd_side = "CE" if np.random.default_rng(d.toordinal()).random() < 0.5 else "PE"
        sides = [("R4_random", rnd_side)]
        if abs(r) >= 0.0025:
            sides.append(("R4", "CE" if r > 0 else "PE"))
        for name, side in sides:
            o = store.candles(opt_sym(nxt[0], k, side), "1minute", datetime.combine(d, time(14, 35)),
                              datetime.combine(d, time(15, 15)))
            e = bar_at(o, time(14, 40), "open")
            xs = o[o["ts"].dt.time == time(15, 9)] if not o.empty else o
            if e is None or xs.empty:
                continue
            leg = Leg(e, float(xs["close"].iloc[0]))
            rows.append({"strategy": name, "half": h, "day": d, "side": side, "first30_ret": r,
                         "net": leg_net(costs, leg), "net2": leg_net(costs, leg, 2.0)})
    return pd.DataFrame(rows)


def short_straddle_path(ce: pd.DataFrame, pe: pd.DataFrame, stop_mult: float = 1.5) -> tuple[float, float, str] | None:
    """Sell at 13:30 opens; buy back at the next open after the summed 1-min close reaches stop_mult × credit,
    else at the 15:09 bar close (= 15:10). Returns (credit_raw, buyback_raw, reason)."""
    m = ce.merge(pe, on="ts", suffixes=("_ce", "_pe")).sort_values("ts").reset_index(drop=True)
    m = m[(m["ts"].dt.time >= time(13, 30)) & (m["ts"].dt.time <= time(15, 9))].reset_index(drop=True)
    if m.empty or m["ts"].iloc[0].time() != time(13, 30):
        return None
    credit = float(m["open_ce"].iloc[0] + m["open_pe"].iloc[0])
    for i in range(len(m)):
        val = float(m["close_ce"].iloc[i] + m["close_pe"].iloc[i])
        if val >= stop_mult * credit:
            if i + 1 < len(m):
                return credit, float(m["open_ce"].iloc[i + 1] + m["open_pe"].iloc[i + 1]), "STOP_1.5x"
            return credit, val, "STOP_1.5x"
    if m["ts"].iloc[-1].time() != time(15, 9):
        return None
    return credit, float(m["close_ce"].iloc[-1] + m["close_pe"].iloc[-1]), "EOD_1510"


def r6_short_straddle(store: MarketStore, idx: pd.DataFrame, expiries: list[date], costs: CostModel,
                      halves: dict[str, tuple[date, date]] | None = None) -> pd.DataFrame:
    """RESEARCH ONLY — selling. Two legs each charged as sell-then-buy with a doubled half-spread (0.22%)."""
    by = {d: g.reset_index(drop=True) for d, g in idx.groupby("day")}
    rows = []
    for d in expiries:
        h = half_of(d, halves)
        if h is None or d not in by:
            continue
        px = close_before(by[d], time(13, 30))
        if px is None:
            continue
        k = int(round(px / 50) * 50)
        legs = {s: store.candles(opt_sym(d, k, s), "1minute", datetime.combine(d, time(13, 25)),
                                 datetime.combine(d, time(15, 15))) for s in ("CE", "PE")}
        if any(v.empty for v in legs.values()):
            continue
        res = short_straddle_path(legs["CE"], legs["PE"])
        if res is None:
            continue
        credit, back, reason = res
        out: dict[str, float] = {}
        for mult in (1.0, 2.0):
            hs = 0.0022 * mult
            sell_px, buy_px = credit * (1 - hs), back * (1 + hs)
            # two legs: charges approximated on the summed premium as one sell + one buy per leg (×2 orders)
            ch = costs.round_trip(buy_px / 2, sell_px / 2, LOT).total * 2 * mult
            out[str(mult)] = (sell_px - buy_px) * LOT - ch
        rows.append({"strategy": "R6", "half": h, "day": d, "credit": credit, "buyback": back, "reason": reason,
                     "net": out["1.0"], "net2": out["2.0"]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------- stock strategies
def _cost_frac(dc: DeliveryCosts) -> tuple[float, float]:
    return dc.buy(NOTIONAL) / NOTIONAL, dc.sell(NOTIONAL) / NOTIONAL


def r2_turn_of_month(data: dict[str, pd.DataFrame], cal: list[date], dc: DeliveryCosts) -> pd.DataFrame:
    """Window = open of the month's last trading day → close of the 3rd trading day of the next month.
    Control = every other 4-day window (open day i → close day i+3) not overlapping a TOM window."""
    buy_c, sell_c = _cost_frac(dc)
    ser = pd.Series(cal, index=pd.to_datetime(cal))
    last = ser.groupby(ser.index.to_period("M")).last()
    pos = {d: i for i, d in enumerate(cal)}
    tom: list[tuple[date, date]] = []
    for d in last:
        i = pos[d]
        if i + 3 < len(cal):
            tom.append((d, cal[i + 3]))
    tom_days = {cal[j] for a, b in tom for j in range(pos[a], pos[b] + 1)}

    def basket(a: date, b: date, mult: float = 1.0) -> float | None:
        rets = []
        for d in data.values():
            if a in d.index and b in d.index:
                e = float(d.at[a, "open"]) * (1 + STOCK_SLIP * mult)
                x = float(d.at[b, "close"]) * (1 - STOCK_SLIP * mult)
                rets.append((x / e - 1 - (buy_c + sell_c) * mult) * 100)
        return float(np.mean(rets)) if len(rets) >= 30 else None

    rows = []
    for a, b in tom:
        h = half_of(a)
        if h and half_of(b) == h:
            n1, n2 = basket(a, b), basket(a, b, 2.0)
            if n1 is not None:
                rows.append({"strategy": "R2", "half": h, "day": a, "net_pct": n1, "net2_pct": n2})
    for i in range(0, len(cal) - 3):
        a, b = cal[i], cal[i + 3]
        h = half_of(a)
        if h and half_of(b) == h and not ({cal[j] for j in range(i, i + 4)} & tom_days):
            n1 = basket(a, b)
            if n1 is not None:
                rows.append({"strategy": "R2_control", "half": h, "day": a, "net_pct": n1, "net2_pct": n1})
    return pd.DataFrame(rows)


def r5_weekly_reversal(data: dict[str, pd.DataFrame], cal: list[date], dc: DeliveryCosts,
                       top: int = 5) -> pd.DataFrame:
    """At each week's last close: hold the 5 worst 5-day performers until next week's last close. Costs only on
    names that change. Benchmark = equal-weight all eligible over the same week (no costs: buy and hold)."""
    buy_c, sell_c = _cost_frac(dc)
    ser = pd.Series(cal, index=pd.to_datetime(cal))
    week_end = ser.groupby(ser.index.to_period("W-FRI")).last().tolist()
    pos = {d: i for i, d in enumerate(cal)}
    rows: list[dict[str, Any]] = []
    held: set[str] = set()
    for w0, w1 in zip(week_end[:-1], week_end[1:], strict=True):
        h = half_of(w0)
        if h is None or half_of(w1) != h:
            held = set()
            continue
        i0 = pos[w0]
        past = cal[i0 - 5] if i0 >= 5 else None
        if past is None:
            continue
        r5, nxt = {}, {}
        for s, d in data.items():
            if all(x in d.index for x in (past, w0, w1)):
                r5[s] = float(d.at[w0, "close"] / d.at[past, "close"] - 1)
                nxt[s] = float(d.at[w1, "close"] / d.at[w0, "close"] - 1)
        if len(r5) < 30:
            continue
        pick = set(sorted(r5, key=lambda k: r5[k])[:top])
        buys, sells = len(pick - held), len(held - pick) if held else 0
        held = pick
        gross = float(np.mean([nxt[s] for s in pick]))
        slip = (buys + sells) / top * STOCK_SLIP
        cost = (buys * buy_c + sells * sell_c) / top
        bench = float(np.mean(list(nxt.values())))
        rows.append({"strategy": "R5", "half": h, "day": w0, "picks": ",".join(sorted(pick)),
                     "net_pct": (gross - cost - slip) * 100, "net2_pct": (gross - 2 * (cost + slip)) * 100,
                     "bench_pct": bench * 100})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------- verdicts
def judge(x: "pd.Series[float]", x2: "pd.Series[float]", control_mean: float | None,
          min_n: int) -> dict[str, Any]:
    v = x.dropna().to_numpy()
    if len(v) == 0:
        return {"n": 0, "PASS": False}
    w, lo_ = v[v > 0].sum(), -v[v <= 0].sum()
    pf = w / lo_ if lo_ > 0 else math.inf
    ci = bootstrap_ci(v) if len(v) >= 10 else (np.nan, np.nan, np.nan)
    beats = control_mean is None or v.mean() > control_mean
    ok = bool(len(v) >= min_n and v.mean() > 0 and float(np.nanmean(x2)) > 0 and pf >= 1.10 and beats)
    return {"n": len(v), "mean": round(float(v.mean()), 3), "mean_2x": round(float(np.nanmean(x2)), 3),
            "win%": round(float((v > 0).mean() * 100), 1), "pf": round(pf, 2), "ci95": f"[{ci[0]:.2f}, {ci[1]:.2f}]",
            "control": None if control_mean is None else round(control_mean, 3), "worst": round(float(v.min()), 1),
            "PASS": ok}


def ci_both(v: "pd.Series[float]") -> tuple[float, float]:
    lo, hi, _ = bootstrap_ci(v.dropna().to_numpy())
    return lo, hi
