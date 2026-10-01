# Popular-strategies study, batch 1 (PRE-DECLARED 2026-10-01, before running)

**Strategies:** CPR, Supertrend, first-5-minute-candle breakout, RSI reversal, and Camarilla (breakout and fade modes): **6 rules** in all. Textbook definitions are used, not tuned. G1/G2 are frozen and unchanged; all code is new (`sim/popular_study.py`).

**Common rules:**
- No expiry days. **One trade per strategy per day** (the first signal).
- Signals on 5-minute bars, labelled by their **end** time (the close is known then). Entry at that minute; ATM option, nearest weekly expiry after today; buying only.
- Exits:
  - **structure strategies:** a −50% premium stop plus the strategy's own thesis-wrong exit on a 5-minute close;
  - **others:** a −30% premium stop.
  - Every strategy: a time exit at 15:10.
- Indicators are computed on **continuous** 5-minute bars across days (warm-up from earlier days). No value at time t uses data after t; a unit test checks this.

| Id | Strategy | Textbook definition used | Signal window | Long (CE) / short (PE) | Thesis-wrong exit | Stop |
|---|---|---|---|---|---|---|
| **K1** | **Narrow-CPR trend day** | P = (H+L+C)/3, BC = (H+L)/2, TC = 2P − BC (yesterday's H, L, C); TC/BC swapped so TC ≥ BC. Width = (TC − BC)/P. **Narrow** = width ≤ the 33rd percentile of the previous 60 days | 09:35–13:30, narrow-CPR days only | first 5-min close **above TC** → CE; **below BC** → PE | 5-min close beyond the other side (CE: < BC; PE: > TC) | −50% |
| **K2** | **Supertrend (10, 3)** | Wilder ATR(10) on 5-min bars, multiplier 3, standard final-band recursion | 09:45–13:30 | first flip to **up** → CE; flip to **down** → PE | opposite flip | −50% |
| **K3** | **First 5-minute candle breakout** | first candle = 09:15–09:19 high/low | 09:25–13:30 | first 5-min close **above its high** → CE; **below its low** → PE | 5-min close beyond the other side of the first candle | −50% |
| **K4** | **RSI(14) reversal** | Wilder RSI(14) on 5-min closes | 09:45–13:30 | RSI crosses **back above 30** → CE; **back below 70** → PE | take-profit exit when RSI reaches 70 (CE) / 30 (PE) on a 5-min close | −30% |
| **K5a** | **Camarilla breakout** | R3/S3 = C ± (H−L)×1.1/4; R4/S4 = C ± (H−L)×1.1/2 (yesterday) | 09:35–13:30 | first 5-min close **above R4** → CE; **below S4** → PE | 5-min close back below R3 (CE) / above S3 (PE) | −50% |
| **K5b** | **Camarilla fade** | same levels | 09:35–13:30 | first 5-min bar with high ≥ R3 **and** close < R3 → PE; low ≤ S3 **and** close > S3 → CE | 5-min close above R4 (PE) / below S4 (CE) | −50% |

## Test (the same protocol as the discovery study; nothing loosened)

**Stage A (decides): direction on untouched NIFTY index data, Nov 2021 – Nov 2023.**
- PASS-A requires all of:
  - n ≥ 80;
  - right direction after 60 min ≥ 53% **and** ≥ the random baseline + 3 pts;
  - mean index move at 15:10 (in daily-ATR units) > 0, with the 95% bootstrap CI above 0.
- 2023–26 is reported for information only.

**Stage B: option P&L, Dec 2023 – Sep 2026, only for strategies that pass A.**
- Groww charges, half-spread fills, and pessimistic stop fills.
- **PASS:** n ≥ 100; positive in dev, validate and test; positive at 2× costs; PF ≥ 1.10; both halves positive.
- **ROBUST:** PASS plus calls and puts each positive, plus still positive without the 5 best days.
- Also reported: 95% CI and overlap with G1/G2 days.

**Multiple testing:** 6 rules × a one-sided 2.5% CI check means about 0.15 false passes are expected by chance. A single marginal pass is treated as a lead, not a discovery.

**Outcome:** A + B-ROBUST → proposed as a candidate for hypercare (a new G-number) for the owner to decide. Otherwise it is recorded as failed, with the reason.

## Result (run 19:28, `popular_A_20261001_1928`): ALL SIX FAIL Stage A, so there is no Stage B

| Strategy | n | Right direction after 60 min (random 53.8%) | Move at 15:10 (ATR) [95% CI] | 2023–26 move (info) |
|---|---:|---:|---|---:|
| K1 narrow CPR | 149 | 50.3% | −0.008 [−0.096, 0.080] | +0.073 |
| K2 Supertrend (10,3) | 262 | 46.9% | −0.022 [−0.076, 0.035] | +0.060 (CI > 0) |
| K3 first 5-min candle | 401 | 50.9% | −0.011 [−0.067, 0.044] | +0.006 |
| K4 RSI reversal | 279 | 44.8% | **−0.068 [−0.126, −0.012]** | −0.014 |
| K5a Camarilla breakout | 264 | 55.3% | +0.055 [−0.008, 0.119] | +0.011 |
| K5b Camarilla fade | 233 | 55.8% | −0.025 [−0.092, 0.042] | −0.017 |

**Findings:**
1. **None beats random entries on unseen data.**
2. **RSI reversal is reliably wrong:** after RSI turns from oversold/overbought, Nifty tends to continue (momentum beats reversal intraday). The inverse is a lead for its own pre-declared test, not a finding.
3. **Narrow CPR and Supertrend work in 2023–26 but not in 2021–23.** They are period-dependent, which is exactly what out-of-sample testing exists to catch.
4. **Why Stage B is not needed:** the Stage A measure is magnitude-weighted. Exit study #1 showed exits cannot create an edge the entry lacks. Without directional drift, option P&L cannot be positive after costs.

## Addendum: recent-regime test (PRE-DECLARED 2026-10-01 at the owner's request, before running)

**Owner's reasoning:** markets change, and 2021–23 may not reflect today. So all six strategies get **Stage B (option P&L) on the latest 2 years only: 2024-10-01 → 2026-09-30** (this includes the switch to Tuesday expiries in Sep 2025).
- **Rules:** unchanged from above. Same entries, exits, stops, costs and fills; nothing tuned.
- **Bar:** unchanged.
  - **PASS:** n ≥ 100; dev, validate and test (60/20/20 by date) all positive; positive at 2× costs; PF ≥ 1.10; both halves positive.
  - **ROBUST:** PASS plus calls and puts each positive, plus still positive without the 5 best days. The RANDOM control is reported alongside.
- **Caveats, recorded up front:**
  1. Direction for 2023–26 was already seen (K1 and K2 looked positive there), so this window is **not untouched**.
  2. Six strategies are tested at once, so a single marginal pass may be luck.
- **Therefore:** a ROBUST strategy can at most become a **paper-only hypercare candidate**. Live forward results would be the deciding test, and only the owner can add it. A PASS that is not ROBUST is recorded as a lead only.

### Result (run 19:33, `popular_B_20261001_1933`): NONE PASS on the latest 2 years either

Net ₹ per trade, 1 lot, after Groww charges and spread.

| Strategy | n | Win | Net/trade | At 2× costs | PF | Dev / Val / Test | Without top 5 days | 95% CI | PASS |
|---|---:|---:|---:|---:|---:|---|---:|---|---|
| K1 narrow CPR | 134 | 40% | +165 | +98 | 1.13 | +191 / +454 / **−95** | **−268** | [−436, 839] | ❌ |
| K2 Supertrend | 236 | 38% | −49 | −117 | 0.96 | −249 / +486 / +38 | −326 | [−472, 406] | ❌ |
| K3 first candle | 385 | 36% | **−319** | −387 | 0.81 | all three negative | −535 | [−717, 76] | ❌ |
| K4 RSI reversal | 277 | 33% | +64 | −4 | 1.05 | −226 / +559 / +419 | −179 | [−386, 517] | ❌ |
| K5a Camarilla breakout | 263 | 38% | −229 | −297 | 0.86 | −324 / +391 / −605 | −534 | [−698, 268] | ❌ |
| K5b Camarilla fade | 248 | 33% | **−367** | −434 | 0.77 | all three negative | −658 | [−808, 104] | ❌ |
| RANDOM | 388 | 36% | +64 | −3 | 1.05 | +84 / +276 / −210 | −124 | [−276, 407] | — |

**Reading:**
- **Only K1 narrow CPR is above random,** and it fails three of the checks:
  - it loses in the most recent 20% of the window (test −95);
  - it turns negative without its 5 best days (−268);
  - its uncertainty range is very wide.
  It is not a pass; recorded as a lead only.
- **K3 and K5b lose money in every sub-period.**
- **Random entries also make +₹64 in this window** (the market trended), so "positive" alone means little.

**Verdict:** recorded as failed. The recent regime does not rescue any of these strategies.

**Scorecard of popular strategies tested so far (all ideas, both studies):** ORB-15/30, EMA cross, gap-and-go, gap-fade, failed breakout, yesterday's-level breakout, afternoon continuation, opening drive, CPR, Supertrend, first-candle, RSI reversal, Camarilla breakout and fade all fail on untouched data. **G2's direction logic is the only one that partly holds out of sample.**
