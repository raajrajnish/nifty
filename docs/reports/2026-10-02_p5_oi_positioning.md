# P5: Option-chain positioning at the open (PRE-DECLARATION ONLY; NOT tested now)

Phase 3, owner-approved **as a declaration only.** The data does not exist yet. It is built from the recorder's `data/raw/date=*/chain.jsonl` (open interest per strike, with Groww IV and greeks).

## Reason (written before testing)
Changes in open interest show where option writers, the larger and better-capitalised side, have put their money overnight. If writers added puts much faster than calls (rising put-call ratio), they expect support, and the day is more likely to drift up; the mirror case holds for calls. No earlier idea used positioning data.

## Rule (fixed now)
- **ΔPCR** = PCR(09:30) − PCR(previous trading day's last snapshot ≥ 15:20). PCR = total PE OI ÷ total CE OI over ATM ± 10 strikes of the nearest expiry.
- **z** = ΔPCR ÷ the SD of ΔPCR over all previous recorded days (at least 20).
- **Signal:** z ≥ +1.5 → buy NIFTY ATM CE at 09:31; z ≤ −1.5 → buy ATM PE. Nearest weekly expiry strictly after today; −30% stop; 15:10 exit; no expiry days.
  - These are the same rules as G2, but filled at the **recorded bid/ask** (not the half-spread model).
- **Control:** a random side at 09:31 on the same days.

## Data needed
- Recorded chain snapshots from 09:20–09:31 and ≥ 15:20 on consecutive trading days.
- Days with a missing snapshot are skipped and counted.

## Test date and pass bar
- **Test date:** when **60 recorded non-expiry days** with a valid ΔPCR exist (expected around January 2027). Tested **once.**
- **Pass:**
  - signals n ≥ 20 (flagged small);
  - right direction after 60 min ≥ 55% and ≥ random + 5 pts;
  - option mean net > 0 at 1× costs;
  - one-sided bootstrap P(mean ≤ 0) ≤ 0.05.
- **Pass → paper-only candidate for the owner.** Fail → P5 ends; no re-tuning of the 1.5 threshold or the strike window.

## Multiple-testing count
Phase 3's 5th and last hypothesis. 1 test, run later.
