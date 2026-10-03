# One-time setup: save your Anthropic API key to .env for the LLM shadow filter.
# The key is typed hidden, checked for shape, saved to .env and never printed. Re-run to replace it.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$envFile = Join-Path $root ".env"
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Say($msg, $color = "White") { Write-Host $msg -ForegroundColor $color }

Say "LLM shadow filter - Anthropic API key setup" Cyan
Say "Create a key at console.anthropic.com -> API Keys. Paste it below (typing is hidden; right-click to paste)."
$secure = Read-Host "Anthropic API key" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }

if (-not $key) { Say "Nothing entered - .env NOT changed." Yellow; Read-Host "Press Enter to close"; exit 1 }
if (-not $key.StartsWith("sk-ant-") -or $key.Length -lt 40) {
    Say "That doesn't look like an Anthropic API key (expected to start with 'sk-ant-'). .env NOT changed." Red
    $key = $null; Read-Host "Press Enter to close"; exit 1
}
$lines = @()
if (Test-Path $envFile) { $lines = [IO.File]::ReadAllLines($envFile) }
$found = $false
$lines = $lines | ForEach-Object {
    if ($_ -match '^\s*ANTHROPIC_API_KEY=') { $found = $true; "ANTHROPIC_API_KEY=$key" } else { $_ }
}
if (-not $found) { $lines = @($lines) + "ANTHROPIC_API_KEY=$key" }
[IO.File]::WriteAllLines($envFile, [string[]]$lines, $utf8)
$key = $null
Say "Key saved to .env." Green
Say "`nOptional check (one real call, costs about Rs 1-3):" Cyan
& uv run tradingagent llm-shadow-check
Read-Host "`nPress Enter to close"
