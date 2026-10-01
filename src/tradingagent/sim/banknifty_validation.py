"""G1/G2 on Bank Nifty — cross-instrument validation (`tradingagent backtest-g-banknifty`).
Spec: docs/reports/2026-10-01_banknifty_g_validation.md (pre-declared). Measurement only — the frozen G1/G2
signal code (discovery_study.g1_signal / g2_signal) is reused unchanged; only the strike step differs.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.discovery_study import VALIDATION, follow
from tradingagent.sim.entry_study import day_features
from tradingagent.sim.exit_study import Entry, simulate
from tradingagent.sim.logic_study import logic_features

BN_STEP = 100
BN_LOT = 30                          # for ₹ costs only; results are judged in R and % of premium
WEEKLY_ERA_END = date(2024, 11, 20)  # last Bank Nifty weekly expiry
Ctx = dict[str, Any]


def contexts(store: MarketStore, underlying: str, expiries: list[date], start: date,
             end: date) -> Iterator[tuple[date, pd.DataFrame, Ctx]]:
    idx = store.candles(f"NSE-{underlying}", "1minute")
    idx["day"] = idx["ts"].dt.date
    vixd = store.candles("NSE-INDIAVIX", "1day")   # only feeds unused logic features; G1/G2 use none of them
    vixd["day"] = vixd["ts"].dt.date
    feats, lf = day_features(idx), logic_features(idx, vixd)
    exp_set = set(expiries)
    for d, g in idx.groupby("day"):
        if not (start <= d <= end) or d in exp_set:
            continue
        nxt = [e for e in expiries if e > d]
        if not nxt or d not in lf.index or pd.isna(lf.at[d, "open_outside"]):
            continue
        yield d, g.reset_index(drop=True), {
            "day": d, "expiry": nxt[0], "open_outside": bool(lf.at[d, "open_outside"]),
            "narrow_or": bool(feats.at[d, "narrow_or"]), "low_vol": feats.at[d, "high_vol"] == False,  # noqa: E712
            "atr_pts": float(lf.at[d, "atr_pts"]) if pd.notna(lf.at[d, "atr_pts"]) else np.nan,
        }


def restrike(e: Entry, g: pd.DataFrame, step: int) -> Entry:
    """ATM on the instrument's own strike grid: index close of the last minute before the signal."""
    px = float(g[g["ts"] < pd.Timestamp(e.signal_ts)]["close"].iloc[-1])
    return replace(e, strike=int(round(px / step) * step))


def signals(store: MarketStore, underlying: str, expiries: list[date], start: date, end: date,
            step: int) -> Iterator[tuple[date, pd.DataFrame, Ctx, str, Entry]]:
    for d, g, c in contexts(store, underlying, expiries, start, end):
        for name, (fn, _, _) in VALIDATION.items():
            e = fn(g, c)
            if e is not None:
                yield d, g, c, name.replace("_oos", ""), restrike(e, g, step)


def stage_a(store: MarketStore, underlying: str, expiries: list[date], start: date, end: date,
            step: int) -> pd.DataFrame:
    rows = [{"setup": n, "day": d, "side": e.side, "entry_ts": e.signal_ts,
             "follow_60": follow(g, e.signal_ts, e.side, 60, c["atr_pts"]),
             "follow_eod": follow(g, e.signal_ts, e.side, None, c["atr_pts"])}
            for d, g, c, n, e in signals(store, underlying, expiries, start, end, step)]
    return pd.DataFrame(rows)


def overlap(bn: pd.DataFrame, nifty: pd.DataFrame) -> pd.DataFrame:
    """Per setup: share of Bank Nifty signal days that were also signal days on Nifty, and same side."""
    m = bn.merge(nifty[["setup", "day", "side"]], on=["setup", "day"], how="left", suffixes=("", "_nifty"))
    out = m.groupby("setup").apply(lambda x: pd.Series({
        "bn_signals": len(x), "also_on_nifty%": round(x["side_nifty"].notna().mean() * 100, 1),
        "same_side%": round((x["side"] == x["side_nifty"]).mean() * 100, 1)}), include_groups=False)
    return out.reset_index()


def stage_b(store: MarketStore, costs: CostModel, underlying: str, expiries: list[date], start: date, end: date,
            step: int, lot: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for d, g, _c, name, e in signals(store, underlying, expiries, start, end, step):
        fn_rule, stop = VALIDATION[f"{name}_oos" if name != "RANDOM" else name][1:]
        sym = f"NSE-{underlying}-{e.expiry.strftime('%d%b%y')}-{e.strike}-{e.side}"
        opt = store.candles(sym, "1minute", datetime.combine(d, time(9, 15)), datetime.combine(d, time(15, 30)))
        if opt.empty:
            rows.append({"day": d, "variant": name, "missing": sym})
            continue
        tr = simulate(e, opt, g, fn_rule, stop_pct=stop)
        if tr is None:
            continue
        cst = costs.round_trip(tr["entry_px"], tr["exit_px"], lot).total
        net = tr["pts"] * lot - cst
        rows.append({**tr, "variant": name, "net_inr": net, "net2_inr": net - cst,
                     "r_net": net / (tr["risk_pts"] * lot), "pct_prem": net / (tr["entry_px"] * lot) * 100,
                     "era": "weekly" if d <= WEEKLY_ERA_END else "monthly", "delay_min": np.nan})
    t = pd.DataFrame(rows)
    if t.empty or "net_inr" not in t:
        return t
    traded = t.dropna(subset=["net_inr"]).copy()
    days_ = sorted(traded["day"].unique())
    n = len(days_)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(days_)}
    traded["split"] = traded["day"].map(split)
    traded["half"] = np.where(traded["day"] <= days_[n // 2], "H1", "H2")
    missing = t[t["net_inr"].isna()] if "missing" in t else t.iloc[0:0]
    return pd.concat([traded, missing], ignore_index=True)
