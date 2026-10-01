# Lessons from SideHustle (BANKNIFTY) applied to this project

Source: read-only review of `Learning/SideHustle_Source_v0.5.1` on 2026-09-30 (v0.5.1.5, 41 diagnostic paper trades, 16 sessions, Sep 2–29 2026). No SideHustle code or data is imported; these are *lessons*, re-implemented here and verified against our own Groww tests.

**Its headline evidence:** net −₹5,032 on 1 lot. That is gross −₹1,511 plus ₹3,521 of costs; profit factor 0.65; 44% of trades never moved further in their favour than their round-trip costs. The model driving entries had already failed its own development gates, scoring 0.52 on a scale where 0.50 is a coin flip.

**Status legend:** ✅ done in code · 📐 written into DESIGN.md (built in the phase shown) · 🧪 hypothesis, logged in shadow mode first

| # | Lesson (what happened there) | Change here | Status |
|---|---|---|---|
| L1 | A live Groww token **and API secret** sat in `runtime.env`, which `.gitignore` did not cover. | `.gitignore` ignores every `*.env` / `*.env.*` except `.env.example`. A unit test scans the repo for secret-looking values and fails the build. | ✅ Phase 0 |
| L2 | Universal hard thresholds (option chase above 2%, cost burden above 1.5%) **rejected large winners** when tested. SideHustle demoted them to "shadow" diagnostics. | Every guardrail rule carries an `authority`: `ENFORCE` rules can reject, while `SHADOW` rules are computed and logged but never block. **New rules start as SHADOW** and are promoted only with written evidence (ADR). | ✅ type · 📐 Phase 6 |
| L3 | "Move consumed during confirmation": the signal was right, but by the time it could actually be traded, most of the move had already happened. | New rule **G16 decision-time revalidation**: re-check index move and premium since the evidence candle, at the moment of entry. Starts as SHADOW. | 📐🧪 Phase 6 |
| L4 | Costs were about 70% of the loss (≈₹86/trade against a median best move of ₹152), and 44% of trades never moved further than their costs. | New rule **G17 expected move vs cost**: the target's premium gain must be at least k × round-trip cost. SHADOW first, because L2 shows fixed thresholds misfire. Metrics add **MFE, MAE, and the "near-zero-MFE rate"** (MFE ≤ cost). | 📐🧪 Phase 3/6 |
| L5 | The Groww websocket can **stall silently**, with no callbacks and no exception. Late callbacks from a replaced socket arrive afterwards. | `LiveFeed` gets a stall watchdog on callback age, then recycles with a **generation id**; callbacks from an old generation are dropped. Trading authority returns only after N fresh callbacks. | 📐 Phase 1 (verify live) |
| L6 | The index stream can be *fresh but wrong or frozen*. | **Spot vs futures consistency** check in the watchdog and G04: if the index is flat or diverging while the futures price moves, block entries and recycle the feed. | 📐 Phase 1/6 |
| L7 | The SDK callback can deliver a cached multi-instrument snapshot, causing duplicate event storms. SideHustle used the callback's `feed_key`. | `LiveFeed` dedupes per instrument using the callback metadata key and bounds the emit rate. The decision path runs *before* archival writes. | 📐 Phase 1 (verify live) |
| L8 | Groww history has no bid/ask, so executable replay needs self-recorded quotes. | Recorder moved to the **first Phase 1 deliverable**, capturing bid/ask/depth for ATM ±N strikes; not just chain snapshots. | 📐 Phase 1 |
| L9 | The instrument list and lot size change over time; SideHustle saves the master list daily with a hash. | Save the Groww instrument master **daily with a SHA-256**; every trade references the snapshot hash it used. | 📐 Phase 1 |
| L10 | Five releases in about four weeks, with thresholds tuned on already-inspected days. The 41 trades mix rule versions, so they can't be evaluated as one group. | Every decision and trade is stamped with `config_hash` **and** `playbook_hash`. Evaluation is **per frozen version**. Rules are never tuned on days that will be used to evaluate them. | 📐 Phase 5/8 |
| L11 | A component that had **failed its development gate** still drove paper trades, so the paper P&L mostly measured a known-bad model. | Hard rule: nothing reaches S1 paper unless its phase gate passed. A failed gate means revise or stop, not "paper-trade and see". | 📐 governance |
| L12 | Its core hypothesis (weighted bank-constituent pressure) was never tested, because the verified weights were never loaded. | Every `[VERIFY]` input that a hypothesis depends on is listed in `DATA_FEASIBILITY.md` with a status. A hypothesis whose inputs are missing is reported as **untested**, never as failed or passed. | 📐 Phase 1 |
| L13 | A fixed 10-minute exit on 1 lot made even the gross result negative. | We keep thesis-based stops plus a time stop. Baselines are **also** backtested with several holding times, so the exit rule isn't assumed. | 📐 Phase 4 |
| L14 | More than 60 release/validation files cluttered the repo root, there was a duplicated 77 KB script, and the docs were Linux-only. | Reports go under `docs/reports/`, one runbook, Windows-first (already in place: `Start Trading.cmd`). | 📐 hygiene |

## Deliberately *not* copied

- **The "no AI in decisions" charter rule.** Our design already keeps the AI inside code-enforced guardrails, with the watchdog handling all hard exits. Whether to go further is an **owner decision** (DESIGN.md §12, Q10), not something to copy silently.
- **Their state model and ML stack.** Its evidence so far is negative, and our plan is to beat simple baselines first.
- **Their thresholds.** The values were tuned on BANKNIFTY development days, so they are not transferable to Nifty.
