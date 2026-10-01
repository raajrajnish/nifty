# End of day (run after ~15:45): analyse today's recording, add today's candles to the database,
# then update the forward paper test of the frozen rules. All read-only — no orders.
$ErrorActionPreference = "Continue"   # see morning.ps1: "Stop" breaks on uv's stderr progress output
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$today = Get-Date -Format "yyyy-MM-dd"

Write-Host "=== tradingagent end of day ($today) ===" -ForegroundColor Cyan
if (Test-Path "data\raw\date=$today") {
    Write-Host "`n[1/3] Analysing today's recording..."
    & uv run --no-sync tradingagent analyze-day $today | Select-Object -Last 3
} else {
    Write-Host "`n[1/3] No recording for today (recorder not run?)" -ForegroundColor Yellow
}
Write-Host "`n[2/3] Adding today's candles to data\market.duckdb (only new data is fetched)..."
& uv run --no-sync tradingagent fetch-history --start 2023-12-01 | Select-String -Pattern "done:|STOPPED|index NSE"
Write-Host "`n[3/3] Forward paper test of frozen rules (candle-based)..."
& uv run --no-sync tradingagent forward-test
Write-Host "`nLive paper ledger (G1/G2, real recorded bid/ask):"
if (Test-Path "data\paper\live_trades.csv") { Import-Csv "data\paper\live_trades.csv" | Format-Table day, setup, side, strike, entry_px, exit_px, reason, net_inr -AutoSize }
else { Write-Host "  (no paper trades yet)" }
Read-Host "`nPress Enter to close"
