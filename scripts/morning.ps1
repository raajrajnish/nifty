# Morning start: ask for today's Groww access token (hidden input), save it to .env,
# verify it with Groww, (re)start the dashboard server and open the browser.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\morning.ps1 [-Demo] [-KeepToken]
param(
    [switch]$Demo,       # stream synthetic, clearly-labelled DEMO candles
    [switch]$KeepToken   # skip the prompt and reuse the token already in .env
)
# "Continue", not "Stop": in Windows PowerShell 5.1, "Stop" turns any stderr text from native tools
# (uv prints progress to stderr) into a fatal error. Failures are checked explicitly via $LASTEXITCODE.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$envFile = Join-Path $root ".env"
$port = 8750
$url = "http://127.0.0.1:$port"
$utf8 = New-Object System.Text.UTF8Encoding($false)   # no BOM

function Say($msg, $color = "Gray") { Write-Host $msg -ForegroundColor $color }

Say "=== tradingagent morning start ===" Cyan
Say "Never paste your token into chat. It is only saved to .env on this computer.`n"

# 1. .env exists
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $root ".env.example") $envFile }

# 2. Ask for today's token (hidden), write it into .env
if (-not $KeepToken) {
    Say "Generate today's access token on the Groww Cloud API Keys page, then paste it here."
    Say "(Typing is hidden. Press Enter on an empty line to keep the token already saved.)" DarkGray
    $secure = Read-Host "Groww access token" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

    if ($token) {
        # Shape check: a Groww access token is a ~1100-char JWT with 3 dot-separated parts.
        # (2026-10-01: a 2-character stray input overwrote a working token — never again.)
        if ($token.Length -lt 200 -or ($token -split '\.').Count -ne 3) {
            Say "That doesn't look like a Groww access token ($($token.Length) characters; expected ~1100 in 3 parts)." Red
            Say "The saved token was NOT changed. Tip: right-click in this window to paste." Yellow
            $token = $null
            Read-Host "Press Enter to close"
            exit 1
        }
        # Test the NEW token before touching .env: the child process sees it via the environment
        # (python-dotenv does not override variables that are already set).
        Say "`nChecking the new token with Groww..."
        $env:GROWW_ACCESS_TOKEN = $token
        & uv run tradingagent auth
        $ok = ($LASTEXITCODE -eq 0)
        Remove-Item Env:GROWW_ACCESS_TOKEN
        if (-not $ok) {
            $token = $null
            Say "`nGroww rejected the new token. The saved token was NOT changed." Red
            Read-Host "Press Enter to close"
            exit 1
        }
        $lines = [IO.File]::ReadAllLines($envFile)
        $found = $false
        $lines = $lines | ForEach-Object {
            if ($_ -match '^\s*GROWW_ACCESS_TOKEN=') { $found = $true; "GROWW_ACCESS_TOKEN=$token" } else { $_ }
        }
        if (-not $found) { $lines = @($lines) + "GROWW_ACCESS_TOKEN=$token" }
        [IO.File]::WriteAllLines($envFile, [string[]]$lines, $utf8)
        $token = $null
        Say "New token verified and saved to .env." Green
    } else {
        Say "Keeping the saved token."
    }
}

# 3. Verify with Groww before starting anything
Say "`nChecking token with Groww..."
& uv run tradingagent auth
if ($LASTEXITCODE -ne 0) {
    Say "`nGroww login FAILED. The token is probably expired or mistyped. Run this again with a fresh token." Red
    Read-Host "Press Enter to close"
    exit 1
}

# 4. Dashboard passphrase (first run only, and only if login is enabled in config\ui.yaml)
$loginOff = Select-String -Path (Join-Path $root "config\ui.yaml") -Pattern '^\s*require_login:\s*false' -Quiet
if (-not $loginOff -and -not (Test-Path (Join-Path $root "runtime\ui_auth.json"))) {
    Say "`nFirst run: choose a dashboard passphrase (min 10 characters)." Yellow
    & uv run tradingagent ui-set-passphrase
    if ($LASTEXITCODE -ne 0) { Read-Host "Passphrase not set. Press Enter to close"; exit 1 }
}

# 5. Stop any server already on the port (restart)
$listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($l in $listeners) {
    Say "Stopping running dashboard (PID $($l.OwningProcess))..."
    Stop-Process -Id $l.OwningProcess -Force -ErrorAction SilentlyContinue
}
if ($listeners) { Start-Sleep -Seconds 1 }

# 6. Start the server in its own minimized window (close that window to stop it)
$uiArgs = "run tradingagent ui"
if ($Demo) { $uiArgs += " --demo" }
Start-Process -FilePath "powershell" -WorkingDirectory $root -WindowStyle Minimized `
    -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle='tradingagent server'; uv $uiArgs"

# 6b. (Re)start the read-only NIFTY recorder in its own minimized window (it waits for 09:14, stops 15:31)
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'tradingagent(\.exe"?)? record' -or $_.CommandLine -match "WindowTitle='tradingagent recorder'"
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Process -FilePath "powershell" -WorkingDirectory $root -WindowStyle Minimized `
    -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle='tradingagent recorder'; uv run tradingagent record"
Say "Recorder started (window 'tradingagent recorder'; data in data\raw\date=<today>)."

# 6c. (Re)start the G1/G2 paper engine — reads the recorder's files, PAPER ONLY (no orders)
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match 'tradingagent(\.exe"?)? paper' -or $_.CommandLine -match "WindowTitle='tradingagent paper'"
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Process -FilePath "powershell" -WorkingDirectory $root -WindowStyle Minimized `
    -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle='tradingagent paper'; uv run tradingagent paper"
Say "G1/G2 paper engine started (window 'tradingagent paper'; shown on the dashboard)."

# 7. Wait until it answers, then open the browser
Say "Starting dashboard..."
$up = $false
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest "$url/healthz" -UseBasicParsing -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $up = $true; break }
    } catch { }
}
if (-not $up) {
    Say "Server did not start. Open the minimized 'tradingagent server' window to see the error." Red
    Read-Host "Press Enter to close"
    exit 1
}
Start-Process $url
Say "`nDashboard running at $url  (Groww connects automatically on startup)." Green
Say "To stop it: close the 'tradingagent server' window."
Start-Sleep -Seconds 4
