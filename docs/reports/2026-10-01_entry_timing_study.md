# Entry-timing study (PRE-DECLARED 2026-10-01, before running)

**Question:** do S1 and S2 work better if we enter at a better moment? The diagnostic showed that S1 entries made 0–2 min after the first 1-minute close beyond the level made +₹318 per trade, against −₹164 for entries made 6–15 min later. That diagnostic only covered breakouts that survived a 5-minute confirmation, so earlier entry must be tested as its own rule.

**Held fixed from the stop study (not re-tuned):**
- **S1:** narrow-opening-range days only. Exit: 5-minute close beyond the *opposite* side of the opening range, a −50% premium stop, and 15:10.
- **S2:** low-volatility days only. Exit: hold to 15:10 with a −30% premium stop.
- **Both:** ATM strike at the signal, nearest weekly expiry after today, expiry days excluded. One trade per setup per day. Costs and fills as in all earlier studies.
- **Bar timing:** a 1-minute bar's close is known at the *end* of that minute, so entry is at the next minute's open.

## S1 variants (opening range = 09:15–09:29 high/low; width w = high − low)

| Id | Entry rule (signals 09:30–13:30) |
|---|---|
| **S1-A** | **Current rule:** first 5-minute close beyond the range |
| **S1-B** | **Fast confirm:** first 1-minute close beyond the range |
| **S1-C** | **Retest:** after the first 1-minute close beyond the range, within the next 30 minutes, a 1-minute bar that dips back into the zone (low ≤ high + 0.1w for calls; high ≥ low − 0.1w for puts) and closes back beyond the level. Any 1-minute close beyond the *opposite* side first cancels the setup. If no retest happens, no trade |
| **S1-D(A)** | S1-A, but **skip** if the signal close is more than 0.5w past the level ("don't chase") |
| **S1-D(B)** | S1-B with the same 0.5w don't-chase check |

## S2 variants

| Id | Entry rule (signals 10:00–13:30; TWAP = running average of 1-minute closes) |
|---|---|
| **S2-A** | **Current rule:** 5-minute bar touches TWAP (within 0.05%) and closes back on the trend side; TWAP is higher/lower than 30 minutes earlier |
| **S2-B** | **Fast confirm:** the same condition on a **1-minute** bar |

## How we decide (fixed in advance)

- **The current rule (A) is the baseline.** A variant is "better" only if its net per trade beats A's on the **dev** days, and also beats A on validate and test combined.
- **The usual bars still apply:** PASS (n ≥ 100; positive in dev, validate and test; positive at 2× costs; PF ≥ 1.10; both halves positive) and ROBUST (PASS plus calls and puts each positive, plus still positive without the 5 best days).
- **Also reported:** 95% bootstrap confidence interval per trade, the share of fake breakouts (trades stopped or exited by their own failure rule), and for S1 the delay between the first 1-minute break and the entry.
- **History has been reused several times**, so even a winning variant only earns a place in the **forward paper test**. Nothing goes live from this study.

## Result (run 11:27, `data/reports/backtests/timing_20261001_1127`): NO variant beats A

| Variant | n | Net per trade | Failed share | Calls / puts | Dev vs A | Val+test vs A | Verdict |
|---|---:|---:|---:|---|---:|---:|---|
| S1-A (current) | 269 | +154 | 36% | −161 / +445 | — | — | baseline (PASS, not ROBUST) |
| S1-B 1-min | 274 | +33 | **43%** | −234 / +271 | +37 | **−347** | worse |
| S1-C retest | 237 | +195 | 39% | **−75** / +454 | +80 | −13 | ≈ A |
| S1-D(A) no chase | 253 | +195 | 36% | −185 / +560 | +84 | −23 | ≈ A |
| S1-D(B) | 273 | −2 | 43% | −234 / +206 | −22 | −347 | worse |
| S2-A (current) | 316 | +285 | 46% | −35 / +657 | — | — | baseline |
| S2-B 1-min | 313 | +177 | 49% | −50 / +423 | −195 | +17 | worse |

**Learnings:**
1. Faster entry admits more fake breakouts (43% vs 36%) and loses more than the better price gains. The 5-minute confirmation is a useful filter.
2. The pre-run diagnostic ("0–2 min delay = +₹318") was survivorship: it only included breakouts that had already survived 5 minutes.
3. Retest and don't-chase are statistically indistinguishable from A. The retest halves call-side losses, which is worth revisiting when the call side is studied.
4. All 95% confidence intervals include zero.

**Decision:** keep A. The forward-test rules are unchanged.
