"""Entry/filter study #2 (`tradingagent backtest-entries`). Exit FIXED; entries and filters vary.

Everything below was declared before the first run (docs/reports/2026-10-01_entry_study.md); nothing is
tuned on results. Filters only use information available at entry time (prior days, or today up to entry).

Exit (fixed): hard stop −30% premium, NO_PROGRESS (≥ +0.5R not reached within 30 min), 15:10 — and
for robustness the same entries are also run with HOLD (stop + 15:10 only).
Pass bar for any (entry, filter) cell — ALL must hold:
  n ≥ 100 · net expectancy > 0 in dev AND validate AND test · net expectancy > 0 at 2× costs ·
  PF ≥ 1.10 · both chronological halves > 0.
"""

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.exit_study import LOT, STEP, Entry, metrics, option_symbol, rule_no_progress, rule_none, simulate

SIGNAL_END = time(13, 30)
EXITS = {"no_progress_30m": rule_no_progress(30, 0.5), "hold_1510": rule_none}
GAP_PCT = 0.004


# ---------------------------------------------------------------------------- per-day context
def five_min(day_idx: pd.DataFrame) -> pd.DataFrame:
    """5-min bars labelled by their RIGHT edge (close known at that time)."""
    s = day_idx.set_index("ts")
    return s.resample("5min", label="right", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


def _entry(d: date, ts: pd.Timestamp, side: str, close: float, expiries: list[date], or_hi: float,
           or_lo: float) -> Entry | None:
    nxt = [e for e in expiries if e > d]
    if not nxt:
        return None
    return Entry(d, ts.to_pydatetime(), side, int(round(close / STEP) * STEP), nxt[0], or_hi, or_lo)


def _or(day_idx: pd.DataFrame, minutes: int) -> tuple[float, float] | None:
    end = (datetime.combine(date.min, time(9, 15)) + timedelta(minutes=minutes)).time()
    o = day_idx[day_idx["ts"].dt.time < end]
    if len(o) < minutes * 0.7:
        return None
    return float(o["high"].max()), float(o["low"].min())


# ---------------------------------------------------------------------------- entries (one per day max)
def e_orb(minutes: int):  # type: ignore[no-untyped-def]
    def f(day_idx: pd.DataFrame, ctx: dict[str, Any], exp: list[date]) -> Entry | None:
        r = _or(day_idx, minutes)
        if r is None:
            return None
        hi, lo = r
        start = (datetime.combine(date.min, time(9, 15)) + timedelta(minutes=minutes)).time()
        for ts, b in five_min(day_idx).iterrows():
            if start < ts.time() <= SIGNAL_END:
                if b["close"] > hi:
                    return _entry(ctx["day"], ts, "CE", b["close"], exp, hi, lo)
                if b["close"] < lo:
                    return _entry(ctx["day"], ts, "PE", b["close"], exp, hi, lo)
        return None
    return f


def e_twap_pullback(day_idx: pd.DataFrame, ctx: dict[str, Any], exp: list[date]) -> Entry | None:
    """Trend (TWAP rising/falling over 30 min) + pullback that touches TWAP and closes back on trend side."""
    s = day_idx.set_index("ts")["close"]
    twap = s.expanding().mean()
    r = _or(day_idx, 15) or (np.nan, np.nan)
    for ts, b in five_min(day_idx).iterrows():
        if not (time(10, 0) <= ts.time() <= SIGNAL_END):
            continue
        t_now = twap[:ts - timedelta(seconds=1)]
        t_then = twap[:ts - timedelta(minutes=30)]
        if t_now.empty or t_then.empty:
            continue
        tw, slope = t_now.iloc[-1], t_now.iloc[-1] - t_then.iloc[-1]
        if slope > 0 and b["low"] <= tw * 1.0005 and b["close"] > tw:
            return _entry(ctx["day"], ts, "CE", b["close"], exp, *r)
        if slope < 0 and b["high"] >= tw * 0.9995 and b["close"] < tw:
            return _entry(ctx["day"], ts, "PE", b["close"], exp, *r)
    return None


def e_ema_cross(day_idx: pd.DataFrame, ctx: dict[str, Any], exp: list[date]) -> Entry | None:
    """EMA9/EMA21 on continuous 5-min closes (warm-up carried over from prior days via ctx)."""
    ema = ctx["ema5"]
    d = ema[ema.index.date == ctx["day"]]
    r = _or(day_idx, 15) or (np.nan, np.nan)
    prev = None
    for ts, row in d.iterrows():
        diff = row["e9"] - row["e21"]
        if prev is not None and time(9, 45) <= ts.time() <= SIGNAL_END:
            if prev <= 0 < diff:
                return _entry(ctx["day"], ts, "CE", row["close"], exp, *r)
            if prev >= 0 > diff:
                return _entry(ctx["day"], ts, "PE", row["close"], exp, *r)
        prev = diff
    return None


def _gap_entry(go: bool):  # type: ignore[no-untyped-def]
    def f(day_idx: pd.DataFrame, ctx: dict[str, Any], exp: list[date]) -> Entry | None:
        g = ctx["gap_pct"]
        if g is None or abs(g) < GAP_PCT:
            return None
        first = day_idx[day_idx["ts"].dt.time < time(9, 30)]
        if len(first) < 10:
            return None
        bar_dir = np.sign(first["close"].iloc[-1] - first["open"].iloc[0])
        gap_dir = np.sign(g)
        if (bar_dir == gap_dir) != go:
            return None
        side_up = gap_dir > 0 if go else gap_dir < 0
        ts = pd.Timestamp(datetime.combine(ctx["day"], time(9, 30)))
        r = _or(day_idx, 15) or (np.nan, np.nan)
        return _entry(ctx["day"], ts, "CE" if side_up else "PE", float(first["close"].iloc[-1]), exp, *r)
    return f


def e_random(day_idx: pd.DataFrame, ctx: dict[str, Any], exp: list[date]) -> Entry | None:
    rng = np.random.default_rng(ctx["day"].toordinal())  # seeded per day → reproducible
    bars = [ts for ts in five_min(day_idx).index if time(9, 45) <= ts.time() <= SIGNAL_END]
    if not bars:
        return None
    ts = bars[int(rng.integers(len(bars)))]
    close = float(day_idx[day_idx["ts"] < ts]["close"].iloc[-1])
    r = _or(day_idx, 15) or (np.nan, np.nan)
    return _entry(ctx["day"], ts, "CE" if rng.random() < 0.5 else "PE", close, exp, *r)


ENTRIES = {
    "orb15": e_orb(15), "orb30": e_orb(30), "twap_pullback": e_twap_pullback, "ema9_21_cross": e_ema_cross,
    "gap_and_go": _gap_entry(True), "gap_fade": _gap_entry(False), "random_control": e_random,
}


# ---------------------------------------------------------------------------- filters (entry-time info only)
def day_features(idx: pd.DataFrame) -> pd.DataFrame:
    daily = idx.groupby("day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                   close=("close", "last"))
    daily["prev_close"] = daily["close"].shift(1)
    daily["gap_pct"] = (daily["open"] - daily["prev_close"]) / daily["prev_close"]
    rng = (daily["high"] - daily["low"]) / daily["close"]
    daily["atr14_pct"] = rng.shift(1).rolling(14).mean()                      # up to yesterday
    # Written as NOT(atr ≤ median): if either value is unknown (too little history) the day counts as
    # volatile, so G2 ("calm days only") does not trade. Plain `atr > median` made unknown days "calm"
    # (warm-up bug found 2026-10-02, see docs/HYPERCARE_LOG.md). Identical whenever both values exist.
    daily["high_vol"] = ~(daily["atr14_pct"] <= daily["atr14_pct"].shift(1).rolling(120, min_periods=40).median())
    or_w = idx[idx["ts"].dt.time < time(9, 30)].groupby("day").apply(
        lambda g: (g["high"].max() - g["low"].min()) / g["close"].iloc[-1], include_groups=False)
    daily["or15_pct"] = or_w
    daily["narrow_or"] = daily["or15_pct"] < daily["or15_pct"].shift(1).rolling(20, min_periods=10).median()
    # Study #3 (pre-declared): trend = yesterday's close vs its N-day average, both as of yesterday
    for n in (20, 50):
        daily[f"trend{n}_up"] = daily["close"].shift(1) > daily["close"].rolling(n).mean().shift(1)
    return daily


def _with_trend(t: pd.DataFrame, n: int) -> "pd.Series[bool]":
    up = t[f"trend{n}_up"] == True  # noqa: E712
    return ((t["side"] == "CE") & up) | ((t["side"] == "PE") & ~up)


FILTERS: dict[str, Callable[[pd.DataFrame], "pd.Series[bool]"]] = {
    "all": lambda t: pd.Series(True, index=t.index),
    "high_vol": lambda t: t["high_vol"] == True,  # noqa: E712
    "low_vol": lambda t: t["high_vol"] == False,  # noqa: E712
    "narrow_or": lambda t: t["narrow_or"] == True,  # noqa: E712
    "wide_or": lambda t: t["narrow_or"] == False,  # noqa: E712
    "gap_day": lambda t: t["gap_pct"].abs() >= GAP_PCT,
    "no_gap": lambda t: t["gap_pct"].abs() < GAP_PCT,
    "before_11": lambda t: pd.to_datetime(t["entry_ts"]).dt.time < time(11, 0),
    "after_11": lambda t: pd.to_datetime(t["entry_ts"]).dt.time >= time(11, 0),
    "pre_expiry_day": lambda t: t["pre_expiry"] == True,  # noqa: E712
    "not_pre_expiry": lambda t: t["pre_expiry"] == False,  # noqa: E712
    # study #3 — direction filter (pre-declared 2026-10-01)
    "with_trend20": lambda t: _with_trend(t, 20),
    "against_trend20": lambda t: ~_with_trend(t, 20),
    "with_trend50": lambda t: _with_trend(t, 50),
    "with_trend20+narrow_or": lambda t: _with_trend(t, 20) & (t["narrow_or"] == True),  # noqa: E712
    "with_trend20+low_vol": lambda t: _with_trend(t, 20) & (t["high_vol"] == False),  # noqa: E712
}


# ---------------------------------------------------------------------------- run
def run_entry_study(store: MarketStore, costs: CostModel, start: date | None = None,
                    entries: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """start: only trade days >= start (features still use all earlier history). entries: subset of ENTRIES."""
    chosen = {k: v for k, v in ENTRIES.items() if entries is None or k in entries}
    expiries = [r[0] for r in store.con.execute(
        "SELECT DISTINCT expiry FROM contracts WHERE kind='CE' AND underlying='NIFTY' ORDER BY expiry").fetchall()]
    exp_set = set(expiries)
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    feats = day_features(idx)
    c5 = idx.set_index("ts")["close"].resample("5min", label="right", closed="left").last().dropna()
    ema5 = pd.DataFrame({"close": c5, "e9": c5.ewm(span=9, adjust=False).mean(),
                         "e21": c5.ewm(span=21, adjust=False).mean()})
    days = sorted(idx["day"].unique())
    next_day = {d: days[i + 1] for i, d in enumerate(days[:-1])}
    opt_cache: dict[tuple[str, date], pd.DataFrame] = {}
    rows = []
    for d, g in idx.groupby("day"):
        if d in exp_set or (start is not None and d < start):  # expiry days not allowed
            continue
        g = g.reset_index(drop=True)
        ctx = {"day": d, "gap_pct": None if pd.isna(feats.at[d, "gap_pct"]) else float(feats.at[d, "gap_pct"]),
               "ema5": ema5}
        for ename, efn in chosen.items():
            e = efn(g, ctx, expiries)
            if e is None:
                continue
            key = (option_symbol(e), d)
            if key not in opt_cache:
                opt_cache[key] = store.candles(key[0], "1minute", datetime.combine(d, time(9, 15)),
                                               datetime.combine(d, time(15, 30)))
            opt = opt_cache[key]
            if opt.empty:
                continue
            for xname, xrule in EXITS.items():
                tr = simulate(e, opt, g, xrule)
                if tr is None:
                    continue
                c1 = costs.round_trip(tr["entry_px"], tr["exit_px"], LOT).total
                tr.update(entry=ename, exit=xname, cost_inr=c1, gross_inr=tr["pts"] * LOT,
                          net_inr=tr["pts"] * LOT - c1, net2_inr=tr["pts"] * LOT - 2 * c1,
                          r_net=(tr["pts"] * LOT - c1) / (tr["risk_pts"] * LOT),
                          gap_pct=feats.at[d, "gap_pct"], high_vol=feats.at[d, "high_vol"],
                          narrow_or=feats.at[d, "narrow_or"], pre_expiry=next_day.get(d) in exp_set,
                          trend20_up=feats.at[d, "trend20_up"], trend50_up=feats.at[d, "trend50_up"])
                rows.append(tr)
    trades = pd.DataFrame(rows)
    if trades.empty:
        return trades, pd.DataFrame()
    all_days = sorted(trades["day"].unique())
    n = len(all_days)
    split = {dd: ("dev" if i < 0.6 * n else "validate" if i < 0.8 * n else "test") for i, dd in enumerate(all_days)}
    trades["split"] = trades["day"].map(split)
    trades["half"] = np.where(trades["day"] <= all_days[n // 2], "H1", "H2")
    return trades, summarize(trades)


def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (ename, xname), g in trades.groupby(["entry", "exit"]):
        for fname, ffn in FILTERS.items():
            sub = g[ffn(g).fillna(False).astype(bool)]
            if sub.empty:
                continue
            m = metrics(sub)
            parts = {p: metrics(sub[sub["split"] == p]).get("exp_inr") for p in ("dev", "validate", "test")}
            halves = {h: metrics(sub[sub["half"] == h]).get("exp_inr") for h in ("H1", "H2")}
            exp2 = round(float(sub["net2_inr"].mean()), 1)
            ok = (m["n"] >= 100 and all(v is not None and v > 0 for v in parts.values())
                  and exp2 > 0 and (m.get("pf") or 0) >= 1.10 and all(v is not None and v > 0 for v in halves.values()))
            # Robustness (added 2026-10-01 after study #2 showed profits resting on a few big put days)
            sides = {s: metrics(sub[sub["side"] == s]).get("exp_inr") for s in ("CE", "PE")}
            ex_top5 = round(float(sub.sort_values("net_inr", ascending=False)["net_inr"].iloc[5:].mean()), 1) \
                if len(sub) > 5 else None
            robust = ok and all(v is not None and v > 0 for v in sides.values()) and (ex_top5 or 0) > 0
            out.append({"entry": ename, "exit": xname, "filter": fname, "n": m["n"], "win": m["win_rate"],
                        "gross": round(float(sub["gross_inr"].mean()), 1), "net": m["exp_inr"], "net_2x": exp2,
                        "pf": m.get("pf"), "dev": parts["dev"], "val": parts["validate"], "test": parts["test"],
                        "H1": halves["H1"], "H2": halves["H2"], "CE": sides["CE"], "PE": sides["PE"],
                        "ex_top5": ex_top5, "max_dd": m["max_dd_inr"], "PASS": ok, "ROBUST": robust})
    return pd.DataFrame(out).sort_values("net", ascending=False)
