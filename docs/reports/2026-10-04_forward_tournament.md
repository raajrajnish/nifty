# Forward tournament: 10 candidate strategies + LLM take/skip with structured reasons (PRE-DECLARED 2026-10-04)

**Owner decision (2026-10-03):** put the 10 leads into paper mode on **new days only**. An LLM says TAKE or SKIP for each signal and records **why** in a structured form, so the relationship between its reasons and the outcomes can be measured later. Then decide.

## Rules of the tournament
- **Frozen strategies:** each candidate's rule is the exact code of the study that produced it (listed below). No parameter, filter or exit changes during the tournament; a changed rule gets a new name and starts from zero.
- **Forward days only:** the first counted day is **Mon 2026-10-05**. The scoreboard never includes earlier days.
- **Paper only:** no orders. R6 is an option-*selling* strategy, tracked as research only; the live system stays buy-only.
- **Every signal is taken on paper,** whatever the LLM says. The LLM's TAKE/SKIP is recorded **before** the outcome is known, and evaluated later.
- **Scoring:** every evening, after End of Day downloads the official 1-min data, each candidate is scored with its study's own simulator, costs and fills (lot 65 Nifty / 30 Bank Nifty; ₹1 lakh per stock trade).

## The 10 candidates (frozen)

| Id | Strategy | Frozen code (signal + exit) | Instrument | Backtest reference |
|---|---|---|---|---|
| G1 | Narrow-OR breakout, open-outside day | live paper engine + `discovery_study.g1_signal` / `stop_study.rule_or_opposite`, −50% stop | Nifty weekly options | +₹833/trade (2023-12..2026-09) |
| G2 | TWAP pullback, calm open-outside day | live paper engine + `discovery_study.g2_signal`, −30% stop, hold | Nifty weekly options | +₹300/trade |
| P4 | Nifty catches up after a Bank Nifty divergence (\|z\| ≥ 2) | `phase3.p4_rel` / `p4_signals`, ATM option, −30% stop, hold to 15:10 | Nifty weekly options | +₹1,140/trade (fragile) |
| SW2 | 55-day breakout with volume, close > SMA200 | `swing_study.sw2_signal` / `sw2_exit` | Nifty 50 stocks, delivery, long | +3.07%/trade (P1); P2 below random |
| FIB71 | Fib 0.71 recovery after a ≥ 135-pt fall, 12:00–13:30, calls only | `internet_study.p5_fib71` / `rule_fib` | Nifty weekly options | +₹769/trade (n = 23) |
| R6 | Sell the ATM straddle 13:30 on expiry day, 1.5× stop (**research only**) | `round2.short_straddle_path` | Nifty options (expiry day) | +₹343 (H-A), +₹31 (H-B) |
| CPR | Narrow CPR breakout | `popular_study.k1_cpr`, `rule_or_opposite`, −50% stop | Nifty weekly options | positive 2023–26 only |
| HL1 | HDFC Bank + ICICI Bank lead → Bank Nifty | `bn_heavy.heavy_signal`, hold to 15:10, −50% | Bank Nifty monthly options | +₹285/trade |
| BSE | 15-min ORB with Nifty agreeing, on BSE Ltd | `stock_study.st1_orb_with_nifty` | BSE stock, intraday, long/short | +0.16%/trade (P2 only) |
| SW1 | RSI-2 pullback above SMA200 | `swing_study.sw1_signal` / `sw1_exit` | Nifty 50 stocks, delivery, long | +0.22%/trade (P1 only) |

## LLM verdict per signal (shadow; prompt version v2, Claude Sonnet 5.5, cap ₹1,000/month)
- **Intraday candidates** (G1, G2, P4, FIB71, R6, CPR, HL1, BSE): signals are detected **live** from recorder prices, and the LLM is asked at the signal time.
- **Swing candidates** (SW1, SW2): signals are known at the close; the LLM is asked that evening, before the next day's entry.
- **Morning:** one "risk of the day" note.
- **Structured output** (for later statistics), on top of the free-text reasons:
  - `decision` TAKE/SKIP and `confidence` 0–1;
  - **`reason_tags`** from a fixed list: NO_SPECIFIC_RISK, SCHEDULED_EVENT_TODAY, SCHEDULED_EVENT_SOON, NEWS_SUPPORTS_TRADE, NEWS_AGAINST_TRADE, GLOBAL_CUES_SUPPORT, GLOBAL_CUES_AGAINST, HIGH_VOLATILITY, LOW_VOLATILITY, TREND_SUPPORTS, TREND_AGAINST, EXPIRY_DYNAMICS, KNOWN_SETUP_WEAKNESS, LATE_IN_SESSION, STOCK_SPECIFIC_NEWS, OTHER;
  - **scores:** `news_for_trade` (−1..1), `event_risk` (0..1), `global_for_trade` (−1..1), `volatility_view` (−1 calm..1 stormy);
  - the web sources returned by the search.
- **Live-detected vs official signals:** live signals come from 2-second snapshots; official ones from Groww's 1-min candles. Both are recorded. A trade is scored on the **official** signal. The LLM verdict attaches to it only if the live signal had the same candidate, day and side, and fired within 5 minutes of the official one. Mismatches are reported.

## Evaluation (fixed now)
- **Review dates:**
  - **first look after 4 weeks (2026-10-30)**, information only, with no decisions on fewer than 20 trades per candidate;
  - **main review after 12 weeks (2026-12-25),** or earlier for any candidate with ≥ 30 trades.
- **Per candidate:** n, net per trade, win rate, PF, worst trade, 95% bootstrap CI, and comparison with its backtest reference.
- **A candidate "earns further work"** if all of these hold:
  - n ≥ 20;
  - net/trade > 0 after costs, and positive at 2× costs;
  - not worse than its backtest reference by more than its backtest's own standard error.
  - This bar is deliberately lenient (forward samples are small); "further work" means more paper time, never live money.
- **LLM, pooled across candidates (primary):** mean net of TAKE minus SKIP, with a bootstrap CI. Per candidate where n ≥ 15.
- **LLM reasons (exploratory, labelled as such):** the outcome (net in R units) regressed on the reason tags and scores (OLS with bootstrap CIs; logistic on win/loss). Reported as hypotheses for a later pre-declared test, never as proof.

## Not in scope
- No rule changes or new candidates mid-tournament. A new idea gets its own pre-declaration and start date.
