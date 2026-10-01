"""Follow-through exit study (`tradingagent backtest-followthrough`).
Spec: docs/reports/2026-10-01_followthrough_study.md (pre-declared)."""

from datetime import datetime, time
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.entry_study import ENTRIES, day_features
from tradingagent.sim.exit_study import LOT, Entry, Rule, State, option_symbol, rule_none, simulate
from tradingagent.sim.stop_study import rule_or_opposite
from tradingagent.sim.timing_study import summarize_timing

CHECKS: tuple[int | None, ...] = (None, 10, 15, 20)


def rule_follow_through(minutes: int, base: Rule) -> Rule:
    """At `minutes` after entry, exit if the index has not moved in the trade's direction; else defer to base."""
    def f(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
        if "i0" not in s.extra:
            s.extra["i0"] = float(i["open"])  # index level when we entered (open of the entry minute)
        if not s.extra.get("ft_done") and s.minutes >= minutes:
            s.extra["ft_done"] = True
            moved = float(i["close"]) - s.extra["i0"]
            if (moved <= 0) if e.side == "CE" else (moved >= 0):
                return "NO_FOLLOW_THROUGH"
        return base(s, o, i, e)
    return f


SETUPS: dict[str, tuple[str, tuple[str, bool] | None, Rule, float]] = {
    "S1": ("orb15", ("narrow_or", True), rule_or_opposite, 0.50),
    "S2": ("twap_pullback", ("high_vol", False), rule_none, 0.30),
    "RANDOM": ("random_control", None, rule_none, 0.30),
}


def run_followthrough(store: MarketStore, costs: CostModel) -> tuple[pd.DataFrame, pd.DataFrame]:
    expiries = [r[0] for r in store.con.execute(
        "SELECT DISTINCT expiry FROM contracts WHERE kind='CE' AND underlying='NIFTY' ORDER BY expiry").fetchall()]
    exp_set = set(expiries)
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    feats = day_features(idx)
    rows: list[dict[str, Any]] = []
    for d, g in idx.groupby("day"):
        if d in exp_set:
            continue
        g = g.reset_index(drop=True)
        ctx = {"day": d, "gap_pct": None, "ema5": None}
        cache: dict[str, pd.DataFrame] = {}
        eod = pd.Timestamp(datetime.combine(d, time(15, 10)))
        for sname, (ename, flt, base, stop) in SETUPS.items():
            if flt is not None and bool(feats.at[d, flt[0]]) != flt[1]:  # same day filter as the stop study
                continue
            e = ENTRIES[ename](g, ctx, expiries)
            if e is None:
                continue
            sym = option_symbol(e)
            if sym not in cache:
                cache[sym] = store.candles(sym, "1minute", datetime.combine(d, time(9, 15)),
                                           datetime.combine(d, time(15, 30)))
            opt = cache[sym]
            if opt.empty:
                continue
            eod_px = opt[opt["ts"] <= eod]["close"]
            for k in CHECKS:
                rule = base if k is None else rule_follow_through(k, base)
                tr = simulate(e, opt, g, rule, stop_pct=stop)
                if tr is None:
                    continue
                c = costs.round_trip(tr["entry_px"], tr["exit_px"], LOT).total
                rows.append({**tr, "setup": sname, "variant": f"{sname}-{'base' if k is None else f'FT{k}'}",
                             "net_inr": tr["pts"] * LOT - c, "net2_inr": tr["pts"] * LOT - 2 * c,
                             "r_net": (tr["pts"] * LOT - c) / (tr["risk_pts"] * LOT), "delay_min": np.nan,
                             "eod_above_entry": bool(len(eod_px) and float(eod_px.iloc[-1]) > tr["entry_px"])})
    trades = pd.DataFrame(rows)
    days = sorted(trades["day"].unique())
    n = len(days)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(days)}
    trades["split"] = trades["day"].map(split)
    trades["half"] = np.where(trades["day"] <= days[n // 2], "H1", "H2")
    return trades, summarize_timing(trades)


def cut_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    """For each FT variant: how many trades were cut, how many cuts were 'false', and what the cut saved."""
    rows = []
    for v, g in trades[trades["variant"].str.contains("FT")].groupby("variant"):
        setup = v.split("-")[0]
        base = trades[trades["variant"] == f"{setup}-base"].set_index("day")
        cut = g[g["reason"] == "NO_FOLLOW_THROUGH"]
        same = base.loc[base.index.intersection(cut["day"])]
        rows.append({"variant": v, "cut_share": round(len(cut) / max(len(g), 1), 3),
                     "false_cut_share": round(float(cut["eod_above_entry"].mean()) if len(cut) else 0.0, 3),
                     "cut_trades_net_now": round(float(cut["net_inr"].mean()), 1) if len(cut) else None,
                     "same_trades_net_baseline": round(float(same["net_inr"].mean()), 1) if len(same) else None})
    return pd.DataFrame(rows)


def verdict_ft(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for setup in SETUPS:
        b = summary[summary["variant"] == f"{setup}-base"]
        if b.empty:
            continue
        b0 = b.iloc[0]
        for _, v in summary[summary["variant"].str.startswith(f"{setup}-FT")].iterrows():
            rows.append({"variant": v["variant"], "net_vs_base": round(v["net"] - b0["net"], 1),
                         "dev_vs_base": round((v["dev"] or 0) - (b0["dev"] or 0), 1),
                         "valtest_vs_base": round(v["val+test"] - b0["val+test"], 1),
                         "beats_base": bool((v["dev"] or -1e9) > (b0["dev"] or -1e9)
                                            and v["val+test"] > b0["val+test"]),
                         "ROBUST": bool(v["ROBUST"])})
    out = pd.DataFrame(rows)
    ft15 = out[out["variant"].isin(["S1-FT15", "S2-FT15"])]
    neighbours = out[out["variant"].str.contains("FT10|FT20") & ~out["variant"].str.startswith("RANDOM")]
    adopt = bool(len(ft15) == 2 and ft15["beats_base"].all() and neighbours["net_vs_base"].gt(0).all())
    out.attrs["ADOPT_FT15"] = adopt
    return out
