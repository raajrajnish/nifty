# LLM "take / skip" shadow filter for G1/G2 (PRE-DECLARED 2026-10-03, before anything was built or run)

**Question:** can an LLM, reading the day's context (news, events, market state), tell which G1/G2 signals to skip, so that the filtered results beat taking every signal?
**Why this test is forward only:** an LLM's training data covers past markets, so it may "know" what happened on historical dates (look-ahead that can't be removed). Only decisions recorded **before** the outcome, on future days, are honest evidence.

## What it is, and what it is not
- **Shadow mode:**
  - the paper engine still takes **every** G1/G2 trade exactly as today;
  - the LLM's decision is only **recorded** next to it;
  - it never changes, delays or blocks a paper trade.
- **No orders, no live money,** no change to G1/G2 rules or to the paper engine's decisions.
- **Failure-safe:** if the API is down, slow or over budget, the engine carries on and the record says "no decision".

## When it is asked (two calls per signal day at most, plus one morning call)
1. **Morning context (≈ 09:05, every trading day):**
   - a short "risk of the day" note: scheduled events, overnight global moves, major news;
   - an index-level view: normal / event-risk / avoid.
   - Recorded every day, signal or not.
2. **At each G1/G2 signal** (when the setup's entry fires, at most one per setup per day): **TAKE or SKIP**, a confidence (0–1) and 2–4 short reasons. It must be written to the log **before the trade's exit**; the record is timestamped and checked.

## What it reads (fixed list)
1. **Market facts from the engine** (no interpretation):
   - Nifty level, gap vs yesterday's close, open outside / inside yesterday's range, opening range and its width;
   - VIX level and change, TWAP;
   - the setup's name, side (CE/PE), strike, premium, entry time;
   - days to expiry; day of week.
2. **Event calendar** (`config/event_calendar.yaml`, maintained by hand): RBI policy days, Union Budget, US Fed / US CPI days, major Nifty heavyweight results, election results.
3. **Live web search** (the API's built-in search tool), limited to the last 24 h: Indian market news, global markets overnight, major macro headlines. Sources (URLs) are saved with the decision.
4. **The setup's plain-language description** (from the playbook) and its known weaknesses (from the hypercare log), so that it judges *this* setup, not trading in general.

**Not given:** the trade's outcome, later prices, or any backtest of the specific day.

## Model and cost (owner to confirm)
- **Model:** Claude Sonnet 5.5 (`claude-sonnet-5-5`) by default: a strong reasoning-to-cost balance. Optionally, run Opus 5.5 on the same calls for comparison (doubles cost).
- **Budget cap:** at most 12 calls per day, with a hard monthly token cap set in config. If over the cap → "no decision". The expected cost is small: about 1–3 calls per trading day.
- **API key:** `ANTHROPIC_API_KEY` entered in the morning window and stored in `.env`, exactly like the Groww token. **Never pasted in chat.**

## Record (one JSON line per decision, `data/paper/llm_shadow.jsonl`)
`day, kind (morning|signal), setup, signal_ts, side, strike, decision (TAKE|SKIP|NO_DECISION), confidence, reasons[], sources[], model, prompt_version, input_hash, decided_at, latency_s, tokens_in/out, cost_inr`.

The prompt text is versioned (`prompt_version`). **Changing the prompt starts a new evaluation count**; the old and new versions are never pooled.

## Evaluation (fixed now)
- **When:** after **30 G1+G2 signals with a recorded decision**, or on **2027-02-28**, whichever comes first (expected ≈ 4 months at ~1.7 signals/week).
- **Primary test (one hypothesis):** mean paper net ₹ of **TAKE** trades minus mean of **SKIP** trades.
  - **The filter "adds value"** if all of these hold:
    1. the difference is > 0 with a bootstrap 95% CI lower bound > 0;
    2. the total P&L of TAKE-only ≥ the total P&L of all trades;
    3. the skip rate is between 10% and 60% (never skipping, or skipping almost everything, proves nothing).
  - Otherwise → **no value**; the filter is not used.
- **Secondary (information only, cannot rescue a fail):**
  - confidence calibration (do high-confidence calls do better?);
  - the morning "avoid" days vs other days;
  - Sonnet vs Opus agreement, if both run.
- **Honest caveat:** 30 signals is a small sample. A pass would justify continuing the shadow test to ~60 signals before the filter is allowed to influence anything. A fail at 30 with the TAKE − SKIP difference ≤ 0 ends it.

## Owner decisions needed before building
1. Model: Sonnet 5.5 only (recommended), or Sonnet + Opus side by side.
2. The monthly budget cap.
3. An Anthropic API key (entered in the morning window, never in chat).
4. Who maintains `config/event_calendar.yaml` (a starter list for Oct–Dec 2026 can be prepared, but dates must be verified from official sources).
