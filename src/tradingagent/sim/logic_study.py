"""Setup-logic study (`tradingagent backtest-logic`). Spec: docs/reports/2026-10-01_setup_logic_study.md."""

from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.entry_study import ENTRIES, day_features
from tradingagent.sim.exit_study import LOT, metrics, option_symbol, simulate
from tradingagent.sim.followthrough_study import SETUPS
from tradingagent.sim.timing_study import bootstrap_ci

GAP_MIN = 0.0015


def logic_features(idx: pd.DataFrame, vix_daily: pd.DataFrame) -> pd.DataFrame:
    """Per-day features known before the session (F1, F2, F4, F5 gap, F6). idx has a 'day' column."""
    daily = idx.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                   close=("close", "last"))
    rng = (daily["high"] - daily["low"]) / daily["close"]
    f = pd.DataFrame(index=daily.index)
    f["squeeze"] = rng.shift(1).rolling(5).mean() / rng.shift(1).rolling(20).mean() < 0.80          # F1
    v = vix_daily.set_index("day")["close"].reindex(daily.index)
    f["vix_prev"] = v.shift(1)
    f["vix_cheap"] = v.shift(1) < v.shift(1).rolling(60, min_periods=30).median()                    # F2
    f["open_outside"] = (daily["open"] > daily["high"].shift(1)) | (daily["open"] < daily["low"].shift(1))  # F4
    f["gap"] = (daily["open"] - daily["close"].shift(1)) / daily["close"].shift(1)                    # F5
    big = (daily["high"] - daily["low"]).shift(1) > 1.5 * (daily["high"] - daily["low"]).shift(2).rolling(14).mean()
    f["after_big_day"] = big                                                                          # F6
    f["atr_pts"] = (daily["high"] - daily["low"]).shift(1).rolling(14).mean()
    return f


def gap_group(gap: float, side: str) -> str:
    if pd.isna(gap) or abs(gap) < GAP_MIN:
        return "no_gap"
    return "aligned" if (gap > 0) == (side == "CE") else "opposed"


def follow(idx_day: pd.DataFrame, entry_ts: pd.Timestamp, side: str, minutes: int | None, atr: float) -> float:
    s = idx_day.set_index("ts")["close"]
    i0 = s[:entry_ts].iloc[-1] if len(s[:entry_ts]) else np.nan
    end = pd.Timestamp(datetime.combine(entry_ts.date(), time(15, 10))) if minutes is None \
        else entry_ts + timedelta(minutes=minutes)
    i1 = s[:end].iloc[-1]
    return float((i1 - i0) / atr * (1 if side == "CE" else -1)) if atr and not np.isnan(atr) else np.nan


