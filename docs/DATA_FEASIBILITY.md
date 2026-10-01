# DATA_FEASIBILITY.md — what Groww actually provides (Phase 1)

Status: **started 2026-09-30.** Facts below were verified live with the owner's Groww token (read-only calls). Items not yet probed stay open.

## Verified facts

| Item | Result | How verified |
|---|---|---|
| Auth | A single daily access token works via `GrowwAPI(token)`; validated with `get_user_profile()` | live, 2026-09-29/30 |
| Nifty option lot size | **65** | instrument master, 2026-09-30 |
| Tick size | options 0.05, futures 0.10; freeze qty 1,801 | instrument master |
| Weekly expiry | **Tuesday**, holiday-shifted. Oct 2026: 06, 13, **19 (Mon)**, 27 | `get_expiries` |
| Monthly future | `NIFTY26OCTFUT` (27 Oct), basis ≈ +112 pts vs index | instrument master, `get_ltp` |
| Index / VIX LTP | `get_ltp(("NSE_NIFTY","NSE_INDIAVIX"), CASH)`, about 0.4 s | live |
| F&O LTP (multi) | `get_ltp(("NSE_<trading_symbol>",...), FNO)`, one call for 23 symbols | live |
| Option chain | `get_option_chain(NSE,"NIFTY",expiry)`: **all strikes** with LTP, OI, volume, IV, delta/gamma/theta/vega/rho in about 0.6 s. **No bid/ask.** | live |
| Bid/ask depth | `get_quote(symbol, NSE, FNO)` → **5 levels** of bid/ask depth, OI, volume, last trade time. Top-level `bid_price`/`offer_price` fields are null; use `depth` | live |
| REST reliability | 16 errors in about 47k calls on 2026-09-30 (0.03%), all "400 Bad Request" on random calls; they succeed on retry | recorder day 1 |
| **Index feed near close** | **Froze 15:15:01–15:20:03, then printed bad values** (22,514.95, about 100 pts off) for about 20 s while the future was steady. See day-1 report | recorder day 1 |

## Historical candles (probed 2026-09-30, `scripts/probe_history.py`; raw output in `data/probes/`)

Call: `get_historical_candles(exchange, segment, groww_symbol, "YYYY-MM-DD HH:MM:SS", …, "1minute"|"5minute"|…)`.
Candles come as `[iso_ts, open, high, low, close, volume, oi]`. Index candles have volume and OI set to `None`.

| Item | Result |
|---|---|
| Groww symbols | index `NSE-NIFTY` (CASH); future `NSE-NIFTY-27Oct26-FUT`; option `NSE-NIFTY-06Oct26-22700-CE` (FNO) |
| **Index 1/5/15-min depth** | **back to at least Oct 2021 (about 5 years)**; 376 × 1-min candles per day = 09:15–15:30 |
| Max window per request | 1-min and 5-min: **30 days**; 15-min: **90 days**; 1-day: **180 days** (Groww error text) |
| Expired futures | available (checked May–Sep 2026) with volume and OI |
| **Expired options** | **available back to at least Dec 2023 (about 3 years)**: OHLC, volume and OI. Jun 2023 returned nothing |
| Option history has bid/ask? | **No.** Backtests must model the spread, using spreads from the daily recordings (2026-09-30 ATM median 0.22%) |
| Post-close candles | extra flat 15:35/15:40 candles on options; the backtester must drop candles after 15:30 |
| Expiry shifts | Mar-2026 monthly expired **Mon 30 Mar** (not Tue 31); Oct 2026 has Mon 19. Always take expiries from Groww |
| Weekday change | expiries before Sep 2025 were **Thursdays** (for example 26 Jun 25, 30 Jan 25) |

**Implication:** exit and entry rules can be tested on about **700 trading days** of real Nifty option prices, not just on our own recordings. The spread and slippage calibration comes from the recordings.

## Open (to probe)
- Rate limits (documented values and behaviour on breach).
- Websocket feed: latency and stall behaviour (SideHustle lesson L5).
- Order types for options (from documentation only; nothing is placed).
- Official charges for `costs.yaml`, with sources and dates.

## Recording
The `tradingagent record` command writes `data/raw/date=YYYY-MM-DD/` with these streams:
- `ltp`: every 2 s
- `quotes`: 5-level depth for the future and ATM ±5 CE/PE, about every 10 s each
- `chain`: ATM ±20, every 60 s
- the daily instrument master with its SHA-256

This is about 41 MB per day as JSONL. `tradingagent analyze-day YYYY-MM-DD` produces `data/reports/date=…/`.
