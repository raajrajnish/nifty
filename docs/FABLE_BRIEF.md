# Brief for an independent review (Claude Fable 5.1)

You are reviewing a research project, independently. The owner is paying for a more capable model and wants **value per token**. Read only what is listed, work in the phase order below, and **stop at the checkpoint** for the owner's decision.

## 1. The project in five lines
- `trading/suzlon/` is a **paper-only** Nifty options system (Python 3.12, uv, DuckDB, FastAPI dashboard). It records live Groww data and paper-trades two frozen setups, **G1** and **G2**, in "hypercare" (forward paper test). There is **no order-placement code**, and none may be added.
- Over 2026-09-30 → 2026-10-02 about **90 trading ideas** were tested. Each was pre-declared, used dev/validate/test splits and untouched data, and was compared with random controls. These covered Nifty options, Bank Nifty options, 10 stocks intraday and the Nifty 50 for swing trading.
- **Only G1 and G2 survived, and both are weak.**
  - G1: in-sample +₹833/trade, but it **failed** untouched Nifty 2021–23 and Bank Nifty.
  - G2: corrected in-sample **+₹300/trade**, not ROBUST, borderline on untouched data.
- **Four bugs or data faults were found late:**
  - G2's warm-up bug: an unknown 120-day median was counted as "calm";
  - Bank Nifty expiry dates mixed into the Nifty studies;
  - Groww 1-min stock prices ×100 on 2025-05-12;
  - **Groww daily candles broken from 2025** (open = previous close, then NULL).
  More may exist.
- The owner's goal: a few **validated** setups, about 3–4 trades a week across Nifty / Bank Nifty / stocks. Real money only after paper evidence.

## 2. Read first (in this order; skim code only as needed)
1. `docs/HYPERCARE_LOG.md`: current evidence, corrections, open observations.
2. `playbook/03_setups.md` and `config/setups.yaml`: G1/G2 definitions and evidence. `config/risk.yaml` and `config/costs.yaml`.
3. `docs/reports/`, newest first:
   - `2026-10-02_swing_study.md`, `2026-10-02_stock_pilot_study.md`, `2026-10-02_banknifty_search.md`, `2026-10-02_inside_day_study.md`, `2026-10-01_banknifty_g_validation.md`, `2026-10-01_internet_strategies_study.md`, `2026-10-01_popular_strategies_study.md`, `2026-10-01_discovery_study.md`, `2026-10-01_magnitude_study.md`;
   - then the earlier Nifty studies: exit, entry, entry_timing, followthrough, scorecard, setup_logic.
4. Code: `src/tradingagent/sim/` (the core is `exit_study.simulate`, `entry_study.day_features`, `timing_study.summarize_timing`); `src/tradingagent/paper/engine.py` (live paper engine); `src/tradingagent/data/{store,history}.py`.
5. `git log --oneline | head -40` for the history of decisions.

**Do not** read `.env` or print any token. Do not re-run the downloads (the data is already in `data/market.duckdb`).

## 3. Data available (`data/market.duckdb`, DuckDB, read-only for you)
- **Nifty:** 1-min index Oct 2021 – Oct 2026. Options 1-min Dec 2023 – Sep 2026 (ATM ±5 strikes per weekly expiry). India VIX 1-min/daily.
- **Bank Nifty:** 1-min index Oct 2021 – Oct 2026. Options Dec 2023 – Sep 2026: weekly until 2024-11-20, then **monthly only**.
- **Stocks:**
  - 10 stocks 1-min Oct 2021 – Sep 2026 (`config/stock_universe_2026-09-30.csv`);
  - all Nifty 50: daily Oct 2021 – Sep 2026 (**broken from 2025**: use `swing_study.rebuild_from_intraday`), plus 15-min Dec 2024 – Sep 2026.
- **Untouched data still available, use with care:**
  - Bank Nifty **lock box 1** (options Oct 2025 – Sep 2026);
  - Bank Nifty **lock box 2** (index Nov 2021 – Nov 2023, used only for G1/G2 and the inside-day ideas).
  - All Nifty history has been examined many times; **treat it as dev data.**
  - Future live recordings (`data/live/`) are the cleanest evidence.
- **Not held:** order book / OI history, news, results dates, FII/DII flows.

## 4. Mission (phases; stop at the checkpoint)

