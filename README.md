# tradingagent — agentic intraday Nifty options (paper-first)

Spec: [MASTER_PLAN.md](MASTER_PLAN.md) · Design: [docs/DESIGN.md](docs/DESIGN.md) · Decisions: [docs/DECISIONS.md](docs/DECISIONS.md)

**Status: Phase 0.** There is no trading, no data and no agent yet. It has config validation, the dashboard, the Groww login step, and a kill switch.
Nothing here is financial advice.

## Setup (once)
```powershell
uv sync --extra broker              # installs deps + growwapi
copy .env.example .env              # then edit .env: GROWW_API_KEY, GROWW_API_SECRET
uv run tradingagent ui-set-passphrase
uv run tradingagent check-config
```
Never paste keys into chat, commits, or logs. `.env` is gitignored.

## Every morning (how you log in)
1. Approve your API key on the **Groww Cloud → API Keys** page.
2. `uv run tradingagent ui` → open http://127.0.0.1:8750 → enter your dashboard passphrase.
3. Click **Connect Groww**. The dot turns green. If it fails, the banner says why (usually the key isn't approved yet).
   CLI alternative: `uv run tradingagent auth`.

`uv run tradingagent ui --demo` streams **synthetic** candles, clearly labelled DEMO, so you can try the dashboard.

## Kill switch
Any one of these works:
- Dashboard **KILL** button (type `KILL` to confirm).
- `uv run tradingagent kill --reason "..."`.
- Create the file `runtime/HALT`.

To resume, run `uv run tradingagent resume --reason "..."` or use the dashboard Resume button.

## Checks
```powershell
uv run pytest -q; uv run ruff check src tests; uv run mypy src; uv run lint-imports
```
