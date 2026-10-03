# Round 2: research-based strategies on 2024 → Sep 2026 (PRE-DECLARED 2026-10-03, before any code or data)

**Owner request:** new strategies, not ones already discussed, drawn from reliable sources, tested on data from 2024 to date, then one combined list with a verdict on what to focus on.

**Selection rule:** only effects documented in peer-reviewed finance research and not yet tested in this project. Sources are named from the model's training knowledge (not re-fetched); the owner can check them. Ideas needing data we don't hold (results dates → post-earnings drift; futures; OI history) are excluded and listed at the end.

| Id | Effect (source) | Rule (fixed; no tuning) | Instrument | Comparison |
|---|---|---|---|---|
| **R1** | **Overnight drift:** equity-index gains accrue mostly overnight, not intraday (Cliff, Cooper & Gulen 2008; Kelly & Clark 2011; also reported for Indian indices) | Every non-expiry day: **buy the ATM Nifty CE at 15:20**, sell at the **next trading day's 09:20** open. Nearest weekly expiry. | Nifty options | The same trade with the ATM **PE** (the opposite bet); the index close → next-open move reported too |
| **R2** | **Turn of the month:** returns cluster from the last trading day to the first 3 days of the month (Ariel 1987; Lakonishok & Smidt 1988; found in India in several studies) | **Buy all Nifty 50 stocks equal-weight** (₹1 lakh each, delivery) at the **open of the last trading day** of the month; sell at the **close of the 3rd trading day** of the new month | Nifty 50 basket (cash) | The same basket over all other 4-day windows (non-turn-of-month) |
| **R4** | **Intraday momentum, index level:** the first half-hour's return predicts the last half-hour's (Gao, Han, Li & Zhou 2018, *J. Financial Economics*). Tested earlier only on stocks (ST3), never on Nifty | Return from yesterday's close to 09:45 ≥ +0.25% → **buy ATM CE at 14:40**; ≤ −0.25% → **buy ATM PE at 14:40**. Exit **15:10**. No expiry days. | Nifty options | Random-side entries at 14:40 on the same days |
| **R5** | **Short-term reversal:** last week's biggest losers outperform next week (Jegadeesh 1990; Lehmann 1990) | Each week, at the last trading day's close: **buy the 5 Nifty 50 stocks with the worst 5-day return**, equal weight; sell at the next week's last close. Full delivery costs on every change. | Nifty 50 stocks (cash) | Equal-weight all 50 over the same week |
| **R6** | **Volatility risk premium:** options are priced above the volatility that follows, so option **sellers** earn a premium on average, with crash risk (Bakshi & Kapadia 2003; Carr & Wu 2009). Fable's Phase 3 measured +₹540/trade for selling expiry-afternoon straddles (no stop) | **RESEARCH ONLY (selling; the system is buy-only):** on Nifty expiry days, **sell the ATM straddle at 13:30**. Buy it back at **15:10**, or earlier if the straddle's value (sum of 1-min closes) reaches **1.5× the credit** (exit at the next minute's open). Costs with a **doubled half-spread** (0.22% per side; expiry-day spreads are wider). | Nifty options | — (judged on its own; tail risk reported: worst trade, worst week) |

The pre-holiday effect (Ariel 1990) was considered but excluded: about 10 occurrences per half-period is too few to judge.

## Test
- **Data:** Nifty 1-min index and options (lot 65); Nifty 50 daily bars (2025+ rebuilt from intraday, per the swing-study data fix). Groww charges, half-spread 0.11% per side (R6: 0.22%), delivery costs for stocks.
- **Two halves, both must pass:** **H-A = 2024-01-01 → 2025-06-30**, **H-B = 2025-07-01 → 2026-09-30**.
- **PASS in each half:**
  - n ≥ 30 trades (R2: n ≥ 12 months, flagged as a small sample);
  - mean net > 0;
  - positive at 2× costs;
  - PF ≥ 1.10;
  - beats its comparison.
- **ROBUST:** PASS in both halves, and the 95% bootstrap CI of the mean net (both halves together) is above 0.
- **Multiple testing:** 5 strategies × 2 halves. About 0.25 would pass both halves at 5% by chance. A pass in one half only is a **lead**.
- **Owner caveat:** this period overlaps data already used (G1/G2 and the Phase 3 design work), so it is not untouched. That is why both halves must pass and the rules are fixed. Any winner still goes to **paper trading first**.

## Deliverable
Results per strategy, then one **combined list** (everything tested so far plus these), with a verdict on what to focus on.

## Excluded (data not held)
- post-earnings announcement drift (needs results dates);
- futures basis / roll;
- option open interest (P5 is recording it);
- FII/DII flow effects.

## Result (run 2026-10-03 23:17, `round2_20261003_2317`; code committed before the run): NONE ROBUST

| Strategy | H-A (Jan 2024 – Jun 2025) | H-B (Jul 2025 – Sep 2026) | Verdict |
|---|---|---|---|
| **R1** overnight, buy CE 15:20 → 09:20 | n = 291, **−₹103**/trade (PE −₹273). The index did rise overnight (+24.6 pts avg) but the option lost: spread and an overnight day of decay | n = 241, **−₹1,028**/trade (CI < 0); index −1.0 pt overnight | ❌ The effect exists in the index in H-A, but options can't capture it |
| **R2** turn of the month, Nifty 50 basket | 17 windows, −0.03% (control −0.17%) | 13 windows, +0.07%, fails at 2× costs (control −0.47%) | ❌ Beats other weeks slightly, but doesn't pay for delivery costs |
| **R4** Nifty intraday momentum 14:40 → 15:10 | n = 150, **−₹387**/trade (CI < 0; random −₹217) | n = 139, −₹81 (random −₹152) | ❌ |
| **R5** weekly reversal, 5 worst losers | 77 weeks, +0.07%/week vs basket +0.38% | 63 weeks, −0.20% vs +0.00% | ❌ Worse than simply holding all 50 |
| **R6** sell expiry straddle 13:30, 1.5× stop (**research only**) | n = 78, **+₹343**/trade, PF 1.35, 23 stops: **PASS** | n = 65, +₹31, **−₹93 at 2× costs**: FAIL | ⚠️ **Lead only** (one half). Worst trade −₹5,671; worst 5-trade run −₹10,538 |

**Reading:**
1. Nothing is robust.
2. **R6, option selling (the volatility risk premium), is the only idea with a sound economic reason AND a positive result,** but the edge shrank in H-B and doesn't survive doubled costs. Selling is outside the buy-only system and is an owner decision.
3. **R1 shows a useful general lesson:** an effect can be real in the index (overnight drift, H-A) and still impossible to capture by buying options, because spreads and decay eat it.
