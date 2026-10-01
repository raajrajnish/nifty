# Discovery study: new setups beyond G1/G2 (PRE-DECLARED 2026-10-01, before running)

**Context:** G1/G2 v1 are frozen in hypercare (git tag `v1-hypercare-freeze`) and are **not changed** by this study. All code for it is new (`sim/discovery_study.py`).

**The overfitting problem:** Dec 2023 – Sep 2026 has been examined in about eight studies. To get a clean test, **Stage A uses NIFTY index data from Oct 2021 – Nov 2023, which has never been examined.**

## Candidates (all four fixed now)

Common rules:
- No expiry days. One trade per setup per day.
- Opening range (OR) = 09:15–09:29 high/low, width w.
- 5-minute bars are labelled by their end time, and entry is at the next minute.
- ATM option, nearest weekly expiry after today. Buying only. Time exit at 15:10.

They are designed to cover what G1/G2 do **not** trade: inside-open days, wide-OR open-outside days, failed breakouts, and the afternoon.

| Id | Name | Day condition | Trigger (direction) | Thesis-wrong exit | Stop |
|---|---|---|---|---|---|
| **H1** | Failed-breakout reversal (trap) | any non-expiry day | After a first 5-min close beyond one OR side, a later 5-min close (≤ 13:30) beyond the **opposite** side → trade in that new direction | 5-min close back beyond the **original** breakout side | −50% |
| **H2** | Yesterday's-level breakout on inside-open days | today's open **inside** yesterday's range | First 5-min close (09:35–13:30) above yesterday's high (PDH) → CE; below yesterday's low (PDL) → PE | 5-min close back past yesterday's mid-point ((PDH+PDL)/2) | −50% |
| **H3** | Afternoon continuation | any non-expiry day | At the 13:00 bar: index > TWAP **and** today's high was made after 12:00 → CE; mirror for PE (< TWAP, low made after 12:00) | none | −30% |
| **H4** | Opening drive on wide-range outside days | open **outside** yesterday's range **and** OR **not** narrow (the complement of G1) | At 09:30: if \|09:29 close − 09:15 open\| ≥ 0.5w, trade in the direction of that move | 5-min close beyond the opposite OR side | −50% |

## Stage A: direction logic on UNTOUCHED index data (Oct 2021 – Nov 2023)

- **Measures,** per signal: index move in the trade's direction after 60 minutes and at 15:10, in daily-ATR units; "right direction after 60 min" %.
- **Baseline:** random entries (random time 09:45–13:30, random side) on the same days.
- **PASS-A,** all required:
  - n ≥ 80;
  - right direction after 60 min ≥ 53% **and** ≥ the random baseline + 3 points;
  - mean move at 15:10 > 0, with the 95% bootstrap confidence interval above 0.
- For information only: the same measures on Dec 2023 – Sep 2026.

## Stage B: option P&L (Dec 2023 – Sep 2026), only for setups that pass A

- Same costs, fills, splits and bars as G1/G2: **PASS** (n ≥ 100; positive in dev, validate and test; positive at 2× costs; PF ≥ 1.10; both halves positive) and **ROBUST** (plus calls and puts each positive, plus still positive without the 5 best days).
- Also reported: 95% CI, the scorecard, and overlap with G1/G2 days.

## Stage A result (run 19:02, `discovery_A_20261001_1902`): ALL FOUR FAIL

| Setup | n | Right direction after 60 min | Move at 15:10 (ATR) | 95% CI | Verdict |
|---|---:|---:|---:|---|---|
| H1 failed breakout | 93 | 48.4% | −0.061 | [−0.154, 0.032] | fail |
| H2 yesterday's-level breakout (inside open) | 143 | 55.9% | −0.044 | [−0.141, 0.055] | fail (right early, gives it back) |
| H3 afternoon continuation | 214 | 55.6% | −0.003 | [−0.056, 0.045] | fail |
| H4 opening drive (wide, outside) | 50 | 52.0% | +0.129 | [−0.048, 0.316] | fail (n < 80; CI includes 0; −0.082 in the 2023–26 era) |
| RANDOM | 410 | 53.4% | +0.030 | [−0.014, 0.072] | — |

None goes to Stage B. (Bookkeeping fix: the random "right direction" was computed before dropping incomplete rows, 52.1% vs 53.4%; no verdict changes.)

## Added BEFORE running (2026-10-01 19:05): out-of-sample check of G1/G2's direction logic

G1/G2 were selected on Dec 2023 – Sep 2026. **Measurement only; the frozen G1/G2 are not changed.** The same Stage A measures are applied to G1/G2 signals on the untouched Oct 2021 – Nov 2023 index data:
- G1 = ORB-15 on open-outside + narrow-OR days;
- G2 = TWAP pullback on open-outside + calm days.

The same PASS-A bar is used, except n ≥ 40 because G-days are rarer. If G1/G2 fail here, their edge is more likely a fit to 2023–26, and hypercare must be judged with that in mind.

### Result: G2 partly holds out of sample; G1 does NOT

| | Untouched 2021-10 → 2023-11: n · right after 60 min · move at 15:10 (ATR) · 95% CI | Selection era 2023-12 → 2026-09 |
|---|---|---|
| G1 | 106 · **50.0%** (random 53.4%) · +0.044 · [−0.043, 0.130] | 117 · 59.0% · +0.142 · [0.042, 0.242] |
| G2 | 129 · **55.8%** (bar 56.4%) · **+0.090 · [0.001, 0.182]** | 114 · 59.6% · +0.031 · [−0.083, 0.143] |

- **G2:** a positive end-of-day drift out of sample, with the CI above 0; it misses the 60-minute right-direction bar by 0.6 pts. It is the more credible setup.
- **G1:** its direction logic is about a coin flip on unseen data, so its backtest edge is likely partly in-sample fit.
- **G1/G2 are NOT changed** (frozen). Hypercare expectations for G1 are lowered; this is recorded in `docs/HYPERCARE_LOG.md`.
- Option P&L for 2021–2023 cannot be tested, because there is no option history before Dec 2023.

## Outcome rules

- A setup passing **A and B-ROBUST** is proposed to the owner as a **G3/G4 candidate** for a future hypercare forward test.
- A setup passing **A** but only **B-PASS** is reported as a lead.
- Failing **A** ends it, whatever Stage B would have shown. Its logic did not hold on unseen data.
- No parameters are tuned. If all four fail, that is the result.
