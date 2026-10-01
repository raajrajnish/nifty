# G1/G2 hypercare log

One entry per trading day: what the setups did, whether the live engine matched the rules, and anything learned. Review triggers are in `playbook/03_setups.md`. **Observations here are hypotheses, never rule changes.**

| Day | G1 | G2 | Paper P&L | Engine vs rules | Notes |
|---|---|---|---|---|---|
| 2026-10-01 (Thu) | Not today: opened outside (below PDL 22,595), but OR 22,509–22,589 **not narrow** | Not today: **not calm** (ATR14 above its 120-day median) | — | ✅ Matches the backtest code on Groww candles | Freeze day, so it is not counted in the forward test. Nifty −1.67% at the low (range 391 pts); VIX 13.5 → 14.5. Recorder ran 09:14–15:31 with 21 errors (0.04%). |

## Open observations (to check over more days)

1. **The live opening range can differ by 1–2 pts from Groww's official candles.** Live 22,509.65–22,589.05 vs official 22,508.35–22,589.35 on 2026-10-01. Live bars are built from 2-second snapshots and can miss the exact extremes. **Risk:** a breakout decided by 1–2 pts could differ from the backtest. Track each G1 day; if it ever changes a decision, consider building the OR from Groww's 1-minute candles at 09:30.
2. **The index feed is unreliable after about 15:15, on 2 of 2 days.** Freezes and bad prints at 15:20–15:21 (7 ticks on 2026-10-01, 4 on 2026-09-30). G1/G2 exit by 15:10 using option prices, so they are unaffected; keep it in mind for any future rule.
3. **The pre-open book (09:14–09:15) reports bid = ask = 0.** The paper engine falls back to LTP; the analysis now counts these as `empty_book`, not crossed.
