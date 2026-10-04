"""End-of-day tournament step (`tradingagent tournament-eod`) and the scoreboard (`tournament-report`).

1. Score all 10 candidates on official candles for every forward day (idempotent: recomputed from scratch).
2. Swing candidates (SW1/SW2): today's new signals enter at tomorrow's open, so the LLM is asked NOW (evening,
   before the outcome). At most MAX_SWING_LLM per evening — a seeded random sample if there are more (unbiased).
3. Join LLM decisions to official trades and print the scoreboard.
"""

import json
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.agent.shadow import Backend, Ledger, ShadowConfig, candidate_prompt, decide, load_events
from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.timing_study import bootstrap_ci
from tradingagent.tournament.candidates import BY_ID, CANDIDATES, FORWARD_START, score_all, score_stock_universe

ROOT = Path(__file__).resolve().parents[3]
TRADES_CSV = ROOT / "data" / "paper" / "tournament_trades.csv"
JOIN_CSV = ROOT / "data" / "paper" / "tournament_llm_join.csv"
LIVE_SIGNALS = ROOT / "data" / "paper" / "tournament_live_signals.jsonl"
MAX_SWING_LLM = 6


def swing_facts(sym: str, d: pd.DataFrame, day: date, cid: str) -> dict[str, Any]:
    r = d.loc[day]
    f = {"candidate": cid, "date": str(day), "stock": sym, "entry": "next trading day's open (delivery, long)",
         "close": round(float(r["close"]), 2), "sma200": round(float(r["sma200"]), 2),
         "atr14": round(float(r["atr14"]), 2), "pct_vs_sma200": round((r["close"] / r["sma200"] - 1) * 100, 2)}
    if cid == "SW1":
        f |= {"rsi2": round(float(r["rsi2"]), 1), "sma5": round(float(r["sma5"]), 2)}
    else:
        f |= {"prior_55d_high_close": round(float(r["hh55"]), 2),
              "volume_vs_20d_avg": round(float(r["volume"] / r["vol20"]), 2)}
    return f


def ask_swing(trades: pd.DataFrame, data: dict[str, pd.DataFrame], day: date, cfg: ShadowConfig, ledger: Ledger,
              now: Callable[[], datetime], backend: Backend | None = None,
              log: Callable[[str], None] = print) -> int:
    new = trades[trades["cand"].isin(["SW1", "SW2"]) & (trades["day"] == day)] if len(trades) else trades
    if new.empty or not cfg.enabled:
        return 0
    new = new.sort_values(["cand", "symbol"]).reset_index(drop=True)
    if len(new) > MAX_SWING_LLM:
        new = new.sample(MAX_SWING_LLM, random_state=day.toordinal()).sort_values(["cand", "symbol"])
        log(f"{len(trades[trades['day'] == day])} swing signals today; LLM asked about a seeded random sample of "
            f"{MAX_SWING_LLM} (unbiased; the rest are still paper-traded)")
    asked = 0
    for _, t in new.iterrows():
        key = f"{t['cand']}:{t['symbol']}"
        if ledger.has(day, "signal", key):
            continue
        c = BY_ID[str(t["cand"])]
        user = candidate_prompt(c.id, c.name, c.description, c.weakness,
                                swing_facts(str(t["symbol"]), data[str(t["symbol"])], day, c.id), load_events(day))
        decide("signal", day, key, user, cfg, ledger, now, backend,
               {"symbol": t["symbol"], "side": "LONG", "instrument": c.instrument})
        asked += 1
    return asked


