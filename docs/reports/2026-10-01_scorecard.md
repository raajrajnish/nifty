# Trade-quality scorecard: logic · entry · profit capture · exit (2026-10-01)

**Command:** `tradingagent scorecard` (measurement only; no rules changed). Output is in `data/reports/backtests/stops_20261001_0925/scorecard/`.

**Trades measured:**
- **S1:** ORB-15, narrow OR, opposite-side exit, −50% stop
- **S2:** TWAP pullback, low volatility, hold, −30% stop
- **RANDOM:** random entry, hold, −30% stop; the no-skill yardstick

## Scorecard

| Link | Measure | RANDOM | S1 | S2 | Reading |
|---|---|---:|---:|---:|---|
| — | Trades / win % / net per trade | 552 / 36% / −₹37 | 269 / 41% / +₹154 | 316 / 40% / +₹285 | |
| **0 Logic** | Index in our direction after 60 min | 47% | 52% | 52% | **barely better than a coin flip** |
| | Index move by 15:10 (in daily-ATR units) | +0.01 | +0.08 | +0.04 | tiny |
| **1 Entry** | Edge ratio, first 10 min (gain ÷ heat) | 0.97 | 1.09 | 0.95 | ≈ random |
| | Median heat in the first 10 min | −5.5% | −7.2% | −6.4% | breakouts buy strength, so a little more heat |
| **2 Capture** | Winners keep this share of their best move | 66% | 59% | 64% | ≈ random; OK |
| | Winners: minutes to their best point (median) | 148 | **227** | **219** | **winners peak late in the day** |
| **3 Exit** | Reached +30%, then still lost | 6.5% | 8.2% | 10.8% | modest |
| | Stopped out, but above entry at 15:10 | 4.5% | 0.7% | 5.7% | low |

**Weakest link: 0, the setup logic.** S1 and S2 point the right way only about 52% of the time, against 47% for random. Entry, capture and exit are all close to random behaviour. They neither help nor hurt much.

## Relationships between the links (the same pattern holds for S1, S2 and RANDOM)

**R1. The first 15 minutes decide most trades.**

| | S1 win % / net per trade | S2 | RANDOM |
|---|---|---|---|
| Index moved our way within 15 min | **57% / +₹1,174** | **51% / +₹892** | 47% / +₹581 |
| Index did not | **26% / −₹733** | 30% / −₹379 | 25% / −₹738 |

Early heat and entry-price quality say the same thing; they are correlated with follow-through at 0.5–0.7.

**R2. All the profit comes from the big movers.** Trades whose best point was in the top third had about 82–84% wins and +₹4,000 per trade. Bottom-third trades lost about ₹2,000 each.

**R3. Winners that peak late are worth the most.** S1 winners: early peak +₹1,522, late peak **+₹5,874**, and late-peak winners keep 83% of their best move.

**R4. The chain:** early follow-through → bigger move (correlation 0.5) → more of it kept (0.8) → profit (0.9).

## What it implies (hypotheses for the next pre-declared study, not rules yet)

- **Link 3 (exit):** a **15-minute follow-through check** (if the index has not moved our way after 15 minutes, exit). This could cut the −₹733 group early. Risk: 26% of that group would have gone on to win.
- **Link 2 (capture):** **once follow-through is confirmed, hold to the end of the day** with only the failure stop. No profit locks, because winners peak late (consistent with exit study #1, where a 70% lock hurt).
- **Link 0 (logic):** because R1 holds **even for random entries**, these exit and capture rules shape the trade, but they do **not** create a direction edge. The setup logic remains the thing to improve.
