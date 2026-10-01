# Setup-logic study (PRE-DECLARED 2026-10-01, before running)

**Why:** the scorecard found link 0 (direction) to be the weak link. S1 and S2 point the right way about 52% of the time after 60 minutes, against 47% for random. All profit comes from "big move" trades.

**Question:** does anything **known before entry** pick out the days and directions where the setup's move is larger and more often right?

**Trades:** unchanged S1, S2 and RANDOM from the stop study (S1: opposite-side failure plus −50% stop; S2 and RANDOM: hold plus −30% stop). Nothing about entry or exit changes. Each idea only selects a **subset** of these trades.

## Features (all known before the entry minute; no look-ahead)

| Id | Feature | Definition |
|---|---|---|
| F1 | Multi-day squeeze | Average daily range (high−low)/close over the previous 5 days ÷ the same over the previous 20 days < 0.80 |
| F2 | Cheap volatility | Yesterday's India VIX close < the median of the previous 60 daily VIX closes |
| F3 | VIX rising at entry | VIX at the last completed minute before entry > yesterday's VIX close |
| F4 | Open outside yesterday's range | Today's first 1-minute open > yesterday's high, or < yesterday's low |
| F5 | Breakout aligned with the gap | Gap = (today's open − yesterday's close) / yesterday's close. **Aligned:** gap of at least 0.15% in the trade's direction. **Opposed:** at least 0.15% against it. **No gap:** otherwise |
| F6 | After a big day | Yesterday's range > 1.5 × the 14-day average range ending the day before yesterday |

Each feature splits each setup's trades into groups (true / false; F5 has three groups).

## Measures per group

- **Link 0 (logic):** share of trades where the index moved our way within 60 minutes; index move by 15:10 in daily-ATR units.
- **Money:** net per trade.
- Also: PASS/ROBUST (as before) and 95% confidence interval.

## Decision rule (fixed in advance)

A feature group is a **logic improvement** only if, for **both S1 and S2**:
- n ≥ 60 trades in the group;
- the 60-minute right-direction % is **higher** than the setup's all-trades value;
- net per trade is **higher** than the setup's all-trades value **on dev days and on validate+test days**.

If RANDOM improves in the same way, it is labelled a **day filter** (it helps any entry), not a setup-specific edge; it is still useful. With about 14 groups per setup, a lucky single-setup result is expected, which is why **both** setups must agree. Anything that qualifies goes to the **forward paper test** only, not to live trading.

## Result (run 12:44, `logic_20261001_1244`): ONE qualifier, F4 "open outside yesterday's range" (setup-specific)

| | n | Right direction after 60 min | Net per trade | Dev / val+test | Without top 5 | 95% CI | Calls / puts |
|---|---:|---:|---:|---|---:|---|---|
| S1, all | 269 | 52.0% | +154 | 76 / 267 | −167 | [−303, 653] | −161 / +445 |
| **S1, open outside** | 117 | **56.4%** | **+837** | 872 / 797 | **+141** | **[46, 1733]** | −4 / +1486 |
| S1, open inside | 152 | 48.7% | −371 | | | | |
| S2, all | 316 | 51.9% | +285 | 444 / 51 | −13 | [−128, 731] | −35 / +657 |
| **S2, open outside** | 133 | **57.1%** | **+862** | 1289 / 153 | **+199** | **[88, 1715]** | +156 / +1775 |
| S2, open inside | 183 | 48.1% | −134 | | | | |
| RANDOM, open outside | 226 | 45.1% (lower than its all-trades 47.1%) | +10 | | | | |

- **Puts are positive even in up-year 2024:** S1 +2,178 (n=25), S2 +2,565 (n=23). RANDOM puts on these days lost −432 in 2024. So this is not only the 2026 decline.
- **Strongest sub-pattern:** opens **above yesterday's high, then breaks down** (trapped buyers). Puts: S1 +1,247 (n=52), S2 +1,654 (n=38). Puts after opening below yesterday's low: S1 +2,374 (n=14), S2 +2,003 (n=20).
- **Calls are roughly flat,** so strict ROBUST is just missed for S1 (calls −₹4).
- Other features did not qualify: F2 (expensive VIX was better for both but failed the dev/val+test consistency check), F3, F5 and F6. F1 (squeeze) helped RANDOM but did not consistently help the setups.

**Decision:** frozen as forward-test rules **G1** (S1 + open outside) and **G2** (S2 + open outside), counted separately from F1–F3. Caveats: small cells, a reused history, and multiple features tested (6 features, 13 groups).

## Risk re-check for G1/G2 (`backtest-risk --g-rules`), 1 lot each, after costs, Dec 2023 – Sep 2026 (about 2.83 years)

| Option | Trades | Total | Per year | Historical max DD | Monte Carlo DD median / p95 / p99 | Hits the ₹20k (10%) kill | Losing-day streak p95 |
|---|---:|---:|---:|---:|---|---:|---:|
| G1 only | 117 | ₹97,893 | ₹34,591 | −₹16,572 | −22k / −36k / −43k | 66% | 10 |
| G2 only | 133 | ₹114,648 | ₹40,511 | −₹21,033 | −23k / −38k / −45k | 74% | 11 |
| G1+G2, max 1 trade/day | 178 | ₹112,278 | ₹39,674 | −₹18,728 | −30k / −49k / −60k | 96% | 13 |
| **G1+G2 both** | 250 | **₹212,541** | **₹75,103** | −₹26,579 | **−36k / −57k / −69k** | 100% | 12 |
| (before the filter: S1+S2, all days) | 585 | ₹131,561 | ₹46,488 | −₹84,426 | −77k / −123k / −146k | — | 15 |

- **The filter roughly halved the drawdown and raised the profit.** G1+G2 together has the best profit-to-drawdown ratio (about 2.1, against about 1.5–1.7 for either alone). "Max 1 trade/day" is worse than either alone.
- Per-trade loss: average about −₹2,100; 1-in-10 −₹3,100 to −₹3,700; worst about −₹5,000. Worst day −₹7,064. Daily caps of ₹3k–₹8k still have no effect.
- **Still incompatible with `kill_criteria.live_drawdown_pct_from_peak: 10`.** A normal bad patch at minimum size (1 lot) is 11–18% of ₹2 lakh. These are backtest numbers on reused history; live results will likely be worse.
- **The owner must decide before any live stage:** (a) a fixed 10% kill (then G1/G2 at 1 lot are not tradeable on ₹2 lakh); (b) a statistical kill (pause if the drawdown passes the backtest p95, stop at p99) combined with the 30-trade expectancy check already in `risk.yaml`; or (c) more capital. No change to `risk.yaml` until then; paper trading continues.
