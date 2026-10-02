# Independent review: Phase 1 (audit) and Phase 2 (G1/G2 verdict)

Reviewer: Claude Fable 5.1, 2026-10-02. Scope: `docs/FABLE_BRIEF.md` Phase 1 and Phase 2 only. **Phase 3 has not been started.**
Database opened read-only. Nothing was downloaded. G1/G2 rules are unchanged.

## 1. For the owner (bottom line first)

**Bottom line: the backtests are honest, but there is still no real edge. I would stop G2 and keep G1 running on paper only as a long shot.**

- **The code is mostly sound.** I looked for the usual backtest cheats: using prices before they were known, unrealistic fills, wrong contracts and bad data. I found **nothing that makes G1 or G2 look better than they really are.** The live paper engine makes the same decisions as the backtest on 51 of 52 test days.
- **Trading costs don't decide anything.** The spreads you recorded (0.22%) match what the backtest assumed. G2 only reaches break-even if fills are about 18× worse than that. G1 survives even then.
- **New finding 1: G2's profit doesn't come from picking the right direction.** On the same days and at the same entry time, holding G2's option to 15:10 made **+₹15 a trade**. Holding the opposite option made −₹97. The difference is pure noise. The +₹300 comes from how the −30% stop happened to cut trades in this particular history, not from a reason that should repeat.
- **New finding 2: G1 and G2 are mostly the same bet.** They trade on the same day 62 times, and on those days their results move together (correlation 0.84). "Two setups" is closer to one.
- **New finding 3: paper trading can't settle this quickly.** One trade's result swings by about ±₹4,000–4,700. At G1's backtest average, telling it apart from luck would take about **130 trades (about 3 years)**. For G2 it would take about **600 trades (about 15 years)**. The planned review after 20 trades is close to a coin flip.
- **G1 still looks the stronger of the two.** On 2024–26 data its direction calls were genuinely good: the chosen option beat the opposite one by about ₹2,200 a trade, consistently across 2024, 2025 and 2026. But it was **picked out of hundreds of tested variations, on the same data,** and it **failed both independent checks** (Nifty 2021–23 and Bank Nifty). The likely explanation is that it fits this period, not that it is a lasting edge.
- **Small bugs fixed** (with tests, committed locally, not pushed):
  1. The engine-vs-backtest check script was choosing Bank Nifty expiry dates.
  2. The forward-test summary still compared G2 with the old, wrong ₹862 figure.
