"""Stop study (`tradingagent backtest-stops`): let each setup tell us the loss it needs.

Owner's question (2026-10-01): a fixed −30% premium stop may kill trades that were right but dipped first.
So each setup runs with its OWN invalidation rule (no fixed stop), and a sweep of premium stops is compared:
  stops: 20%, 30%, 40%, 50%, 60%, none
For every no-stop trade we keep the worst dip (MAE) and the final result → "killed winners" per stop level:
trades whose dip went past the stop but which finished profitable.
Choice rule (declared before running): pick the stop on DEV days only; confirm on validate + test; prefer a
level whose neighbours are similar (flat region), not the single best number.

Setups (from studies #2/#3):
  S1 = ORB-15 breakout on narrow-OR mornings      own rule: 5-min close back INSIDE the opening range
       (variant S1b own rule: 5-min close beyond the OPPOSITE side of the range — full failure)
  S2 = TWAP pullback on low-volatility days        own rule: 5-min close on the wrong side of TWAP
References: same entries without the day filter, and the random-entry control.
"""

from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.entry_study import ENTRIES, day_features
from tradingagent.sim.exit_study import LOT, Entry, Rule, State, option_symbol, rule_none, simulate

STOPS: tuple[float | None, ...] = (0.2, 0.3, 0.4, 0.5, 0.6, None)


def _five_min_close(i: pd.Series) -> bool:
    return bool(pd.Timestamp(i["ts"]).minute % 5 == 4)  # the 1-min bar that completes a 5-min bar


