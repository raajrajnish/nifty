# Exit-rule study #1: ORB-15 entry, 10 exit rules (2026-10-01)

**Command:** `tradingagent backtest-exits`. Code is in `src/tradingagent/sim/exit_study.py`; the raw trades are in `data/reports/backtests/exits_20261001_0846/`.

**Data:** NIFTY weekly options, 1-minute candles, Dec 2023 – Sep 2026 (`data/market.duckdb`). **533 trades**, one per qualifying day; expiry days are excluded.

**Costs:** today's Groww charges (`config/costs.yaml`, about ₹67 per trade) plus a half-spread on each side (0.11%, from the 2026-09-30 recording). Results are for 1 lot of 65.

## Setup (declared before running, not tuned)

- **Entry:** first 5-minute close outside the 09:15–09:30 opening range → buy the ATM call (breakout up) or put (breakout down), nearest weekly expiry. Signals allowed 09:30–13:30.
- **Every variant also has** a hard stop at −30% of premium (= 1R) and a 15:10 exit.
- **Fill rules:**
  - The stop is checked against minute lows; a gap through the stop fills at the open.
  - If the stop and another exit fall in the same minute, the stop wins.
  - Other exits act on the minute close and fill at the next minute's open.
- **Data split:** dev 60% / validate 20% / test 20% by date. Also split into halves, and calls vs puts.

## Results (₹ per trade, net, 1 lot)

| Rule | Win % | Gross before costs | **Net expectancy** | PF | Dev | Validate | Test | Net at 2× costs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E5 lock 50% after +1R | 44.8 | +30 | **−37** | 0.97 | −31 | +78 | −173 | −105 |
| E4 no progress in 30 min | 33.2 | +18 | **−49** | 0.95 | −104 | +7 | +58 | −117 |
| E5 lock 60% | 44.8 | +4 | −63 | 0.95 | −35 | −69 | −142 | −131 |
| E2 breakeven after +1R | 44.3 | 0 | −67 | 0.95 | −2 | −103 | −227 | −135 |
| E0 hold to 15:10 (baseline) | 35.1 | −5 | −73 | 0.95 | −77 | +64 | −198 | −140 |
| E5 lock 80% | 44.8 | −31 | −99 | 0.92 | −94 | −95 | −116 | −166 |
| **E5 lock 70% (the idea we discussed)** | 44.8 | −34 | **−101** | 0.92 | −77 | −94 | −183 | −169 |
| E3 5-min swing trail | 33.0 | −49 | −116 | 0.85 | −28 | −118 | −381 | −183 |
| E0b 60-minute time exit | 42.6 | −57 | −124 | 0.86 | −99 | −124 | −199 | −191 |
| E1 thesis (index back past OR mid) | 28.0 | −178 | −245 | 0.82 | −210 | −147 | −451 | −312 |

## Conclusions

1. **No exit rule passes.** All ten lose after costs. None is positive in all of dev, validate and test, and none survives doubled costs.
2. **The entry has no edge.** Gross P&L before costs is roughly zero (−₹5 when holding). Exit rules only re-shape the wins and losses; they cannot create an edge that the entry doesn't have.
3. **The 70% profit lock** raised the win rate (35% → 45%) but **lowered expectancy** (−₹73 → −₹101). This matches the one-day test and SideHustle's Q2 finding.
4. **Costs of about ₹67 per trade** are bigger than any rule's gross edge. One-lot ATM buying needs a gross edge well above ₹100 per trade.
5. Holding to 15:10 hit the −30% stop on 55% of days (291 of 533).

## Limits (honest)

- Only one entry type was tested (ORB-15). Better entries may change the ranking of exits.
- 1-minute candles use the last traded price, not bid/ask; the spread is modelled as fixed at 0.22%.
- Rupee figures use today's lot (65) and charges throughout.
- One stop size (30%) was used; it was not optimised, on purpose.

## What this means for the plan

Exits are not the bottleneck; **entries and trade selection are.** The next study should hold an exit fixed (for example E4 or E5-50, as simple, low-cost options) and compare **entry and regime filters**: VWAP trend, trend days vs range days, VIX/IV level, time of day, gap days. It should also keep testing the "do nothing" baseline. If nothing beats costs on 2.8 years of data, that is a valid result (MASTER_PLAN §1).
