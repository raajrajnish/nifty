"""Exit-rule study on stored history (Phase 4 style; `tradingagent backtest-exits`).

Question: holding the ENTRY fixed, which EXIT rule survives after real costs?

Entry (fixed, simple, pre-declared — not tuned):
  ORB-15 on the NIFTY index: opening range = 09:15–09:29 one-minute highs/lows. First 5-minute close
  above the range high → buy ATM CE; below the range low → buy ATM PE. Signals 09:30–13:30, one per day.
  Expiry days are skipped (risk.yaml: expiry_day.allowed=false). Contract = nearest weekly expiry after today.
Fills (pessimistic, from 2026-09-30 recorded spreads, median ATM 0.22%):
  enter at the next one-minute OPEN after the signal + half-spread; exit at the trigger price − half-spread.
  Premium stop is checked against one-minute LOWS (gaps fill at the open); if stop and any other exit fall
  in the same minute, the stop wins. Rules other than the hard stop act on CLOSES and fill at the next open.
Risk unit R = HARD_STOP_PCT of entry premium (hard stop present in every variant).
Rupees = 1 lot of 65 (today's lot) at today's charges (config/costs.yaml) — current economics, not historic.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel

LOT = 65
STEP = 50
HARD_STOP_PCT = 0.30
HALF_SPREAD_PCT = 0.0011       # half of the measured 0.22% ATM spread
EOD_EXIT = time(15, 10)
SIGNAL_START, SIGNAL_END = time(9, 30), time(13, 30)


# ---------------------------------------------------------------------------- entries
@dataclass(frozen=True)
class Entry:
    day: date
    signal_ts: datetime
    side: str            # CE | PE
    strike: int
    expiry: date
    or_high: float
    or_low: float


def orb_signal(idx: pd.DataFrame, expiries: list[date]) -> Entry | None:
    """idx: one day's index 1-min candles (ts, open, high, low, close)."""
    d = idx["ts"].iloc[0].date()
    if d in set(expiries):
        return None  # expiry day: not allowed
    nxt = [e for e in expiries if e > d]
    if not nxt:
        return None
    opening = idx[idx["ts"].dt.time < time(9, 30)]
    if len(opening) < 10:
        return None
    hi, lo = float(opening["high"].max()), float(opening["low"].min())
    five = idx.set_index("ts")["close"].resample("5min", label="right", closed="left").last().dropna()
    for ts, c in five.items():
        if not (SIGNAL_START < ts.time() <= SIGNAL_END):
            continue
        side = "CE" if c > hi else "PE" if c < lo else None
        if side:
            strike = int(round(c / STEP) * STEP)
            return Entry(d, ts.to_pydatetime(), side, strike, nxt[0], hi, lo)
    return None


# ---------------------------------------------------------------------------- exit rules
@dataclass
class State:
    entry_px: float
    risk: float               # R in premium points
    peak_close: float
    minutes: int = 0
    stop: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


# A rule sees (state, option minute bar, index minute bar, entry) and returns an exit reason or None.
# It may also raise the stop (tighten-only). Rules act on CLOSES → fill at next minute open.
Rule = Callable[[State, pd.Series, pd.Series, Entry], str | None]


