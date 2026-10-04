"""Exit diagnosis (spec: docs/reports/2026-10-04_exit_diagnosis.md). MEASUREMENT ONLY — chooses no rule.
Trades come from the tournament's own scoring code (frozen rules), Dec 2023 – Sep 2026. Read-only DB.
Usage: uv run --no-sync python scripts/exit_diagnosis.py
"""

import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from tradingagent.config import load_config  # noqa: E402
from tradingagent.data.store import MarketStore  # noqa: E402
from tradingagent.sim import stock_study as ss  # noqa: E402
from tradingagent.sim.costs import CostModel  # noqa: E402
from tradingagent.sim.discovery_study import load_expiries  # noqa: E402
from tradingagent.sim.exit_study import HALF_SPREAD_PCT  # noqa: E402
from tradingagent.sim.swing_study import NOTIONAL, DeliveryCosts  # noqa: E402
from tradingagent.tournament.candidates import score_all, score_stock_universe  # noqa: E402

ROOT = Path(".")
START, END = date(2023, 12, 1), date(2026, 9, 30)
FIXED = [time(10, 30), time(11, 30), time(12, 30), time(13, 30), time(14, 30), time(15, 10)]
OPT = {"G1", "G2", "P4", "FIB71", "CPR", "HL1"}
STOP_REASONS = {"STOP", "OR_OPPOSITE_SIDE", "FIB_SL", "INDEX_SL", "OPPOSITE_SIDE", "STOP_1.5x", "STOP_2ATR",
                "STOP_3ATR", "TRAIL_20D_LOW"}
out = ROOT / "data" / "reports" / "backtests" / f"exit_diag_{datetime.now():%Y%m%d_%H%M}"
out.mkdir(parents=True, exist_ok=True)


def close_at(p: pd.DataFrame, t: time) -> float | None:
    s = p[p["ts"].dt.time < t]
    return float(s["close"].iloc[-1]) if len(s) else None


costs = CostModel(load_config(ROOT / "config").costs)
store = MarketStore(ROOT / "data" / "market.duckdb", read_only=True)
try:
    data = score_stock_universe(store)
    trades = score_all(store, costs, load_expiries(ROOT / "data" / "expiries" / "NIFTY.csv"), START, END,
                       stock_data=data)
    trades = trades[trades["status"] == "CLOSED"].dropna(subset=["net_inr"]).reset_index(drop=True)
    bse_adj = ss.adjust_splits(ss.clean_bad_prints(store.candles("NSE-BSE", "1minute"))[0])[0]
    print(f"{len(trades)} closed trades: {trades['cand'].value_counts().to_dict()}", flush=True)
    rows: list[dict[str, Any]] = []
    for _, t in trades.iterrows():
        c, d = t["cand"], t["day"]
        r: dict[str, Any] = {"cand": c, "day": d, "net_inr": t["net_inr"], "reason": t["reason"]}
        if c in OPT or c == "BSE":
            lot = 30 if c == "HL1" else 65
            if c == "BSE":   # same split-adjusted, cleaned prices the strategy itself used (BSE bonus 2022, 2025)
                path = bse_adj[bse_adj["day"] == d].drop(columns="day")
            else:
                path = store.candles(t["symbol"], "1minute", datetime.combine(d, time(9, 15)),
                                     datetime.combine(d, time(15, 30)))
            e_ts, x_ts = pd.Timestamp(t["entry_ts"]), pd.Timestamp(t["exit_ts"])
            path = path[path["ts"] >= e_ts]
            if path.empty:
                continue
            sign = -1.0 if (c == "BSE" and t["side"] == "SHORT") else 1.0
            entry = float(t["entry_px"])
            held = path[path["ts"] <= x_ts]
            fav = (held["low"] if sign < 0 else held["high"])
            adv = (held["high"] if sign < 0 else held["low"])
            mfe = sign * (float(fav.max() if sign > 0 else fav.min()) / entry - 1) * 100
            mae = sign * (float(adv.min() if sign > 0 else adv.max()) / entry - 1) * 100
            peak_t = held.loc[(fav.idxmax() if sign > 0 else fav.idxmin()), "ts"].time() if len(held) else None
            if c == "BSE":
                cost_pct = 0.12
            else:
                cost_pct = costs.round_trip(entry, entry, lot).total / (entry * lot) * 100 + 2 * HALF_SPREAD_PCT * 100
            r |= {"mfe": mfe, "mae": mae, "peak_t": peak_t, "cost_pct": cost_pct}
            for ft in FIXED:
                px = close_at(path, ft) if ft > e_ts.time() else None
                r[f"exit_{ft:%H%M}"] = None if px is None else sign * (px / entry - 1) * 100 - cost_pct
            final = close_at(path, time(15, 10))
            r["eod_above_entry"] = None if final is None else sign * (final - entry) > 0
        elif c == "R6":
            exp = d
            credit, back = float(t["entry_px"]), float(t["exit_px"])
            # rebuild the straddle path from both legs (ATM strike chosen at 13:30, as in round2.r6)
            idx = store.candles("NSE-NIFTY", "1minute", datetime.combine(d, time(9, 15)),
                                datetime.combine(d, time(13, 30)))
            k = int(round(float(idx["close"].iloc[-1]) / 50) * 50)
            legs = [store.candles(f"NSE-NIFTY-{exp:%d%b%y}-{k}-{s}", "1minute", datetime.combine(d, time(13, 30)),
                                  datetime.combine(d, time(15, 10))) for s in ("CE", "PE")]
            m = legs[0].merge(legs[1], on="ts", suffixes=("_c", "_p"))
            if m.empty:
                continue
            val = m["close_c"] + m["close_p"]
            r |= {"mfe": float((credit - val.min()) / credit * 100), "mae": float((credit - val.max()) / credit * 100),
                  "peak_t": m.loc[val.idxmin(), "ts"].time(), "cost_pct": 2 * 0.22}
            for ft in (time(14, 0), time(14, 30), time(15, 10)):
                s = m[m["ts"].dt.time < ft]
                r[f"exit_{ft:%H%M}"] = None if s.empty else float((credit - (s["close_c"].iloc[-1] +
                                                                              s["close_p"].iloc[-1])) / credit * 100)
            r["eod_above_entry"] = bool(credit - float(val.iloc[-1]) > 0)
        else:  # SW1 / SW2 — daily path
            sd = data[t["symbol"]]
            days = list(sd.index)
            i0, i1 = days.index(t["entry_day"]), days.index(t["exit_day"])
            entry = float(sd.iloc[i0]["open"])
            held = sd.iloc[i0:i1 + 1]
            mfe = (float(held["high"].max()) / entry - 1) * 100
            mae = (float(held["low"].min()) / entry - 1) * 100
            dc = DeliveryCosts()
            cost_pct = (dc.buy(NOTIONAL) + dc.sell(NOTIONAL)) / NOTIONAL * 100 + 0.1
            r |= {"mfe": mfe, "mae": mae, "peak_day": int(np.argmax(held["high"].to_numpy())), "cost_pct": cost_pct}
            for n in (3, 5, 10, 20):
                r[f"hold_{n}d"] = (float(sd.iloc[i0 + n]["close"]) / entry - 1) * 100 - cost_pct \
                    if i0 + n < len(days) else None
            r["eod_above_entry"] = (float(sd.iloc[min(i0 + 10, len(days) - 1)]["close"]) > entry)
        rows.append(r)
