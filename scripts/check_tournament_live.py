"""Fidelity check: replay past days through the LIVE tournament checks (history up to the day before + that day's
official 1-min bars revealed one 5-min step at a time) and compare with the official end-of-day signals.
Usage: uv run --no-sync python scripts/check_tournament_live.py 2026-09-01 2026-09-30   (read-only)"""

import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")
from tradingagent.agent.shadow import Ledger, ShadowConfig  # noqa: E402
from tradingagent.config import load_config  # noqa: E402
from tradingagent.data.store import MarketStore  # noqa: E402
from tradingagent.sim.costs import CostModel  # noqa: E402
from tradingagent.sim.discovery_study import load_expiries  # noqa: E402
from tradingagent.tournament import live  # noqa: E402
from tradingagent.tournament.candidates import score_all  # noqa: E402

ROOT = Path(".")
DB = ROOT / "data" / "market.duckdb"
a, b = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2])
exps = load_expiries(ROOT / "data" / "expiries" / "NIFTY.csv")
store = MarketStore(DB, read_only=True)
official = score_all(store, CostModel(load_config(ROOT / "config").costs), exps, a, b)
days = sorted({d for d in store.candles("NSE-NIFTY", "1day")["ts"].dt.date if a <= d <= b})
full = {s: store.candles(s, "1minute", datetime.combine(a, time(0)), datetime.combine(b, time(23, 59)))
        for s in live.LIVE_SYMBOLS.values()}
store.close()
bn_exps = live.bn_expiries(DB)
rows = []
for d in days:
    w = live.Watcher(d, live.load_history(DB, d), exps, bn_exps, ShadowConfig(enabled=False), Ledger(Path("nul")),
                     now=datetime.now, log=lambda m: None)
    found = {}
    t = datetime.combine(d, time(9, 20))
    while t <= datetime.combine(d, time(13, 35)) and len(found) < len(live.CHECKS):
        for s, df in full.items():
            day_df = df[(df["ts"].dt.date == d) & (df["ts"] < pd.Timestamp(t))].reset_index(drop=True)
            if len(day_df):
                w.mem.today[s] = day_df
        for cid, chk in live.CHECKS.items():
            if cid in found:
                continue
            try:
                res = chk(w, t)
            except Exception as e:
                res = None
                print(f"{d} {cid} error: {e}")
            if res is not None and res[0] <= t:
                found[cid] = (res[0], res[1], t)
        t += timedelta(minutes=5)
    off = official[official["day"] == d]
    for cid in live.CHECKS:
        o = off[off["cand"] == cid]
        o_sig = (pd.Timestamp(o["signal_ts"].iloc[0]).to_pydatetime(), str(o["side"].iloc[0])) if len(o) else None
        l_sig = found.get(cid)
        lt = (l_sig[0], {"LONG": "LONG", "SHORT": "SHORT"}.get(l_sig[1], l_sig[1])) if l_sig else None
        same = (o_sig is None and lt is None) or (o_sig is not None and lt is not None and o_sig[1] == lt[1]
                                                  and abs((o_sig[0] - lt[0]).total_seconds()) <= 300)
        if o_sig or lt:
            rows.append({"day": d, "cand": cid, "official": o_sig, "live": lt, "match": same})
r = pd.DataFrame(rows)
with pd.option_context("display.width", 200, "display.max_rows", 200):
    print(r.to_string(index=False))
    print("\nmatch rate by candidate:\n" + r.groupby("cand")["match"].agg(["sum", "size"]).to_string())
