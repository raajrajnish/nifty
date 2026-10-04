"""Exit variants X1 (breakeven lock) / X2 (keep half the gain) — spec: docs/reports/2026-10-04_exit_variants.md.

Each variant re-exits EXACTLY the base candidate's trades (same signals, same entries); before the +50% / +3% / +5%
gain is reached it behaves exactly like the frozen rule. Paper research only.
"""

from collections.abc import Callable, Iterator
from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim import popular_study
from tradingagent.sim import swing_study as sw
from tradingagent.sim.costs import CostModel
from tradingagent.sim.discovery_study import VALIDATION, day_contexts
from tradingagent.sim.exit_study import Entry, Rule, State, option_symbol, rule_none, simulate
from tradingagent.sim.phase3 import Data, atm, close_before, p4_rel, p4_signals
from tradingagent.sim.stop_study import rule_or_opposite

VARIANTS = ("BASE", "X1", "X2")
# Forward set (historical filter 2026-10-04, exit_variants_20261004_0917): every variant not worse than BASE in BOTH
# halves. Dropped: G1-X2, SW2-X1 (worse in both). Left out: SW1-X1/X2 (identical to BASE: no information).
FORWARD_VARIANTS = ("G1-X1", "P4-X1", "P4-X2", "R6-X1", "R6-X2", "CPR-X1", "CPR-X2", "SW2-X2")


