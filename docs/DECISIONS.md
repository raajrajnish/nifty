# DECISIONS.md — Architecture Decision Records

Format: ID · date · decision · why · status.

## ADR-001 · 2026-09-29 · Owner answers to DESIGN.md §12
- **Groww auth:** API key + secret with daily approval on the Groww Cloud page, then "Connect Groww". **No TOTP automation.** (Q3)
- **Risk config:** MASTER_PLAN §12 defaults confirmed: 1% per trade (₹2,000), 3% daily (₹6,000), 7% weekly, max 2 trades/day, max 2 lots. (Q5)
- **Telegram:** not requested. v1 uses the dashboard + CLI + `runtime/HALT` file for kill. Phone-reachable kill switch (MASTER_PLAN §15) is therefore **still open**. (Q2)
- Still open: Q1 (remote UI), Q4 (paid data plan), Q6 (LLM budget), Q7 (event calendar), Q8 (hosting), Q9 (legal).

## ADR-002 · 2026-09-29 · Local web dashboard (FastAPI + Jinja + vanilla JS + SSE)
- **Why:** it is a single Python process with no Node build, and it can be tested with TestClient. DESIGN.md said HTMX, but plain `fetch` + `EventSource` turned out simpler for this page count, so HTMX was dropped.
- **Chart:** lightweight-charts 4.2.0 from unpkg, which needs internet. It will be vendored into `ui/static/` before S1.
- **Safety:**
  - Localhost bind (enforced by config validation).
  - Host header allowlist (DNS rebinding) and Origin check on POST.
  - scrypt-hashed passphrase, a lockout after 5 failures in 5 minutes, and server-side sessions.
  - A CSRF token on every POST.
  - The UI can only connect, kill, resume, and log out. A test asserts there are no config/order/stop/qty endpoints.

## ADR-003 · 2026-09-29 · Repo root = `trading/suzlon/`; package `tradingagent`; `uv` for locking
Parent git repo is `Learning/`. This folder has its own `.gitignore` covering `.env`, `runtime/`, `data/`.

## ADR-004 · 2026-09-29 · Broker auth injected into Runtime via a Protocol
This keeps `ui/` and `orchestrator/` free of any import of `broker.auth`, which import-linter checks, including transitive imports. `cli.py` is the composition root.

## ADR-010 · 2026-10-01 · All loss limits are percentages; G1/G2 in HYPERCARE
- **Owner:** limits must follow tradeable money and the position actually bought, never fixed rupee values.
  - Stops: % of the premium paid.
  - Per-trade risk: % of **current equity**.
  - Daily loss: % of start-of-day equity.
  - Drawdown kill: % below peak equity.
- **Equity** = `capital_inr` + realised net P&L (paper ledger now; broker funds later). `risk.yaml: capital_basis: equity` (or `fixed`).
- Every paper trade records `premium_paid_inr`, `stop_pct_of_premium`, `risk_pct_of_equity`, `net_pct_of_premium` and `net_pct_of_equity`. The dashboard shows every limit as % first, with the rupee value it means right now.
- G1/G2 status is **HYPERCARE** (forward paper under close watch). The review triggers are declared in `playbook/03_setups.md`. The percentage values themselves (1% per trade, 3% daily, 10% drawdown) are unchanged pending the forward results.

## ADR-009 · 2026-10-01 · Live paper engine for G1/G2 on the dashboard
- `tradingagent paper` (started by the morning script) follows the recorder's files and runs the **same signal code as the backtest**, fed only complete 1-minute bars cut at the last complete 5-minute boundary. It fills at the recorded **ask** for entries and **bid** for exits. The ledger is `data/paper/live_trades.csv` (one row per day and setup). The dashboard panel reads `runtime/paper_state.json` every 3 s.
- **Fidelity check** (`scripts/check_paper_fidelity.py`): on 18 historical G1/G2 trades the live engine made the **same signal (side, strike, entry minute) and the same exit reason** as the backtest, 18/18. Rupee results differ slightly (latest-quote fill vs next-minute open).
- **Safety:** no order code. A recorder start after 09:16 (open unknown), an expiry day, or history more than 4 days stale → the setup is SKIPPED with the reason shown. The engine does not call Groww.

## ADR-008 · 2026-10-01 · G1 and G2 are the only setups (v1, forward paper only)
- `playbook/03_setups.md` (for the owner and the agent) and `config/setups.yaml` (for code) define **G1** (narrow-range ORB on open-outside days) and **G2** (TWAP pullback on calm open-outside days). `tests/unit/test_setups.py` fails if the playbook, the YAML and the evidence code disagree.
- Setups are versioned, never edited in place. A change becomes a new version with its own forward count.
- **Why:** the owner asked for a handful of fixed, well-defined setups. Every rule survived a pre-declared study; rejected ideas are listed in the playbook so they are not re-added by intuition.
- **Open owner decisions** (conflicts with `risk.yaml`, listed in the playbook):
  - `per_trade_risk_pct` 1% is below G1/G2's need of about 1.4–2.3% at 1 lot;
  - `max_open_positions` 1 is below the 2 that G1+G2 run together need;
  - the 10% drawdown kill is below the typical G1/G2 drawdown.

  None of these is changed until forward paper results exist.

## ADR-007 · 2026-09-30 · Historical data lives in a local DuckDB file (`data/market.duckdb`)
- `tradingagent fetch-history` downloads 1-minute candles for the NIFTY index and, for every weekly expiry, all strikes the ATM visited that week ±5. It also downloads daily index candles. It is read-only and resumable.
- A `coverage` table records every symbol and day requested, including empty days such as holidays or untraded far strikes. Reruns never refetch those. Days that failed are stored as `error` and are retried.
- 5-minute and 15-minute candles are derived from the 1-minute data, not downloaded separately. Candles after 15:30 (flat post-close rows) are dropped.
- **Why:** the owner asked that Groww not be re-queried for data already held. DuckDB is a single file with no server, fast for backtests over millions of rows, and was already the choice in DESIGN.md §4.3.
- **Known gap:** history has no bid/ask. Slippage comes from the daily recordings (`data/raw`). Historical **lot sizes are not in the candles**; the backtester needs a dated lot-size table `[VERIFY]`.

## ADR-006 · 2026-09-30 · Adopt lessons from the SideHustle review (docs/LESSONS_FROM_SIDEHUSTLE.md)
- Guardrail rules carry `authority: ENFORCE | SHADOW`, and every new rule starts as SHADOW. G16 (decision-time revalidation) and G17 (expected move vs cost) are added as SHADOW.
- Feed stall watchdog with generation ids, a spot-vs-futures consistency check, and per-instrument callback dedupe are built into `LiveFeed`/`Watchdog` (verified live in Phase 1).
- The recorder (bid/ask/depth) and a daily instrument-master snapshot with SHA-256 come first in Phase 1.
- Every trade is stamped with `config_hash` + `playbook_hash`; evaluation is per frozen version; MFE, MAE and the near-zero-MFE rate are tracked.
- Governance: a component that fails its phase gate never goes to paper.
- `.gitignore` covers all `*.env`, and a secret-scan test guards the repo.
- **Why:** SideHustle's live paper evidence (41 trades, −₹5,032, 44% never cleared costs) showed each of these failure modes on real Groww data.
- **Not adopted:** its "no LLM authority" rule. That is left as open question Q10, recommended to be decided by the Phase 7 replay evidence.

## ADR-005 · 2026-09-29 · HALT is a file (`runtime/HALT`) and survives restarts
Resume requires a written reason and returns to `BOOT`, never directly to trading.
