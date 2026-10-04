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
