# Stock intraday pilot (PRE-DECLARED 2026-10-01, before any stock data was downloaded or viewed)

**Instrument type:** cash-equity intraday (Groww intraday product), **long and short**. Not stock options: they have monthly expiries only, wide spreads and time decay. Paper only, like everything else. The Nifty / Bank Nifty work is unaffected.

## 1. Which stocks: fixed by rule, based on today's market (owner change, 2026-10-01, before any data)
1. **Candidates:** the **Nifty 50 members as of 30 Sep 2026**, i.e. the stocks that can be traded today. The list comes from NSE's official records and is saved in `config/stock_universe_2026-09-30.csv` before any stock price data is downloaded.
2. **Ranking:** average daily traded value (close × volume) over **1 Jul – 30 Sep 2026**, the most recent quarter.
3. **Universe:** the **top 10** by that ranking. No swaps afterwards. Stocks with less than 4 years of history on Groww (recent listings) are skipped, and the next one is taken; any such skip is recorded here.
4. **Known risk: hindsight (survivorship) bias.** Stocks that are large today are partly the ones that grew since 2021. For intraday setups (flat by the close) the effect is small. It is controlled by three of the pass rules:
   - longs and shorts must each be positive;
   - the setup must beat a same-stock random-side control, which cancels the stock's drift;
   - the latest 2 years must pass on their own.
   Each stock's buy-and-hold return over the period is also reported, to show any drift.

**The selection runs ONCE, then the list is frozen** (owner confirmation, 2026-10-01).
- The ranking rule exists only to choose the 10 by a fixed rule, not by hand. It is **not** re-run daily.
- Every setup is tied to one named stock (e.g. ST3-RELIANCE).
- Only stock-setups that pass become live paper setups.
- Stocks that no longer trade cannot go live.
- Any change to the list is a separate, pre-declared review (e.g. yearly), never automatic.

## 2. Setups: three ideas, each run as a separate setup per stock (owner rule: one setup = one instrument)
Common frame:
- One trade per setup per stock per day.
- Signals on completed 5-min bars; fill at the next minute's open.
- **Exit by 15:10 at the latest** (before the broker's automatic square-off).
- **Skip days:** the stock's quarterly-results day and the day after; days the stock is in the F&O ban list, if that data is available, otherwise this is recorded as a limitation.

| Id | Idea | Entry | Exit |
|---|---|---|---|
| **ST1** | **Opening-range breakout with Nifty in agreement** | First 5-min close beyond the stock's 15-min opening range (09:30–13:30). **Long only if Nifty is above its own 09:15 open at that bar; short only if below.** | 5-min close beyond the opposite side of the range; 15:10 |
| **ST2** | **G1 logic on the stock** | Stock opened **outside** yesterday's range **and** its 15-min opening range is narrower than its own 20-day median. First 5-min close beyond the range → that direction. | 5-min close beyond the opposite side of the range; 15:10 |
| **ST3** | **Intraday momentum (from published research)** | Return from yesterday's close to 09:45 is ≥ +0.5% → **long at 14:15**; ≤ −0.5% → **short at 14:15**. | 15:10, or a stop at 0.5 × the stock's 14-day average daily range against the entry |

The ST3 research: Gao, Han, Li & Zhou (2018), "Market Intraday Momentum". The first half-hour return predicts the last half-hour return. It is used here as a fixed rule, not tuned.

**Control:** RANDOM per stock: random entry time (09:45–13:30), random side, exit 15:10.

## 3. Costs (Groww intraday equity, applied to every trade)
- **Brokerage:** ₹20 or 0.1% per order, whichever is lower.
- **STT:** 0.025% on the sell side.
- **NSE transaction charge:** 0.00297%.
- **SEBI:** ₹10 per crore.
- **Stamp duty:** 0.003% on the buy side.
- **GST:** 18% on brokerage + exchange charges.
- **Slippage:** 0.03% per side; the robustness test doubles all costs.
- Results are reported as **net % per trade** on a fixed ₹1 lakh position (so stocks compare fairly), and in ₹.
- The exact rates are checked against Groww's published charges before running.

## 4. Test: both periods are untouched (no stock data has been looked at)
Each stock × setup pair is judged on its own data:
1. **Check 1: Oct 2021 – Sep 2024** (3 years).
2. **Check 2: Oct 2024 – Sep 2026** (the latest 2 years, the owner's preferred window).

A setup PASSES for a stock only if **both** checks pass. Each check requires:
- n ≥ 60 trades;
- net % per trade > 0;
- positive at 2× costs;
- PF ≥ 1.10;
- beats that stock's RANDOM control;
- each half of the period positive.

**ROBUST** also requires longs and shorts each positive, and still positive without the 5 best days.

**Multiple testing:** 10 stocks × 3 setups = 30 setups. About 1.5 would pass one check by luck, but only about 0.08 would pass both by luck. That is why both checks are required. A pass on one check is a lead, not a setup.

**Outcome:** a stock-setup that passes both checks and is ROBUST → **paper-only candidate**, owner decides. Then:
- the equity cost model and a stock view are added to the paper engine and UI (a new version);
- combined risk limits across Nifty, Bank Nifty and stocks are set by the owner.

## 5. Data needed (downloaded once and kept in the database)
- 1-min and daily candles, Oct 2021 – Sep 2026, for the 10 stocks: about 77 requests per stock, ~800 in total.
- Daily candles for Jul – Sep 2026, for the ranking: candidates only, 50 small requests.
- Results dates per stock: from NSE corporate announcements. Where these are unavailable, days with a gap of more than 4% are treated as event days, and this is noted.