- **Two engine weaknesses to fix before trusting forward results** (I did not change the engine; that's your call):
  1. If the index feed stops before 15:10, an open paper trade is never closed and never written to the ledger.
  2. If you skip End of Day, the next morning the engine silently uses an older day as "yesterday".
- **A fifth data fault:** Groww's **Nifty daily** candles are also wrong from 2025. Nothing in G1/G2 uses them, and I checked that no option data is missing because of it.

**What to do next:**
1. Retire G2 as a candidate.
2. Keep G1 on paper unchanged, with a direction-based review after 40 signals (section 3).
3. Fix the two engine weaknesses.
4. Then decide whether to try Phase 3, the new kinds of information (section 4). Don't search Nifty price patterns any more.

## 2. Findings table

Severity: **High** = changes how a stated result should be read; **Medium** = can corrupt future evidence; **Low** = small or no effect on results; **Info** = checked and found OK.

| # | Severity | Where | Failing case (reproduced) | Effect on a stated result | Status |
|---|---|---|---|---|---|
| 1 | **High** | G2 rules (`sim/entry_study.py:71-88`, stop in `followthrough_study.py:36`); stated in `HYPERCARE_LOG.md` ("G2 is the stronger candidate") | Opposite-leg test on the 114 G2 trades (`logic_20261002_1109`), same strike, entry minute and costs, both held to 15:10 with no stop: **own option +₹15/trade, opposite option −₹97, difference +₹112, 95% CI [−1,314, 1,469], P(≤0) = 0.44.** The −30% stop turns +₹15 into +₹300. The same stop adds +₹71 for RANDOM on the same kind of days. This agrees with the discovery study's selection-era G2 index drift of +0.031 ATR, CI [−0.083, 0.143]. | G2's in-sample ₹300/trade is **not a direction edge.** Its only support is the borderline untouched-2021–23 drift (CI touches 0), and Bank Nifty shows no edge. "G2 is the stronger candidate" is not supported. | Not fixed (rules frozen); reported |
| 2 | **High** | Selection process: `sim/logic_study.py:138-157` (`decide` uses dev **and** val+test), entry/stop/timing/follow-through grids | The Nifty funnel that produced G1/G2 tested well over 250 cells: entry study 7 entries × 2 exits × 16 filters, stop sweep 6×6, timing 7, follow-through 9, logic 13 groups × 2. All three splits were then used to choose F4. G1's CI lower bound of ₹40 means t ≈ 1.9. Its directional opposite-leg difference is +₹2,183, CI [832, 3,560], t ≈ 3.1. | "PASS/ROBUST" is **in-sample**, not out-of-sample. A t of about 2–3 is what the best of a few hundred tries looks like by chance. That fits G1 failing untouched Nifty 2021–23 (50.0% right vs random 53.4%) and Bank Nifty (−₹876/trade). | Not fixed; reported |
| 3 | **High** | `playbook/03_setups.md` ("Running G1 and G2 together"; combined ₹46k/yr) | 62 of the 169 G-days have both a G1 and a G2 trade. On those days the daily P&L correlation is **0.84**. On 2025-11-14 they took opposite sides. | The combined result is close to one bet doubled on overlap days, not two independent setups. The risk study's day-level Monte Carlo (`risk_study.py:110-124`) already sums by day, so its drawdowns are fine. Forward trade counts for G1 and G2 must not be added together as independent evidence. | Not fixed; reported |
| 4 | Medium | `playbook/03_setups.md` hypercare trigger 3 (review after 20 trades) | Per-trade SD: G1 ₹4,734, G2 ₹3,735. Trades needed for a 2-SE result at the backtest mean: **G1 ≈ 129 (≈3 years), G2 ≈ 618 (≈15 years).** After 20 trades, P(net < 0) is about 22% if G1 is as good as its backtest, and 50% if it has no edge. | Forward paper trading **cannot validate either setup within months.** The 20-trade trigger barely separates "works" from "doesn't". | Not fixed; proposal in section 3 |
| 5 | Medium | `paper/engine.py:168-183, 316-330` (EOD exit and G1 invalidation run only when an **index** minute bar completes); `paper/runner.py:224` (only closed trades reach the ledger) | `scripts/check_paper_fidelity.py 40` on **2025-09-26** (index data stops at 14:35): the G2 PE 24800 trade stays `IN_TRADE`. It never exits and never reaches the ledger. The backtest has +₹6,138 (DATA_END). | An index-feed or recorder outage before 15:10 **silently drops a trade** from the forward evidence. Big moves are when this is likeliest. | Not fixed (engine is outside my allowed fix scope); recommended: a time-based exit from quotes plus ledgering of unclosed trades |
| 6 | Medium | `paper/engine.py:95-97` | History is checked only for being "> 4 calendar days old". It is updated only by End of Day (`scripts/eod.ps1:16`). If EOD is skipped on a Tuesday, Wednesday's engine uses **Monday** as "yesterday" for PDH/PDL (open-outside) and for the narrow-OR and ATR medians, with no warning. | Wrong day conditions on such days, so the forward record no longer matches the frozen rules. | Not fixed; recommended: compare with the previous `data/raw/date=*` folder, or fetch history in the morning |
| 7 | Medium | `scripts/check_paper_fidelity.py:34,40` | The unfiltered `contracts` query includes Bank Nifty. For **40 of 169** G-days, "next expiry" was a Bank Nifty Wednesday (e.g. 2024-01-08 → 2024-01-10, not 2024-01-11). That covered 4 of the default 12 sampled days. | The fidelity check (the hypercare "execution mismatch" guard) would have reported false mismatches, or matched against wrong contracts. | **Fixed** `c3b1ed2` (`sim/fidelity.py` + `tests/unit/test_fidelity.py`). Re-run on 40 days: **51/52 same signal, 51/52 same exit reason.** The one miss is finding 5. |
| 8 | Low | `sim/forward.py:51-52` | The forward summary benchmarked G2 at 133 trades / +₹862 (the pre-warm-up-fix numbers). `forward_summary.csv` showed them. | The forward G2 results would have been compared with a figure about 3× too high. | **Fixed** `04c3e80`; a test now ties these numbers to `setups.yaml` evidence |
| 9 | Low | Data: `NSE-NIFTY` `1day` candles; used by `data/history.py` `download_options` → `strike_range` | Daily high/low differ from the 1-minute data on **137/248 days in 2025 and 127/186 in 2026**, against ≤5 a year before. Example: 2025-01-03 daily open 24,533.35 / high 24,540.45, while the previous close was 24,188.65 and the true high was about 24,226. | This is a **fifth data fault** (Nifty daily, not only stocks). **No effect on G1/G2:** the studies build days from 1-minute bars. Every needed ATM contract exists 2023-12 → 2026-09, except 4 contract-days (2026-06-24/29), and none of those is a G1/G2 trade. Risk for any future code that reads `1day`. | Not fixed; warn |
| 10 | Low | Data: special sessions counted as normal days (`entry_study.day_features`, `logic_features`) | 2024-03-02 and 2024-05-18 were Saturday DR sessions (about 110 bars); 2025-10-21 was Muhurat. **G1 traded 2024-05-18** (−₹1,028, data ended 12:30). Index data also stops early on 2025-09-26 (14:35) and 2026-09-29 (14:04); G2 on 2025-09-26 (+₹6,138) exited at 15:00. These short days also become "yesterday" for the next day's open-outside check (live too, e.g. after Muhurat). | G1 mean +₹16 if 2024-05-18 is excluded. Negligible. | Not fixed; reported |
| 11 | Low | `sim/logic_study.py:43-49` `follow()` | The start price is the **close** of the entry minute (known one minute after entry). `discovery_study.follow` correctly uses the open. Right-direction-60m for S1 open-outside: 56.4% (close start) vs 59.0% (open start). S2: 57.0% vs 59.6%. | Measure only, not P&L. **The F4 selection is unchanged** under either start. | Not fixed (study concluded) |
| 12 | Info | Costs: `config/costs.yaml`, `sim/exit_study.py:32` | Recorded ATM spread: median 0.222% / 0.224% (2026-09-30 / 10-01), p90 0.27%. That equals the modelled 0.11% half-spread. Charges ≈ ₹67/trade; spread ≈ ₹18/trade. Net/trade at half-spread 0.11 / 0.22 / 0.5 / 1 / 2%: G1 833 / 815 / 768 / 686 / 520; G2 300 / 282 / 236 / 155 / −9. | **Costs and spread cannot change the verdict.** Breakout-moment spreads are still unmeasured, but would need to be about 18× wider to matter for G2. Lot 65 is used throughout (today's lot, a stated convention); that rescales rupees but cannot flip a sign. Bank Nifty used the Nifty spread, which makes its already-negative results optimistic, so its conclusion is unchanged. | OK |
| 13 | Info | Fill realism: `sim/exit_study.py:160-203` | Entry: option open vs the previous minute's close, median 0.00%, p5/p95 −1.05% / +0.92%. Entry-bar volume ≥ 41k (median 0.9M). No stale fills. Stops fill at min(open, stop), checked on 1-minute lows first (pessimistic). No ×100 faults in Nifty options: all 469 bar-to-bar jumps > 3× are near-zero premiums on expiry days, which are never traded. | OK | OK |
| 14 | Info | Timing / look-ahead: `entry_study.five_min`, `e_orb`, `e_twap_pullback`, `day_features`, `logic_features`, `simulate` | 5-minute bars are right-labelled (09:35 = 09:30–09:34). Entry is at the next minute's open. TWAP uses closes < signal time. ATR, OR median and PDH/PDL use only earlier days. Strike comes from the signal close. Expiries are NIFTY-only (strictly after today). Timestamps are naive IST (first bar 09:15 every regular day). The engine replay agrees on 51/52 days. | No look-ahead found in the G1/G2 P&L. | OK |
| 15 | Info | Live vs backtest details: `paper/engine.py` | The engine checks stops on the **bid** at every tick; the backtest uses trade-print lows. The engine exits at about 15:10:00; the backtest uses the 15:10 bar's close. The engine needs ≥10 OR bars; `e_orb` needs ≥11. | All tiny, and they lean pessimistic for live. Fidelity 51/52. | OK |

Not checked: breakout-moment spreads (only 3 recorded days, none with a G1/G2 signal); Groww contract-note charges (no real trade exists); the Bank Nifty and stock studies line by line (their conclusions are all "fail", and nothing I found would turn a fail into a pass).

## 3. G1/G2 verdict

**G2: stop** (retire as a candidate, v1 stays frozen in git). Three reasons:
1. In-sample, the profit isn't directional (finding 1).
2. Out of sample, the direction is borderline: CI [−0.002, 0.191] ATR.
3. On Bank Nifty there's no edge, and confirming +₹300 on paper would take about 15 years.

Logging it in the engine costs nothing, but it should not count toward "validated setups".

**G1: continue on paper, unchanged** (no G1.v2), as a long shot with an expected edge close to zero.
- **For:** in-sample, its direction calls are real and steady (+₹2,183/trade vs the opposite option, positive in 2024, 2025 and 2026).
- **Against:** it is the winner of a large search on that same data, and it failed both independent checks.
- Real money should not be considered in 2026.

**Cheap checks that could settle it faster than months of paper trading:**
- **Cost sensitivity:** done above, settled. Costs don't decide it.
- **Opposite-leg direction test:** done above, as a measurement of the frozen rules, not a new search. It answers G2 (no direction edge).
- **No other untouched history is left that would be a fair new test of G1.** Nifty 2021–23 and Bank Nifty index 2021–23 are already used. Bank Nifty lock box 1 belongs to the Bank Nifty search. Stocks behave differently, so a fail there would prove little.

**Proposed pre-declared G1 review (owner to approve; a monitoring rule, not a trading rule):**
- **What is measured:** for every forward G1 signal, the index move from the entry minute's **open** to 15:10, in ATR14 units. This is the same measure as the discovery study.
- **In-sample reference:** +0.142 ATR, SD about 0.55.
- **Review at 40 signals (about 1 year):**
  - mean < +0.07 ATR → **stop G1**;
  - mean ≥ +0.07 ATR → continue to 80 signals.
- **Error rates:** about 20% chance of wrongly stopping a G1 that is as good as its backtest, and about 21% chance of wrongly continuing a G1 with no edge.
- Direction is about 1.5× more informative per trade than rupee P&L, which is why it is used instead.

**Before relying on any forward numbers,** fix findings 5 and 6 in the engine. Both can silently change what the forward record contains.

## 4. Phase 3: awaiting the owner's go-ahead (nothing below has been run)

Per the brief: at most 5 hypotheses, each using information the ~90 earlier ideas did not use, each pre-declared in its own report before any test. These are proposals only.

| # | Hypothesis (reason first) | Data | Pass bar (sketch) | Cost |
|---|---|---|---|---|
| P1 | **Cheap vs dear options at 09:30.** Option buyers only win when the realised move beats what the premium already prices. The magnitude study found that OR width predicts move size. Buy the ATM straddle only when the predicted move is well above the straddle's implied move. This is a volatility bet, not a direction bet, and is new information: premiums as implied volatility. | Nifty options Dec 2023 – Sep 2026 (09:30 straddle), index 1-min, VIX | Design on 2023-12 → 2025-06; one-shot test on 2025-07 → 2026-09; must beat a random-day straddle; n ≥ 80; CI > 0 | ~1 day |
| P2 | **Expiry-day behaviour** (skipped by every study so far). Same-day options decay fast; hedging flows around big strikes may pin the index or release it in the afternoon. Measure first, then at most one rule. | Nifty options on expiry days, Dec 2023 – Sep 2026 (about 140 days) | Measurement first; any rule is tested only on the later half | ~1 day |
| P3 | **Intraday VIX vs index divergence.** VIX rising while the index is flat signals hedging demand ahead of a move. | VIX 1-min and Nifty 1-min 2021–2026 (VIX 1-min is unused so far) | Direction / magnitude test on Nifty 2021–23, then options 2023–26 | ~0.5 day |
| P4 | **Nifty vs Bank Nifty intraday spread reversion.** Index arbitrage and basket flows pull the ratio back after an extreme gap. | Both indices 1-min 2021–2026, options for both | Design on 2023–25; Bank Nifty lock box rules apply; must beat random | ~1 day |
| P5 | **Option-chain positioning (OI / PCR at the open).** Needs live recording. Start recording now; test after about 60 recorded days. | `data/raw/*/chain.jsonl` (3 days so far) | Pre-declare now; test in about 3 months | ~0.5 day now + later |

Option selling (for example the other side of P1/P2) stays **research-only and an owner decision**; the system is buy-only.

## 5. Commits (local only, not pushed)

- `c3b1ed2` Fix check_paper_fidelity: use NIFTY expiries/contracts only (adds `src/tradingagent/sim/fidelity.py`, `tests/unit/test_fidelity.py`)
- `04c3e80` Forward summary: compare G1/G2 with the corrected backtest evidence (`src/tradingagent/sim/forward.py`, `tests/unit/test_setups.py`)

All 196 tests pass; ruff and mypy are clean.
