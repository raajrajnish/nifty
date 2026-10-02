# 03 — Setups (the ONLY setups the system may trade)

> **Status: FORWARD PAPER ONLY — HYPERCARE. No real money.** Frozen **2026-10-01, version 1**. Machine-readable twin: `config/setups.yaml`, kept identical to this file by `tests/unit/test_setups.py`.
> **Change policy:** a setup is never edited in place. Any change creates a new version (`G1.v2`), which starts its own forward count; the old version is retired, not overwritten. Changes need owner approval (MASTER_PLAN §3.10).
> **Evidence:** `docs/reports/2026-10-01_*.md`. Every rule below survived a pre-declared test. Rules that were tested and **rejected** are listed so they are not re-added by intuition.

---

## Shared definitions (both setups)

| Term | Exact meaning |
|---|---|
| Index | NIFTY 50 spot, 1-minute candles (`NSE-NIFTY`). A 1-minute bar stamped *t* covers *t*…*t*+59 s; its close is known at *t*+1 min. |
| 5-minute bar | Built from the 1-minute bars; labelled by its **end** time (the bar labelled 09:35 covers 09:30:00–09:34:59). |
| Opening range (OR) | High and low of the 1-minute bars from 09:15 to 09:29. Width w = high − low. |
| Yesterday's range | High and low of the previous trading day's 1-minute bars (PDH, PDL). |
| **Open outside** (both setups) | Today's first 1-minute **open** is **> PDH or < PDL**. Known at 09:15. |
| Expiry day | A day that is itself a NIFTY weekly expiry. **No trades** (`risk.yaml: expiry_day.allowed=false`). |
| Contract | **Strike** = index close at the signal, rounded to the nearest 50 (ATM). **Expiry** = the nearest weekly expiry **strictly after today**, taken from Groww (never assumed to be Tuesday; holidays move it). **Call (CE)** for an up signal, **put (PE)** for a down signal. Buying only. |
| Entry fill | Buy at the **open of the minute after the signal bar closes** (that is, at the 5-minute boundary). Limit at the ask; the backtest assumed open + half-spread (0.11%). |
| Exit fill | Sell at the bid; the backtest assumed price − half-spread. A stop that gaps fills at the open. |
| Time exit | **15:10** for every open position (`schedule.yaml: square_off 15:15` is the hard backstop). |
| Size | 1 lot (65) in all evidence. Code computes the quantity from the risk budget; the agent never sets quantity. |

---

## G1 — Narrow-range opening breakout on an "open-outside" day (v1)

**Idea:** the morning range is quiet relative to recent days, but the market opened outside yesterday's range, so there is an imbalance. When price escapes the opening range, it tends to keep going for hours.

| | Rule |
|---|---|
| **Day conditions (all required)** | 1. Not an expiry day. 2. **Open outside** yesterday's range. 3. **Narrow OR:** (OR width ÷ index close) < the median of the same ratio over the previous 20 trading days (at least 10 days needed). Known at 09:30. |
| **Trigger** | The **first 5-minute bar** labelled after 09:30 and up to 13:30 whose **close > OR high → CE**, or **close < OR low → PE**. |
| **Entry** | At the next minute's open (the 5-minute boundary). ATM strike, next weekly expiry. **One G1 trade per day.** |
| **Stop (safety)** | Option premium **−50% from entry** (checked on 1-minute lows). |
| **Invalidation (thesis wrong)** | A 5-minute bar closes **beyond the opposite side** of the OR (CE: close < OR low; PE: close > OR high). Exit at the next minute's open. |
| **Profit handling** | **Hold to 15:10.** No profit lock, no trailing stop, no early cut. |
| **Mechanical pre-screen** (agent cadence) | At 09:30, the day passes conditions 1–3. After that, from 09:35, check each 5-minute close against the OR edges. |

**Backtest evidence (Dec 2023 – Sep 2026, 1 lot, after Groww charges and half-spread; re-run 2026-10-02 on full index history):**
- 117 trades; win rate 45%; **+₹833 per trade**; 95% CI [₹40, ₹1,733]
- without the 5 best days: +₹137 per trade
- average loss −₹2,079; worst trade −₹4,962
- calls +₹33 per trade, puts +₹1,430 per trade
- alone: typical drawdown about ₹23k; bad case (p95) about ₹36k
- ⚠️ **Out-of-sample:** direction failed on untouched Nifty 2021–23 and on Bank Nifty (see `docs/HYPERCARE_LOG.md`).

---

## G2 — TWAP trend pullback on a calm "open-outside" day (v1)

**Idea:** on a calm day that opened outside yesterday's range, an intraday trend forms. Enter when price pulls back to the day's average price (TWAP) and holds it.

| | Rule |
|---|---|
| **Day conditions (all required)** | 1. Not an expiry day. 2. **Open outside** yesterday's range. 3. **Low volatility:** ATR14% (the average of (high − low) ÷ close over the previous 14 days) ≤ the median of ATR14% over the previous 120 days (at least 40 days needed). Known before the open. |
| **TWAP** | Running average of the 1-minute index closes since 09:15, as of the end of the signal bar. |
| **Trigger** | The first 5-minute bar labelled from 10:00 to 13:30 where: **CE:** TWAP is higher than about 30 minutes earlier, the bar's low ≤ TWAP × 1.0005, and its close > TWAP. **PE (mirror):** TWAP is lower than 30 minutes earlier, the bar's high ≥ TWAP × 0.9995, and its close < TWAP. |
| **Entry** | At the next minute's open. ATM strike, next weekly expiry. **One G2 trade per day.** |
| **Stop (safety)** | Option premium **−30% from entry**. |
| **Invalidation** | None beyond the stop. A TWAP-cross exit was tested and **rejected** (it exited too early). |
| **Profit handling** | **Hold to 15:10.** No profit lock, no trailing stop, no early cut. |
| **Mechanical pre-screen** | Before the open: day conditions 1 and 3. At 09:15: condition 2. From 10:00, check each 5-minute bar against TWAP and the 30-minute TWAP slope. |

