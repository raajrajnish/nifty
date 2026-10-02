"""Fidelity check: does the LIVE paper engine make the same decisions as the BACKTEST?

For historical days where the backtest traded G1/G2, stored 1-min candles are turned into a recorder-like feed
(index ticks O→L/H→H/L→C per minute; option quotes = close ± half-spread) and run through PaperEngine.
Signals (side, strike, entry minute) and exit reasons are compared with the backtest trades.
Usage: uv run python scripts/check_paper_fidelity.py [N_DAYS]
"""

import glob
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

from tradingagent.config import load_config
from tradingagent.data.store import MarketStore
from tradingagent.paper.engine import PaperEngine
from tradingagent.sim.costs import CostModel
from tradingagent.sim.exit_study import HALF_SPREAD_PCT
from tradingagent.sim.fidelity import next_expiry, option_contracts, option_expiries

N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
ROOT = Path(__file__).resolve().parents[1]
logic = sorted(glob.glob(str(ROOT / "data/reports/backtests/logic_*")))[-1]
bt = pd.read_csv(f"{logic}/trades.csv", parse_dates=["entry_ts", "exit_ts"])
bt = bt[bt["setup"].isin(["S1", "S2"]) & (bt["F4_open_outside"] == True)]  # noqa: E712
bt["day"] = pd.to_datetime(bt["day"]).dt.date
days = sorted(bt["day"].unique())
sample = [days[i] for i in range(0, len(days), max(1, len(days) // N))][:N]

store = MarketStore(ROOT / "data/market.duckdb", read_only=True)
hist = store.candles("NSE-NIFTY", "1minute")
vix = store.candles("NSE-INDIAVIX", "1day")
expiries = option_expiries(store.con, "NIFTY")  # NIFTY only: the table also holds Bank Nifty expiries
costs = CostModel(load_config(ROOT / "config").costs)
rows = []
for d in sample:
    exp = next_expiry(d, expiries)
    assert exp is not None, d
    eng = PaperEngine(d, hist, vix, exp, costs)
    syms = option_contracts(store.con, exp, "NIFTY")
    eng.symbols = {(int(k), side): s for s, k, side in syms}
    start, end = datetime.combine(d, time(9, 15)), datetime.combine(d, time(15, 30))
    events = []
    idx = hist[(hist["ts"] >= start) & (hist["ts"] <= end)]
    for _, b in idx.iterrows():
        lo_first = b["close"] >= b["open"]
        seq = [(0, b["open"]), (15, b["low"] if lo_first else b["high"]), (30, b["high"] if lo_first else b["low"]),
               (50, b["close"])]
        for sec, px in seq:
            events.append((b["ts"] + timedelta(seconds=sec), "ltp", px))
    for s, _, _ in syms:
        o = store.candles(s, "1minute", start, end)
        for _, b in o.iterrows():
            events.append((b["ts"] + timedelta(seconds=55), "quote", (s, b["close"])))
    events.sort(key=lambda e: e[0])
    for ts, kind, payload in events:
        if kind == "ltp":
            eng.on_ltp(ts.to_pydatetime(), float(payload), {})
        else:
            s, c = payload
            eng.on_quote(ts.to_pydatetime(), s, c * (1 - HALF_SPREAD_PCT), c * (1 + HALF_SPREAD_PCT), c)
    eng.on_ltp(datetime.combine(d, time(15, 30, 59)), float(idx["close"].iloc[-1]), {})  # flush the last bar
    for setup, g in (("S1", "G1"), ("S2", "G2")):
        b = bt[(bt["day"] == d) & (bt["setup"] == setup)]
        live = next((t for t in eng.closed if t["setup"] == g), None)
        st = eng.s[g]
        if b.empty and live is None:
            continue
        brow = b.iloc[0] if len(b) else None
        rows.append({
            "day": d, "setup": g,
            "bt_side": None if brow is None else brow["side"], "live_side": None if live is None else live["side"],
            "bt_strike": None if brow is None else int(brow["strike"]),
            "live_strike": None if live is None else live["strike"],
            "bt_entry": None if brow is None else brow["entry_ts"].strftime("%H:%M"),
            "live_entry": None if live is None else live["entry_ts"][11:16],
            "bt_exit": None if brow is None else brow["reason"], "live_exit": None if live is None else live["reason"],
            "bt_net": None if brow is None else round(brow["net_inr"]),
            "live_net": None if live is None else round(live["net_inr"]),
            "live_status": st.status,
        })
store.close()
r = pd.DataFrame(rows)
pd.set_option("display.width", 220)
print(r.to_string(index=False))
same = (r["bt_side"] == r["live_side"]) & (r["bt_strike"] == r["live_strike"]) & (r["bt_entry"] == r["live_entry"])
print(f"\nSame signal (side, strike, entry minute): {int(same.sum())}/{len(r)}")
print(f"Same exit reason (STOP/EOD/opposite side): "
      f"{int((r['bt_exit'].str[:3] == r['live_exit'].fillna('').str[:3]).sum())}/{len(r)}")
