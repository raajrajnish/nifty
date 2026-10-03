# End of day (run after ~15:45): analyse today's recording, add today's candles to the database,
# update the forward tests, and score the 10-candidate forward tournament. All read-only — no orders.
$ErrorActionPreference = "Continue"   # see morning.ps1: "Stop" breaks on uv's stderr progress output
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$today = Get-Date -Format "yyyy-MM-dd"
$thisMonth = Get-Date -Format "yyyy-MM"
$plus2 = (Get-Date).AddMonths(2).ToString("yyyy-MM")

Write-Host "=== tradingagent end of day ($today) ===" -ForegroundColor Cyan
if (Test-Path "data\raw\date=$today") {
    Write-Host "`n[1/6] Analysing today's recording..."
    & uv run --no-sync tradingagent analyze-day $today | Select-Object -Last 3
} else {
    Write-Host "`n[1/6] No recording for today (recorder not run?)" -ForegroundColor Yellow
}
Write-Host "`n[2/6] Adding today's NIFTY candles (index + options) to data\market.duckdb..."
& uv run --no-sync tradingagent fetch-history --start 2023-12-01 | Select-String -Pattern "done:|STOPPED|index NSE"
Write-Host "`n[3/6] Tournament data: expiry dates, Bank Nifty (index + options), stocks..."
& uv run --no-sync python scripts/fetch_expiries.py $thisMonth $plus2 | Select-Object -Last 1
& uv run --no-sync tradingagent fetch-history --underlying BANKNIFTY --step 100 --start 2026-10-01 | Select-String -Pattern "done:|STOPPED"
& uv run --no-sync python scripts/fetch_stock_universe.py update | Select-String -Pattern "stock update|STOPPED"
Write-Host "`n[4/6] Forward paper test of frozen rules (candle-based)..."
& uv run --no-sync tradingagent forward-test
Write-Host "`n[5/6] Forward tournament (10 candidates, official candles; LLM asked about tomorrow's swing entries)..."
& uv run --no-sync tradingagent tournament-eod
Write-Host "`n[6/6] Live paper ledger (G1/G2, real recorded bid/ask):"
if (Test-Path "data\paper\live_trades.csv") { Import-Csv "data\paper\live_trades.csv" | Format-Table day, setup, side, strike, entry_px, exit_px, reason, net_inr -AutoSize }
else { Write-Host "  (no paper trades yet)" }
Read-Host "`nPress Enter to close"
