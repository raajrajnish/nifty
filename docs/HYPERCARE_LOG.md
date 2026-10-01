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

## Open observations (to check over more days)

1. **The live opening range can differ by 1–2 pts from Groww's official candles.** Live 22,509.65–22,589.05 vs official 22,508.35–22,589.35 on 2026-10-01. Live bars are built from 2-second snapshots and can miss the exact extremes. **Risk:** a breakout decided by 1–2 pts could differ from the backtest. Track each G1 day; if it ever changes a decision, consider building the OR from Groww's 1-minute candles at 09:30.
2. **The index feed is unreliable after about 15:15, on 2 of 2 days.** Freezes and bad prints at 15:20–15:21 (7 ticks on 2026-10-01, 4 on 2026-09-30). G1/G2 exit by 15:10 using option prices, so they are unaffected; keep it in mind for any future rule.
3. **The pre-open book (09:14–09:15) reports bid = ask = 0.** The paper engine falls back to LTP; the analysis now counts these as `empty_book`, not crossed.