finally:
    store.close()

df = pd.DataFrame(rows)
df.to_csv(out / "per_trade.csv", index=False)
summary = []
for c, g in df.groupby("cand"):
    is_stock = c in ("SW1", "SW2", "BSE")
    big, bigger = (1.0, 3.0) if is_stock else (20.0, 50.0)
    losers = g[g["net_inr"] <= 0]
    winners = g[g["net_inr"] > 0]
    turned = float((losers["mfe"] >= big).mean() * 100) if len(losers) else np.nan
    stopped = g[g["reason"].isin(STOP_REASONS)]
    regret = float(stopped["eod_above_entry"].astype(float).mean() * 100) if len(stopped) else np.nan
    cols = [col for col in g.columns if col.startswith("exit_") or col.startswith("hold_")]
    profile = {col: round(float(pd.to_numeric(g[col]).mean()), 1) for col in cols if g[col].notna().sum() >= 10}
    base = profile.get("exit_1510", np.nan)
    best_fixed = max(profile.items(), key=lambda kv: kv[1]) if profile else (None, np.nan)
    s = {"cand": c, "n": len(g), "win%": round(float((g["net_inr"] > 0).mean() * 100)),
         "MFE_med%": round(float(g["mfe"].median()), 1), "MAE_med%": round(float(g["mae"].median()), 1),
         f"MFE>={big:g}%": round(float((g["mfe"] >= big).mean() * 100)),
         f"MFE>={bigger:g}%": round(float((g["mfe"] >= bigger).mean() * 100)),
         "losers_first_up%": round(turned) if turned == turned else None,
         "stop_regret%": round(regret) if regret == regret else None, "n_stopped": len(stopped),
         "fixed_exit_profile": profile, "best_fixed": best_fixed[0]}
    if "peak_t" in g and g["peak_t"].notna().any():
        w = winners["peak_t"].dropna()
        s["winners_peak_by"] = {h: round(float((w.apply(lambda x: x.hour * 60 + x.minute) <= h * 60 + 30).mean()
                                               * 100)) for h in (10, 11, 12, 13, 14)} if len(w) else {}
    if "peak_day" in g:
        s["winner_peak_day_median"] = float(winners["peak_day"].median()) if len(winners) else None
    room = []
    if s["losers_first_up%"] is not None and s["losers_first_up%"] >= 30:
        room.append("(a) losers first up")
    if base == base and best_fixed[1] - base >= 5:
        room.append(f"(b) {best_fixed[0]} beats 15:10 by {best_fixed[1] - base:.1f} pts")
    if s["stop_regret%"] is not None and s["stop_regret%"] >= 40:
        room.append("(c) stop regret")
    s["ROOM"] = "; ".join(room) or "none"
    summary.append(s)
sm = pd.DataFrame(summary)
sm.to_csv(out / "summary.csv", index=False)
with pd.option_context("display.width", 300, "display.max_columns", 30, "display.max_colwidth", 200):
    print(sm.drop(columns=["fixed_exit_profile"]).to_string(index=False))
    print("\nFixed-exit profile (avg net % of premium/price if every trade exited at that time / after N days):")
    for s in summary:
        print(f"  {s['cand']:6s} {s['fixed_exit_profile']}")
    print("\nWinners' best point reached by (share of winners, %):")
    for s in summary:
        if s.get("winners_peak_by"):
            print(f"  {s['cand']:6s} {s['winners_peak_by']}")
print(f"\nWritten to {out}")
