# G1/G2 on Bank Nifty: cross-instrument validation (PRE-DECLARED 2026-10-01, before downloading data)

**Question:** do the frozen G1/G2 rules work on an instrument they never saw? This is a **measurement only**: G1/G2 stay frozen (tag `v1-hypercare-freeze`) and we do not trade Bank Nifty.

**Rules: applied unchanged.** Every G1/G2 threshold is relative to the instrument's own history:
- open outside yesterday's range;
- opening range narrower than its own 20-day median;
- ATR14 ≤ its own 120-day median;
- −50% / −30% premium stops; 15:10 exit.

The only Bank Nifty-specific values: **strike step 100**, ATM = nearest 100. Expiry days are skipped, and the nearest expiry after today is used (whatever the exchange listed then, weekly or monthly).

> **Owner rule added 2026-10-01, before any result:** each setup belongs to ONE index. So this study now answers two separate questions:
> 1. **Nifty G1/G2:** does Bank Nifty add supporting evidence? Information only; it cannot change Nifty G1/G2.
> 2. **Candidate Bank Nifty setups "BN-G1" / "BN-G2":** do the same rules pass **on Bank Nifty's own data**?
>    - Decided by Stage A on Bank Nifty 2021-10 → 2023-11, plus Stage B on Bank Nifty options, **monthly-options period Dec 2024 – Sep 2026** (n ≥ 60, flagged as a smaller sample).
>    - The weekly period is shown for information.
>    - Passing makes them a separate paper-only candidate for Bank Nifty, with the owner's approval.

## Stage A (main verdict): direction on Bank Nifty index, Oct 2021 – Sep 2026
- Same measure and bar as the discovery study. **PASS-A** requires all of:
  - n ≥ 80;
  - right direction after 60 min ≥ 53% and ≥ random + 3 pts;
  - mean move at 15:10 (ATR units) > 0 with the 95% bootstrap CI above 0.
- Reported separately:
  - **2021-10 → 2023-11:** the cleanest evidence; no G1/G2 data from this period has ever been used, for any instrument;
  - **2023-12 → 2026-09:** overlaps the period G1/G2 were built on (Nifty);
  - the share of G-signal days that were also G-signal days on Nifty, with the same direction.

## Stage B: option P&L on Bank Nifty options, Dec 2023 – Sep 2026
- Same simulator, costs and fills. Results are reported in **R** (P&L as a multiple of the amount risked) and **% of premium**, because Bank Nifty lot sizes changed during the period. ₹ are shown at the current lot size.
- Same PASS bar as every study:
  - n ≥ 100;
  - dev, validate and test all positive;
  - positive at 2× costs;
  - PF ≥ 1.10;
  - both halves positive.
- Reported separately by expiry era: **weekly** (up to Nov 2024) and **monthly** (Bank Nifty weeklies were discontinued after that).

## Reading the result
- **PASS on Bank Nifty:** more confidence that G1/G2 capture a real market behaviour, not a fit to Nifty's history. Weighted mainly by the 2021–23 Stage A result.
- **FAIL:** a warning recorded in the hypercare log. G1/G2 are not changed or dropped because of it; the live paper test decides.
- **Caveat:** Bank Nifty and Nifty move together on most days, so the overlapping period is only partly independent evidence.

## Result (run 2026-10-02 00:33, `g_banknifty_20261002_0033`): FAIL

**Data:** Bank Nifty 1-min index Oct 2021 – Oct 2026 (1,234 days). Bank Nifty options Dec 2023 – Sep 2026: 5,210 contracts, 17.1 M candles, 0 download errors. 10 of 216 option signals had no data (mostly the last days of the window).

| Check | G1 | G2 | Random |
|---|---|---|---|
| Direction, clean 2021–23: right after 60 min | **43.6%** (n = 101) | 51.3% (n = 117) | 52.9% |
| Direction, clean: move at 15:10, ATR [CI] | +0.008 [−0.089, 0.112] | +0.045 [−0.056, 0.152] | +0.018 |
| Direction 2023–26 (info) | 49.5% / −0.032 | 53.0% / +0.033 | 46.3% / +0.019 |
| Options, all Dec 2023 – Sep 2026: ₹/trade (lot 30) [CI] | **−876 [−1,666, −78]** (n = 90) | −40 [−784, 781] (n = 116) | −131 |
| Monthly-options period (decides BN-G1/BN-G2) | −584 (n = 62), dev/val/test all negative | −125 (n = 88), dev −572 / val −2,555 / test +1,678 | −203 |
| Weekly-options period (info) | −1,523 (n = 28) | +226 (n = 28) | +35 |

**Signal overlap with Nifty (clean period):** 62% of Bank Nifty G1 days were also Nifty G1 days, but on the **same side only 46%** of the time. G2: 74% and 53%. So the two indices often qualify on the same day but disagree on direction about half the time, which supports the owner's view that they have their own moves.

**Verdict:**
1. **Nifty G1/G2: no supporting evidence from Bank Nifty.** G1 has now failed two independent checks (untouched Nifty direction, and Bank Nifty). This is recorded in the hypercare log; the rules are not changed, as pre-declared.
2. **BN-G1 / BN-G2 as Bank Nifty setups: REJECTED** (Stage A fails; options negative in the monthly period).
