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

## Change of direction (owner, 2026-10-02): find Bank Nifty's OWN setups

Step 1 (below) only re-tested the Nifty entry catalogue on Bank Nifty. The owner asked for setups **derived from Bank Nifty's own behaviour.** New order:
1. **Step B1: behaviour study.** Measurement only, no trading rules, search window only.
2. **Step B2:** turn the strongest *measured* behaviours into ≤5 Bank Nifty hypotheses, pre-declared, including exits designed for **monthly** options.
3. **Step B3:** test them in the search window.
4. **Step B4:** open the lock boxes once for the ≤3 best.

### Step B1: what is measured (declared before running), Bank Nifty Dec 2023 – Sep 2025
1. **Time of day:**
   - when the day's high and low are made (30-min slots);
   - average absolute move per slot (ATR units);
   - does a slot's direction carry on into the next slot, or reverse? (trend vs mean-reversion by time of day)
2. **Opening behaviour:**
   - does the first-hour direction (09:15 → 10:15) persist to 15:10, split by size of first-hour move (terciles)?
   - gap size buckets: how often the gap fills by 15:10, and how often it continues.
3. **Day types:**
   - how often trend days happen (|close − open| ≥ 0.6 × day range);
   - what known-before-10:15 conditions make them more likely: prior-day narrow range (NR7), open outside yesterday's range, gap size, VIX level, first-hour range.
4. **Bank Nifty vs Nifty (relative strength):** at 10:15, Bank Nifty's move minus Nifty's move since yesterday's close. Does the sign predict Bank Nifty's move to 15:10?
5. **Monthly options economics:**
   - for ATM monthly options bought intraday, how the premium responds to the index move (effective delta) and how much it decays per hour;
   - **the index move (in points and ATR units) needed just to break even after costs**, weekly vs monthly.
   - This sets the minimum move any Bank Nifty setup must target.

**Each measurement reports a 95% CI where relevant, plus the same statistic for random times/days.** Only effects with a CI clear of the random baseline become hypotheses in step B2. Not measured yet (data not held): heavyweight-stock lead (HDFC Bank, ICICI Bank), and RBI-policy and bank-results days. Those can be added after the stock data is downloaded.

### Step B1 result (2026-10-02, search window, 455 days)
1. **Time of day:** U-shaped.
   - The day's high/low is made in the first 30 min on ~29% of days and in the last 30 min on ~16%; midday is quiet (~0.10 ATR per 30 min).
   - **No 30-min momentum anywhere.** The next slot goes the same way 41–53% of the time.
   - Slight reversal tendencies at 09:15–09:30 (46.6%) and 14:00–15:30 (41–45%). Tiny (≤0.02 ATR); the only significant one is after 15:00.
2. **Opening:**
   - The first-hour direction does **not** persist (+0.004 ATR [−0.048, 0.059]), whatever its size.
   - Gaps < 0.2% fill 90% of the time, 0.2–0.5% fill 71%, 0.5–1% fill 46%, > 1% fill 9%. (No baseline yet; see the B1 addendum.)
3. **Trend days:** 32.5% of days. Nothing known by 10:15 changes this significantly. A wide first hour (> 0.6 ATR) gives 39.4% [32.4, 46.3] vs 32.5% overall: overlapping, a weak lead.
4. **Relative strength vs Nifty at 10:15:** trading in its direction gives +0.044 ATR [−0.041, 0.133]. Not significant.
5. **Monthly options economics (key):**
   - ATM monthly bought at 10:00 and sold at 15:10 loses only ~11 premium pts to decay (premium ₹609, delta 0.46).
   - **Break-even index move ≈ 30 pts**, against a median |move| of 166 pts.
   - **Monthly options are cheap to hold intraday.** Step 1's monthly losses therefore came from **direction**, not decay: ORB-15/30 lost ≈ 35 premium pts per trade ≈ 75 index pts *against* the breakout.

**Reading:** Bank Nifty in this window looks **mean-reverting, not trending**, at the intraday scale. The evidence: no momentum, the first hour doesn't persist, and breakouts fail.

### Step B1 addendum (declared before running): two direct measurements
- **(a) Breakout follow-through:** after the first 5-min close beyond the 15-min and 30-min opening range (09:30/09:45 – 13:30), the index move in the breakout direction at +60 min and at 15:10 (ATR units, 95% CI). Random times as the baseline.
- **(b) Gap fill vs a fair baseline:** for each gap bucket, how often the index touches yesterday's close by 15:10, versus how often it touches the level the same distance on the *other* side of the open (continuation). Fill ≫ continuation means a real pull back towards yesterday's close.

**Addendum results:**
- **(a) Breakouts are a coin flip, not a reversal.** ORB-15: 47.9% right at +60 min, 15:10 move −0.006 ATR [−0.068, 0.057]. ORB-30: 50.0%, −0.012. Random: 47.9%, +0.038.
- **(b) Real pull back to yesterday's close for medium gaps:**

  | Gap | Fill | Same-distance continuation |
  |---|---:|---:|
  | 0.2–0.5% (n = 125) | **71%** | 55% |
  | 0.5–1% (n = 59) | **44%** | 27% |
  | < 0.2% | 91% | 89% (no difference) |
  | > 1% | 10% | 14% (no difference) |

