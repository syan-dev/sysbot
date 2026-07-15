#Requires -Version 5.1
# SysBot uninstall script — Windows
# Usage (PowerShell): .\scripts\uninstall.ps1
# If execution policy blocks it: powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1

$ErrorActionPreference = 'Stop'

function Info ($msg) { Write-Host "  ->  $msg" -ForegroundColor Cyan }
function Ok   ($msg) { Write-Host "  v  $msg"  -ForegroundColor Green }
function Warn ($msg) { Write-Host "  !  $msg"  -ForegroundColor Yellow }
function Hr   ()     { Write-Host ("─" * 60) }

Hr
Write-Host "  SysBot Uninstaller" -ForegroundColor White
Hr

# ── 1. Remove Task Scheduler entry ───────────────────────────────────────────
$TaskName = "SysBot"
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask  -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Ok "Scheduled task '$TaskName' removed"
} else {
    Warn "No scheduled task '$TaskName' found — skipping"
}

# ── 2. Uninstall Python package ───────────────────────────────────────────────
Info "Removing sysbot package ..."
try {
    $check = & python -m pip show sysbot 2>&1
    if ($LASTEXITCODE -eq 0) {
        & python -m pip uninstall sysbot -y --quiet
        Ok "Package uninstalled"
    } else {
        Warn "Package not found in pip — skipping"
    }
} catch {
    Warn "Python not found — package not removed"
}

# ── 3. Per-user data home (config, tools, logs) ──────────────────────────────
$DataDir = if ($env:SYSBOT_HOME) { $env:SYSBOT_HOME } else { Join-Path $HOME ".sysbot" }
if (Test-Path $DataDir) {
    $resp = Read-Host "  Remove your config, tools and logs in $DataDir? [y/N]"
    if ($resp -match '^[Yy]') {
        Remove-Item -Recurse -Force $DataDir
        Ok "Removed $DataDir"
    } else {
        Info "Kept $DataDir (edit or delete it manually later)"
    }
}

Hr
Ok "SysBot has been uninstalled."
Write-Host ""
Write-Host "  Optional cleanup:"
Write-Host "    Remove-Item -Recurse -Force $DataDir     # config, tools and logs"
Write-Host ""
