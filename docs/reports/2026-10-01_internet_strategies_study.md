# Internet strategies study, batch 2 (PRE-DECLARED 2026-10-01, before any code was run)

**Source:** strategies collected by the owner from the internet (YouTube/blogs). G1/G2 stay frozen. All code is new (`sim/internet_study.py`).

## Translation rules (decided before running)
- **Instrument.** We hold no Bank Nifty data, and Bank Nifty weekly options were discontinued in Nov 2024. Bank Nifty strategies are therefore tested **on Nifty**. Point values are converted at **×0.45** (Bank Nifty ≈ 2.2× Nifty). Nifty-specific rules keep their numbers.
- **Gap filter.** "Massive gap of 300–400 points" is read as Bank Nifty scale → skip a day if |09:15 open − previous close| ≥ **150 Nifty points**.
- **"Breaks above/below".** The first **1-minute close** beyond the level counts (wicks don't). The option fills at the next minute's open.
  - Exception, P6: its rule is "1 point past", so the 1-min high counts; the fill is still next minute.
- **Standard frame.** No expiry days. One trade per strategy per day. ATM option, nearest weekly expiry. Buying only. A −50% premium stop as a disaster backstop. Forced exit at 15:10. Groww charges plus half-spread fills, as in every study.
- **Targets and stops on index levels.** Detected on a 1-minute index close; the option fills at the next minute's open.
- **Strategies without a stated stop (P1, P2).** Our standard thesis-wrong exit: a 5-min close beyond the opposite side of the range.

## The six strategies

| Id | Strategy (source) | Setup | Entry | Exit |
|---|---|---|---|---|
| **P1** | 15-min inside candle | First 15-min candle (09:15–09:30) = range. The next five 15-min candles (09:30–10:45) stay **strictly inside** it. Gap filter. | 10:45–13:30: first 1-min close above high → CE, below low → PE | 5-min close beyond opposite side; −50%; 15:10 |
| **P2** | First 5-min candle breakout, within 30 min | First 5-min candle 09:15–09:20 | 09:20–09:45: first 1-min close above high → CE, below low → PE | 5-min close beyond opposite side; −50%; 15:10 |
| **P3** | 44 Fibonacci retracement (Nifty, buy only) | Running day high H; L = lowest low since H; requires H − L ≥ **80** points | 09:30–13:30: 5-min close crosses **above L + 0.44(H−L)** → CE. Levels frozen at entry. | Stop: index close ≤ 0.22 level. Target: close ≥ **0.77 level (T1), full exit**; −50%; 15:10 |
| **P4** | Bank Nifty 9:20 option buying (→ Nifty) | As P2, plus gap filter | As P2 | Stop: index 1-min close beyond the opposite side of the first candle, but **at least 35 points** from entry (70–80 Bank Nifty points ×0.45). **Stagnation exit:** at 20 min after entry, exit if the option is not above entry price. −50%; 15:10 |
| **P5** | Fib 71 call buying (Bank Nifty → Nifty, buy only) | As P3 but fall ≥ **135** points (300 ×0.45) | **12:00–13:30**: 5-min close crosses above **0.71** level → CE | Stop: close ≤ **0.38** level. Target: close ≥ **1.00** level (T1), full exit; −50%; 15:10 |
| **P6** | Window strategy (Bank Nifty 1-min → Nifty) | First 1-min candle (09:15). Buy setup: its high is 0–15 pts **above** a multiple of 50. Sell setup: its low is 0–15 pts **below** a multiple of 50. (Bank Nifty: 30-pt window, 100s → ×0.45, Nifty's 50-pt grid) | 2nd or 3rd minute trades ≥ 1 pt past that high → CE (buy setup) / low → PE (sell setup). Both in the same minute → skip. | Stop: index 1-min close 40 pts against entry (90 ×0.45). Trail: exit on the first 1-min close below the previous minute's low (CE) / above its high (PE). −50%; 15:10 |
| RANDOM | control | random entry time, random side | — | −30% stop / 15:10 |

**Fixed choices where the source is vague:**
- Only T1 is used for the target exits; that's where the "90% success" claim applies.
- No partial booking.
- P5's "works best 12:00–1:30" is used as its entry window.

## Test
**Decides (owner's choice: recent regime): Stage B, option P&L, 2024-10-01 → 2026-09-30.** These strategies have never been run on any of our data, so this window is untouched for them.
- **PASS:** n ≥ 100; dev, validate and test (60/20/20 by date) all positive; positive at 2× costs; PF ≥ 1.10; both halves positive.
- **ROBUST:** PASS plus still positive without the 5 best days, plus calls and puts each positive where both are traded (P3/P5 are calls only).
- **For n < 100:** reported as "insufficient sample", never a pass.

**For information only (cannot pass or fail a strategy):**
1. Direction on Nov 2021 – Nov 2023 index data (Stage A measure), to show whether any edge lasts across regimes.
2. **Claim checks on index data, Oct 2021 – Sep 2026:**
   - signal frequency per month (P1 claims 18–20, P6 claims 3–4);
   - P3/P5: % of entries where the index reaches T1 before the stop (claimed > 90%), plus T2/T3.

**Caveats:**
- **Multiple testing:** 6 strategies, so a single marginal pass may be luck.
- **P6 fill is slightly pessimistic:** the real entry happens mid-minute, but we fill at the next minute's open.
- **Opening-minute spreads are wider than our 0.11% half-spread**, so P2/P4/P6 results are slightly flattered.

**Outcome:** ROBUST → **paper-only hypercare candidate**, owner decides. PASS that is not ROBUST → lead. Otherwise → failed, with the reason recorded.

## Result (run 19:47, `internet_20261001_1947`): NONE PASS

### Decides: option P&L, Oct 2024 – Sep 2026 (net ₹ per trade, 1 lot, after all costs)

| Strategy | n | Win | Net/trade | PF | Dev / Val / Test | Without top 5 | 95% CI | Verdict |
|---|---:|---:|---:|---:|---|---:|---|---|
| P1 inside 15m | 8 | 25% | −1,305 | 0.30 | — | — | — | ❌ too rare (n = 8) |
| P2 first-5m, 30 min | 340 | 34% | **−392** | 0.77 | all negative | −652 | [−809, 50] | ❌ |
| P3 Fib 44 buy | 233 | 49% | **−212** | 0.73 | −317 / −53 / +9 | −307 | **[−422, −5]** | ❌ significantly negative |
| P4 Bank Nifty 9:20 | 297 | 23% | −256 | 0.80 | all negative | −526 | [−635, 148] | ❌ |
| P5 Fib 71 buy | 23 | 70% | +769 | 1.85 | **−381** / +1,633 / +759 | +30 | [−391, 1,811] | ❌ n = 23, too few; a lead only |
| P6 window | 81 | 40% | +95 | 1.27 | +243 / −204 / −172 | −134 | [−149, 373] | ❌ n = 81, recent periods negative |
| RANDOM | 388 | 36% | +64 | 1.05 | +84 / +276 / −210 | −124 | [−276, 407] | control |

### For information: direction, Nov 2021 – Nov 2023
None of the six is above random (53.8%). Range: 45.5%–51.5%, all moves by end of day ≤ 0. **P5 is flat there too** (n = 18, −0.010 ATR).

### Claim checks (index only, Oct 2021 – Sep 2026)

| Claim | Measured |
|---|---|
| P1 occurs 18–20 sessions a month | **0.4 a month** (strict "5 candles inside" is rare) |
| P6 occurs 3–4 times a month | **3.2 a month** ✔ (the conversion to Nifty matches the claim) |
| P3 (Fib 44) > 90% success | **T1 reached before stop on 54%** of entries; stop first on 43%. T2 38%, T3 30%. |
| P5 (Fib 71) high success | **T1 reached before stop on 67%** of entries; stop first on 29%. Only about 0.8 signals a month. |

**Reading:**
1. **The breakout-at-open family (P2, P4) loses steadily.** This matches K3 from batch 1. The P4 rules (stagnation exit, 35-pt minimum stop) cut the loss slightly but don't turn it positive.
2. **The 90% claim for the 44 Fib setup is false on Nifty data:** it hits T1 54% of the time. Even with a better than 1:1 index payoff, the option version loses money reliably (CI entirely below 0), because of option delta, time decay, fill delay and costs.
3. **P5 Fib 71 is the only interesting one,** but with 23 trades in 2 years it cannot be tested statistically. It also loses in its earliest period and is flat in 2021–23. Recorded as a **lead only.** At about 1 signal a month, forward paper testing would need years to judge.
4. **P6's frequency matches the claim, but its edge does not hold up:** profits come from the earliest period only.

**Verdict:** batch 2 failed. No hypercare candidates.