def build_trades(store: MarketStore, costs: CostModel, start: date | None = None) -> pd.DataFrame:
    """start: only trade days >= start (features still use all earlier history)."""
    expiries = [r[0] for r in store.con.execute(
        "SELECT DISTINCT expiry FROM contracts WHERE kind='CE' AND underlying='NIFTY' ORDER BY expiry").fetchall()]
    exp_set = set(expiries)
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    vix1 = store.candles("NSE-INDIAVIX", "1minute")
    vixd = store.candles("NSE-INDIAVIX", "1day")
    vixd["day"] = vixd["ts"].dt.date
    feats = day_features(idx)
    lf = logic_features(idx, vixd)
    vix_series = vix1.set_index("ts")["close"]
    rows: list[dict[str, Any]] = []
    for d, g in idx.groupby("day"):
        if d in exp_set or (start is not None and d < start):
            continue
        g = g.reset_index(drop=True)
        ctx = {"day": d, "gap_pct": None, "ema5": None}
        cache: dict[str, pd.DataFrame] = {}
        for sname, (ename, flt, rule, stop) in SETUPS.items():
            if flt is not None and bool(feats.at[d, flt[0]]) != flt[1]:
                continue
            e = ENTRIES[ename](g, ctx, expiries)
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
            ets = pd.Timestamp(tr["entry_ts"])
            vix_now = vix_series[:ets - timedelta(seconds=1)]
            vix_at = float(vix_now.iloc[-1]) if len(vix_now) and vix_now.index[-1].date() == d else np.nan
            atr = lf.at[d, "atr_pts"]
            rows.append({**tr, "setup": sname, "net_inr": tr["pts"] * LOT - c, "net2_inr": tr["pts"] * LOT - 2 * c,
                         "r_net": (tr["pts"] * LOT - c) / (tr["risk_pts"] * LOT),
                         "follow_60": follow(g, ets, e.side, 60, atr), "follow_eod": follow(g, ets, e.side, None, atr),
                         "F1_squeeze": lf.at[d, "squeeze"], "F2_vix_cheap": lf.at[d, "vix_cheap"],
                         "F3_vix_rising": bool(vix_at > lf.at[d, "vix_prev"]) if not np.isnan(vix_at) else None,
                         "F4_open_outside": lf.at[d, "open_outside"],
                         "F5_gap": gap_group(lf.at[d, "gap"], e.side), "F6_after_big_day": lf.at[d, "after_big_day"]})
    trades = pd.DataFrame(rows)
    if trades.empty:
        return trades
    days = sorted(trades["day"].unique())
    n = len(days)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(days)}
    trades["split"] = trades["day"].map(split)
    trades["half"] = np.where(trades["day"] <= days[n // 2], "H1", "H2")
    return trades


FEATURES = ("F1_squeeze", "F2_vix_cheap", "F3_vix_rising", "F4_open_outside", "F5_gap", "F6_after_big_day")


def group_stats(g: pd.DataFrame) -> dict[str, Any]:
    m = metrics(g)
    parts = {p: metrics(g[g["split"] == p]).get("exp_inr") for p in ("dev", "validate", "test")}
    vt = g[g["split"].isin(["validate", "test"])]["net_inr"]
    sides = {s: metrics(g[g["side"] == s]).get("exp_inr") for s in ("CE", "PE")}
    top = g.sort_values("net_inr", ascending=False)["net_inr"]
    lo, hi, p0 = bootstrap_ci(g["net_inr"].to_numpy()) if len(g) >= 10 else (np.nan, np.nan, np.nan)
    return {"n": m["n"], "right_dir_60%": round(float((g["follow_60"] > 0).mean() * 100), 1),
            "follow_eod_atr": round(float(g["follow_eod"].mean()), 3), "net": m.get("exp_inr"),
            "dev": parts["dev"], "val+test": round(float(vt.mean()), 1) if len(vt) else None,
            "CE": sides["CE"], "PE": sides["PE"],
            "ex_top5": round(float(top.iloc[5:].mean()), 1) if len(top) > 5 else None,
            "ci95": f"[{lo:.0f}, {hi:.0f}]", "P(<=0)": round(p0, 2)}


def feature_table(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for setup, g in trades.groupby("setup"):
        rows.append({"setup": setup, "feature": "ALL", "value": "-", **group_stats(g)})
        for f in FEATURES:
            for val, sub in g.groupby(f, dropna=True):
                rows.append({"setup": setup, "feature": f, "value": str(val), **group_stats(sub)})
    return pd.DataFrame(rows)


def decide(table: pd.DataFrame) -> pd.DataFrame:
    """Pre-declared: improves right_dir_60 and net (dev AND val+test) for BOTH S1 and S2, n ≥ 60 each."""
    base = table[table["feature"] == "ALL"].set_index("setup")
    out = []
    for (f, val), grp in table[table["feature"] != "ALL"].groupby(["feature", "value"]):
        ok_setups = {}
        for setup in ("S1", "S2", "RANDOM"):
            r = grp[grp["setup"] == setup]
            if r.empty or setup not in base.index:
                ok_setups[setup] = False
                continue
            r0, b = r.iloc[0], base.loc[setup]
            ok_setups[setup] = bool(r0["n"] >= 60 and r0["right_dir_60%"] > b["right_dir_60%"]
                                    and (r0["dev"] or -1e9) > (b["dev"] or -1e9)
                                    and (r0["val+test"] or -1e9) > (b["val+test"] or -1e9))
        improves = ok_setups["S1"] and ok_setups["S2"]
        out.append({"feature": f, "value": val, "S1_ok": ok_setups["S1"], "S2_ok": ok_setups["S2"],
                    "RANDOM_ok": ok_setups["RANDOM"], "LOGIC_IMPROVEMENT": improves,
                    "kind": ("day filter (helps any entry)" if improves and ok_setups["RANDOM"]
                             else "setup-specific" if improves else "-")})
    return pd.DataFrame(out)


__all__ = ["build_trades", "feature_table", "decide", "logic_features", "gap_group", "FEATURES", "date"]
