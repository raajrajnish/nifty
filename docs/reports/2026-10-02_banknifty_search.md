# Bank Nifty setup search (PRE-DECLARED 2026-10-02, owner approved)

**Goal:** find Bank Nifty-only setups using the same depth of work as the Nifty search: entry study → stop/exit study → direction logic → shortlist. Owner rule: a Bank Nifty setup is judged on Bank Nifty data only.

**Lesson from Nifty:** G1/G2 were searched for and chosen on the same data, and G1 failed both later independent checks. So the evaluation data is **locked before the search starts.**

## Data split (fixed now; nothing below is looked at early)

| Data | Role |
|---|---|
| **Search:** Bank Nifty options **Dec 2023 – Sep 2025** (weekly options to 2024-11-20, monthly after) | All searching, comparing and choosing. Every step's report is restricted to this window, and the code refuses later dates. |
| **Lock box 1:** Bank Nifty options **Oct 2025 – Sep 2026** (monthly options; how Bank Nifty trades today) | Opened **once**, for the final ≤3 candidates. |
| **Lock box 2:** Bank Nifty index **Nov 2021 – Nov 2023** (direction) | Opened **once**, for the same candidates. It was previously used only for G1/G2 and the inside-day ideas, never for any idea from this search. |

**Final pass rules (when the lock boxes are opened):**
- **Lock box 2:** PASS-A as in every study:
  - n ≥ 80;
  - right direction after 60 min ≥ 53% and ≥ random + 3 pts;
  - move at 15:10 (ATR units) > 0 with the CI above 0.
- **Lock box 1:** n ≥ 40 (12 months only, flagged as a small sample); net/trade > 0; positive at 2× costs; PF ≥ 1.10; beats RANDOM in the same window; both halves (6 months each) positive.
- **Both** must pass → a Bank Nifty paper-trading candidate, with owner approval.
- A failure is final for that candidate on this data.

## Common simulation settings
- Bank Nifty strike step 100; ATM from the index close before the signal; nearest expiry after today (weekly or monthly, whatever was listed). No expiry days.
- Same simulator, fills (half-spread), pessimistic stops and Groww charges as Nifty.
- ₹ at **lot 30** for comparability (the real lot size changed during the period). Results are also reported in R (multiples of the amount risked).
- Day features (volatility, opening-range width, trend) use only past data, with **unknown values never counted as "calm" or "narrow"** (the warm-up fix from 2026-10-02). Bank Nifty history starts Oct 2021, so all medians are fully formed by Dec 2023.

## Step 1: entry study (this document; the same design as Nifty study #2)
- **Entries (7):** ORB-15, ORB-30, TWAP pullback, EMA 9/21 cross, gap-and-go, gap-fade, random control. Definitions are identical to `sim/entry_study.py`; one per day.
- **Exits (2, fixed):**
  - no-progress (exit if +0.5R isn't reached within 30 min), −30% stop, 15:10;
  - hold: −30% stop, 15:10.
- **Filters (16):** the same list as the Nifty entry study: volatility, opening-range width, gap, time, pre-expiry, trend 20/50, and two combinations.
- **Cell PASS** (as for Nifty):
  - n ≥ 100;
  - dev, validate and test (60/20/20 within the search window) all positive;
  - positive at 2× costs;
  - PF ≥ 1.10;
  - both halves positive.
  **ROBUST** = PASS plus CE and PE each positive, plus still positive without the 5 best days.
### Step 1 result (run 2026-10-02 11:14, `bn_search_entries_20261002_1114`): 0 of 216 cells PASS

- 3,756 simulated trades; 25 signals had no option data.
- **No cell passes, and none is ROBUST.** Fewer than the ~11 expected by chance, so this is not a near miss.
- The best-looking cells (EMA cross with the 20-day trend +₹528; TWAP pullback on wide-OR days +₹429) all have a **negative validate period and a weak second half.**

**Key finding: Bank Nifty weekly and monthly options are different products for an intraday buyer** (held to 15:10, ₹ per trade at lot 30):

| Entry | Weekly period (to Nov 2024) | Monthly period (Dec 2024 – Sep 2025) |
|---|---:|---:|
| TWAP pullback | +535 (n = 176) | −426 (n = 196) |
| EMA 9/21 cross | −156 | −306 |
| ORB-15 / ORB-30 | −202 / −123 | −1,054 / −1,005 |
| Random | +34 | −127 |
| Median premium / days to expiry | ₹330 / 3 days | ₹602 / 15 days |

**Reading:**
- A monthly option bought intraday costs about twice as much, so the same index move gives a much smaller percentage gain.
- The −30% premium stop and the hold-to-15:10 exit (designed on Nifty weeklies) don't suit it. Opening-range breakouts lose about ₹1,000 a trade.
- **Only the monthly product can be traded today,** and the search window contains only ~10 months of it (Dec 2024 – Sep 2025).

- **The output of step 1 is a ranking, not a decision.** The best cells move to step 2 (stops/exits) and step 3 (direction logic). With 7 × 2 × 16 = 224 cells, about 11 would pass by chance at a 5% level. That is why nothing is chosen until the lock boxes.
