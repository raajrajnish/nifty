# Exit diagnosis for the 10 tournament candidates (DECLARED 2026-10-04, before running; MEASUREMENT ONLY)

**Owner goal:** exit trades at the right time. **Step 1 (this document)** measures, on each candidate's own historical trades, whether a different exit *could plausibly* help. **No exit rule is chosen here.** Step 2 picks a small fixed menu of exits (pre-declared) only for candidates where this shows room; step 3 runs those as extra variants next to the frozen originals in the forward tournament.

**Data:**
- **Option candidates:** Dec 2023 – Sep 2026. Every trade comes from the tournament's own scoring code (the exact frozen rules), and the instrument's 1-min path is followed from entry **to 15:10, beyond the actual exit**.
- **Swing candidates:** daily bars, from entry until 60 trading days later.

**In-sample by design:** these are the periods the strategies were found on. That's fine for a diagnosis, never for choosing a rule.

## Measured per candidate
1. **Excursions** (as % of entry premium, or of stock price):
   - **MFE**: best point in our favour before the actual exit;
   - **MAE**: worst point against us before the actual exit;
   - medians, and the share of trades with MFE ≥ +20% / +50% (options) or ≥ +1% / +3% (stocks).
2. **Capture:** final net vs MFE, i.e. how much of the best point the frozen exit kept (winners and all trades).
3. **Winners that turned into losers:** the share of losing trades whose MFE first reached ≥ +20% (options) / ≥ +1% (stocks).
4. **When the best point happens:**
   - intraday: the clock-time distribution of the MFE (30-min buckets);
   - swing: trading days to the MFE.
5. **Fixed-time exit profile (intraday):** average net % if *every* trade were closed at 10:30, 11:30, 12:30, 13:30, 14:30 or 15:10, after the same costs. This shows whether holding to 15:10 pays or just feeds time decay.
6. **Stop regret:** for trades that hit their stop or thesis exit, the share that would have finished above the entry price at 15:10 (intraday) or after 10 / 20 days (swing).

**Reading rule (fixed now):** a candidate shows **room for a better exit** if any of these hold:
- (a) losers that were first up ≥ +20% make up ≥ 30% of losers;
- (b) some fixed exit time beats 15:10 by ≥ 5 percentage points of premium on average;
- (c) stop regret ≥ 40%.

Otherwise its frozen exit is left alone.

## Result (run 2026-10-04, `exit_diag_20261004_*`; 2,961 historical trades, Dec 2023 – Sep 2026)
- **Bug found and fixed before reading BSE:** the first run followed BSE's raw prices against split-adjusted entries (BSE bonus 2022/2025), giving an impossible −12.7% average. The re-run uses the same adjusted, cleaned prices the strategy uses. The other 9 candidates were unaffected.

**Average net % of premium if EVERY trade were closed at that time** (options; costs included):

| | 10:30 | 11:30 | 12:30 | 13:30 | 14:30 | 15:10 | Winners' best point by 12:30 / 14:30 |
|---|---:|---:|---:|---:|---:|---:|---|
| G1 (n = 117) | +0.6 | +3.3 | +6.8 | +9.9 | +13.5 | **+15.4** | 15% / 68% |
| G2 (114) | −2.0 | −3.0 | −2.7 | +0.3 | **+3.3** | +0.8 | 22% / 73% |
| P4 (88) | +2.3 | +3.0 | +7.6 | +4.5 | +6.4 | **+9.1** | 12% / 47% |
| CPR (194) | −1.3 | −2.6 | −0.9 | −2.3 | +0.3 | **+1.1** | 30% / 56% |
| HL1 (390) | +0.3 | +0.7 | +1.7 | +2.1 | **+2.4** | +1.9 | 25% / 65% |
| FIB71 (30) | — | — | +0.4 | +0.7 | +7.7 | **+11.7** | 9% / 91% |
| R6 short straddle (147) | — | — | — | (14:00 +3.1) | +8.7 | **+17.2** | — |
| BSE stock % (521) | −0.1 | −0.2 | −0.1 | −0.1 | 0.0 | +0.1 | 19% / 49% |

**Swing** (average net % if held N days): SW1 3d −0.2, 5d +0.1, 10d +0.5, 20d +0.7. SW2 3d −0.5, 5d −0.4, 10d −0.1, 20d +0.6.

| Candidate | Losers that were first up ≥ 20% (options) / ≥ 1% (stocks) | Stop regret | **Room (declared rule)** |
|---|---:|---:|---|
| G1 | 36% | 15% | **(a)** |
| G2 | 26% | 8% | none |
| P4 | 34% | 19% | **(a)** |
| CPR | 33% | 18% | **(a)** |
| HL1 | 20% | 0% | none |
| FIB71 | 14% | 0% (6 stops) | none (n = 30) |
| R6 | 64% (the straddle was in profit first) | 28% | **(a)** |
| BSE | 12% | 5% | none |
| SW1 | 42% | 7% | **(a)** (a +1% move is a low bar for stocks) |
| SW2 | 73% | 39% | **(a)**; stop regret just under the 40% bar |

**Reading:**
1. **"Exit earlier" is not supported** for the option candidates. Average results rise into the afternoon, and winners mostly peak after 13:00. Holding to 15:10 is right for G1, P4, CPR, FIB71 and R6. G2 and HL1 are marginally better at 14:30, but by less than the 5-point bar.
2. **The room that does show up is "give-back":** trades that were well in profit and ended as losers (G1, P4, CPR, R6; SW1/SW2 for stocks). The matching exit family is a **lock-in / trailing rule that activates only after a large gain**, not an earlier time exit and not a tighter stop.
3. **Caution:** option premiums move ±20% routinely, so measure (a) is noisy. Any variant must prove itself forward.
