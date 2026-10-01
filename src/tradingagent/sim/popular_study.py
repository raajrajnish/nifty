"""Popular-strategies study, batch 1 (`tradingagent backtest-popular`).
Spec: docs/reports/2026-10-01_popular_strategies_study.md (pre-declared). NEW code only; G1/G2 untouched.
"""

from collections.abc import Callable, Iterator
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.features.indicators import camarilla, cpr, rsi, supertrend
from tradingagent.sim.costs import CostModel
from tradingagent.sim.discovery_study import follow, random_entry
from tradingagent.sim.entry_study import day_features, five_min
from tradingagent.sim.exit_study import LOT, STEP, Entry, Rule, State, option_symbol, rule_none, simulate
from tradingagent.sim.logic_study import logic_features
from tradingagent.sim.stop_study import rule_or_opposite

NAN = float("nan")
Ctx = dict[str, Any]


def _e(c: Ctx, ts: pd.Timestamp, side: str, close: float, hi: float = NAN, lo: float = NAN) -> Entry:
    return Entry(c["day"], ts.to_pydatetime(), side, int(round(close / STEP) * STEP), c["expiry"], hi, lo)


def _window(bars: pd.DataFrame, start: time, end: time = time(13, 30)) -> pd.DataFrame:
    return bars[(bars.index.time >= start) & (bars.index.time <= end)]


# ---------------------------------------------------------------------------- strategies
def k1_cpr(g: pd.DataFrame, c: Ctx) -> Entry | None:
    if not c["cpr_narrow"]:
        return None
    tc, bc = c["tc"], c["bc"]
    for ts, b in _window(five_min(g), time(9, 35)).iterrows():
        if b["close"] > tc:
            return _e(c, ts, "CE", b["close"], hi=tc, lo=bc)
        if b["close"] < bc:
            return _e(c, ts, "PE", b["close"], hi=tc, lo=bc)
    return None


def k2_supertrend(g: pd.DataFrame, c: Ctx) -> Entry | None:
    st: pd.Series = c["st_trend"]          # 5-min labels of TODAY, with the previous label's trend in c["st_prev"]
    prev = c["st_prev"]
    bars = five_min(g)
    for ts, tr in st.items():
        if np.isnan(tr) or prev is None or np.isnan(prev):
            prev = tr
            continue
        if time(9, 45) <= ts.time() <= time(13, 30) and tr != prev:
            return _e(c, ts, "CE" if tr > 0 else "PE", float(bars.at[ts, "close"]))
        prev = tr
    return None


def k3_first_candle(g: pd.DataFrame, c: Ctx) -> Entry | None:
    first = g[g["ts"].dt.time < time(9, 20)]
    if len(first) < 4:
        return None
    hi, lo = float(first["high"].max()), float(first["low"].min())
    for ts, b in _window(five_min(g), time(9, 25)).iterrows():
        if b["close"] > hi:
            return _e(c, ts, "CE", b["close"], hi=hi, lo=lo)
        if b["close"] < lo:
            return _e(c, ts, "PE", b["close"], hi=hi, lo=lo)
    return None


def k4_rsi(g: pd.DataFrame, c: Ctx) -> Entry | None:
    r: pd.Series = c["rsi"]
    prev = c["rsi_prev"]
    bars = five_min(g)
    for ts, v in r.items():
        if prev is not None and not np.isnan(prev) and not np.isnan(v) and time(9, 45) <= ts.time() <= time(13, 30):
            if prev < 30 <= v:
                return _e(c, ts, "CE", float(bars.at[ts, "close"]))
            if prev > 70 >= v:
                return _e(c, ts, "PE", float(bars.at[ts, "close"]))
        prev = v
    return None


def k5a_camarilla_breakout(g: pd.DataFrame, c: Ctx) -> Entry | None:
    lv = c["cam"]
    for ts, b in _window(five_min(g), time(9, 35)).iterrows():
        if b["close"] > lv["R4"]:
            return _e(c, ts, "CE", b["close"], lo=lv["R3"])     # exit: close back below R3
        if b["close"] < lv["S4"]:
            return _e(c, ts, "PE", b["close"], hi=lv["S3"])     # exit: close back above S3
    return None


def k5b_camarilla_fade(g: pd.DataFrame, c: Ctx) -> Entry | None:
    lv = c["cam"]
    for ts, b in _window(five_min(g), time(9, 35)).iterrows():
        if b["high"] >= lv["R3"] and b["close"] < lv["R3"]:
            return _e(c, ts, "PE", b["close"], hi=lv["R4"])     # exit: close above R4
        if b["low"] <= lv["S3"] and b["close"] > lv["S3"]:
            return _e(c, ts, "CE", b["close"], lo=lv["S4"])     # exit: close below S4
    return None


def rule_series_exit(series: pd.Series, test: Callable[[float, str], bool], reason: str) -> Rule:
    """Exit on a completed 5-min bar when test(value_at_that_bar, side) is True."""
    def f(s: State, o: pd.Series, i: pd.Series, e: Entry) -> str | None:
        ts = pd.Timestamp(i["ts"])
        if ts.minute % 5 != 4:
            return None
        v = series.get(ts + timedelta(minutes=1))  # 5-min bar completing at this minute is labelled +1 min
        return reason if v is not None and not np.isnan(v) and test(float(v), e.side) else None
    return f