def rule_or_inside(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    if not _five_min_close(i):
        return None
    failed = i["close"] < e.or_high if e.side == "CE" else i["close"] > e.or_low
    return "OR_BACK_INSIDE" if failed else None


def rule_or_opposite(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
    if not _five_min_close(i):
        return None
    failed = i["close"] < e.or_low if e.side == "CE" else i["close"] > e.or_high
    return "OR_OPPOSITE_SIDE" if failed else None


def rule_twap_cross(twap: pd.Series) -> Rule:
    """twap: expanding mean of index closes, indexed by minute (value at t uses closes ≤ t only)."""
    def f(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
        if not _five_min_close(i):
            return None
        tw = twap.get(pd.Timestamp(i["ts"]))
        if tw is None:
            return None
        failed = i["close"] < tw if e.side == "CE" else i["close"] > tw
        return "TWAP_CROSSED" if failed else None
    return f


SETUPS = {
    # name: (entry, day filter column/value or None, own-rule key)
    "S1_orb15_narrow": ("orb15", ("narrow_or", True), "or_inside"),
    "S1b_orb15_narrow_fullfail": ("orb15", ("narrow_or", True), "or_opposite"),
    "S2_twap_lowvol": ("twap_pullback", ("high_vol", False), "twap"),
    "ref_orb15_all": ("orb15", None, "or_inside"),
    "ref_twap_all": ("twap_pullback", None, "twap"),
    "ref_random": ("random_control", None, "none"),
}


def run_stop_study(store: MarketStore, costs: CostModel) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
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
        twap = g.set_index("ts")["close"].expanding().mean()
        own: dict[str, Rule] = {"or_inside": rule_or_inside, "or_opposite": rule_or_opposite,
                                "twap": rule_twap_cross(twap), "none": rule_none}
        ctx = {"day": d, "gap_pct": None, "ema5": None}
        made: dict[str, Entry | None] = {}
        opt_cache: dict[str, pd.DataFrame] = {}
        for sname, (ename, flt, own_key) in SETUPS.items():
            if flt is not None and bool(feats.at[d, flt[0]]) != flt[1]:
                continue
            if ename not in made:
                made[ename] = ENTRIES[ename](g, ctx, expiries)
            e = made[ename]
            if e is None:
                continue
            sym = option_symbol(e)
            if sym not in opt_cache:
                opt_cache[sym] = store.candles(sym, "1minute", datetime.combine(d, time(9, 15)),
                                               datetime.combine(d, time(15, 30)))
            opt = opt_cache[sym]
            if opt.empty:
                continue
            for exit_mode, rule in (("own_rule", own[own_key]), ("hold_1510", rule_none)):
                for stop in STOPS:
                    tr = simulate(e, opt, g, rule, stop_pct=stop)
                    if tr is None:
                        continue
                    c = costs.round_trip(tr["entry_px"], tr["exit_px"], LOT).total
                    rows.append({**tr, "setup": sname, "exit_mode": exit_mode,
                                 "stop": "none" if stop is None else f"{int(stop * 100)}%",
                                 "net_inr": tr["pts"] * LOT - c, "net2_inr": tr["pts"] * LOT - 2 * c,
                                 "mae_pct": tr["mae_r"] * 0.30 * 100})  # mae_r is in units of 30% of entry
    trades = pd.DataFrame(rows)
    days = sorted(trades["day"].unique())
    n = len(days)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(days)}
    trades["split"] = trades["day"].map(split)
    return trades, summarize_stops(trades), killed_winners(trades)


def _m(x: pd.DataFrame) -> dict[str, Any]:
    if x.empty:
        return {"n": 0}
    w, lo = x[x["net_inr"] > 0]["net_inr"].sum(), -x[x["net_inr"] <= 0]["net_inr"].sum()
    return {"n": len(x), "net": round(x["net_inr"].mean(), 1), "pf": round(w / lo, 2) if lo else None,
            "win": round((x["net_inr"] > 0).mean(), 3)}


def summarize_stops(trades: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (s, x, st), g in trades.groupby(["setup", "exit_mode", "stop"]):
        top = g.sort_values("net_inr", ascending=False)
        out.append({
            "setup": s, "exit": x, "stop": st, **_m(g),
            "dev": _m(g[g["split"] == "dev"]).get("net"), "val": _m(g[g["split"] == "validate"]).get("net"),
            "test": _m(g[g["split"] == "test"]).get("net"),
            "CE": _m(g[g["side"] == "CE"]).get("net"), "PE": _m(g[g["side"] == "PE"]).get("net"),
            "ex_top5": round(top["net_inr"].iloc[5:].mean(), 1) if len(top) > 5 else None,
            "net_2x": round(g["net2_inr"].mean(), 1),
            "worst_trade": round(g["net_inr"].min()), "p95_loss": round(g["net_inr"].quantile(0.05)),
            "avg_loss": round(g[g["net_inr"] <= 0]["net_inr"].mean(), 1),
        })
    return pd.DataFrame(out)


def killed_winners(trades: pd.DataFrame) -> pd.DataFrame:
    """From NO-STOP runs: how many trades dipped past each stop level but still finished profitable."""
    ns = trades[trades["stop"] == "none"]
    out = []
    for (s, x), g in ns.groupby(["setup", "exit_mode"]):
        winners = g[g["net_inr"] > 0]
        row: dict[str, Any] = {"setup": s, "exit": x, "n": len(g), "winners": len(winners),
                               "winner_mae_p50": round(winners["mae_pct"].median(), 1),
                               "winner_mae_p75": round(winners["mae_pct"].quantile(0.25), 1),
                               "winner_mae_p90": round(winners["mae_pct"].quantile(0.10), 1)}
        for lvl in (20, 30, 40, 50, 60):
            dipped = g[g["mae_pct"] <= -lvl]
            row[f"dipped_{lvl}"] = len(dipped)
            row[f"recovered_{lvl}"] = int((dipped["net_inr"] > 0).sum())
        out.append(row)
    return pd.DataFrame(out)


def pick_stop(summary: pd.DataFrame, setup: str, exit_mode: str) -> dict[str, Any]:
    """Declared rule: best DEV expectancy, then report whether validate/test agree."""
    g = summary[(summary["setup"] == setup) & (summary["exit"] == exit_mode)].copy()
    best = g.sort_values("dev", ascending=False).iloc[0]
    return {"setup": setup, "exit": exit_mode, "chosen_on_dev": best["stop"], "dev": best["dev"],
            "val": best["val"], "test": best["test"],
            "confirmed": bool(best["val"] is not None and best["val"] > 0 and best["test"] is not None
                              and best["test"] > 0 and not np.isnan(best["val"]))}


__all__ = ["STOPS", "SETUPS", "run_stop_study", "pick_stop", "killed_winners", "summarize_stops", "date"]
