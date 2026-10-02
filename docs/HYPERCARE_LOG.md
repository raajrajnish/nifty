# G1/G2 hypercare log

One entry per trading day: what the setups did, whether the live engine matched the rules, and anything learned. Review triggers are in `playbook/03_setups.md`. **Observations here are hypotheses, never rule changes.**

| Day | G1 | G2 | Paper P&L | Engine vs rules | Notes |
|---|---|---|---|---|---|
| 2026-10-01 (Thu) | Not today: opened outside (below PDL 22,595), but OR 22,509–22,589 **not narrow** | Not today: **not calm** (ATR14 above its 120-day median) | — | ✅ Matches the backtest code on Groww candles | Freeze day, so it is not counted in the forward test. Nifty −1.67% at the low (range 391 pts); VIX 13.5 → 14.5. Recorder ran 09:14–15:31 with 21 errors (0.04%). |

## Out-of-sample evidence (2026-10-01, discovery study)

Measured on NIFTY index data from Oct 2021 – Nov 2023, which was never used to choose G1/G2:
- **G2's direction logic holds:** end-of-day drift +0.090 ATR, 95% CI [0.001, 0.182].
- **G1's does not:** right direction after 60 min was 50% against 53% for random; the CI includes 0.

**Expectation for hypercare: G2 is the stronger candidate; G1 may underperform its backtest.** No rule change. This is context for judging the forward results.

The magnitude study (same untouched data) adds that **a narrow opening range predicts SMALLER moves.** On narrow-OR days the rest of the day was "big" only 20.7% of the time, against 46.7% on wide-OR days. G1 trades only narrow-OR days. If G1 struggles in hypercare, this is the first suspect; any fix becomes **G1.v2**, a new forward count.

## ⚠️ Backtest correction: G2's "calm day" filter had a warm-up bug (found 2026-10-02)

**What happened:** when G1/G2 were selected (logic study, 2026-10-01 12:44), the database's Nifty index history started only around late 2023.
- G2's filter "ATR14 ≤ its 120-day median" could not be computed for the early option-data days (Dec 2023 – early 2024).
- `ATR > NaN` evaluates to False, so those days were treated as **calm**.
- With the full history (from Oct 2021, downloaded later), **those days were volatile, and G2 should not have traded them.**
- Found by re-running the logic study after fixing an unrelated expiry-filter issue (the contracts table now holds Bank Nifty too).

**Corrected backtest (Dec 2023 – Sep 2026, 1 lot):**

| | Before | **Corrected** |
|---|---|---|
| G1 | 117 trades, +₹837/trade | **117, +₹833 — unchanged**, PASS and ROBUST |
| G2 | 133 trades, +₹862/trade, PF 1.73 | **114, +₹300/trade, PF 1.24**, PASS (marginal); **not ROBUST** (−₹212 without its 5 best days); 95% CI [−374, 1,001] |

- 19 of G2's removed trades were on volatile days, including some of its largest wins (20 Dec 2023, 8 Jan, 17 Jan and 23 Jan 2024).
- **G2's untouched-data check (2021–23)** also had 14 early days without a computable median. Excluding them: right direction 54.8% vs random 54.2%; move at 15:10 +0.092 ATR, **CI [−0.002, 0.191], now just touching zero.**

**The live paper engine is NOT affected:** it loads the full history from 2021, so the 120-day median is always computed. The rules are unchanged. Only the backtest *expectations* for G2 were overstated.

**Consequences:**
- G2's expected edge is about **₹300/trade, not ₹862.**
- The monthly breakdown given to the owner on 2026-10-01 overstated Dec 2023 / Jan 2024 for G2.
- The risk-study figures need re-running.
- Overall: G1 is strong in-sample but fails both independent checks; G2 is weak in-sample and only borderline out of sample. **Neither has strong evidence now.**

## Independent review (Fable 5.1, 2026-10-02): `docs/reports/2026-10-02_independent_review.md`
- **Findings:**
  - no look-ahead or fill bias that flatters G1/G2;
  - **G2's in-sample profit is not directional** (its own option +₹15 vs the opposite option −₹97 held to 15:10; the −30% stop makes the +₹300);
  - G1 and G2 are largely one bet (daily correlation 0.84 on shared days);
  - confirming either on paper needs ~130 (G1) / ~600 (G2) trades.
- **Reviewer's recommendation:** retire G2, keep G1. **Owner decision (2026-10-02): keep BOTH on paper for now.**
- **Engine fixes (owner approved; no G1/G2 rule changed):**
  1. **Finding 5:** the 15:10 exit now also fires on quote ticks, and `finish_day()` closes any trade still open when the feed or recording ends (reason `EOD_NO_DATA`), so a trade can no longer go missing from the ledger.
  2. **Finding 6:** history must end on the **previous trading day** (`config/market_holidays.yaml`); otherwise the day is skipped with a clear message. Unlisted holidays fail safe.
  - Fidelity re-check 15/15; tests 200 pass.

## Bank Nifty cross-check (2026-10-02, pre-declared: `docs/reports/2026-10-01_banknifty_g_validation.md`)

The same G1/G2 rules on Bank Nifty (never used before) **do not work**:
- **Direction, clean 2021–23:**
  - G1 43.6% right vs random 52.9%;
  - G2 51.3% vs random 52.9%.
  - Neither beats random.
- **Option P&L, Dec 2023 – Sep 2026:**
  - G1 **−₹876/trade (95% CI [−1,666, −78], reliably negative)**;
  - G2 −₹40/trade, no better than random.
- **Monthly-options period:** both negative.

**Reading:**
1. This is the **second independent check G1 fails** (after untouched Nifty 2021–23).
2. G2 holds on untouched Nifty but not on Bank Nifty.
3. As pre-declared, **this does not change the Nifty G1/G2 rules** (owner rule: each setup is judged on its own index).
4. It **raises the bar for G1 in hypercare**: if G1's forward results are weak, a stop-early review should come sooner rather than later.
5. BN-G1/BN-G2 are **rejected** as Bank Nifty setups.

## Open observations (to check over more days)

1. **The live opening range can differ by 1–2 pts from Groww's official candles.** Live 22,509.65–22,589.05 vs official 22,508.35–22,589.35 on 2026-10-01. Live bars are built from 2-second snapshots and can miss the exact extremes. **Risk:** a breakout decided by 1–2 pts could differ from the backtest. Track each G1 day; if it ever changes a decision, consider building the OR from Groww's 1-minute candles at 09:30.
2. **The index feed is unreliable after about 15:15, on 2 of 2 days.** Freezes and bad prints at 15:20–15:21 (7 ticks on 2026-10-01, 4 on 2026-09-30). G1/G2 exit by 15:10 using option prices, so they are unaffected; keep it in mind for any future rule.
3. **The pre-open book (09:14–09:15) reports bid = ask = 0.** The paper engine falls back to LTP; the analysis now counts these as `empty_book`, not crossed.
