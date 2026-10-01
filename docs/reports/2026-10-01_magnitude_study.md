# Magnitude study: can a big-move day be predicted by 09:30? (PRE-DECLARED 2026-10-01, before running)

**Why:** option buying only pays on days with big moves; small-move days lose to time decay and costs. The discovery study showed intraday **direction** is hard to predict. This asks a different question: is the **size** of the move predictable? It is measurement only; G1/G2 are frozen and unchanged.

**Data:** NIFTY 1-minute index data. **Deciding period: Oct 2021 – Nov 2023 (never studied).** Consistency check: Dec 2023 – Sep 2026. Expiry days are excluded.

## Target (measured after 09:30)

- **Range after 09:30** = (highest high − lowest low of the index from 09:30 to 15:10) ÷ ATR14, where ATR14 is the average daily range of the previous 14 days in points.
- **Big day** = range after 09:30 in the **top third** of all days in the period.
- Also reported: the absolute move from the 09:30 open to the 15:10 close ÷ ATR14 (the trend size).

## Predictors (all known by 09:30; no look-ahead)

| Id | Predictor |
|---|---|
| P1 | Squeeze: average daily range over the previous 5 days ÷ the same over the previous 20 days |
| P2 | VIX level: yesterday's VIX close ÷ the median of the previous 60 VIX closes |
| P3 | VIX change at the open: VIX at 09:29 ÷ yesterday's VIX close − 1 |
| P4 | Gap size: \|today's open − yesterday's close\| ÷ ATR14 |
| P5 | Opening-range width: 09:15–09:29 high − low ÷ ATR14 |
| P6 | Opened outside yesterday's range (yes/no) |
| P7 | Trading days to the next expiry (1 = the day before expiry) |

## Pass rule for a predictor (all must hold)

1. On untouched data, the Spearman rank correlation with "range after 09:30" has \|ρ\| ≥ 0.10, and its 95% bootstrap CI excludes 0.
2. **The same sign** in the 2023–26 period.
3. In its best third of days, the big-day rate is ≥ 40% (the baseline is 33.3% by construction) on untouched data.

## If two or more predictors pass

A **simple combined score** is built: the sum of each passing predictor's tercile rank (1–3), with the direction set by its sign on the untouched data. It is then evaluated **only on Dec 2023 – Sep 2026**, as the big-day rate in the score's top third. A useful score must reach a big-day rate of ≥ 45% there.

## Result (run 19:13, `magnitude_20261001_1913`): size is PARTLY predictable; the combined score just misses

405 untouched days and 553 days in 2023–26 (expiry days excluded). Big day = range after 09:30 ≥ 0.94 × ATR14.

| Predictor | ρ untouched [95% CI] | ρ 2023–26 | Big-day rate by third (low/mid/high) | PASS |
|---|---|---:|---|---|
| **P5 OR width** | **+0.305 [0.215, 0.390]** | **+0.358** | 20.7 / 32.6 / **46.7%** | **✅** |
| P2 VIX level | +0.141 [0.045, 0.239] | +0.086 | 28.8 / 29.5 / 42.1% | ✅ |
| P1 recent/long range | +0.160 [0.060, 0.261] | +0.154 | 28.9 / 34.1 / 37.0% | ✗ (best < 40%) |
| P7 days to expiry | +0.126 [0.026, 0.224] | +0.053 | 33.3 / 29.6 / 37.0% | ✗ |
| P3 VIX change at open | +0.079 [−0.024, 0.176] | +0.089 | — | ✗ |
| P4 gap size | −0.017 | +0.078 | — | ✗ |
| P6 open outside | −0.092 | 0.000 | 35.3 / 31.1% | ✗ |

**Combined score (P2 + P5), evaluated on 2023–26 only:** 44.0% big days in its top third against 33.3% baseline. **That is below the pre-declared 45%, so it is NOT adopted.**

**Findings:**
1. **Volatility clusters.** A wide first 15 minutes, elevated VIX, and recently wide days all point to bigger moves later. There is no "squeeze, then explosion" effect.
2. **G1's narrow-OR filter selects the days least likely to move big** (20.7% big days in the narrowest third). This is consistent with G1 failing the out-of-sample direction check. G1 is **not changed** (frozen); this is noted for the hypercare review.
3. **Lead for a future pre-declared study:** OR width as a magnitude filter (ρ ≈ 0.3 in both periods). Any use would be a new setup version, never an edit of v1.

## What it means

- **If big days are predictable:** a later pre-declared study tests whether G2/G1 do better on predicted-big days. That would become a new version, never an edit of v1.
- **If they are not:** intraday option buying here depends largely on luck in which days turn out big. Sizing, and the judgement of G1/G2, must reflect that.
