"""Run one Phase 3 hypothesis stage (research only; DuckDB read-only).

Usage: uv run --no-sync python scripts/run_phase3.py {p1|p2|p3|p4} {design|test}
The TEST stage of a hypothesis may be run ONCE, and only after its design stage passed (see the pre-declarations
in docs/reports/2026-10-02_p*_*.md). Outputs go to data/reports/backtests/phase3_<hyp>_<stage>_<stamp>/.
"""

import json
import sys
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.config import load_config
from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.discovery_study import follow, load_expiries
from tradingagent.sim.entry_study import e_random
from tradingagent.sim.exit_study import Entry, rule_none, simulate
from tradingagent.sim.logic_study import logic_features
from tradingagent.sim.phase3 import (
    DESIGN,
    STEP,
    TEST,
    Data,
    atm,
    close_before,
    leg_net,
    legs_from_sim,
    p1_rows,
    p1_signals,
    p2_pin,
    p2_rows,
    p3_signal,
    p4_rel,
    p4_signals,
    passes,
    stats,
    straddle_net,
)
from tradingagent.sim.timing_study import bootstrap_ci

ROOT = Path(__file__).resolve().parents[1]
HYP, STAGE = sys.argv[1], sys.argv[2]
WIN = DESIGN if STAGE == "design" else TEST
P_MAX = 0.05 if STAGE == "design" else 0.0125
OUT = ROOT / "data/reports/backtests" / f"phase3_{HYP}_{STAGE}_{datetime.now():%Y%m%d_%H%M}"
OUT.mkdir(parents=True, exist_ok=True)
store = MarketStore(ROOT / "data/market.duckdb", read_only=True)
costs = CostModel(load_config(ROOT / "config").costs)
data = Data(store)
result: dict[str, Any] = {"hypothesis": HYP, "stage": STAGE, "window": [str(WIN[0]), str(WIN[1])]}


def option_trade(d: date, ts: datetime, side: str, close: float, stop: float = 0.30) -> dict[str, Any] | None:
    exp = data.next_expiry(d)
    if exp is None:
        return None
    k = atm(close)
    opt = data.option(d, exp, k, side)
    if opt.empty:
        return None
    tr = simulate(Entry(d, ts, side, k, exp, np.nan, np.nan), opt, data.idx[d], rule_none, stop_pct=stop)
    if tr is None:
        return None
    leg = legs_from_sim(tr)
    return {**tr, "net": leg_net(costs, leg), "net2": leg_net(costs, leg, 2)}


def random_control(days: list[date]) -> pd.DataFrame:
    rows = []
    for d in days:
        e = e_random(data.idx[d], {"day": d}, data.expiries)
        if e is None:
            continue
        tr = option_trade(d, e.signal_ts, e.side, float(data.idx[d][data.idx[d]["ts"] < e.signal_ts]["close"].iloc[-1]))
        if tr:
            rows.append(tr)
    return pd.DataFrame(rows)


def eligible(window: tuple[date, date]) -> list[date]:
    return [d for d in data.days(window) if d not in data.exp_set and data.next_expiry(d) is not None]


if HYP == "p1":
    rows = p1_rows(data, DESIGN[0], WIN[1])            # R needs earlier days (past-only percentile)
    rows["signal"] = p1_signals(rows["R"].reset_index(drop=True)).to_numpy()
    rows = rows[(rows["day"] >= WIN[0]) & (rows["day"] <= WIN[1])].copy()
    rows["net"] = [straddle_net(costs, c, p) for c, p in zip(rows["ce"], rows["pe"], strict=True)]
    rows["net2"] = [straddle_net(costs, c, p, 2) for c, p in zip(rows["ce"], rows["pe"], strict=True)]
    sig, ctl = rows[rows["signal"]], rows[~rows["signal"]]
    s = stats(sig["net"], sig["net2"], ctl["net"])
    result |= {"signal": s, "all_days": stats(rows["net"], rows["net2"]),
               "PASS": passes(s, 60 if STAGE == "design" else 40, P_MAX)}
    rows.drop(columns=["ce", "pe"]).to_csv(OUT / "days.csv", index=False)

elif HYP == "p2":
    t = p2_rows(data, costs, *WIN)
    t.to_csv(OUT / "trades.csv", index=False)
    per = {}
    for m, g in t.groupby("m"):
        per[m] = stats(g["net"], g["net2"], g["control"] if m == "M2" else None)
        per[m]["gross"] = round(float(g["gross"].mean()), 1)
        per[m]["short_research_net"] = round(float((-g["gross"] - (g["gross"] - g["net"])).mean()), 1)
    result["measurements"] = per
    pin = p2_pin(data, *WIN)
    result["pin_dist100_mean"] = pin.groupby("expiry_day")["dist100"].agg(["mean", "count"]).round(1).to_dict()
    if STAGE == "design":
        best = max(per, key=lambda m: per[m].get("net", -1e9))
        result["selected"] = best
        result["PASS"] = passes(per[best], 40, P_MAX, need_control=False)

