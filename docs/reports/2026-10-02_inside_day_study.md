# Inside-day setups study (PRE-DECLARED 2026-10-01, before any code was written or run)

**Goal:** find setups for days that **open inside yesterday's high–low range**. That is about 68% of days, and G1/G2 never trade them. G1/G2 stay frozen; all code is new.

**Already ruled out (not retested):** these were tested before and failed. Retesting them on a narrower subset would just be fishing for a pass.
- First close beyond yesterday's high/low (H2, discovery study);
- ORB-15 and TWAP pullback on inside days (setup-logic study: the open-outside filter was what made them work).

**Honest prior:** inside days are often range days, and range days are hard for option buyers because time decay eats small moves. **"No setup works on inside days" is an acceptable answer.**

## Common frame (same as every study)
- **Inside-open day:** yesterday's low ≤ today's 09:15 open ≤ yesterday's high (PDL/PDH).
- No expiry days. One trade per setup per day. ATM option, nearest weekly expiry, buying only.
- Signals on completed 5-min bars, with the option fill at the next minute's open. Exit at 15:10. Groww charges plus half-spread fills.
- **Control: RANDOM_inside**, i.e. random entries on the **same inside days**. Every candidate must beat this, not just random entries on all days.

## Candidates

| Id | Idea | Setup / entry (09:30–13:30 unless stated) | Exit |
|---|---|---|---|
| **N1** | **Rejection at yesterday's extreme** | The first 5-min bar that trades **at or above PDH but closes back below it** → PE. Mirror at PDL → CE. | 5-min close back beyond the level (thesis wrong); −30% stop; 15:10 |
| **N2** | **Acceptance beyond yesterday's extreme** | A 5-min close beyond PDH **and the next two 5-min closes also stay beyond it** (15 minutes of acceptance) → CE. Mirror at PDL → PE. | 5-min close back on the other side of the level; −50%; 15:10 |
| **N3** | **Quiet-morning expansion** | The first-hour range (09:15–10:15) is **< 0.25 × ATR14** (yesterday's 14-day average range). Then the first 5-min close beyond that range, 10:15–13:30 → that direction. | 5-min close beyond the opposite side of the first-hour range; −50%; 15:10 |
| **N4** | **Gap fill inside the range** | Gap from yesterday's close ≥ 0.25%. The first 5-min close beyond the 15-min opening range **towards yesterday's close** → trade towards the gap fill. | **Target:** index 1-min close reaches yesterday's close. Stop: 5-min close beyond the other side of the opening range; −50%; 15:10 |

## Test: revised 2026-10-01 before any run, per the owner's rule "each setup belongs to ONE index"

Each idea is tested as **two separate setups**: Nifty-N1…N4 and BankNifty-N1…N4. **Each passes or fails on its own index's data only.** The other index's result is shown for information and can neither rescue nor sink it. Rules are identical for both (no per-index tuning). The only difference is the strike step: 50 for Nifty, 100 for Bank Nifty.

**Per index, two checks; the setup must pass BOTH:**
1. **Stage A: direction on that index's untouched data, Nov 2021 – Nov 2023.** PASS-A:
   - n ≥ 80;
   - right direction after 60 min ≥ 53% **and ≥ that index's RANDOM_inside + 3 pts**;
   - mean move at 15:10 (ATR units) > 0 with the 95% bootstrap CI above 0.
   - Dec 2023 – Sep 2026 direction is shown for information.
2. **Stage B: option P&L on that index.** Runs only for its Stage A passers.
   - **Nifty:** Dec 2023 – Sep 2026 (weekly options).
   - **Bank Nifty:** decided on **Dec 2024 – Sep 2026, the monthly-options period that matches how Bank Nifty can be traded today**. The weekly period (Dec 2023 – Nov 2024) is shown for information.
   - **PASS:** n ≥ 100 (Bank Nifty monthly period: n ≥ 60, flagged as a smaller sample); dev, validate and test all positive; positive at 2× costs; PF ≥ 1.10; both halves positive.
   - **ROBUST:** PASS plus calls and puts each positive, plus still positive without the 5 best days.
   - Also reported: RANDOM_inside on the same days.

**Multiple testing:** 8 setups (4 ideas × 2 indices), each needing 2 checks. About 0.2 setups would pass both checks by chance alone. A pass on only one check counts as a lead, not a setup.

## Result (run 2026-10-02 00:35, `inside_A_20261002_0035`): ALL 8 FAIL Stage A, so no Stage B

**Random on the same inside days:** Nifty 56.7% right after 60 min; Bank Nifty 52.8%. Untouched Nov 2021 – Nov 2023.

| Setup | Nifty: n / right % / move at 15:10 [CI] | Bank Nifty: n / right % / move at 15:10 [CI] |
|---|---|---|
| N1 rejection | 123 / 48.0% / +0.060 [−0.031, 0.155] | 135 / 52.6% / +0.056 [−0.030, 0.140] |
| N2 acceptance | 127 / 53.5% / −0.041 | 136 / **44.9%** / −0.080 [−0.169, 0.007] |
| N3 quiet expansion | **1 signal in 2 years** | 5 signals |
| N4 gap fill | 46 (too few) / 60.9% / +0.030 | 56 (too few) / 51.8% / −0.010 |

**2023–26 (info):** nothing stands out. Nifty N2 58.6% vs random 49.8%, but its move to 15:10 is only +0.026 (CI includes 0).

**Reading:**
1. **N1 rejection** is the only idea with a positive end-of-day move on both indices (+0.06 ATR). But it isn't significant, and its 60-minute direction is no better than random. It is a lead only.
2. **N3's filter ("first hour < 0.25 × ATR") almost never happens** (1 Nifty day in 2 years). The declared threshold was unrealistic. It is recorded as a design error and not re-tuned after seeing the data; any new threshold would be a new pre-declared study.
3. **N4 fires too rarely** (about 2 a month) to judge.

**Verdict:** no inside-day setup qualifies on either index. This supports the honest prior that inside days are poor days for option buyers.

**Outcome:** a setup that passes A + B-ROBUST on its own index → **paper-only hypercare candidate for that index**, with the owner's approval. Otherwise it is recorded as failed, with the reason.
