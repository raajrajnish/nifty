# P4: Nifty vs Bank Nifty intraday spread (PRE-DECLARED 2026-10-02, before any test)

Phase 3, owner-approved. **Research only, paper only.**

## Reason (written before testing)
Bank Nifty is about a third of Nifty. A large same-day divergence between the two (for example, banks rallying while Nifty lags) is pulled back partly by index arbitrage and basket flows. The hypothesis: after an unusually large divergence, **Nifty catches up** with Bank Nifty's lead by 15:10. No earlier idea used the relation **between** the two indices.

## Rule (fixed now; threshold chosen from signal frequency only)
- **Divergence:** rel_t = ln(BN_t / BN_open) − ln(N_t / N_open). "Open" is the 09:15 one-minute open; t is the close of the minute before a 5-minute label.
- **Scale:** z = rel_t ÷ the SD of rel at the **same clock time** over the previous 60 trading days (at least 30; past only).
  - The warm-up starts 2023-12-01, so **Bank Nifty lock box 2 (index Nov 2021 – Nov 2023) is not touched.**
- **Signal:** the first bar labelled 10:00 … 13:30 with |z| ≥ **2.0**.
  - Frequency only: about 63 of 391 days in the design window.
  - s = sign(rel): +1 means Bank Nifty is ahead.
- **Trade (fixed leg, "Nifty catches up"):**
  - s = +1 → buy NIFTY ATM **CE**; s = −1 → buy NIFTY ATM **PE**;
  - nearest weekly expiry strictly after today; entry at the open of the signal-label minute;
  - −30% stop, 15:10 exit; no NIFTY expiry days.
- **Index measures:**
  - reversion = −s × (rel_15:10 − rel_t), in basis points;
  - Nifty catch-up = s × (N_15:10 / N_t − 1), in basis points.
- **Random control:** random time and side on all eligible days in the same window (`entry_study.e_random`).

## Data split and pass bars
- **Design (2023-12-01 → 2025-06-30):**
  - n ≥ 50;
  - mean reversion > 0 with the 95% CI above 0;
  - option mean net > 0 at 1× and 2× costs;
  - > the random control;
  - one-sided P ≤ 0.05.
- **One-shot test (2025-07-01 → 2026-09-30), only if design passes.** This uses Bank Nifty **index** data inside the lock-box-1 period (Oct 2025 – Sep 2026), so it is declared as **lock-box opening #1 of 2.** Pass:
  - n ≥ 40;
  - mean reversion > 0;
  - option mean net > 0 at 1× and 2×;
  - > random;
  - one-sided P ≤ 0.0125.

## Multiple-testing count
1 design rule (Phase 3 total: 7); 1 one-shot test at most.

## Result (run 2026-10-02 14:12, `data/reports/backtests/phase3_p4_design_20261002_1412/`)
n=50, net +₹1,140/trade (2× +₹1,048), random control −₹125, CI [−600, 3,361], P=0.13, without the best 5 days −₹823. Spread reversion +2.7 bp, CI [−11.4, 17.7]; Nifty catch-up +8.7 bp. **Design FAIL** (P > 0.05, reversion CI includes 0). The test window and Bank Nifty lock box 1 were NOT opened. P4 ends.