### Phase 1: Audit (highest priority)
Find anything that would change a conclusion. In particular:
1. **Look-ahead or timing errors:**
   - signal bar vs fill minute;
   - 5-min bar labelling;
   - `follow()` start price;
   - the use of the same-day high/low before it is known.
2. **Fill and cost realism:**
   - the half-spread 0.11% vs live recorded spreads (`data/live/`);
   - pessimistic stop fills;
   - Groww charges (`config/costs.yaml`);
   - lot sizes over time (Nifty 75→65?, Bank Nifty 15→30→35?);
   - strike selection.
3. **Data integrity beyond the four known faults:**
   - missing minutes;
   - option bars with stale prices;
   - expiry calendar holiday shifts;
   - timezone;
   - the 15:15+ index-feed problem.
4. **Statistics:**
   - multiple-testing accounting across ~90 ideas;
   - whether the pass bars are too strict or too loose;
   - overlapping trades (G1/G2 same day);
   - the bootstrap method.
5. **Live vs backtest:** does `paper/engine.py` implement exactly what the backtest measured (`scripts/check_paper_fidelity.py`)?

**Rules:**
- Reproduce before you claim.
- Each finding needs file:line, a concrete failing case, and its estimated impact on a stated result.
- Fix only with a unit test.
- **Do not change G1/G2 rules.** Rules are frozen (tag `v1-hypercare-freeze`); report instead.

### Phase 2: Verdict on G1/G2
Given the audit, are G1 and G2 worth continuing to paper-trade?
- Is there any cheap, **pre-declared** check left that would settle it faster than months of paper trading? For example: the cost sensitivity on real recorded spreads.
- Give a plain verdict: continue / continue with changes (as a new version, G1.v2 — never an edit) / stop.

### ⛔ CHECKPOINT: stop here
Write the report (section 6) and **ask the owner** before Phase 3.

### Phase 3: New ideas (only with the owner's go-ahead)
- **At most 5 hypotheses in total.** Each has an economic or market-structure reason **written before any test**, and draws on **information the previous ~90 ideas did not use**. Good directions:
  - option-chain positioning / open interest (needs live recording; check `data/live/`);
  - expiry-day behaviour (skipped so far);
  - event days (RBI, results);
  - the VIX term structure / intraday VIX moves;
  - Nifty vs Bank Nifty spread mean-reversion;
  - option-selling structures (**paper only**, and only as research; the system is buy-only by design, so flag this as an owner decision).
- **No more pure price-pattern mining on Nifty history.** It is exhausted, and more searching will only produce lucky false positives.
- Pre-declare each one in `docs/reports/<date>_<name>.md` (rules, data split, pass bar, multiple-testing count) **before** running it. Follow the existing pattern (see `banknifty_search.md`).
- The Bank Nifty lock boxes may be opened **once**, for at most 2 finalists. Nifty ideas must name their untouched evidence: forward paper days, or another instrument.
- Anything that passes → a **paper-only** candidate for the owner. Never live trading.

## 5. Hard rules
- **Paper only.** No order code, and no option selling in the live system.
- Never read or print `.env`; never ask for the Groww token in chat.
- Don't modify `SideHustle_Source_v0.5.1` or anything outside `trading/suzlon/`.
- Keep the repo green: `uv run pytest -q`, `uv run ruff check src tests scripts`, `uv run mypy src`. On Windows, set `PYTHONIOENCODING=utf-8` for CLI output.
- Commit locally with clear messages. **Ask the owner before pushing** to GitHub (`origin main`).
- Honesty over optimism. "Nothing works" is an acceptable answer; a lucky backtest presented as a winner is not.

## 6. Deliverable: `docs/reports/<date>_independent_review.md`
1. **For the owner (one screen, plain language, no jargon):**
   - what you found;
   - whether anything changes the earlier conclusions;
   - what to do next.
   The owner writes short informal messages and wants the bottom line first.
2. **Findings table:** severity, file:line, the failing case, the impact on a stated result, and fixed / not fixed.
3. **G1/G2 verdict**, with the reasoning.
4. **Phase 3 plan** (after the checkpoint): ≤ 5 hypotheses with their rationale, data, pass bar and expected cost in time.

**Budget guidance:** spend most effort on Phase 1. Phase 1 + 2 should take one focused session. Don't re-run long backtests unless an audit finding requires it; the previous outputs are saved in `data/reports/backtests/`.