elif HYP == "p3":
    vix = data._by_day("NSE-INDIAVIX")
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    vixd = store.candles("NSE-INDIAVIX", "1day")
    vixd["day"] = vixd["ts"].dt.date
    lf = logic_features(idx, vixd)
    exp_a = load_expiries(ROOT / "data/expiries/NIFTY.csv")
    exp_set_a = set(exp_a)

    def stage_a(window: tuple[date, date]) -> dict[str, Any]:
        sig, rnd = [], []
        for d in sorted(data.idx):
            if not (window[0] <= d <= window[1]) or d in exp_set_a or d not in vix:
                continue
            g, atr = data.idx[d], float(lf.at[d, "atr_pts"])
            lab = p3_signal(g, vix[d])
            if lab is not None:
                ts = datetime.combine(d, lab)
                sig.append((follow(g, ts, "PE", 60, atr), follow(g, ts, "PE", None, atr)))
            e = e_random(g, {"day": d}, exp_a)
            if e is not None:
                rnd.append((follow(g, e.signal_ts, e.side, 60, atr), follow(g, e.signal_ts, e.side, None, atr)))
        s, r = np.array(sig, dtype=float), np.array(rnd, dtype=float)
        s, r = s[~np.isnan(s).any(axis=1)], r[~np.isnan(r).any(axis=1)]
        lo, hi, p0 = bootstrap_ci(s[:, 1])
        right, rright = float((s[:, 0] > 0).mean() * 100), float((r[:, 0] > 0).mean() * 100)
        return {"n": len(s), "right_60%": round(right, 1), "random_right_60%": round(rright, 1),
                "eod_atr": round(float(s[:, 1].mean()), 3), "eod_ci95": f"[{lo:.3f}, {hi:.3f}]",
                "PASS_A": bool(len(s) >= 60 and right >= 53 and right >= rright + 3 and s[:, 1].mean() > 0 and lo > 0)}

    def stage_b(window: tuple[date, date]) -> tuple[dict[str, Any], pd.DataFrame]:
        rows = []
        days = eligible(window)
        for d in days:
            if d not in vix:
                continue
            lab = p3_signal(data.idx[d], vix[d])
            if lab is None:
                continue
            tr = option_trade(d, datetime.combine(d, lab), "PE", close_before(data.idx[d], lab) or 0.0)
            if tr:
                rows.append(tr)
        t, rc = pd.DataFrame(rows), random_control(days)
        return stats(t["net"], t["net2"], rc["net"]) if len(t) else {"n": 0}, t

    if STAGE == "design":
        result["stage_A_2021_10_to_2025_06"] = stage_a((date(2021, 10, 1), DESIGN[1]))
        sb, t = stage_b(DESIGN)
        result["stage_B_options"] = sb
        result["PASS"] = bool(result["stage_A_2021_10_to_2025_06"]["PASS_A"] and sb.get("net", -1) > 0)
    else:
        result["index_test"] = stage_a(TEST)
        sb, t = stage_b(TEST)
        result["options_test"] = sb
        result["PASS"] = bool(passes(sb, 20, P_MAX) and result["index_test"]["eod_atr"] > 0)
    t.to_csv(OUT / "trades.csv", index=False)

elif HYP == "p4":
    bn = data._by_day("NSE-BANKNIFTY")
    days = [d for d in sorted(data.idx) if DESIGN[0] <= d <= WIN[1] and d in bn]   # warm-up from 2023-12-01 only
    rel = pd.DataFrame({d: p4_rel(data.idx[d], bn[d]) for d in days}).T.sort_index()
    sigs = p4_signals(rel)
    rows = []
    win_days = eligible(WIN)
    for d in win_days:
        if d not in sigs:
            continue
        lab, s, r_t = sigs[d]
        n, b = data.idx[d], bn[d]
        n_t, n_e = close_before(n, lab), close_before(n, time(15, 11))
        b_e = close_before(b, time(15, 11))
        if not (n_t and n_e and b_e):
            continue
        rel_e = np.log(b_e / float(b["open"].iloc[0])) - np.log(n_e / float(n["open"].iloc[0]))
        tr = option_trade(d, datetime.combine(d, lab), "CE" if s > 0 else "PE", n_t)
        if tr is None:
            continue
        rows.append({**tr, "s": s, "label": str(lab), "reversion_bp": -s * (rel_e - r_t) * 1e4,
                     "nifty_catchup_bp": s * (n_e / n_t - 1) * 1e4})
    t = pd.DataFrame(rows)
    rc = random_control(win_days)
    st = stats(t["net"], t["net2"], rc["net"])
    lo, hi, _ = bootstrap_ci(t["reversion_bp"].to_numpy())
    st |= {"reversion_bp": round(float(t["reversion_bp"].mean()), 1), "reversion_ci95": f"[{lo:.1f}, {hi:.1f}]",
           "nifty_catchup_bp": round(float(t["nifty_catchup_bp"].mean()), 1)}
    result["signal"] = st
    rev_ok = lo > 0 if STAGE == "design" else st["reversion_bp"] > 0
    result["PASS"] = bool(passes(st, 50 if STAGE == "design" else 40, P_MAX) and rev_ok)
    t.to_csv(OUT / "trades.csv", index=False)

store.close()
(OUT / "result.json").write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
print(json.dumps(result, indent=1, default=str))
print(f"saved {OUT}  (STEP={STEP})")
