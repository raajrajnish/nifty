"""Bank Nifty behaviour study, step B1 (`tradingagent bn-behaviour`). MEASUREMENT ONLY — no trading rules.
Spec: docs/reports/2026-10-02_banknifty_search.md ("Step B1"). Search window only; lock boxes refused.
"""

from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.banknifty_search import SEARCH_END, SEARCH_START, check_window, expiries, option_symbol
from tradingagent.sim.costs import CostModel
from tradingagent.sim.exit_study import HALF_SPREAD_PCT
from tradingagent.sim.timing_study import bootstrap_ci

WEEKLY_END = date(2024, 11, 20)


def _ci(x: pd.Series) -> str:
    x = x.dropna()
    if len(x) < 10:
        return "n<10"
    lo, hi, _ = bootstrap_ci(x.to_numpy())
    return f"{x.mean():+.3f} [{lo:+.3f}, {hi:+.3f}] n={len(x)}"


def _at(g: pd.DataFrame, t: time) -> float:
    s = g[g["ts"].dt.time < t]
    return float(s["close"].iloc[-1]) if len(s) else np.nan


def daily_table(idx: pd.DataFrame, nifty: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    """One row per day; every 'known before' feature uses past data only."""
    d = idx.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                               close=("close", "last"))
    rng = d["high"] - d["low"]
    d["prev_close"] = d["close"].shift(1)
    d["atr"] = rng.shift(1).rolling(14).mean()
    d["gap_pct"] = (d["open"] - d["prev_close"]) / d["prev_close"] * 100
    d["open_outside"] = (d["open"] > d["high"].shift(1)) | (d["open"] < d["low"].shift(1))
    d["nr7"] = rng.shift(1) <= rng.shift(1).rolling(7).min()
    v = vix.groupby("day")["close"].last()
    d["vix_prev"] = v.reindex(d.index).shift(1)
    by_day = {k: g for k, g in idx.groupby("day")}
    nf_day = {k: g for k, g in nifty.groupby("day")}
    nf_prev = nifty.groupby("day")["close"].last().shift(1)
    d["c1015"] = [_at(by_day[k], time(10, 15)) for k in d.index]
    d["c1510"] = [_at(by_day[k], time(15, 10)) for k in d.index]
    d["fh_range"] = [float(by_day[k][by_day[k]["ts"].dt.time < time(10, 15)]["high"].max()
                           - by_day[k][by_day[k]["ts"].dt.time < time(10, 15)]["low"].min()) for k in d.index]
    d["nf_1015"] = [_at(nf_day[k], time(10, 15)) if k in nf_day else np.nan for k in d.index]
    d["nf_prev"] = nf_prev.reindex(d.index)
    d["trend_day"] = (d["close"] - d["open"]).abs() >= 0.6 * rng
    return d


def time_of_day(idx: pd.DataFrame, d: pd.DataFrame) -> dict[str, pd.DataFrame]:
    s = idx.copy()
    s["slot"] = s["ts"].dt.floor("30min").dt.strftime("%H:%M")
    hi_slot = s.loc[s.groupby("day")["high"].idxmax(), "slot"].value_counts(normalize=True).sort_index()
    lo_slot = s.loc[s.groupby("day")["low"].idxmin(), "slot"].value_counts(normalize=True).sort_index()
    sc = s.groupby(["day", "slot"])["close"].last().unstack()
    r = sc.diff(axis=1).div(d["atr"].reindex(sc.index), axis=0)
    r.iloc[:, 0] = (sc.iloc[:, 0] - d["open"].reindex(sc.index)) / d["atr"].reindex(sc.index)
    cols = list(r.columns)
    rows = []
    for a, b in zip(cols[:-1], cols[1:], strict=True):
        x, y = r[a], r[b]
        ok = x.notna() & y.notna() & (x != 0)
        same = (np.sign(x[ok]) == np.sign(y[ok])).astype(float)
        cont = (y[ok] * np.sign(x[ok]))
        rows.append({"from": a, "to": b, "P(same dir)": round(same.mean() * 100, 1),
                     "next move in same dir (ATR)": _ci(cont)})
    absmove = r.abs().mean().round(3).rename("mean |move| ATR")
    return {"high_slot": (hi_slot * 100).round(1).to_frame("% of days high made"),
            "low_slot": (lo_slot * 100).round(1).to_frame("% of days low made"),
            "abs_move": absmove.to_frame(), "persistence": pd.DataFrame(rows)}


