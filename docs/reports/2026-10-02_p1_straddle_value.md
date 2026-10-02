# P1: Cheap or dear options at 09:30 (PRE-DECLARED 2026-10-02, before any test)

Phase 3 of the independent review (`2026-10-02_independent_review.md`), owner-approved. **Research only, paper only.**

## Reason (written before testing)
An option buyer only profits when the realised move beats the move the premium already prices in. The magnitude study found that a wide opening range predicts a larger rest-of-day move. No earlier idea compared that **predicted move** with the **option price** (implied volatility). The hypothesis: on days when the morning has already been active, relative to what the straddle charges, buying the ATM straddle at 09:30 and holding it to 15:10 pays. This is a volatility bet; no direction is chosen.

## Rules (fixed now)
- **Days:** NIFTY non-expiry days. Contract = nearest NIFTY weekly expiry strictly after today; ATM = 09:29 one-minute close rounded to 50.
- **Straddle price at 09:30:** open of the 09:30 one-minute bar, CE + PE.
- **Implied daily move:** IDM = straddle ÷ √B, where B = number of weekdays from today to expiry, both included.
- **Ratio:** R = OR width (high − low of the 09:15–09:29 one-minute index bars) ÷ IDM.
- **Signal:** R > the 67th percentile of R over the **previous 60 eligible days** (at least 30 needed; past only).
- **Trade:** buy 1 lot (65) of the ATM CE and the ATM PE at the 09:30 open + half-spread (0.11%). Sell both at the 15:10 one-minute close − half-spread. No stop. Groww charges per leg (`config/costs.yaml`).
- **Control:** the same straddle on the eligible days **without** the signal.

## Data split
- **Design:** 2023-12-01 → 2025-06-30.
- **One-shot test:** 2025-07-01 → 2026-09-30. It is run only if the design stage passes, opened once, and nothing is changed afterwards.

## Pass bars
- **Design:**
  - n ≥ 60;
  - mean net > 0 at 1× costs, and at 2× costs (charges **and** half-spread doubled);
  - mean net > the control's mean net;
  - one-sided bootstrap P(mean ≤ 0) ≤ 0.05 (5,000 resamples, `timing_study.bootstrap_ci`).
- **Test:** the same, with n ≥ 40 and **P ≤ 0.0125** (Bonferroni over the 4 possible one-shot tests of Phase 3).
- **Paper-only candidate:** passes both.

## Multiple-testing count
1 rule, no parameter grid. This is 1 of 7 design-stage tests in Phase 3 (P1: 1, P2: 4, P3: 1, P4: 1) and 1 of at most 4 one-shot tests.

## Result (run 2026-10-02 14:12, `data/reports/backtests/phase3_p1_design_20261002_1412/`)
Signal days n=98, net +₹27/trade, 2× costs −₹154, control (non-signal days) −₹702, CI [−747, 881], P(≤0)=0.49. **Design FAIL** (2× costs negative, P > 0.05). The test window was not opened. P1 ends.