def strategies(c: Ctx) -> dict[str, tuple[Callable[[pd.DataFrame, Ctx], Entry | None], Rule, float]]:
    st_exit = rule_series_exit(c["st_trend"], lambda v, side: (v < 0) if side == "CE" else (v > 0), "ST_FLIP")
    rsi_exit = rule_series_exit(c["rsi"], lambda v, side: (v >= 70) if side == "CE" else (v <= 30), "RSI_TARGET")
    return {
        "K1_narrow_cpr": (k1_cpr, rule_or_opposite, 0.50),
        "K2_supertrend": (k2_supertrend, st_exit, 0.50),
        "K3_first_candle": (k3_first_candle, rule_or_opposite, 0.50),
        "K4_rsi_reversal": (k4_rsi, rsi_exit, 0.30),
        "K5a_camarilla_breakout": (k5a_camarilla_breakout, rule_or_opposite, 0.50),
        "K5b_camarilla_fade": (k5b_camarilla_fade, rule_or_opposite, 0.50),
        "RANDOM": (random_entry, rule_none, 0.30),
    }


# ---------------------------------------------------------------------------- day contexts
def contexts(store: MarketStore, expiries: list[date], start: date,
             end: date) -> Iterator[tuple[date, pd.DataFrame, Ctx]]:
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    vixd = store.candles("NSE-INDIAVIX", "1day")
    vixd["day"] = vixd["ts"].dt.date
    feats, lf = day_features(idx), logic_features(idx, vixd)
    daily = idx.groupby("day").agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    # continuous 5-min bars (labelled by end time) → indicators with warm-up across days
    b5 = pd.concat([five_min(g) for _, g in idx.groupby("day")]).sort_index()
    st = supertrend(b5)["trend"]
    rs = rsi(b5["close"])
    widths = {}
    days = list(daily.index)
    for i in range(1, len(days)):
        p, tc, bc = cpr(*daily.loc[days[i - 1], ["high", "low", "close"]].astype(float))
        widths[days[i]] = ((tc - bc) / p, p, tc, bc)
    wser = pd.Series({d: v[0] for d, v in widths.items()})
    narrow_cut = wser.shift(1).rolling(60, min_periods=40).quantile(0.33)
    exp_set = set(expiries)
    for d, g in idx.groupby("day"):
        if not (start <= d <= end) or d in exp_set or d not in widths:
            continue
        nxt = [e for e in expiries if e > d]
        if not nxt:
            continue
        prev_day = days[days.index(d) - 1]
        h, low, cl = (float(daily.at[prev_day, k]) for k in ("high", "low", "close"))
        width, p, tc, bc = widths[d]
        today = st[st.index.date == d]
        before = st[st.index < pd.Timestamp(datetime.combine(d, time(0, 0)))]
        rtoday = rs[rs.index.date == d]
        rbefore = rs[rs.index < pd.Timestamp(datetime.combine(d, time(0, 0)))]
        yield d, g.reset_index(drop=True), {
            "day": d, "expiry": nxt[0], "tc": tc, "bc": bc,
            "cpr_narrow": bool(pd.notna(narrow_cut.get(d)) and width <= narrow_cut.get(d)),
            "cam": camarilla(h, low, cl),
            "st_trend": today, "st_prev": float(before.iloc[-1]) if len(before) else None,
            "rsi": rtoday, "rsi_prev": float(rbefore.iloc[-1]) if len(rbefore) else None,
            "atr_pts": float(lf.at[d, "atr_pts"]) if pd.notna(lf.at[d, "atr_pts"]) else NAN,
            "G1_day": bool(lf.at[d, "open_outside"]) and bool(feats.at[d, "narrow_or"]),
            "G2_day": bool(lf.at[d, "open_outside"]) and feats.at[d, "high_vol"] == False,  # noqa: E712
        }


# ---------------------------------------------------------------------------- stages
def stage_a(store: MarketStore, expiries: list[date], start: date, end: date) -> pd.DataFrame:
    rows = []
    for d, g, c in contexts(store, expiries, start, end):
        for name, (fn, _, _) in strategies(c).items():
            e = fn(g, c)
            if e is None:
                continue
            rows.append({"setup": name, "day": d, "side": e.side, "entry_ts": e.signal_ts,
                         "follow_60": follow(g, e.signal_ts, e.side, 60, c["atr_pts"]),
                         "follow_eod": follow(g, e.signal_ts, e.side, None, c["atr_pts"])})
    return pd.DataFrame(rows)


def stage_b(store: MarketStore, costs: CostModel, expiries: list[date], setups: list[str],
            start: date, end: date) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for d, g, c in contexts(store, expiries, start, end):
        cache: dict[str, pd.DataFrame] = {}
        for name, (fn, rule, stop) in strategies(c).items():
            if name not in setups and name != "RANDOM":
                continue
            e = fn(g, c)
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
            cst = costs.round_trip(tr["entry_px"], tr["exit_px"], LOT).total
            net = tr["pts"] * LOT - cst
            rows.append({**tr, "G1_day": c["G1_day"], "G2_day": c["G2_day"], "variant": name, "net_inr": net,
                         "net2_inr": net - cst, "r_net": net / (tr["risk_pts"] * LOT), "delay_min": np.nan})
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    days_ = sorted(t["day"].unique())
    n = len(days_)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(days_)}
    t["split"] = t["day"].map(split)
    t["half"] = np.where(t["day"] <= days_[n // 2], "H1", "H2")
    return t