def opening(d: pd.DataFrame) -> dict[str, pd.DataFrame]:
    fh = (d["c1015"] - d["open"]) / d["atr"]
    rest = (d["c1510"] - d["c1015"]) / d["atr"] * np.sign(fh)
    terc = pd.qcut(fh.abs(), 3, labels=["small", "medium", "large"])
    sizes = ("small", "medium", "large")
    vals = [_ci(rest)] + [_ci(rest[terc == k]) for k in sizes]
    t1 = pd.DataFrame({"first-hour size": ["all", *sizes], "rest of day in first-hour direction (ATR)": vals})
    gap = d["gap_pct"]
    up = gap > 0
    filled = np.where(up, d["low"] <= d["prev_close"], d["high"] >= d["prev_close"])
    cont = np.where(up, d["c1510"] > d["open"], d["c1510"] < d["open"])
    b = pd.cut(gap.abs(), [0, 0.2, 0.5, 1.0, 10], labels=["<0.2%", "0.2-0.5%", "0.5-1%", ">1%"])
    t2 = pd.DataFrame({"bucket": b, "filled": filled, "continued": cont}).groupby("bucket", observed=True).agg(
        n=("filled", "size"), fill_pct=("filled", lambda x: round(x.mean() * 100, 1)),
        continue_pct=("continued", lambda x: round(x.mean() * 100, 1)))
    return {"first_hour": t1, "gaps": t2}


def day_types(d: pd.DataFrame) -> pd.DataFrame:
    base = d["trend_day"].mean() * 100
    fhr = d["fh_range"] / d["atr"]
    conds = {"all days": pd.Series(True, index=d.index), "NR7 yesterday": d["nr7"] == True,  # noqa: E712
             "open outside": d["open_outside"] == True, "open inside": d["open_outside"] == False,  # noqa: E712
             "|gap| >= 0.5%": d["gap_pct"].abs() >= 0.5, "|gap| < 0.2%": d["gap_pct"].abs() < 0.2,
             "VIX above 60d median": d["vix_prev"] > d["vix_prev"].rolling(60).median(),
             "VIX below 60d median": d["vix_prev"] <= d["vix_prev"].rolling(60).median(),
             "first-hour range < 0.35 ATR": fhr < 0.35, "first-hour range > 0.6 ATR": fhr > 0.6}
    rows = []
    for name, m in conds.items():
        x = d.loc[m.fillna(False), "trend_day"].astype(float)
        lo, hi, _ = bootstrap_ci(x.to_numpy()) if len(x) >= 10 else (np.nan, np.nan, np.nan)
        rows.append({"condition (known by 10:15)": name, "n": len(x), "trend-day %": round(x.mean() * 100, 1),
                     "95% CI": f"[{lo * 100:.1f}, {hi * 100:.1f}]", "vs base": round(x.mean() * 100 - base, 1)})
    return pd.DataFrame(rows)


def relative_strength(d: pd.DataFrame) -> pd.DataFrame:
    bn = (d["c1015"] / d["prev_close"] - 1) * 100
    nf = (d["nf_1015"] / d["nf_prev"] - 1) * 100
    rel = bn - nf
    rest = (d["c1510"] - d["c1015"]) / d["atr"]
    rows = []
    for name, m in {"BN stronger than Nifty by >0.2%": rel > 0.2, "BN weaker than Nifty by >0.2%": rel < -0.2,
                    "|difference| <= 0.2%": rel.abs() <= 0.2}.items():
        rows.append({"at 10:15": name, "BN 10:15→15:10 move (ATR)": _ci(rest[m])})
    s = np.sign(rel.where(rel.abs() > 0.2))
    rows.append({"at 10:15": "trade in direction of relative strength", "BN 10:15→15:10 move (ATR)": _ci(rest * s)})
    return pd.DataFrame(rows)


