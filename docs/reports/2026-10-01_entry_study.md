# Entry studies #2 and #3 (2026-10-01)

## Study #2: 7 entries × 2 exits × 11 filters (146 cells)

`tradingagent backtest-entries`; output in `data/reports/backtests/entries_20261001_0903/`. Data from Dec 2023 to Sep 2026; expiry days excluded. Costs and fills are as in exit study #1.

**Result:** 3 of 146 cells passed the pre-declared bar; **0 of 22 random-control cells passed.** Stress tests (`robust.py`, run the same day) found all three fragile:

| Candidate | n | Net per trade | Without top 5 days | CE / PE | By year |
|---|---:|---:|---:|---|---|
| TWAP pullback, low volatility, hold | 316 | +₹285 | **−₹13** | −₹35 / +₹657 | decaying: 2024 +465 → 2025 +203 → 2026 +30 |
| ORB-15, narrow OR, 30-min no-progress exit | 269 | +₹183 | **−₹109** | −₹40 / +₹388 | 2024 −7, 2025 +229, 2026 +441 |
| ORB-15, narrow OR, hold | 269 | +₹143 | **−₹178** | −₹166 / +₹428 | sensitive to the OR lookback (40/60-day versions negative) |

**Verdict:** not tradeable. The profits come from a handful of big down days during Nifty's 2025–26 decline, and only puts made money. One interesting signal remains: ORB on narrow-OR mornings (+₹183) vs wide-OR mornings (−₹285), consistent under both exits.

## Study #3: direction filter (PRE-DECLARED before running, 2026-10-01)

- **Hypothesis:** study #2's one-sidedness comes from market direction. Taking only trades in the direction of the prevailing trend should help on **both** sides.
- **Trend definition:** yesterday's close compared with the 20-day simple average of daily closes, both as of yesterday (no look-ahead). Calls only in an up-trend, puts only in a down-trend. **Sensitivity:** 50-day.
- **Cells:** every entry from study #2 × both exits × {`with_trend20`, `against_trend20`, `with_trend50`, `with_trend20+narrow_or`, `with_trend20+low_vol`}, alongside the existing filters.
- **Pass:** the study #2 bar (n ≥ 100; positive in dev, validate and test; positive at 2× costs; PF ≥ 1.10; both halves positive).
- **ROBUST (new, required to go any further):** PASS **and** positive for both calls and puts **and** still positive after removing the 5 best days.
- **Expectation, stated in advance:** `against_trend20` should be clearly worse than `with_trend20`. If it isn't, the trend idea is noise.

### Study #3 result (run 09:14, `entries_20261001_0914`): hypothesis REJECTED

- 216 cells; 4 PASS; **0 ROBUST**. The pre-declared check failed: `against_trend20` was not consistently worse than `with_trend20`. TWAP pullback was the opposite: +₹370 against the trend vs −₹1 with it.
- **A random-entry control passed** (`random + with_trend20 + narrow_or`: +₹288 per trade, PF 1.46; calls −₹161, puts +₹998). That proves the PASS bar alone can be met by luck or by market regime, which is why ROBUST is now required.
- **Puts only paid in the falling year.** Random puts by year: 2024 −₹122 (Nifty +8.8%), 2025 −₹191 (+10.1%), 2026 +₹412 (−13.5%). Random calls lost even in up years, because slow rallies don't beat time decay.
- **The one structure that survives:** ORB-15 on narrow-OR mornings +₹183 vs **random entries on the same narrow-OR mornings −₹127**. The breakout timing adds about ₹300 per trade beyond the day selection. It is still put-heavy and depends on a few big days, so it is a lead, not a rule.

## Stop study (`backtest-stops`, `stops_20261001_0925`): letting each setup set its own loss

- **Owner's hypothesis:** a fixed −30% stop kills trades that were right but dipped first. **Partly confirmed:**
  - For S1 (ORB narrow, hold), 19 of 122 eventual winners (16%) dipped beyond −30%.
  - The median winner dips −16%; the 90th percentile dips −38%.
  - S1 improves with wider stops: −30% gives +₹143, −50% gives +₹169, no stop gives +₹253. With no stop, the worst single loss was −₹11,580 per lot.
- **"Back inside the range" is the wrong invalidation for ORB.** Retests are normal; that rule won 15% of trades at −₹229 per trade. "Close beyond the opposite side" is correct. **S1b** (opposite-side rule plus a −50% stop) was positive in dev, validate and test (+76 / +44 / +491) with the stop chosen on dev only, and positive at 2× costs.
- **S2 (TWAP, low volatility)** is best with the −30% stop; wider stops hurt it. Its own TWAP-cross exit exits too early.
- **Random entries do not improve with wider stops.** The S1 effect is specific to that setup.
- **Still not robust:** calls are negative in both setups, and results without the top 5 days are negative.

## Risk study (`backtest-risk`): S1b (−50%) + S2 (−30%), 1 lot each, 430 days

| | Value |
|---|---|
| Per-trade loss | S1 average −₹2,213, 1-in-10 −₹3,554, worst −₹4,962 · S2 average −₹2,008, 1-in-10 −₹3,122, worst −₹7,332 (gap) |
| Daily | worst −₹7,332; 5th percentile −₹5,021; 1st percentile −₹6,926; winning days 39%; average +₹306 |
| Daily caps ₹3k–₹8k | **no effect.** The second trade usually starts before the first closes; the stops are the real daily limit |
| Monte Carlo drawdown | median −₹77k; **5th percentile −₹1.23 lakh**; losing-day streak median 10, 95th percentile 15 |
| Total | +₹1.32 lakh over about 2.8 years (+₹225 per trade) |

**Setup-derived limits:**
- Per trade: S1 about ₹5,000, S2 about ₹3,000.
- Per day: about ₹8,000, as a backstop only.
- Drawdown to plan for: ₹75k–₹1.2 lakh.

**Conflict with risk.yaml:** `kill_criteria.live_drawdown_pct_from_peak: 10` (₹20k) would stop these setups in almost every simulated sequence. **Recommendation (a), acknowledged by the owner with "ok" on 2026-10-01: do not trade yet.** Keep improving the edge per trade and keep forward paper testing; risk.yaml is unchanged.

## Forward paper test (frozen 2026-10-01)

These rules are frozen as of 2026-10-01 and are evaluated only on trading days **after** 2026-10-01, which no study has seen:
1. `orb15 | no_progress_30m | narrow_or`
2. `orb15 | hold_1510 | narrow_or`
3. `twap_pullback | hold_1510 | low_vol`

The ledger is `data/paper/forward_ledger.csv`, updated by `tradingagent forward-test` after each day's `fetch-history`. No rule may be changed while it is being forward-tested. A change starts a new, separately counted forward test.
