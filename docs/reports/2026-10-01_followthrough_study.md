# Follow-through exit study (PRE-DECLARED 2026-10-01, before running)

**From the scorecard:** when the index has not moved our way within 15 minutes of entry, trades win 26% of the time and average −₹733 per trade (S1). When it has moved our way, they win 57% and average +₹1,174.

**Hypothesis:** exiting trades that show no follow-through, while holding the rest, improves net per trade.

**Rule FT-k:** k minutes after entry, compare the index close with the index level at entry (the open of the entry minute).
- If it has **not** moved in the trade's direction (≤ 0 for a call, ≥ 0 for a put), **exit at the next minute's open** (reason `NO_FOLLOW_THROUGH`).
- Otherwise keep the trade under the setup's existing rules: S1 opposite-side failure plus −50% stop; S2 hold plus −30% stop; RANDOM hold plus −30% stop. **No profit lock**, because winners peak late.
- The check runs **once**, at minute k.

**Variants:** FT-10, **FT-15 (primary)**, FT-20, each compared with the baseline (no check). Applied to S1, S2 and RANDOM. Entries, costs and fills are as in all earlier studies.

**Decision rule (fixed in advance):**
- **FT-15 is adopted** only if it beats the baseline on net per trade for **both S1 and S2**, on dev days **and** on validate+test combined.
- FT-10 and FT-20 are **sensitivity checks only**. If FT-15 wins but its neighbours don't, it is treated as a lucky number and **not** adopted.
- Also reported: the share of trades cut, the **false cuts** (cut trades whose option was above the entry price at 15:10), the average result of cut trades compared with the same trades under the baseline, PASS/ROBUST, and 95% confidence intervals.

**Expectation, stated in advance:** it should help RANDOM too, because it is a trade-management rule, not a direction edge. It cannot fix the weak setup logic.

## Result (run 12:35, `followthrough_20261001_1235`): REJECTED. ADOPT FT-15 = False

| | base | FT-10 | FT-15 | FT-20 |
|---|---:|---:|---:|---:|
| S1 net per trade | **+154** | −120 | −12 | +68 |
| S2 net per trade | **+285** | +178 | +146 | +236 |
| RANDOM | −37 | −38 | −23 | −54 |

**Why:** cut trades lose **more** when cut than when held. For S1-FT15, the cut trades averaged −₹828 against −₹497 for the same trades held to the baseline exit; for S2-FT15, −₹790 against −₹499. Also, 34–40% of cut trades finished above entry by 15:10.

**Lesson:** follow-through *predicts* outcomes (scorecard R1), but by the time it is known, non-follow-through trades are near their worst point. Acting on it locks in the low.

**Consistent finding across exit study #1, the stop study and this study:** for these setups, give trades room and hold (failure rule plus a wide safety stop). Tight management, profit locks and early cuts all reduce results.
