"""Historical filter for exit variants (spec: docs/reports/2026-10-04_exit_variants.md). Read-only DB.
A variant goes forward unless it is worse than BASE (mean net per trade) in BOTH halves (split at the median
trade date per candidate). Usage: uv run --no-sync python scripts/exit_variants_check.py
"""

import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from tradingagent.config import load_config  # noqa: E402
from tradingagent.data.store import MarketStore  # noqa: E402
from tradingagent.sim.costs import CostModel  # noqa: E402
from tradingagent.sim.discovery_study import load_expiries  # noqa: E402
from tradingagent.tournament import exits as ex  # noqa: E402
from tradingagent.tournament.candidates import score_stock_universe  # noqa: E402

ROOT = Path(".")
START, END = date(2023, 12, 1), date(2026, 9, 30)
out = ROOT / "data" / "reports" / "backtests" / f"exit_variants_{datetime.now():%Y%m%d_%H%M}"
out.mkdir(parents=True, exist_ok=True)
costs = CostModel(load_config(ROOT / "config").costs)
exps = load_expiries(ROOT / "data" / "expiries" / "NIFTY.csv")
store = MarketStore(ROOT / "data" / "market.duckdb", read_only=True)
try:
    rows = ex.option_variants(store, costs, "G1", ex.g1_entries(store, exps, START, END))
    rows += ex.option_variants(store, costs, "P4", ex.p4_entries(store, START, END))
    rows += ex.option_variants(store, costs, "CPR", ex.cpr_entries(store, exps, START, END))
    rows += ex.r6_variants(store, costs, exps, START, END)
    rows += ex.swing_variants(score_stock_universe(store), START, END)
finally:
    store.close()
t = pd.DataFrame(rows)
t.to_csv(out / "trades.csv", index=False)
key = ["cand", "day", "side", "symbol"] if "symbol" in t else ["cand", "day", "side"]
t["symbol"] = t.get("symbol", pd.Series(index=t.index, dtype=object)).fillna("")
out_rows = []
for c, g in t.groupby("cand"):
    days = sorted(g["day"].unique())
    cut = days[len(days) // 2]
    w = g.pivot_table(index=["day", "side", "symbol"], columns="variant", values="net_inr", aggfunc="first").dropna()
    half = np.where(w.index.get_level_values("day") <= cut, "H1", "H2")
    for v in ("X1", "X2"):
        diff = w[v] - w["BASE"]
        changed = diff.abs() > 1e-6
        m1, m2 = (w.loc[half == h, v].mean() - w.loc[half == h, "BASE"].mean() for h in ("H1", "H2"))
        worse_both = bool(m1 < 0 and m2 < 0)
        out_rows.append({
            "cand": c, "variant": v, "n": len(w), "base_net": round(w["BASE"].mean(), 1),
            "variant_net": round(w[v].mean(), 1), "diff_H1": round(m1, 1), "diff_H2": round(m2, 1),
            "trades_changed%": round(changed.mean() * 100, 1),
            "rescued_avg": round(diff[changed & (diff > 0)].mean(), 0) if (changed & (diff > 0)).any() else 0,
            "rescued_n": int((changed & (diff > 0)).sum()),
            "cut_avg": round(diff[changed & (diff < 0)].mean(), 0) if (changed & (diff < 0)).any() else 0,
            "cut_n": int((changed & (diff < 0)).sum()),
            "GOES_FORWARD": not worse_both})
r = pd.DataFrame(out_rows)
r.to_csv(out / "verdict.csv", index=False)
with pd.option_context("display.width", 250, "display.max_columns", 20):
    print("(₹ per trade: options 1 lot of 65; R6 1 lot; swing on ₹1 lakh)")
    print(r.to_string(index=False))
    base_tot = t[t.variant == "BASE"].groupby("cand")["net_inr"].agg(["size", "sum"]).round(0)
    print("\nBASE sanity (trades, total ₹):\n" + base_tot.to_string())
print(f"\nWritten to {out}")