- **Open question:** with zero index edge, ORB monthly-option trades lost ≈ 35 premium pts per trade. The 10:00 decay measurement predicts only ≈ 14 (decay + costs).

### Step B1 addendum 2 (declared before running): does the time of buying matter?
- **(c)** ATM monthly-period options bought at **09:20, 09:35, 10:00, 11:00, 12:00 and 13:00**, sold at 15:10, every non-expiry day.
- For each entry time: effective delta, the decay intercept (premium pts lost with zero index move), and the break-even index move.
- Same for the weekly period, for comparison.
- Hypothesis being measured: options bought in the first 30–45 minutes carry a premium that deflates during the day.

**Addendum 2 result: buying time barely matters for monthly options.**

| Buy at | 09:20 | 09:35 | 10:00 | 11:00 | 12:00 | 13:00 |
|---|---:|---:|---:|---:|---:|---:|
| Decay to 15:10 (pts, premium ≈ ₹610) | −11.8 | −11.4 | −10.8 | −8.8 | −6.1 | −4.9 |
| Break-even index move (pts) | 32 | 31 | 30 | 25 | 20 | 17 |

- Delta is ≈ 0.47 at every time. **Early-morning options are not overpriced**, so the hypothesis is rejected.
- The ORB monthly loss is therefore ordinary direction noise in that sub-period (index edge ≈ 0; the standard error is about ±7 premium pts per trade), not a structural effect.

### Step B1 conclusions (what Bank Nifty's own behaviour offers)
1. **Requirement for any Bank Nifty monthly setup:** a directional edge of **> ~30 index pts (≈ 0.05 ATR) by 15:10.** Below that, decay plus costs eat it. Holding all day is cheap (≈ 2% of premium).
2. **The one measured Bank Nifty-specific effect:** a pull back to yesterday's close after **medium gaps (0.2–1.0%)**. Fill 71% vs 55% continuation (0.2–0.5%), and 44% vs 27% (0.5–1%).
3. **Not present:** intraday momentum, first-hour persistence, breakout follow-through, relative-strength edge, or predictable trend days.
4. **Not yet measurable:** heavyweight-stock lead (HDFC Bank and ICICI Bank are ≈ 50% of the index), and RBI-policy and bank-results days. These need the stock data and event dates.

## Step B2: Bank Nifty gap-fill hypotheses (PRE-DECLARED 2026-10-02, before any test of them)

Built on the one Bank Nifty-specific effect measured in B1: after a medium gap, the index is pulled back towards yesterday's close (PC).

**Common rules:**
- **Gap** = (09:15 open − PC) / PC.
- Trade **towards PC**: a gap up → buy PE, a gap down → buy CE.
- ATM monthly/weekly option (the nearest expiry); no expiry days; one trade per variant per day.
- **Target:** the first index 1-min close at or beyond PC; exit at the next minute's open.
- −50% premium disaster stop; time exit 15:10.
- **If the gap has already filled before entry, there is no trade.**

| Id | Gap size | Entry | Stop (index) |
|---|---|---|---|
| **GF1: open fade** | 0.2–1.0% | **09:20** (after the first 5 minutes) | 1-min close beyond **open ± 1 × gap distance**, i.e. the gap doubles away from PC |
| **GF2: confirmed fade** | 0.2–1.0% | **09:30**, only if the 09:15–09:30 bar **closed on the PC side of the open** (the move towards the fill has started) | 5-min close beyond that first 15-min bar's extreme on the gap side |
| **GF3: open fade, strongest bucket** | **0.2–0.5%** only | as GF1 | as GF1 |

**Control:** RANDOM_gap. Same gap days (0.2–1.0%), entry at 09:20, random side (seeded per day), −50% stop, 15:10.

### Step B3: test on the search window only (Dec 2023 – Sep 2025; ₹ at lot 30)
**Advance to the lock boxes** if all of these hold:
- n ≥ 60;
- net/trade > 0;
- positive at 2× costs;
- PF ≥ 1.10;
- **positive in the monthly-options period** (the product traded today);
- both halves positive;
- beats RANDOM_gap.

At most **2** variants advance, the best by monthly-period net per trade. GF3 is a subset of GF1, so if both pass, only the better one advances.

**Lock boxes** (rules already fixed above):
- **Lock box 1:** options Oct 2025 – Sep 2026, n ≥ 40.
- **Lock box 2:** index direction Nov 2021 – Nov 2023, PASS-A with n ≥ 80.

### Step B3 result (run 2026-10-02 12:10, `bn_search_gapfill_20261002_1210`): NONE ADVANCE; the lock boxes stay sealed

