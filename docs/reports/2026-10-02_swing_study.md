# Swing trading study: Nifty 50 basket (PRE-DECLARED 2026-10-02, before any swing test was run)

**Why:** every intraday idea (≈ 80 across Nifty, Bank Nifty and stocks) failed by roughly the cost of a round trip. Holding for days to weeks makes costs a much smaller share of each trade. Paper only; G1/G2 and the daily system are untouched.

**Owner decisions (2026-10-02):**
- **Fixed-basket setups:** one rule applied to a frozen list. This is an exception to "one setup = one instrument" for swing trading, because per-stock signals are too rare to judge.
- **Universe: all 50 Nifty 50 members as of Sep 2026** (`data/universe/ind_nifty50list.csv`). Daily candles Oct 2021 – Sep 2026 are already downloaded.
- **Long only** (cash delivery). Overnight shorting isn't available in delivery.

## Data rules (same as the stock pilot)
- Split/bonus ex-dates (> 15% open-vs-close jump with a clean ratio) are back-adjusted, and the ex-date is not used as a signal day.
- A daily bar whose high/low is > 20× its close (the 2025-05-12 Groww ×100 prints) gets that field divided by 100.
- Stocks with history starting after Oct 2021 (ETERNAL 2025-04, JIOFIN 2023-08, SHRIRAMFIN 2022-12, TMPV 2025-10) join only once they have enough history for the indicators (200 days for SMA200).
- **Survivorship bias:** today's Nifty 50 members did well in hindsight. So every trade is compared with a **matched random buy**: the same stock and the same holding days, at a random entry date (seeded) in the same period. Setups must beat that, which removes the basket's general rise.

## Costs (Groww equity delivery; verify against a real contract note before any live use)
- **Brokerage:** ₹20 or 0.1% per order, whichever is lower.
- **STT:** 0.1% on buy **and** sell.
- **Stamp duty:** 0.015% on buy.
- **NSE transaction charge:** 0.00297%.
- **SEBI:** ₹10 per crore.
- **GST:** 18% on brokerage + exchange + SEBI.
- **DP charge:** ₹20 + GST per sell.
- **Slippage:** 0.05% per side.
- **Total:** ≈ 0.4% per round trip on ₹1 lakh.
- **Position:** ₹1 lakh per trade; several positions may be open at once. The maximum number of concurrent positions is reported, as it determines the capital needed.

## Setups (signals on the daily close; enter at the next day's open; close-based exits fill at the next day's open)

| Id | Idea | Entry signal | Exits (first to happen) |
|---|---|---|---|
| **SW1** | **Pullback in an uptrend** (Connors RSI-2) | Close > SMA200 **and** RSI(2) < 10 | Close > SMA5; **or** 10 trading days; **or** close < entry − 3 × ATR14 |
| **SW2** | **55-day breakout with volume** | Close > the highest close of the prior 55 days **and** volume > 1.5 × its 20-day average **and** close > SMA200 | Close < the lowest low of the prior 20 days (trailing); **or** close < entry − 2 × ATR14; **or** 60 trading days |
| **SW3** | **Monthly momentum rotation** | First trading day of each month: rank all stocks with ≥ 252 days of history by return from t−126 to t−21 (6-month momentum, skipping the last month). Hold the **top 5**, equal weight. | Sold at the next month's rebalance if no longer in the top 5 |

- One open SW1/SW2 position per stock at a time (no pyramiding).
- **SW3 benchmark:** an equal-weight portfolio of **all** eligible stocks, rebalanced monthly with the same costs. This is its matched control.

## Test: two periods, both must pass (the owner prefers the latest 2 years; the earlier period is a second check)
- **P1:** signals from Oct 2022 (after the 200-day warm-up) to Sep 2024.
- **P2:** Oct 2024 – Sep 2026.

**PASS per period (SW1, SW2):**
- n ≥ 60 trades;
- mean net % per trade > 0;
- positive at 2× costs;
- PF ≥ 1.10;
- **mean excess over the matched random buy > 0**;
- both halves of the period positive.

**PASS per period (SW3):**
- mean monthly excess return vs the equal-weight benchmark > 0, after costs;
- positive at 2× costs;
- both halves positive.

**ROBUST** (both periods combined):
- PASS in P1 and P2;
- 95% CI of the mean excess (over matched random / benchmark) above 0;
- still positive without the 5 best trades (or best months, for SW3).

**Multiple testing:** 3 setups × 2 periods. A setup must pass **both** periods. A pass in one period is a lead only.

**Outcome:** ROBUST → **paper-only swing candidate**, owner decides; a daily (end-of-day) paper process would then be built as a separate component. Otherwise → recorded as failed.

## Data problem found and fixed before the verdict (2026-10-02)
**Groww's DAILY candles are broken from 2025:**
- In 2025 the daily "open" equals the previous close on 99% of days (vs 1–9% in 2021–24).
- From late Oct 2025 the open is NULL, for every stock. Nifty, Bank Nifty and VIX daily bars are not affected.

**Fix (applied the same way to every trade; independent of results):**
- From 2025-01-01, each stock's daily OHLCV is **rebuilt from intraday bars**: 1-min for the 10 pilot stocks, 15-min (downloaded for this) for the other 40.
- Pre-2025 daily opens are kept: they match the first intraday trade (±0.05%) on **98.8–100%** of 8,815 checked days.
- 21,290 stock-days rebuilt; 40 dropped (no intraday data).
- A first run on the broken data was discarded.

**Other studies:** they all use 1-min bars, never Groww daily opens, so they are unaffected.

## Result (run 2026-10-02 13:14, `swing_20261002_1314`): NONE PASS

| Setup | Period | n | Win | Net/trade | At 2× costs | Matched random | **Excess** [95% CI] | Median hold |
|---|---|---:|---:|---:|---:|---:|---|---:|
| SW1 RSI-2 pullback | P1 | 779 | 62% | +0.22% | −0.17% | +0.01% | +0.21 [−0.08, 0.51] | 3 days |
| SW1 | P2 | 670 | 55% | −0.38% | −0.77% | −0.38% | **0.00** [−0.36, 0.36] | 3.5 |
| SW2 55-day breakout | P1 | 262 | 40% | +3.07% | +2.67% | **+4.24%** | −1.17 [−2.94, 0.79] | 30 |
| SW2 | P2 | 172 | 28% | −1.09% | −1.47% | +0.94% | **−2.02 [−3.62, −0.25]** | 22.5 |
| SW3 momentum top 5 | P1 | 23 months | — | +3.37%/month | — | bench +2.51% | +0.87%/month [−1.32, 2.98] | 1 month |
| SW3 | P2 | 23 months | — | −0.85%/month | — | bench +0.09% | −0.94%/month [−2.60, 0.77] | 1 month |

**Reading:**
1. **SW1:** a small P1 edge over random that disappears at 2× costs, and exactly zero in P2.
2. **SW2:** profitable in P1 only because the whole basket rose (random buys made even more). In P2 it is **significantly worse than random**: buying breakouts lost in 2024–26.
3. **SW3:** beat the basket in P1 (not significant), lost to it in P2.
4. Capital note: SW1/SW2 would have needed up to 32–39 simultaneous ₹1 lakh positions.

**Verdict:** the swing study failed. No swing setup goes to paper trading. The matched-random control did its job: without it, SW2's P1 +3.07%/trade would have looked like an edge.