def join_llm(trades: pd.DataFrame, ledger_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Attach the LLM verdict to each official trade. Intraday: same candidate, day and side, and the LLM's
    signal time within 5 minutes of the official one. Swing: same candidate:symbol and signal day."""
    sig = [r for r in ledger_rows if r.get("kind") == "signal"]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for r in sig:
        by_key.setdefault((str(r.get("setup")), str(r.get("day"))), r)
    out = []
    for _, t in trades.iterrows():
        cand, day = str(t["cand"]), str(t["day"])
        key = f"{cand}:{t['symbol']}" if cand in ("SW1", "SW2") else cand
        hit = by_key.get((key, day))
        ok = hit is not None
        if hit is not None and cand not in ("SW1", "SW2"):
            side_ok = str(hit.get("side")) == str(t["side"])
            ts_ok = True
            if hit.get("signal_ts") and pd.notna(t.get("signal_ts")):
                ts_ok = abs((pd.Timestamp(hit["signal_ts"]).tz_localize(None) - pd.Timestamp(t["signal_ts"]))
                            .total_seconds()) <= 300
            ok = side_ok and ts_ok
        rec = t.to_dict()
        rec["llm_match"] = "matched" if ok else ("mismatch" if hit is not None else "no_llm_record")
        if ok and hit is not None:
            for k in ("decision", "confidence", "reason_tags", "news_for_trade", "event_risk", "global_for_trade",
                      "volatility_view", "reasons", "equiv_cost_inr", "prompt_version", "decided_at"):
                rec[f"llm_{k}"] = json.dumps(hit.get(k)) if isinstance(hit.get(k), list) else hit.get(k)
        out.append(rec)
    return pd.DataFrame(out)


def scoreboard(j: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in CANDIDATES:
        g = j[(j["cand"] == c.id)] if len(j) else j
        closed = g[g["status"] == "CLOSED"].dropna(subset=["net_inr"]) if len(g) else g
        v = closed["net_inr"].to_numpy() if len(closed) else np.array([])
        ci = bootstrap_ci(v) if len(v) >= 10 else (np.nan, np.nan, np.nan)
        dec = closed.get("llm_decision") if len(closed) else None
        take = closed[dec == "TAKE"]["net_inr"] if dec is not None else pd.Series(dtype=float)
        skip = closed[dec == "SKIP"]["net_inr"] if dec is not None else pd.Series(dtype=float)
        rows.append({"cand": c.id, "name": c.name, "trades": len(v), "open": int((g["status"] == "OPEN").sum())
                     if len(g) else 0, "net_per_trade": round(float(v.mean()), 0) if len(v) else None,
                     "total": round(float(v.sum()), 0) if len(v) else 0, "win%": round(float((v > 0).mean() * 100), 0)
                     if len(v) else None, "worst": round(float(v.min()), 0) if len(v) else None,
                     "ci95": f"[{ci[0]:.0f}, {ci[1]:.0f}]" if len(v) >= 10 else "n<10",
                     "llm_take_n": len(take), "llm_take_avg": round(float(take.mean()), 0) if len(take) else None,
                     "llm_skip_n": len(skip), "llm_skip_avg": round(float(skip.mean()), 0) if len(skip) else None,
                     "backtest": c.backtest})
    return pd.DataFrame(rows)


def run_eod(db: Path, costs: CostModel, exps: list[date], today: date, now: Callable[[], datetime],
            log: Callable[[str], None] = print, ask_llm: bool = True) -> pd.DataFrame:
    store = MarketStore(db, read_only=True)
    try:
        data = score_stock_universe(store)
        trades = score_all(store, costs, exps, FORWARD_START, today, stock_data=data)
    finally:
        store.close()
    TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(TRADES_CSV, index=False)
    if ask_llm and len(trades):
        n = ask_swing(trades, data, today, ShadowConfig.load(), Ledger(), now, log=log)
        log(f"LLM asked about {n} swing signal(s) for tomorrow's entries (shadow only).")
    return report(trades)


def report(trades: pd.DataFrame | None = None) -> pd.DataFrame:
    if trades is None:
        trades = pd.read_csv(TRADES_CSV, parse_dates=["signal_ts"]) if TRADES_CSV.exists() else pd.DataFrame()
        if len(trades):
            trades["day"] = pd.to_datetime(trades["day"]).dt.date
    if trades.empty:
        return scoreboard(pd.DataFrame(columns=["cand", "status", "net_inr"]))
    j = join_llm(trades, Ledger().rows())
    j.to_csv(JOIN_CSV, index=False)
    return scoreboard(j)