| Variant | n | Win | Net ₹/trade | Monthly period | Weekly period | Filled / stopped / 15:10 |
|---|---:|---:|---:|---:|---:|---|
| GF1 open fade | 147 | 46% | **−411** | −818 | −9 | 60 / 51 / 27 |
| GF2 confirmed fade | 64 | 53% | −99 | −502 | +235 | 32 / 26 / 6 |
| GF3 open fade, 0.2–0.5% | 89 | 44% | **−605** (CI entirely < 0) | −1,044 | −213 | 40 / 39 / 8 |
| RANDOM_gap | 182 | 33% | −543 | −692 | −399 | — |

**Why the measured pull did not pay:**
- B1 counted "touches yesterday's close at any time by 15:10". A tradeable version needs the fill **before the stop.**
- With a stop at the gap doubling, 35% of GF1 trades were stopped first, and filled trades earned less than stopped trades lost.
- Calls (fading gap-downs) were the worst: −₹1,241/trade.
- The monthly period, the product traded today, is negative for every variant.
- **Verdict: rejected.** The rules are not re-tuned on the same data, so "a wider stop" is not tried here.

### Bank Nifty status after B1–B3
**No Bank Nifty-specific setup found yet.** Bank Nifty showed no exploitable intraday direction in the search window: no momentum, no persistence, breakouts are coin flips, and the gap pull doesn't survive a stop.

**Remaining Bank Nifty-specific idea:** the heavyweight lead (HDFC Bank / ICICI Bank ≈ 50% of the index). It needs their 1-min data, which comes with the stock pilot. The lock boxes stay sealed for that.

## Step B5: heavyweight lead (PRE-DECLARED 2026-10-02, before looking at any HDFC Bank/ICICI Bank vs Bank Nifty data)

**Idea (Bank Nifty-specific):** HDFC Bank and ICICI Bank are about half of Bank Nifty. When they have moved **more** than Bank Nifty over the last 30 minutes, the rest of the index catches up, so **Bank Nifty follows the heavyweights.**

**Hypothesis direction is fixed:** follow the heavyweights. If the data shows the opposite (Bank Nifty reverts towards them), that is recorded as a *new* hypothesis needing its own test. The sign is **not** flipped on the same data.

**Signal (5-min bars labelled by end time, 09:45–13:30; first signal of the day; no expiry days):**
- Basket return = the average of HDFCBANK and ICICIBANK % returns over the last 30 min.
- D = basket return − Bank Nifty % return over the same 30 min.
- **D ≥ +0.25% → Bank Nifty CE; D ≤ −0.25% → Bank Nifty PE.**
- Stock data cleaning: the 2025-05-12 ×100 prints are repaired and that day is excluded. Split ex-dates are excluded (30-min returns are otherwise unaffected).

| Id | Exit |
|---|---|
| **HL1** | Hold to 15:10; −50% premium disaster stop |
| **HL2** | Exit after **60 minutes** (lead-lag effects are usually short); −50% disaster stop |

**Control:** RANDOM: the same days, random 5-min bar in 09:45–13:30, random side.

**Search-window tests (Dec 2023 – Sep 2025):**
- **Direction:**
  - n ≥ 80;
  - right after 60 min ≥ random + 3 pts;
  - mean move in ATR units > 0 with the CI above 0 (at +60 min for HL2; at 15:10 for HL1).
- **Option P&L (lot 30):**
  - n ≥ 60;
  - net > 0;
  - positive at 2× costs;
  - PF ≥ 1.10;
  - monthly period positive;
  - beats RANDOM.
- Pass both → go to the lock boxes (rules already fixed above). **Lock box 2** uses HDFC Bank/ICICI Bank/Bank Nifty data from Nov 2021 – Nov 2023, which is held.

### Step B5 result (run 2026-10-02 12:53, `bn_search_heavy_20261002_1253`): FAIL; the lock boxes stay sealed

**Direction:**
- HEAVY: n = 222; right after 60 min **47.7%, identical to random (47.7%)**; move at +60 min −0.014 ATR; at 15:10 +0.035 [−0.055, 0.118] vs random +0.036.
- **No lead effect at all.** When the heavyweights pull ahead, Bank Nifty does not follow (and does not clearly revert either).

**Options:**
- **HL1:** +₹285/trade overall (PF 1.15). But validate −108, test −202, and the **monthly period −₹299**, so it fails.
- **HL2:** −₹163.
- **Random:** −₹98.

## Bank Nifty search: conclusion (2026-10-02)
Five Bank Nifty-specific lines were tested on the search window only, with the lock boxes never opened:
1. Nifty's entry catalogue (step 1);
2. own-behaviour measurement (B1);
3. gap fill (B2/B3);
4. option-timing economics (B1 addendum);
5. heavyweight lead (B5).

**No Bank Nifty intraday setup qualifies.** What was learned and remains useful:
- Monthly options are cheap to hold intraday (≈ 2% decay; break-even ≈ 30 index pts).
- Bank Nifty showed no intraday momentum, no first-hour persistence, coin-flip breakouts, a gap pull that doesn't survive a stop, and no heavyweight lead.

**The lock boxes (Oct 2025 – Sep 2026 options; 2021–23 index) remain unused** and available for any future pre-declared Bank Nifty idea.

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