def rule_none(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    return None


def rule_time(minutes: int) -> Rule:
    def f(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
        return "TIME" if s.minutes >= minutes else None
    return f


def rule_thesis(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    """Breakout failed: index closes back past the opening-range midpoint."""
    mid = (e.or_high + e.or_low) / 2
    return "THESIS" if (i["close"] < mid if e.side == "CE" else i["close"] > mid) else None


def rule_breakeven(trigger_r: float = 1.0) -> Rule:
    def f(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
        if s.peak_close >= s.entry_px + trigger_r * s.risk:
            s.stop = max(s.stop, s.entry_px * (1 + 2 * HALF_SPREAD_PCT) + 1.0)  # ≈ entry + spread + charges
        return None
    return f


def rule_swing_trail(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    """Exit when the index closes beyond the extreme of the previous three completed 5-min bars."""
    hist: list[tuple[float, float]] = s.extra.setdefault("bars5", [])
    cur = s.extra.setdefault("cur5", [i["high"], i["low"]])
    cur[0], cur[1] = max(cur[0], i["high"]), min(cur[1], i["low"])
    if pd.Timestamp(i["ts"]).minute % 5 == 4:  # bar complete
        hist.append((cur[0], cur[1]))
        s.extra["cur5"] = [-math.inf, math.inf]
    if len(hist) < 3:
        return None
    last3 = hist[-3:]
    if e.side == "CE":
        return "SWING" if i["close"] < min(b[1] for b in last3) else None
    return "SWING" if i["close"] > max(b[0] for b in last3) else None


def rule_no_progress(minutes: int = 30, need_r: float = 0.5) -> Rule:
    def f(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
        if s.minutes >= minutes and s.peak_close < s.entry_px + need_r * s.risk:
            return "NO_PROGRESS"
        return None
    return f


def rule_giveback(keep: float, activate_r: float = 1.0) -> Rule:
    def f(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
        gain_peak = s.peak_close - s.entry_px
        if gain_peak >= activate_r * s.risk and (o["close"] - s.entry_px) <= keep * gain_peak:
            return f"LOCK{int(keep * 100)}"
        return None
    return f


RULES: dict[str, Rule] = {
    "E0_hold_to_1510": rule_none,
    "E0b_time_60m": rule_time(60),
    "E1_thesis_or_mid": rule_thesis,
    "E2_breakeven_1R": rule_breakeven(1.0),
    "E3_swing_trail_5m": rule_swing_trail,
    "E4_no_progress_30m": rule_no_progress(30, 0.5),
    "E5_lock50_after_1R": rule_giveback(0.5),
    "E5_lock60_after_1R": rule_giveback(0.6),
    "E5_lock70_after_1R": rule_giveback(0.7),
    "E5_lock80_after_1R": rule_giveback(0.8),
}


# ---------------------------------------------------------------------------- simulation
def simulate(entry: Entry, opt: pd.DataFrame, idx: pd.DataFrame, rule: Rule,
             stop_pct: float | None = HARD_STOP_PCT) -> dict[str, Any] | None:
    """opt/idx: that day's 1-min candles. Returns trade dict or None if no fill possible.
    stop_pct=None → no premium stop at all (the setup's own rule / 15:10 decides); R is then still
    measured as HARD_STOP_PCT of entry so results stay comparable across stop levels."""
    # signal_ts is the 5-min bar's right edge (e.g. 09:35 = close of the 09:34 minute) → fill at the 09:35 open
    after = opt[opt["ts"] >= entry.signal_ts].reset_index(drop=True)
    if after.empty or (after["ts"].iloc[0] - entry.signal_ts) > timedelta(minutes=3):
        return None
    entry_px = float(after["open"].iloc[0]) * (1 + HALF_SPREAD_PCT)
    risk = HARD_STOP_PCT * entry_px
    stop = -math.inf if stop_pct is None else entry_px * (1 - stop_pct)
    s = State(entry_px=entry_px, risk=risk, peak_close=entry_px, stop=stop)
    idx_by_ts = idx.set_index("ts")
    pending: str | None = None
    exit_px, reason, exit_ts = None, None, None
    mfe = mae = 0.0
    for k in range(len(after)):
        o = after.iloc[k]
        if pending:  # a close-based rule fired on the previous minute → fill at this open
            exit_px, reason, exit_ts = float(o["open"]), pending, o["ts"]
            break
        if o["low"] <= s.stop:  # hard/raised stop first (pessimistic); gap → fill at open
            exit_px = min(float(o["open"]), s.stop)
            reason, exit_ts = ("STOP" if s.stop < entry_px else "BREAKEVEN_STOP"), o["ts"]
            break
        mfe = max(mfe, float(o["high"]) - entry_px)
        mae = min(mae, float(o["low"]) - entry_px)
        s.peak_close = max(s.peak_close, float(o["close"]))
        s.minutes = int((o["ts"] - after["ts"].iloc[0]).total_seconds() // 60)
        if o["ts"].time() >= EOD_EXIT:
            exit_px, reason, exit_ts = float(o["close"]), "EOD", o["ts"]
            break
        i_bar = idx_by_ts.loc[o["ts"]] if o["ts"] in idx_by_ts.index else None
        if i_bar is not None:
            pending = rule(s, o, pd.Series({**i_bar.to_dict(), "ts": o["ts"]}), entry)
    if exit_px is None:
        last = after.iloc[-1]
        exit_px, reason, exit_ts = float(last["close"]), "DATA_END", last["ts"]
    exit_px *= (1 - HALF_SPREAD_PCT)
    return {"day": entry.day, "side": entry.side, "strike": entry.strike, "expiry": entry.expiry,
            "entry_ts": after["ts"].iloc[0], "exit_ts": exit_ts, "entry_px": entry_px, "exit_px": exit_px,
            "reason": reason, "risk_pts": risk, "pts": exit_px - entry_px, "r": (exit_px - entry_px) / risk,
            "mfe_r": mfe / risk, "mae_r": mae / risk}


def option_symbol(e: Entry) -> str:
    return f"NSE-NIFTY-{e.expiry.strftime('%d%b%y')}-{e.strike}-{e.side}"


def build_entries(store: MarketStore) -> tuple[list[Entry], dict[date, pd.DataFrame]]:
    expiries = [r[0] for r in store.con.execute(
        "SELECT DISTINCT expiry FROM contracts WHERE kind='CE' ORDER BY expiry").fetchall()]
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    entries, by_day = [], {}
    for d, g in idx.groupby("day"):
        g = g.reset_index(drop=True)
        by_day[d] = g
        e = orb_signal(g, expiries)
        if e:
            entries.append(e)
    return entries, by_day


def metrics(t: pd.DataFrame) -> dict[str, Any]:
    if t.empty:
        return {"n": 0}
    w, lo = t[t["net_inr"] > 0], t[t["net_inr"] <= 0]
    eq = t["net_inr"].cumsum()
    return {"n": len(t), "win_rate": round(len(w) / len(t), 3),
            "exp_inr": round(t["net_inr"].mean(), 1), "exp_r_net": round(t["r_net"].mean(), 3),
            "median_inr": round(t["net_inr"].median(), 1),
            "pf": round(w["net_inr"].sum() / -lo["net_inr"].sum(), 2) if lo["net_inr"].sum() < 0 else None,
            "total_inr": round(t["net_inr"].sum()), "max_dd_inr": round(float((eq - eq.cummax()).min())),
            "avg_win": round(w["net_inr"].mean(), 1) if len(w) else 0,
            "avg_loss": round(lo["net_inr"].mean(), 1) if len(lo) else 0}


def run_study(store: MarketStore, costs: CostModel, cost_mult: float = 1.0,
              rules: dict[str, Rule] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    rules = rules or RULES
    entries, idx_by_day = build_entries(store)
    rows = []
    for e in entries:
        opt = store.candles(option_symbol(e), "1minute",
                            datetime.combine(e.day, time(9, 15)), datetime.combine(e.day, time(15, 30)))
        if opt.empty:
            continue
        for name, rule in rules.items():
            tr = simulate(e, opt, idx_by_day[e.day], rule)
            if tr is None:
                continue
            c = costs.round_trip(tr["entry_px"], tr["exit_px"], LOT).total * cost_mult
            tr.update(rule=name, cost_inr=c, gross_inr=tr["pts"] * LOT, net_inr=tr["pts"] * LOT - c,
                      r_net=(tr["pts"] * LOT - c) / (tr["risk_pts"] * LOT))
            rows.append(tr)
    trades = pd.DataFrame(rows)
    days = sorted(trades["day"].unique())
    n = len(days)
    split = {d: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, d in enumerate(days)}
    trades["split"] = trades["day"].map(split)
    trades["half"] = np.where(trades["day"] <= days[n // 2], "H1", "H2")
    summary = []
    for name, g in trades.groupby("rule"):
        row: dict[str, Any] = {"rule": name, **metrics(g)}
        for part in ("dev", "validate", "test"):
            row[f"{part}_exp_inr"] = metrics(g[g["split"] == part]).get("exp_inr")
        for side in ("CE", "PE"):
            row[f"{side}_exp_inr"] = metrics(g[g["side"] == side]).get("exp_inr")
        for h in ("H1", "H2"):
            row[f"{h}_exp_inr"] = metrics(g[g["half"] == h]).get("exp_inr")
        summary.append(row)
    return trades, pd.DataFrame(summary).sort_values("exp_inr", ascending=False)