**Backtest evidence (CORRECTED 2026-10-02):** the original figures (133 trades, +₹862 per trade) came from a warm-up bug. With too little index history, the 120-day median was unknown and those days were counted as calm. The rule above was always correct; the code now follows it (an unknown median means "not calm").
- 114 trades; win rate 43%; **+₹300 per trade**; 95% CI [−₹374, ₹1,001] (**could be zero**)
- without the 5 best days: **−₹212 per trade**, so the edge rests on a few big days
- average loss −₹2,158; worst trade −₹4,520
- calls +₹150 per trade, puts +₹531 per trade
- alone: typical drawdown about ₹28k; bad case (p95) about ₹44k
- Out-of-sample (untouched Nifty 2021–23): direction borderline, CI [−0.002, 0.191] ATR. Bank Nifty: no edge.

---

## Loss limits are percentages, never fixed rupees (owner, 2026-10-01)

| Limit | Basis |
|---|---|
| Per-trade stop | **% of the premium paid** for the position: G1 −50%, G2 −30% |
| Per-trade risk budget | **% of current equity** (`risk.yaml: per_trade_risk_pct`). Lots = budget ÷ (stop % × premium × lot size), rounded down |
| Daily loss limit | **% of equity at the start of the day** |
| Drawdown kill | **% below peak equity** |

**Equity** = starting trading money + all realised net P&L so far. Paper equity comes from the paper ledger. Every paper trade records its risk and result as **% of premium** and **% of equity**.

## HYPERCARE: how G1/G2 are judged during forward paper trading (declared in advance)

Each trading day the dashboard shows each setup's checks, signals and paper P&L, and End of Day.cmd prints the ledger. **Review triggers** (any one starts a review; reviews do not change rules on the spot):

1. **Execution mismatch:** the live paper engine did something the written rules would not do (a wrong day check, signal, contract or exit). Treated as a **bug**; fix the code and re-run the fidelity check.
2. **Fills:** the average entry/exit slippage versus the recorded mid is more than **2× the assumed half-spread (0.11%)**. Re-cost the backtest with the measured value.
3. **Results after 20 paper trades per setup:** net per trade below **₹0**, or a profit factor below 1.0, means a review. The backtest's 95% range was G1 ₹40–1,733 and G2 −₹374 to ₹1,001 per trade (corrected 2026-10-02).
4. **Drawdown** beyond the backtest's bad case (p95: G1 ≈ 18%, G2 ≈ 22%, both ≈ 31% of ₹2 lakh; corrected 2026-10-02) means pause and review.
5. **Learnings:** any repeated pattern in losing trades (for example call-side losses or expiry-week behaviour) is written down as a **hypothesis** for a pre-declared study. It is never added directly to the rules.

## Running G1 and G2 together

- **Both may be open at the same time.** They were tested independently, and "max one trade per day" was **worse**. Combined (1 lot each, corrected 2026-10-02): 231 trades, about ₹46k per year in the backtest (was ₹75k before the G2 correction); typical drawdown about ₹38k, bad case (p95) about ₹61k.
- **Daily loss caps of ₹3k–₹8k had no effect;** the stops are the real limit.

## ⚠ Conflicts with current `config/risk.yaml` (owner decisions needed before any live stage)

| Setting | Current | What G1/G2 need at 1 lot | Effect if unchanged |
|---|---|---|---|
| `per_trade_risk_pct: 1.0` (₹2,000) | ₹2,000 | G1 ≈ ₹4,500 (50% of a ~₹140 premium × 65); G2 ≈ ₹2,700 | Guardrail G10 sizing gives **0 lots**, so the trades are rejected |
| `max_open_positions: 1` | 1 | 2 (G1 and G2 together) | The second setup is blocked |
| `kill_criteria.live_drawdown_pct_from_peak: 10` | ₹20k | Normal bad patch is ₹23k–₹61k | Kill fires during normal noise |

**The forward paper test is not affected** (it evaluates the setups, not the guardrails). These must be decided before S1 paper trading through the guardrails or any live stage.

## Tested and REJECTED (do not re-add without a new pre-declared study)

| Idea | Result | Report |
|---|---|---|
| Faster entry (1-minute confirmation) | More fake breakouts; worse for both setups | entry_timing_study |
| Retest entry / don't-chase filter | Equal to the current rule, not better | entry_timing_study |
| Profit lock (keep 50–80% of peak) | Higher win rate but lower expectancy; cuts late-peaking winners | exit study #1 |
| Fixed −30% stop for G1 | Too tight; −50% plus the opposite-side rule is better | stop study |
| "Back inside the range" exit for G1 | Retests are normal; wins only 15% | stop study |
| 15-minute follow-through exit | Cuts trades at their worst point; worse at 10, 15 and 20 minutes | followthrough_study |
| Daily trend filter (20/50-day average) | Hypothesis rejected; a random control passed | entry_study #3 |
| Gap-and-go, gap-fade, EMA cross, ORB-30 | Negative or fragile | entry_study #2 |

## Known weaknesses (honest)

- The **call side is roughly break-even;** puts carry most of the profit.
- Samples are small (117 and 133) and the history has been studied many times. **Only forward days are clean evidence.**
- Fill prices at breakout moments are unverified; daily bid/ask recordings will measure them.
- Strike and expiry choice (ATM, next weekly) has not been optimised (a study is pending).
