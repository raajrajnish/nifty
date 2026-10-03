"""The 10 frozen tournament candidates and their official end-of-day scoring.

Every candidate is scored with the EXACT code of the study that produced it (no re-implementation of rules), on
official Groww 1-min candles, forward days only (>= FORWARD_START). Paper research only — no orders.
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim import bn_heavy, internet_study, popular_study, round2
from tradingagent.sim import stock_study as ss
from tradingagent.sim import swing_study as sw
from tradingagent.sim.costs import CostModel
from tradingagent.sim.discovery_study import VALIDATION, day_contexts
from tradingagent.sim.exit_study import Entry, option_symbol, rule_none, simulate
from tradingagent.sim.phase3 import Data, atm, close_before, leg_net, legs_from_sim, p4_rel, p4_signals

FORWARD_START = date(2026, 10, 5)
NIFTY_LOT = 65
ROOT = Path(__file__).resolve().parents[3]
UNIVERSE = ROOT / "data" / "universe" / "ind_nifty50list.csv"


@dataclass(frozen=True)
class Candidate:
    id: str
    name: str
    instrument: str
    description: str
    weakness: str
    backtest: str
    live: bool          # intraday: LLM asked live at the signal; False = swing (asked in the evening)


CANDIDATES: tuple[Candidate, ...] = (
    Candidate("G1", "Narrow-range opening breakout", "Nifty weekly ATM option (buy)",
              "Day opened outside yesterday's range and the 09:15-09:30 range is narrower than its 20-day median; "
              "buy CE/PE on the first 5-min close beyond the range; exit on a 5-min close beyond the opposite side, "
              "-50% premium stop, or 15:10.",
              "Direction failed on untouched Nifty 2021-23 and on Bank Nifty; profit came mostly from puts.",
              "+₹833/trade (2023-12..2026-09)", True),
    Candidate("G2", "TWAP pullback on a calm open-outside day", "Nifty weekly ATM option (buy)",
              "Calm day (ATR14 <= 120-day median) that opened outside yesterday's range; buy on a 5-min pullback "
              "to the day's TWAP in the TWAP's direction (10:00-13:30); -30% stop; hold to 15:10.",
              "Profit is not directional (an independent review found it comes from the stop geometry).",
              "+₹300/trade", True),
    Candidate("P4", "Nifty catches up after a Bank Nifty divergence", "Nifty weekly ATM option (buy)",
              "When Bank Nifty's move since the open diverges from Nifty's by >= 2 SD (per time of day, 60-day SD), "
              "buy the Nifty option in Bank Nifty's direction (Nifty expected to catch up); -30% stop; hold to 15:10.",
              "Backtest rests on a few big days (negative without the best 5); the pull-back itself was not proven.",
              "+₹1,140/trade (n=50)", True),
    Candidate("SW2", "55-day breakout with volume (swing)", "Nifty 50 stock, delivery, long",
              "Stock closes above its highest close of the prior 55 days with volume > 1.5x its 20-day average and "
              "above its 200-day average; buy next open; exit below the 20-day low, 2xATR stop, or 60 days.",
              "In 2024-26 it did worse than random buys of the same stocks.", "+3.07%/trade (2022-24)", False),
    Candidate("FIB71", "Fibonacci 0.71 recovery (calls only)", "Nifty weekly ATM call (buy)",
              "After a >= 135-pt fall from the day high, a 5-min close back above the 0.71 retracement between "
              "12:00 and 13:30 buys a call; stop at the 0.38 level; target the day high; 15:10.",
              "Only 23 backtest trades; negative in its earliest period.", "+₹769/trade (n=23)", True),
    Candidate("R6", "Sell the expiry-day straddle (RESEARCH ONLY)", "Nifty ATM straddle, SOLD (paper)",
              "On expiry day at 13:30 sell the ATM call and put; buy back at 15:10 or if their value reaches 1.5x "
              "the credit. Collects the option-volatility premium; large losses on sharp moves.",
              "Edge shrank in 2025-26 and failed at double costs; unlimited-risk selling.", "+₹343 (H-A), +₹31 (H-B)",
              True),
    Candidate("CPR", "Narrow Central Pivot Range breakout", "Nifty weekly ATM option (buy)",
              "On days whose CPR (from yesterday's H/L/C) is in the narrowest third of the last 60 days, buy on the "
              "first 5-min close above the top / below the bottom of the CPR (09:35-13:30); exit beyond the other "
              "side, -50% stop, 15:10.",
              "Positive in 2023-26 but negative in 2021-23 (period-dependent).", "positive 2023-26 only", True),
    Candidate("HL1", "HDFC Bank + ICICI Bank lead Bank Nifty", "Bank Nifty monthly ATM option (buy)",
              "When the average 30-min return of HDFC Bank and ICICI Bank exceeds Bank Nifty's by >= 0.25%, buy the "
              "Bank Nifty option in their direction (09:45-13:30); hold to 15:10; -50% stop.",
              "Direction was no better than random; monthly-option period negative.", "+₹285/trade", True),
    Candidate("BSE", "BSE Ltd opening-range breakout with Nifty agreeing", "BSE stock, intraday, long/short",
              "First 5-min close beyond BSE's 09:15-09:30 range (09:30-13:30), long only if Nifty is above its open, "
              "short only if below; exit beyond the other side of the range or 15:10. ₹1 lakh position.",
              "Positive only in 2024-26; flat in 2021-24.", "+0.16%/trade (2024-26)", True),
    Candidate("SW1", "RSI-2 pullback in an uptrend (swing)", "Nifty 50 stock, delivery, long",
              "Stock above its 200-day average with RSI(2) < 10 at the close; buy next open; exit when the close "
              "rises above the 5-day average, after 10 days, or below entry - 3xATR.",
              "Edge only in 2022-24; zero in 2024-26.", "+0.22%/trade (2022-24)", False),
)
BY_ID = {c.id: c for c in CANDIDATES}


# ---------------------------------------------------------------------------- scoring helpers
def _opt_net(costs: CostModel, tr: dict[str, Any], lot: int = NIFTY_LOT) -> tuple[float, float]:
    c = costs.round_trip(tr["entry_px"], tr["exit_px"], lot).total
    net = tr["pts"] * lot - c
    return net, net - c


def _row(cand: str, d: date, ts: Any, side: str, net: float, net2: float, **kw: Any) -> dict[str, Any]:
    return {"cand": cand, "day": d, "signal_ts": pd.Timestamp(ts) if ts is not None else None, "side": side,
            "net_inr": round(float(net), 1), "net2_inr": round(float(net2), 1), **kw}


def score_g12(store: MarketStore, costs: CostModel, exps: list[date], start: date, end: date) -> list[dict[str, Any]]:
    rows = []
    for d, g, c in day_contexts(store, exps, start, end):
        for key, cid in (("G1_oos", "G1"), ("G2_oos", "G2")):
            fn, rule, stop = VALIDATION[key]
            e = fn(g, c)
            if e is None:
                continue
            opt = store.candles(option_symbol(e), "1minute", datetime.combine(d, time(9, 15)),
                                datetime.combine(d, time(15, 30)))
            tr = simulate(e, opt, g, rule, stop_pct=stop) if not opt.empty else None
            if tr is None:
                rows.append(_row(cid, d, e.signal_ts, e.side, np.nan, np.nan, status="NO_OPTION_DATA"))
                continue
            net, net2 = _opt_net(costs, tr)
            rows.append(_row(cid, d, e.signal_ts, e.side, net, net2, symbol=option_symbol(e), reason=tr["reason"],
                             entry_px=tr["entry_px"], exit_px=tr["exit_px"], status="CLOSED"))
    return rows


def score_p4(store: MarketStore, costs: CostModel, start: date, end: date) -> list[dict[str, Any]]:
    data = Data(store)
    bn = data._by_day("NSE-BANKNIFTY")  # noqa: SLF001
    warm = [d for d in sorted(data.idx) if (start - pd.Timedelta(days=150).to_pytimedelta()) <= d <= end and d in bn]
    rel = pd.DataFrame({d: p4_rel(data.idx[d], bn[d]) for d in warm}).T.sort_index()
    sigs = p4_signals(rel)
    rows = []
    for d in warm:
        if d < start or d in data.exp_set or data.next_expiry(d) is None or d not in sigs:
            continue
        lab, s, _ = sigs[d]
        n_t = close_before(data.idx[d], lab)
        exp = data.next_expiry(d)
        if n_t is None or exp is None:
            continue
        side, k = ("CE" if s > 0 else "PE"), atm(n_t)
        e = Entry(d, datetime.combine(d, lab), side, k, exp, np.nan, np.nan)
        opt = data.option(d, exp, k, side)
        tr = simulate(e, opt, data.idx[d], rule_none, stop_pct=0.30) if not opt.empty else None
        if tr is None:
            rows.append(_row("P4", d, e.signal_ts, side, np.nan, np.nan, status="NO_OPTION_DATA"))
            continue
        leg = legs_from_sim(tr)
        rows.append(_row("P4", d, e.signal_ts, side, leg_net(costs, leg), leg_net(costs, leg, 2.0),
                         symbol=option_symbol(e), reason=tr["reason"], entry_px=tr["entry_px"], exit_px=tr["exit_px"],
                         status="CLOSED"))
    return rows


def _from_study(t: pd.DataFrame, variant: str, cid: str) -> list[dict[str, Any]]:
    if t.empty or "variant" not in t:
        return []
    t = t[t["variant"] == variant]
    return [_row(cid, r["day"], r["entry_ts"], r["side"], r["net_inr"], r["net2_inr"], reason=r["reason"],
                 entry_px=r["entry_px"], exit_px=r["exit_px"], status="CLOSED") for _, r in t.iterrows()]


def score_stock_universe(store: MarketStore) -> dict[str, pd.DataFrame]:
    data = {}
    for r in csv.DictReader(UNIVERSE.open(encoding="utf-8")):
        s = r["Symbol"]
        raw = store.candles(f"NSE-{s}", "1day")
        if raw.empty:
            continue
        intra = store.candles(f"NSE-{s}", "1minute")
        if intra.empty:
            intra = store.candles(f"NSE-{s}", "15minute")
        data[s] = sw.prepare(sw.rebuild_from_intraday(raw, intra)[0])[0]
    return data


def score_swing(data: dict[str, pd.DataFrame], start: date, end: date) -> list[dict[str, Any]]:
    rows, dc = [], sw.DeliveryCosts()
    for sym, d in data.items():
        for cid in ("SW1", "SW2"):
            for t in sw.run_signal_setup(sym, d, set(), cid, dc, periods={"FWD": (start, end)}):
                open_ = t["reason"] == "DATA_END"
                rows.append(_row(cid, t["signal_day"], None, "LONG", t["net_pct"] * 1000, t["net2_pct"] * 1000,
                                 symbol=sym, reason=t["reason"], entry_day=t["entry_day"], exit_day=t["exit_day"],
                                 status="OPEN" if open_ else "CLOSED"))
    return rows


def score_all(store: MarketStore, costs: CostModel, exps: list[date], start: date = FORWARD_START,
              end: date | None = None, stock_data: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    end = end or date.today()
    rows = score_g12(store, costs, exps, start, end)
    rows += score_p4(store, costs, start, end)
    rows += _from_study(internet_study.stage_b(store, costs, exps, start, end), "P5_fib71_buy", "FIB71")
    cpr = popular_study.stage_b(store, costs, exps, ["K1_narrow_cpr"], start, end)
    rows += _from_study(cpr, "K1_narrow_cpr", "CPR")
    _, ht = bn_heavy.run(store, costs, start, end)
    rows += _from_study(ht, "HL1", "HL1")
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    r6 = round2.r6_short_straddle(store, idx, exps, costs, halves={"FWD": (start, end)})
    rows += [_row("R6", r["day"], datetime.combine(r["day"], time(13, 30)), "SHORT_STRADDLE", r["net"], r["net2"],
                  reason=r["reason"], entry_px=r["credit"], exit_px=r["buyback"], status="CLOSED")
             for _, r in r6.iterrows()]
    m1 = store.candles("NSE-BSE", "1minute")
    if not m1.empty:
        bt, _ = ss.run_stock("BSE", m1, idx.drop(columns="day"), ss.EquityIntradayCosts(),
                             periods={"FWD": (start, end)}, setups={"ST1": ss.st1_orb_with_nifty})
        rows += [_row("BSE", r["day"], r["entry_ts"], r["side"], r["net"], r["net2"], symbol="BSE",
                      reason=r["reason"], entry_px=r["entry"], exit_px=r["exit"], status="CLOSED")
                 for _, r in bt.iterrows()]
    rows += score_swing(stock_data if stock_data is not None else score_stock_universe(store), start, end)
    t = pd.DataFrame(rows)
    if not t.empty:
        t = t[t["day"] >= start].sort_values(["day", "cand"]).reset_index(drop=True)
    return t
