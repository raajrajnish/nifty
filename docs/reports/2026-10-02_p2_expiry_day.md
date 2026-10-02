# P2: Expiry-day behaviour (PRE-DECLARED 2026-10-02, before any test)

Phase 3, owner-approved. **Research only, paper only.** Every earlier study skipped expiry days.

## Reason (written before testing)
On expiry day the nearest options decay to intrinsic value within hours, and dealer hedging around big strikes may **pin** the index or release it late in the session. Same-day (0DTE) options are cheap in rupees but very sensitive to moves (high gamma). It is unknown whether buying them, at any time of day, is fairly priced. **Measurement first; at most ONE rule** goes to the held-out test.

## Days and contracts
NIFTY expiry days (dates taken from the contracts table, so holidays are already reflected), using **today's** expiry (0DTE). ATM = index one-minute close before the entry, rounded to 50. Lot 65, half-spread 0.11%, Groww charges per leg; 2× costs doubles charges and half-spread.

## Design measurements (2023-12-01 → 2025-06-30, about 75 expiry days)
1. **M1-0930 / M1-1100 / M1-1330:** buy the ATM straddle at the open of the 09:30 / 11:00 / 13:30 bar. Hold to the 15:10 close; no stop.
2. **M2, afternoon breakout:**
   - range = index high/low of 09:15–12:59;
   - signal = the first 5-minute bar (right-labelled 13:05 … 14:30) whose close is beyond the range: above → CE, below → PE;
   - entry at the open of the signal-label minute;
   - −50% premium stop (1-minute lows, `exit_study.simulate`); exit at the 15:10 close.
3. **M3, pin measurement (information only, no trade):**
   - distance of the 15:10 index from the nearest multiple of 100 (a uniform spread would give a mean of 25 pts);
   - and the same on non-expiry days.
4. **Option selling (research only, owner decision, never live):** the short-straddle results are reported as the mirror of M1 (−gross − costs).

## Rule selection (fixed now)
- Among M1-0930, M1-1100, M1-1330 and M2, take the one with the highest design mean net. It goes to the test **only if**, on design data:
  - n ≥ 40;
  - mean net > 0 at 1× and 2× costs;
  - one-sided bootstrap P(mean ≤ 0) ≤ 0.05.
- Otherwise P2 ends with no rule.
- **Control:** the M1 candidates are judged against zero (a straddle has no random-direction control). M2 is also judged against the straddle bought at the same minute on the same days.

## One-shot test
2025-07-01 → 2026-09-30 expiry days (about 60), opened once.
- **Pass:**
  - n ≥ 30;
  - mean net > 0 at 1× and 2×;
  - (M2 only) > its control;
  - one-sided P ≤ 0.0125.

## Multiple-testing count
4 design candidates (Phase 3 total: 7 design tests); 1 one-shot test at most.

## Result (run 2026-10-02 14:12, `data/reports/backtests/phase3_p2_design_20261002_1412/`)
Straddles (n=82 each): 09:30 −₹413, 11:00 +₹188 (P=0.39), 13:30 −₹760. M2 afternoon breakout n=39, +₹406 (2× +₹345), control −₹442, CI [−541, 1,566], P=0.24. Selected M2 → **Design FAIL** (n < 40, P > 0.05). No rule; the test window was not opened. Pin: 23.6 pts from a 100-strike on expiry days vs 26.3 on other days (uniform 25), so no pin. Short straddle (RESEARCH ONLY, owner decision): 09:30 +₹154, 11:00 −₹432, 13:30 +₹539 per trade.
