"""Magnitude study (`tradingagent backtest-magnitude`). Spec: docs/reports/2026-10-01_magnitude_study.md.

Measurement only. Can the SIZE of the move after 09:30 be predicted from information known by 09:30?
"""

from datetime import date, time
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore

PREDICTORS = ("P1_squeeze", "P2_vix_level", "P3_vix_change_open", "P4_gap_atr", "P5_or_width_atr",
              "P6_open_outside", "P7_days_to_expiry")


def day_table(idx: pd.DataFrame, vix1: pd.DataFrame, vixd: pd.DataFrame, expiries: list[date]) -> pd.DataFrame:
    """One row per trading day: predictors (known by 09:30) and targets (after 09:30). idx/vix1: 1-min bars."""
    idx = idx.copy()
    idx["day"] = idx["ts"].dt.date
    idx["t"] = idx["ts"].dt.time
    daily = idx.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                   close=("close", "last"))
    rng = daily["high"] - daily["low"]
    atr = rng.shift(1).rolling(14).mean()                                       # previous 14 days only
    rngp = rng / daily["close"]
    p1 = rngp.shift(1).rolling(5).mean() / rngp.shift(1).rolling(20).mean()
    vd = vixd.assign(day=vixd["ts"].dt.date).set_index("day")["close"].reindex(daily.index)
    p2 = vd.shift(1) / vd.shift(1).rolling(60, min_periods=30).median()
    v1 = vix1.assign(day=vix1["ts"].dt.date, t=vix1["ts"].dt.time)
    vix_0929 = v1[v1["t"] <= time(9, 29)].groupby("day")["close"].last().reindex(daily.index)
    p3 = vix_0929 / vd.shift(1) - 1
    first = idx.groupby("day")["open"].first()
    p4 = (first - daily["close"].shift(1)).abs() / atr
    o = idx[idx["t"] < time(9, 30)].groupby("day").agg(h=("high", "max"), lo=("low", "min"))
    p5 = (o["h"] - o["lo"]).reindex(daily.index) / atr
    p6 = ((first > daily["high"].shift(1)) | (first < daily["low"].shift(1))).astype(float)
    days = list(daily.index)
    pos = {d: i for i, d in enumerate(days)}
    exp_sorted = sorted(expiries)

    def to_expiry(d: date) -> float:
        """Trading days from d to the next expiry (0 = expiry day itself, 1 = the day before)."""
        nxt = next((e for e in exp_sorted if e >= d), None)
        return float(pos[nxt] - pos[d]) if nxt in pos else np.nan

    p7 = pd.Series({d: to_expiry(d) for d in days})
    after = idx[(idx["t"] >= time(9, 30)) & (idx["t"] <= time(15, 10))].groupby("day").agg(
        h=("high", "max"), lo=("low", "min"), o=("open", "first"), c=("close", "last"))
    tbl = pd.DataFrame({
        "P1_squeeze": p1, "P2_vix_level": p2, "P3_vix_change_open": p3, "P4_gap_atr": p4, "P5_or_width_atr": p5,
        "P6_open_outside": p6, "P7_days_to_expiry": p7,
        "range_after_atr": (after["h"] - after["lo"]).reindex(daily.index) / atr,
        "trend_after_atr": (after["c"] - after["o"]).abs().reindex(daily.index) / atr,
    })
    tbl["expiry_day"] = [d in set(expiries) for d in tbl.index]
    return tbl


def _spearman_ci(x: pd.Series, y: pd.Series, runs: int = 2000, seed: int = 3) -> tuple[float, float, float]:
    d = pd.DataFrame({"x": x, "y": y}).dropna()
    rho = float(d["x"].rank().corr(d["y"].rank()))
    rng = np.random.default_rng(seed)
    n = len(d)
    xs, ys = d["x"].to_numpy(), d["y"].to_numpy()
    boots = []
    for _ in range(runs):
        i = rng.integers(0, n, n)
        boots.append(pd.Series(xs[i]).rank().corr(pd.Series(ys[i]).rank()))
    return rho, float(np.nanquantile(boots, 0.025)), float(np.nanquantile(boots, 0.975))


def evaluate(tbl: pd.DataFrame, seen: pd.DataFrame) -> pd.DataFrame:
    """tbl = untouched period (decides), seen = 2023–26 (consistency). Expiry days already removed."""
    big_cut = tbl["range_after_atr"].quantile(2 / 3)
    out = []
    for p in PREDICTORS:
        d = tbl[[p, "range_after_atr"]].dropna()
        rho, lo, hi = _spearman_ci(d[p], d["range_after_atr"])
        rho_seen = float(seen[p].rank().corr(seen["range_after_atr"].rank()))
        if d[p].nunique() <= 2:
            groups = d.groupby(d[p])
        else:
            groups = d.groupby(pd.qcut(d[p].rank(method="first"), 3, labels=["low", "mid", "high"]), observed=True)
        rates = {str(k): round(float((g["range_after_atr"] >= big_cut).mean() * 100), 1) for k, g in groups}
        best = max(rates.values())
        ok = abs(rho) >= 0.10 and (lo > 0 or hi < 0) and np.sign(rho) == np.sign(rho_seen) and best >= 40
        out.append({"predictor": p, "n": len(d), "rho_untouched": round(rho, 3), "ci95": f"[{lo:.3f}, {hi:.3f}]",
                    "rho_2023_26": round(rho_seen, 3), "big_day_rate_by_group_%": rates, "best_rate_%": best,
                    "PASS": bool(ok)})
    return pd.DataFrame(out)


def combined_score(untouched: pd.DataFrame, seen: pd.DataFrame, passing: list[str],
                   signs: dict[str, float]) -> dict[str, Any]:
    """Tercile-rank sum of passing predictors (direction from untouched). Evaluated on `seen` only."""
    s = seen.dropna(subset=[*passing, "range_after_atr"]).copy()
    score = pd.Series(0.0, index=s.index)
    for p in passing:
        r = pd.qcut(s[p].rank(method="first"), 3, labels=[1, 2, 3]).astype(float)
        score += r if signs[p] > 0 else 4 - r
    s["score"] = score
    big_cut = s["range_after_atr"].quantile(2 / 3)
    top = s[s["score"] >= s["score"].quantile(2 / 3)]
    return {"n": len(s), "top_third_days": len(top),
            "big_day_rate_top_%": round(float((top["range_after_atr"] >= big_cut).mean() * 100), 1),
            "baseline_%": 33.3, "USEFUL": bool((top["range_after_atr"] >= big_cut).mean() >= 0.45)}


def load(store: MarketStore) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (store.candles("NSE-NIFTY", "1minute"), store.candles("NSE-INDIAVIX", "1minute"),
            store.candles("NSE-INDIAVIX", "1day"))
