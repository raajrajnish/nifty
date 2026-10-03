"""Run Round 2 (spec: docs/reports/2026-10-03_round2_strategies.md). DuckDB read-only; prints per-half verdicts."""

import csv
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")
from tradingagent.config import load_config  # noqa: E402
from tradingagent.data.store import MarketStore  # noqa: E402
from tradingagent.sim import round2 as r2  # noqa: E402
from tradingagent.sim import swing_study as sw  # noqa: E402
from tradingagent.sim.costs import CostModel  # noqa: E402
from tradingagent.sim.discovery_study import load_expiries  # noqa: E402

ROOT = Path(".")
out = ROOT / "data" / "reports" / "backtests" / f"round2_{datetime.now():%Y%m%d_%H%M}"
out.mkdir(parents=True, exist_ok=True)
costs = CostModel(load_config(ROOT / "config").costs)
exps = load_expiries(ROOT / "data" / "expiries" / "NIFTY.csv")
store = MarketStore(ROOT / "data" / "market.duckdb", read_only=True)
try:
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    cal = sorted(idx["day"].unique())
    t1 = r2.r1_overnight(store, idx, exps, costs)
    t4 = r2.r4_index_momentum(store, idx, exps, costs)
    t6 = r2.r6_short_straddle(store, idx, exps, costs)
    data = {}
    for r in csv.DictReader((ROOT / "data" / "universe" / "ind_nifty50list.csv").open()):
        s = r["Symbol"]
        raw = store.candles(f"NSE-{s}", "1day")
        intra = store.candles(f"NSE-{s}", "1minute")
        if intra.empty:
            intra = store.candles(f"NSE-{s}", "15minute")
        if raw.empty:
            continue
        data[s] = sw.prepare(sw.rebuild_from_intraday(raw, intra)[0])[0]
finally:
    store.close()
dc = sw.DeliveryCosts()
t2 = r2.r2_turn_of_month(data, cal, dc)
t5 = r2.r5_weekly_reversal(data, cal, dc)
for name, t in (("r1", t1), ("r2", t2), ("r4", t4), ("r5", t5), ("r6", t6)):
    t.to_csv(out / f"{name}.csv", index=False)

rows = []
for h in r2.HALVES:
    a = t1[(t1.half == h)]
    ce, pe = a[a.side == "CE"], a[a.side == "PE"]
    rows.append({"strategy": "R1 overnight CE (₹/trade)", "half": h, **r2.judge(ce.net, ce.net2, pe.net.mean(), 30),
                 "info": f"PE same trade {pe.net.mean():.0f}; index close→open {ce.idx_overnight_pts.mean():+.1f} pts"})
    b = t2[t2.half == h]
    tm, ct = b[b.strategy == "R2"], b[b.strategy == "R2_control"]
    rows.append({"strategy": "R2 turn of month (% per window)", "half": h,
                 **r2.judge(tm.net_pct, tm.net2_pct, ct.net_pct.mean(), 12), "info": f"control windows n={len(ct)}"})
    c = t4[t4.half == h]
    m, rd = c[c.strategy == "R4"], c[c.strategy == "R4_random"]
    rows.append({"strategy": "R4 index momentum (₹/trade)", "half": h, **r2.judge(m.net, m.net2, rd.net.mean(), 30),
                 "info": f"random n={len(rd)}"})
    e = t5[t5.half == h]
    rows.append({"strategy": "R5 weekly reversal (% per week)", "half": h,
                 **r2.judge(e.net_pct, e.net2_pct, e.bench_pct.mean(), 30), "info": "control = equal-weight all"})
    f = t6[t6.half == h]
    rows.append({"strategy": "R6 short straddle RESEARCH (₹/trade)", "half": h, **r2.judge(f.net, f.net2, None, 30),
                 "info": f"stops {int((f.reason == 'STOP_1.5x').sum())}"})
v = pd.DataFrame(rows)
v.to_csv(out / "verdicts.csv", index=False)
with pd.option_context("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 70):
    print(v.to_string(index=False))
    print("\nROBUST (both halves PASS + CI of all trades > 0):")
    series = {"R1": t1[t1.side == "CE"].net, "R2": t2[t2.strategy == "R2"].net_pct, "R4": t4[t4.strategy == "R4"].net,
              "R5": t5.net_pct - t5.bench_pct, "R6": t6.net}
    for k, s in series.items():
        both = v[v.strategy.str.startswith(k)].PASS.all()
        lo, hi = r2.ci_both(s)
        robust = bool(both and lo > 0)
        print(f"  {k}: both halves PASS={bool(both)}; all-trades CI [{lo:.2f}, {hi:.2f}] → ROBUST={robust}")
    if len(t6):
        print(f"\nR6 tail: worst trade ₹{t6.net.min():,.0f}; worst 5-trade run ₹{t6.net.rolling(5).sum().min():,.0f}")
print(f"\nWritten to {out}")