def score_forward_variants(store: MarketStore, costs: CostModel, exps: list[date], start: date, end: date,
                           data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Forward-tournament rows for FORWARD_VARIANTS (same signals as their base candidate)."""
    rows = option_variants(store, costs, "G1", g1_entries(store, exps, start, end))
    rows += option_variants(store, costs, "P4", p4_entries(store, start, end))
    rows += option_variants(store, costs, "CPR", cpr_entries(store, exps, start, end))
    rows += r6_variants(store, costs, exps, start, end)
    rows += swing_variants({s: d for s, d in data.items()}, start, end) if data else []
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    t["cand"] = t["cand"] + "-" + t["variant"]
    t = t[t["cand"].isin(FORWARD_VARIANTS)].copy()
    t["status"] = np.where(t["reason"] == "DATA_END", "OPEN", "CLOSED")
    t["net2_inr"] = np.nan
    return t.drop(columns=["variant"]).reset_index(drop=True)
OPT_GAIN, SW1_X1, SW_X2 = 0.50, 0.03, 0.05
NIFTY_LOT = 65


# ---------------------------------------------------------------------------- long options (G1, P4, CPR)
def wrap_option(base: Rule, variant: str) -> Rule:
    """Arms after a 1-min close ≥ entry × 1.5; then raises the stop (tighten only). The raised stop is checked
    from the next minute on by exit_study.simulate (pessimistic fill)."""
    if variant == "BASE":
        return base

    def f(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
        if s.peak_close >= s.entry_px * (1 + OPT_GAIN):
            lock = s.entry_px if variant == "X1" else s.entry_px + 0.5 * (s.peak_close - s.entry_px)
            s.stop = max(s.stop, lock)
        return base(s, o, i, e)
    return f


OptEntry = tuple[date, Entry, pd.DataFrame, Rule, float]


def g1_entries(store: MarketStore, exps: list[date], start: date, end: date) -> Iterator[OptEntry]:
    fn, rule, stop = VALIDATION["G1_oos"]
    for d, g, c in day_contexts(store, exps, start, end):
        e = fn(g, c)
        if e is not None:
            yield d, e, g, rule, stop


def cpr_entries(store: MarketStore, exps: list[date], start: date, end: date) -> Iterator[OptEntry]:
    for d, g, c in popular_study.contexts(store, exps, start, end):
        e = popular_study.k1_cpr(g, c)
        if e is not None:
            yield d, e, g, rule_or_opposite, 0.50


def p4_entries(store: MarketStore, start: date, end: date) -> Iterator[OptEntry]:
    data = Data(store)
    bn = data._by_day("NSE-BANKNIFTY")  # noqa: SLF001
    warm = [d for d in sorted(data.idx) if (start - pd.Timedelta(days=150).to_pytimedelta()) <= d <= end and d in bn]
    sigs = p4_signals(pd.DataFrame({d: p4_rel(data.idx[d], bn[d]) for d in warm}).T.sort_index())
    for d in warm:
        exp = data.next_expiry(d)
        if d < start or d in data.exp_set or exp is None or d not in sigs:
            continue
        lab, s, _ = sigs[d]
        n_t = close_before(data.idx[d], lab)
        if n_t is None:
            continue
        side = "CE" if s > 0 else "PE"
        yield d, Entry(d, datetime.combine(d, lab), side, atm(n_t), exp, np.nan, np.nan), data.idx[d], rule_none, 0.30


def option_variants(store: MarketStore, costs: CostModel, cand: str,
                    entries: Iterator[OptEntry]) -> list[dict[str, Any]]:
    rows = []
    for d, e, g, rule, stop in entries:
        opt = store.candles(option_symbol(e), "1minute", datetime.combine(d, time(9, 15)),
                            datetime.combine(d, time(15, 30)))
        if opt.empty:
            continue
        for v in VARIANTS:
            tr = simulate(e, opt, g, wrap_option(rule, v), stop_pct=stop)
            if tr is None:
                break
            c = costs.round_trip(tr["entry_px"], tr["exit_px"], NIFTY_LOT).total
            rows.append({"cand": cand, "variant": v, "day": d, "side": e.side, "signal_ts": e.signal_ts,
                         "reason": tr["reason"], "net_inr": tr["pts"] * NIFTY_LOT - c})
    return rows


# ---------------------------------------------------------------------------- sold straddle (R6)
def straddle_variant(ce: pd.DataFrame, pe: pd.DataFrame, variant: str,
                     stop_mult: float = 1.5) -> tuple[float, float, str] | None:
    """BASE reproduces round2.short_straddle_path. X1/X2 arm once value ≤ 50% of the credit."""
    m = ce.merge(pe, on="ts", suffixes=("_ce", "_pe")).sort_values("ts").reset_index(drop=True)
    m = m[(m["ts"].dt.time >= time(13, 30)) & (m["ts"].dt.time <= time(15, 9))].reset_index(drop=True)
    if m.empty or m["ts"].iloc[0].time() != time(13, 30):
        return None
    credit = float(m["open_ce"].iloc[0] + m["open_pe"].iloc[0])
    low, armed = credit, False

    def nxt(i: int, val: float) -> float:
        return float(m["open_ce"].iloc[i + 1] + m["open_pe"].iloc[i + 1]) if i + 1 < len(m) else val

    for i in range(len(m)):
        val = float(m["close_ce"].iloc[i] + m["close_pe"].iloc[i])
        if val >= stop_mult * credit:
            return credit, nxt(i, val), "STOP_1.5x"
        low = min(low, val)
        armed = armed or low <= 0.5 * credit
        if armed and variant != "BASE":
            trigger = credit if variant == "X1" else low + 0.5 * (credit - low)
            if val >= trigger:
                return credit, nxt(i, val), f"LOCK_{variant}"
    if m["ts"].iloc[-1].time() != time(15, 9):
        return None
    return credit, float(m["close_ce"].iloc[-1] + m["close_pe"].iloc[-1]), "EOD_1510"


def r6_variants(store: MarketStore, costs: CostModel, exps: list[date], start: date, end: date) -> list[dict[str, Any]]:
    rows = []
    for d in exps:
        if not (start <= d <= end):
            continue
        idx = store.candles("NSE-NIFTY", "1minute", datetime.combine(d, time(9, 15)), datetime.combine(d, time(13, 30)))
        s = idx[idx["ts"].dt.time < time(13, 30)]
        if s.empty:
            continue
        k = int(round(float(s["close"].iloc[-1]) / 50) * 50)
        legs = [store.candles(f"NSE-NIFTY-{d:%d%b%y}-{k}-{x}", "1minute", datetime.combine(d, time(13, 25)),
                              datetime.combine(d, time(15, 15))) for x in ("CE", "PE")]
        if any(x.empty for x in legs):
            continue
        for v in VARIANTS:
            res = straddle_variant(legs[0], legs[1], v)
            if res is None:
                break
            credit, back, reason = res
            sell_px, buy_px = credit * (1 - 0.0022), back * (1 + 0.0022)
            ch = costs.round_trip(buy_px / 2, sell_px / 2, NIFTY_LOT).total * 2
            rows.append({"cand": "R6", "variant": v, "day": d, "side": "SHORT_STRADDLE", "reason": reason,
                         "net_inr": (sell_px - buy_px) * NIFTY_LOT - ch})
    return rows


# ---------------------------------------------------------------------------- swing (SW1, SW2)
SwingExit = Callable[[pd.Series, float, float, int], str | None]


def swing_reexit(d: pd.DataFrame, e_i: int, atr: float, base: SwingExit, variant: str) -> tuple[int, str]:
    """Walk the base trade's daily closes from entry; return (exit index, reason). Exit at the next day's open."""
    entry = float(d.iloc[e_i]["open"])
    peak = -np.inf
    days = len(d)
    j = e_i
    while j < days:
        r = d.iloc[j]
        reason = base(r, entry, atr, j - e_i + 1)
        peak = max(peak, float(r["close"]))
        if not reason and variant != "BASE":
            if variant == "X1" and peak >= entry * (1 + SW1_X1) and r["close"] < entry:
                reason = "LOCK_X1"
            if variant == "X2" and peak >= entry * (1 + SW_X2) and r["close"] < entry + 0.5 * (peak - entry):
                reason = "LOCK_X2"
        if reason or j == days - 1:
            return j, reason or "DATA_END"
        j += 1
    return days - 1, "DATA_END"


def swing_variants(data: dict[str, pd.DataFrame], start: date, end: date) -> list[dict[str, Any]]:
    rows, dc = [], sw.DeliveryCosts()
    for sym, d in data.items():
        for cid in ("SW1", "SW2"):
            base_ex = sw.SETUPS[cid][1]
            for t in sw.run_signal_setup(sym, d, set(), cid, dc, periods={"H": (start, end)}):
                e_i = int(t["e_idx"])
                atr = float(d.loc[t["signal_day"], "atr14"])
                entry = float(d.iloc[e_i]["open"])
                for v in VARIANTS:
                    j, reason = swing_reexit(d, e_i, atr, base_ex, v)
                    x_i = j + 1 if reason != "DATA_END" and j + 1 < len(d) else j
                    exit_px = float(d.iloc[x_i]["open"]) if x_i > j else float(d.iloc[j]["close"])
                    rows.append({"cand": cid, "variant": v, "day": t["signal_day"], "symbol": sym, "side": "LONG",
                                 "reason": reason, "net_inr": sw._net_pct(entry, exit_px, dc) * 1000})  # noqa: SLF001
    return rows