def option_economics(store: MarketStore, idx: pd.DataFrame, costs: CostModel, lot: int,
                     start: date, end: date) -> pd.DataFrame:
    """ATM CE and PE bought at 10:00 open, sold at 15:10 close, every non-expiry day.
    Fit option_pts = intercept + slope × index_move_pts (signed for the side).
    Break-even index move = (−intercept + cost) / slope."""
    exps = expiries(store)
    exp_set = set(exps)
    rows: list[dict[str, Any]] = []
    for day, g in idx.groupby("day"):
        if not (start <= day <= end) or day in exp_set:
            continue
        nxt = [e for e in exps if e > day]
        i0 = g[g["ts"].dt.time == time(10, 0)]
        i1 = g[g["ts"].dt.time == time(15, 10)]
        if not nxt or i0.empty or i1.empty:
            continue
        px0, px1 = float(i0["open"].iloc[0]), float(i1["close"].iloc[0])
        k = int(round(px0 / 100) * 100)
        for side in ("CE", "PE"):
            o = store.candles(option_symbol(nxt[0], k, side), "1minute", datetime.combine(day, time(10, 0)),
                              datetime.combine(day, time(15, 10)))
            if o.empty or o["ts"].iloc[0].time() != time(10, 0) or o["ts"].iloc[-1].time() != time(15, 10):
                continue
            e = float(o["open"].iloc[0]) * (1 + HALF_SPREAD_PCT)
            x = float(o["close"].iloc[-1]) * (1 - HALF_SPREAD_PCT)
            mv = (px1 - px0) * (1 if side == "CE" else -1)
            rows.append({"day": day, "side": side, "era": "weekly" if day <= WEEKLY_END else "monthly",
                         "dte": (nxt[0] - day).days, "entry": e, "opt_pts": x - e, "idx_move": mv,
                         "cost_pts": costs.round_trip(e, x, lot).total / lot})
    t = pd.DataFrame(rows)
    out = []
    for era, g in t.groupby("era"):
        slope, icpt = np.polyfit(g["idx_move"], g["opt_pts"], 1)
        cost = g["cost_pts"].median()
        out.append({"era": era, "n": len(g), "median premium": round(g["entry"].median()),
                    "median days to expiry": g["dte"].median(), "effective delta": round(slope, 3),
                    "decay 10:00→15:10 (pts)": round(icpt, 1), "costs (pts)": round(cost, 1),
                    "break-even index move (pts)": round((-icpt + cost) / slope),
                    "median |index move| (pts)": round(g["idx_move"].abs().median())})
    return pd.DataFrame(out)


def run(store: MarketStore, costs: CostModel, lot: int = 30) -> dict[str, Any]:
    check_window(SEARCH_START, SEARCH_END)
    idx = store.candles("NSE-BANKNIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    nf = store.candles("NSE-NIFTY", "1minute")
    nf["day"] = nf["ts"].dt.date
    vix = store.candles("NSE-INDIAVIX", "1day")
    vix["day"] = vix["ts"].dt.date
    d_all = daily_table(idx, nf, vix)
    d = d_all[(d_all.index >= SEARCH_START) & (d_all.index <= SEARCH_END)].dropna(subset=["atr", "c1015", "c1510"])
    win = idx[(idx["day"] >= SEARCH_START) & (idx["day"] <= SEARCH_END)]
    return {"days": len(d), "tod": time_of_day(win, d), "opening": opening(d), "day_types": day_types(d),
            "relative": relative_strength(d),
            "options": option_economics(store, win, costs, lot, SEARCH_START, SEARCH_END)}
