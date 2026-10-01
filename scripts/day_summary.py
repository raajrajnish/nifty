"""Print a short, readable summary of `tradingagent analyze-day` output.
Usage: uv run python scripts/day_summary.py YYYY-MM-DD"""

import json
import sys
from pathlib import Path

day = sys.argv[1]
m = json.loads((Path("data/reports") / f"date={day}" / "metrics.json").read_text(encoding="utf-8"))
q, s, e, mk, st = m["quality"], m["spreads"], m["entry_test"], m["market"], m["straddle"]
print(f"QUALITY  ltp median gap {q['ltp']['median_gap_s']}s, gaps>3x {q['ltp']['gaps_over_3x']} "
      f"({q['ltp']['gap_seconds_lost']}s lost) | quotes missing bid/ask {q['quotes']['missing_bid_or_ask']}, "
      f"crossed {q['quotes']['crossed_or_locked']} | last-trade age median {q['quotes']['last_trade_age_s_median']}s")
print(f"INDEX    frozen episodes {q['frozen_index_episodes']} | bad ticks "
      f"{q['index_anomalies']['bad_index_ticks']} {q['index_anomalies']['times'][:6]}")
print(f"MARKET   open {mk['nifty_open_recorded']} high {mk['nifty_high']} low {mk['nifty_low']} "
      f"range {mk['range_pts']} close(15:15) {mk['nifty_close_recorded']} | VIX {mk['vix_first']}->{mk['vix_last']} "
      f"| fut basis {mk['fut_basis_median']}")
print(f"STRADDLE {st['straddle_pts']} pts at {st['at'][11:16]} (to expiry) | ATM IV {st['atm_iv']:.2f} "
      f"| realised range after {st['realized_range_after_pts']} | close move {st['realized_close_move_pts']}")
print(f"SPREADS  ATM median {s['atm_spread_pct_median']}% (₹{s['atm_spread_inr_per_lot_median']}/lot), "
      f"p90 {s['atm_spread_pct_p90']}% | top-of-book {s['atm_top_bid_lots_median']} lots")
print("         near-ATM by time: " + ", ".join(f"{r['bucket']} {r['median_pct']}%" for r in s["near_atm_by_time"]))
for h in ("h10", "h25", "h60"):
    x = e[h]
    print(f"ENTRY {h}: best move (MFE) median ₹{x['mfe_median']:,.0f} | time-exit median ₹{x['exit_median']:,.0f} "
          f"mean ₹{x['exit_mean']:,.0f} | hindsight-best-side MFE ₹{x['hindsight_best_side_mfe_median']:,.0f}")
