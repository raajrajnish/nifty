# P3: VIX rising while the index is flat (PRE-DECLARED 2026-10-02, before any test)

Phase 3, owner-approved. **Research only, paper only.** The intraday India VIX (1-minute) was never used by the earlier ideas.

## Reason (written before testing)
If implied volatility rises during the morning while Nifty has barely moved, someone is paying up for protection before the price reacts (hedging demand, mostly puts). The hypothesis: such days tend to end **lower**, and a long ATM put captures it.

## Rule (fixed now; thresholds chosen from signal frequency only, no outcomes seen)
- **Reference:** the closes of the 09:19 one-minute bars (known at 09:20) of NIFTY (N0) and INDIAVIX (V0).
- **Signal:** at each 5-minute bar labelled 10:00 … 13:30 (value = close of the minute before the label), take the **first** bar where VIX/V0 − 1 ≥ **+3%** and |NIFTY/N0 − 1| ≤ **0.30%**.
  - Frequency check (counts only): 85 of 925 days in 2021-10 → 2025-06.
- **Trade:**
  - buy the NIFTY ATM **PE** (nearest weekly expiry strictly after today) at the open of the signal-label minute;
  - −30% premium stop; hold to 15:10 (the same simulator, fills and costs as G2);
  - no expiry days.
- **Index measure:** move from the entry minute's open to +60 min and to 15:10, in the trade's direction, in ATR14 points (`logic_features.atr_pts`), as in the discovery study.
- **Random control:** random time (09:45–13:30) and random side on all eligible days in the same window (`entry_study.e_random`).

## Data split and pass bars
- **Design A (index direction, 2021-10-01 → 2025-06-30):** PASS-A as in every study:
  - n ≥ 60;
  - right direction after 60 min ≥ 53% and ≥ random + 3 pts;
  - mean move at 15:10 > 0 with the bootstrap 95% CI above 0.
- **Design B (options, 2023-12-01 → 2025-06-30):** information only, because n is small (expected about 35). It must not be negative at 1× costs.
- **One-shot test (2025-07-01 → 2026-09-30, options and index), only if Design A passes and B is not negative:**
  - n ≥ 20 (flagged small);
  - option mean net > 0 at 1× and 2× costs;
  - > the random control's option net in the same window;
  - index mean move at 15:10 > 0;
  - option one-sided P(mean ≤ 0) ≤ 0.0125.

## Multiple-testing count
1 design rule (Phase 3 total: 7); 1 one-shot test at most.
