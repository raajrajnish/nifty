"""Stock intraday pilot (`tradingagent backtest-stocks`). Spec: docs/reports/2026-10-02_stock_pilot_study.md.

Cash-equity intraday, long AND short, fixed ₹1 lakh position. Every setup is per stock (owner rule).
Two untouched periods; a stock-setup must pass BOTH. Nothing here touches the option studies or G1/G2.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.sim.entry_study import five_min
from tradingagent.sim.timing_study import bootstrap_ci

NOTIONAL = 100_000.0
SLIP = 0.0003                       # 0.03% per side (spec §3)
EOD = time(15, 10)
SIGNAL_END = time(13, 30)
PERIODS = {"P1": (date(2021, 10, 1), date(2024, 9, 30)), "P2": (date(2024, 10, 1), date(2026, 9, 30))}
EVENT_GAP = 0.04                    # fallback event-day rule (results dates not held): |gap| > 4% → skip day + next
SPLIT_GAP = 0.15
RATIOS = (1.5, 2.0, 3.0, 4.0, 5.0, 10.0)


# ---------------------------------------------------------------------------- costs (spec §3)
@dataclass(frozen=True)
class EquityIntradayCosts:
    """Groww intraday equity, as declared in the spec. Verify against a real contract note before any live use."""
    brokerage_pct: float = 0.001     # 0.1% per order, capped at ₹20
    brokerage_cap: float = 20.0
    stt_sell: float = 0.00025
    exchange: float = 0.0000297
    sebi_per_cr: float = 10.0
    stamp_buy: float = 0.00003
    gst: float = 0.18

    def round_trip(self, buy_value: float, sell_value: float) -> float:
        brk = min(self.brokerage_cap, buy_value * self.brokerage_pct) + min(self.brokerage_cap,
                                                                           sell_value * self.brokerage_pct)
        exch = (buy_value + sell_value) * self.exchange
        sebi = (buy_value + sell_value) * self.sebi_per_cr / 1e7
        taxes = sell_value * self.stt_sell + buy_value * self.stamp_buy
        return brk + exch + sebi + taxes + (brk + exch + sebi) * self.gst


# ---------------------------------------------------------------------------- data cleaning (spec §1 data rule)
def clean_bad_prints(m1: pd.DataFrame) -> tuple[pd.DataFrame, set[date]]:
    """Groww data error found 2026-10-02: on 2025-05-12 (10:32–10:34) every stock printed prices ×100.
    Any O/H/L/C more than 20× the day's median close is divided by 100 (keeps ATR / previous-day levels sane),
    and the whole day is excluded from trading."""
    m1 = m1.copy()
    day = m1["ts"].dt.date
    med = m1.groupby(day)["close"].transform("median")
    bad_days: set[date] = set()
    for c in ("open", "high", "low", "close"):
        bad = m1[c] > 20 * med
        if bad.any():
            m1.loc[bad, c] = m1.loc[bad, c] / 100
            bad_days |= set(day[bad])
    return m1, bad_days



def adjust_splits(m1: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]], set[date]]:
    """Back-adjust prices before ex-dates (open vs previous close moves > 15% with a clean ratio).
    Returns adjusted 1-min candles, the list of ex-dates found, and days to exclude."""
    m1 = m1.sort_values("ts").copy()
    m1["day"] = m1["ts"].dt.date
    daily = m1.groupby("day").agg(open=("open", "first"), close=("close", "last"))
    events, exclude = [], set()
    factor = pd.Series(1.0, index=daily.index)
    prev = daily["close"].shift(1)
    for d in daily.index[1:]:
        r = prev[d] / daily.at[d, "open"]
        if abs(r - 1) <= SPLIT_GAP and abs(1 / r - 1) <= SPLIT_GAP:
            continue
        exclude.add(d)
        best = min(RATIOS, key=lambda q: abs(r / q - 1))
        if abs(r / best - 1) < 0.08:
            factor[factor.index < d] *= best
            events.append({"day": d, "ratio": best, "raw_ratio": round(float(r), 3)})
        else:
            events.append({"day": d, "ratio": None, "raw_ratio": round(float(r), 3)})
    f = m1["day"].map(factor)
    for c in ("open", "high", "low", "close"):
        m1[c] = m1[c] / f
    return m1, events, exclude


def day_table(m1: pd.DataFrame) -> pd.DataFrame:
    d = m1.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                              close=("close", "last"))
    d["prev_close"] = d["close"].shift(1)
    d["pdh"], d["pdl"] = d["high"].shift(1), d["low"].shift(1)
    d["gap"] = d["open"] / d["prev_close"] - 1
    d["atr"] = (d["high"] - d["low"]).shift(1).rolling(14).mean()
    or_w = m1[m1["ts"].dt.time < time(9, 30)].groupby("day").apply(
        lambda g: (g["high"].max() - g["low"].min()) / g["close"].iloc[-1], include_groups=False)
    d["or_pct"] = or_w
    d["narrow_or"] = d["or_pct"] < d["or_pct"].shift(1).rolling(20, min_periods=10).median()  # unknown → False
    big = d["gap"].abs() > EVENT_GAP
    d["event_skip"] = big | big.shift(1, fill_value=False)
    return d


# ---------------------------------------------------------------------------- signals
@dataclass(frozen=True)
class Signal:
    day: date
    ts: datetime          # fill at this minute's open
    side: int             # +1 long, −1 short
    hi: float             # thesis levels (range), or stop level for ST3 (in hi for short / lo for long)
    lo: float
    kind: str


Strat = Callable[[pd.DataFrame, pd.Series, pd.DataFrame | None], Signal | None]


def _or15(g: pd.DataFrame) -> tuple[float, float] | None:
    o = g[g["ts"].dt.time < time(9, 30)]
    return (float(o["high"].max()), float(o["low"].min())) if len(o) >= 10 else None


def st1_orb_with_nifty(g: pd.DataFrame, row: pd.Series, nifty: pd.DataFrame | None) -> Signal | None:
    r = _or15(g)
    if r is None or nifty is None or nifty.empty:
        return None
    hi, lo = r
    n_open = float(nifty["open"].iloc[0])
    n_close = nifty.set_index("ts")["close"]
    for ts, b in five_min(g).iterrows():
        if not (time(9, 30) < ts.time() <= SIGNAL_END):
            continue
        nc = n_close[:ts - timedelta(seconds=1)]
        if nc.empty:
            continue
        up = float(nc.iloc[-1]) > n_open
        if b["close"] > hi and up:
            return Signal(row.name, ts.to_pydatetime(), +1, hi, lo, "range")
        if b["close"] < lo and not up:
            return Signal(row.name, ts.to_pydatetime(), -1, hi, lo, "range")
    return None


def st2_g1_logic(g: pd.DataFrame, row: pd.Series, _: pd.DataFrame | None) -> Signal | None:
    outside = row["open"] > row["pdh"] or row["open"] < row["pdl"]
    if not (outside and row["narrow_or"] == True):  # noqa: E712
        return None
    r = _or15(g)
    if r is None:
        return None
    hi, lo = r
    for ts, b in five_min(g).iterrows():
        if time(9, 30) < ts.time() <= SIGNAL_END:
            if b["close"] > hi:
                return Signal(row.name, ts.to_pydatetime(), +1, hi, lo, "range")
            if b["close"] < lo:
                return Signal(row.name, ts.to_pydatetime(), -1, hi, lo, "range")
    return None


def st3_intraday_momentum(g: pd.DataFrame, row: pd.Series, _: pd.DataFrame | None) -> Signal | None:
    early = g[g["ts"].dt.time < time(9, 45)]
    if early.empty or pd.isna(row["prev_close"]) or pd.isna(row["atr"]):
        return None
    ret = float(early["close"].iloc[-1]) / row["prev_close"] - 1
    if abs(ret) < 0.005:
        return None
    at = g[g["ts"].dt.time == time(14, 15)]
    if at.empty:
        return None
    px, side = float(at["open"].iloc[0]), (1 if ret > 0 else -1)
    stop = px - side * 0.5 * float(row["atr"])
    ts = datetime.combine(row.name, time(14, 15))
    return Signal(row.name, ts, side, stop if side < 0 else math.inf, stop if side > 0 else -math.inf, "stop")


def random_control(g: pd.DataFrame, row: pd.Series, _: pd.DataFrame | None) -> Signal | None:
    rng = np.random.default_rng(row.name.toordinal())
    bars = [ts for ts in five_min(g).index if time(9, 45) <= ts.time() <= SIGNAL_END]
    if not bars:
        return None
    ts = bars[int(rng.integers(len(bars)))]
    return Signal(row.name, ts.to_pydatetime(), 1 if rng.random() < 0.5 else -1, math.inf, -math.inf, "none")


SETUPS: dict[str, Strat] = {"ST1": st1_orb_with_nifty, "ST2": st2_g1_logic, "ST3": st3_intraday_momentum,
                            "RANDOM": random_control}


# ---------------------------------------------------------------------------- simulation
def simulate(sig: Signal, g: pd.DataFrame, costs: EquityIntradayCosts, cost_mult: float = 1.0) -> dict[str, Any] | None:
    """Fill at sig.ts open ± slippage. Exits (on closes, filled at the next minute's open):
    range → 5-min close beyond the opposite side; stop → 1-min close through the stop. Else 15:10 close."""
    after = g[g["ts"] >= pd.Timestamp(sig.ts)].reset_index(drop=True)
    if after.empty or (after["ts"].iloc[0] - pd.Timestamp(sig.ts)) > timedelta(minutes=3):
        return None
    entry = float(after["open"].iloc[0]) * (1 + sig.side * SLIP)
    qty = math.floor(NOTIONAL / entry)
    if qty < 1:
        return None
    exit_px, reason, pending = None, None, False
    for k in range(len(after)):
        b = after.iloc[k]
        if pending:
            exit_px, reason = float(b["open"]), reason
            break
        if b["ts"].time() >= EOD:
            exit_px, reason = float(b["close"]), "EOD"
            break
        c = float(b["close"])
        if sig.kind == "range" and b["ts"].minute % 5 == 4:
            if (sig.side > 0 and c < sig.lo) or (sig.side < 0 and c > sig.hi):
                pending, reason = True, "OPPOSITE_SIDE"
        elif sig.kind == "stop" and ((sig.side > 0 and c <= sig.lo) or (sig.side < 0 and c >= sig.hi)):
            pending, reason = True, "STOP"
    if exit_px is None:
        exit_px, reason = float(after["close"].iloc[-1]), "DATA_END"
    exit_px *= 1 - sig.side * SLIP
    buy_v, sell_v = (entry * qty, exit_px * qty) if sig.side > 0 else (exit_px * qty, entry * qty)
    gross = (exit_px - entry) * qty * sig.side
    cst = costs.round_trip(buy_v, sell_v)
    return {"day": sig.day, "side": "LONG" if sig.side > 0 else "SHORT", "entry_ts": after["ts"].iloc[0],
            "entry": entry, "exit": exit_px, "qty": qty, "reason": reason, "gross": gross, "cost": cst,
            "net": gross - cst, "net2": gross - 2 * cst - 2 * qty * entry * SLIP}


def run_stock(symbol: str, m1: pd.DataFrame, nifty: pd.DataFrame,
              costs: EquityIntradayCosts) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    m1, bad_days = clean_bad_prints(m1)
    adj, events, ex_days = adjust_splits(m1)
    ex_days |= bad_days
    days = day_table(adj)
    nifty_by_day = {k: v for k, v in nifty.groupby(nifty["ts"].dt.date)}
    rows = []
    for d, g in adj.groupby("day"):
        if d in ex_days or d not in days.index or bool(days.at[d, "event_skip"]):
            continue
        per = next((p for p, (s, e) in PERIODS.items() if s <= d <= e), None)
        if per is None or pd.isna(days.at[d, "prev_close"]):
            continue
        g = g.reset_index(drop=True)
        row = days.loc[d]
        for name, fn in SETUPS.items():
            sig = fn(g, row, nifty_by_day.get(d))
            if sig is None:
                continue
            tr = simulate(sig, g, costs)
            if tr:
                rows.append({**tr, "symbol": symbol, "setup": name, "period": per})
    return pd.DataFrame(rows), events


# ---------------------------------------------------------------------------- verdicts (spec §4)
def _check(t: pd.DataFrame, rnd_net: float) -> dict[str, Any]:
    if t.empty:
        return {"n": 0, "PASS": False}
    net_pct = t["net"] / NOTIONAL * 100
    w, lo_ = t[t["net"] > 0]["net"].sum(), -t[t["net"] <= 0]["net"].sum()
    pf = w / lo_ if lo_ > 0 else math.inf
    days = sorted(t["day"].unique())
    half = t["day"] <= days[len(days) // 2]
    h1, h2 = t[half]["net"].mean(), t[~half]["net"].mean()
    ci_lo, ci_hi, _ = bootstrap_ci(net_pct.to_numpy()) if len(t) >= 10 else (np.nan, np.nan, np.nan)
    ok = bool(len(t) >= 60 and t["net"].mean() > 0 and t["net2"].mean() > 0 and pf >= 1.10
              and t["net"].mean() > rnd_net and h1 > 0 and h2 > 0)
    return {"n": len(t), "win%": round((t["net"] > 0).mean() * 100, 1), "net%": round(float(net_pct.mean()), 3),
            "ci95%": f"[{ci_lo:+.3f}, {ci_hi:+.3f}]", "net_2x%": round(float(t["net2"].mean() / NOTIONAL * 100), 3),
            "pf": round(pf, 2), "H1>0": bool(h1 > 0), "H2>0": bool(h2 > 0), "PASS": ok,
            "long%": round(float(t[t["side"] == "LONG"]["net"].mean() / NOTIONAL * 100), 3),
            "short%": round(float(t[t["side"] == "SHORT"]["net"].mean() / NOTIONAL * 100), 3),
            "ex_top5%": round(float(t.sort_values("net", ascending=False)["net"].iloc[5:].mean() / NOTIONAL * 100), 3)}


def verdicts(trades: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (sym, setup), g in trades.groupby(["symbol", "setup"]):
        if setup == "RANDOM":
            continue
        row: dict[str, Any] = {"symbol": sym, "setup": setup}
        both = True
        for p in PERIODS:
            rnd = trades[(trades["symbol"] == sym) & (trades["setup"] == "RANDOM") & (trades["period"] == p)]
            c = _check(g[g["period"] == p], float(rnd["net"].mean()) if len(rnd) else 0.0)
            row.update({f"{p}_{k}": v for k, v in c.items()})
            both = both and c["PASS"]
        full = _check(g, -math.inf)
        row["PASS_both"] = both
        row["ROBUST"] = bool(both and full.get("long%", -1) > 0 and full.get("short%", -1) > 0
                             and full.get("ex_top5%", -1) > 0)
        out.append(row)
    return pd.DataFrame(out)
