#Requires -Version 5.1
# SysBot install script — Windows
# Usage: .\scripts\install.ps1
# If blocked by execution policy: powershell -ExecutionPolicy Bypass -File scripts\install.ps1

param(
    [switch]$NoService   # Install package only; skip Task Scheduler setup
)

$ErrorActionPreference = 'Stop'

# ── helpers ───────────────────────────────────────────────────────────────────
function Ok      ($m) { Write-Host "  v  $m" -ForegroundColor Green }
function Warn    ($m) { Write-Host "  !  $m" -ForegroundColor Yellow }
function Die     ($m) { Write-Host "  x  $m" -ForegroundColor Red; exit 1 }
function Section ($m) {
    Write-Host ""
    Write-Host "  $m" -ForegroundColor Cyan -NoNewline
    Write-Host ""
    Write-Host ("  " + ("─" * 50))
}
function Hr { Write-Host ("  " + ("─" * 50)) }

function Ask {
    param([string]$Prompt, [string]$Default = "")
    $hint = if ($Default) { " [$Default]" } else { "" }
    $answer = Read-Host "  ?  $Prompt$hint"
    if ([string]::IsNullOrWhiteSpace($answer)) { $Default } else { $answer.Trim() }
}

function AskYN {
    param([string]$Prompt, [bool]$Default = $true)
    $hint = if ($Default) { "[Y/n]" } else { "[y/N]" }
    $answer = Read-Host "  ?  $Prompt $hint"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    $answer.Trim().ToLower() -like "y*"
}

function Menu {
    param([int]$Default = 1, [string[]]$Options)
    $n = $Options.Count

    # Fall back to a typed prompt when keystroke reading isn't available
    # (redirected input, ISE, or a non-interactive host).
    $canKeys = -not [Console]::IsInputRedirected -and $Host.Name -notmatch 'ISE'
    if (-not $canKeys) {
        $i = 1
        foreach ($opt in $Options) { Write-Host "    $i) $opt"; $i++ }
        Write-Host ""
        $raw = Ask "Choice" "$Default"
        $num = 0
        if ([int]::TryParse($raw, [ref]$num) -and $num -ge 1 -and $num -le $n) { return $num }
        return $Default
    }

    $sel = $Default - 1
    if ($sel -lt 0 -or $sel -ge $n) { $sel = 0 }

    Write-Host "  ?  Use Up/Down then Enter, or press a number:" -ForegroundColor Cyan

    function Draw {
        for ($j = 0; $j -lt $n; $j++) {
            if ($j -eq $sel) { Write-Host ("  > " + $Options[$j]) -ForegroundColor Cyan }
            else            { Write-Host ("    " + $Options[$j]) }
        }
    }

    [Console]::CursorVisible = $false
    try {
        $startY = [Console]::CursorTop
        Draw
        $endY = [Console]::CursorTop
        while ($true) {
            $key = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
            switch ($key.VirtualKeyCode) {
                38 { $sel = ($sel - 1 + $n) % $n }   # Up arrow
                40 { $sel = ($sel + 1) % $n }         # Down arrow
                13 { return ($sel + 1) }              # Enter confirms
                default {
                    if ($key.Character -match '[1-9]') {
                        $d = [int][string]$key.Character
                        if ($d -ge 1 -and $d -le $n) { $sel = $d - 1 }
                    }
                }
            }
            # Blank the rows actually drawn last time (tracked via the real
            # cursor position, so a wrapped label can't leave a ghost), then
            # redraw from the top.
            $blank = ' ' * [Console]::WindowWidth
            for ($r = $startY; $r -lt $endY; $r++) {
                [Console]::SetCursorPosition(0, $r); [Console]::Write($blank)
            }
            [Console]::SetCursorPosition(0, $startY)
            Draw
            $endY = [Console]::CursorTop
        }
    } finally {
        [Console]::CursorVisible = $true
    }
}

# ── Ollama helpers ──────────────────────────────────────────────────────────
# Installed Ollama model names (empty array if none / no server).
function Get-OllamaModels {
    try { $out = & ollama list 2>$null } catch { return @() }
    if (-not $out) { return @() }
    $models = foreach ($line in ($out | Select-Object -Skip 1)) {
        $name = ($line.Trim() -split '\s+')[0]
        if ($name) { $name }
    }
    return @($models)
}

# Pull a model, streaming progress to the console. Returns $true on success.
function Invoke-OllamaPull {
    param([string]$Model)
    Write-Host ""
    Write-Host "  Pulling $Model ... this can take a few minutes."
    Write-Host ""
    & ollama pull $Model
    if ($LASTEXITCODE -eq 0) { Ok "Pulled $Model"; return $true }
    Warn "Could not pull $Model — you can do it later with: ollama pull $Model"
    return $false
}

# Interactive Ollama model picker. Returns the chosen model name.
function Select-OllamaModel {
    $default = "llama3.2"

    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Warn "Ollama CLI not found on PATH."
        Write-Host "  Install it from https://ollama.com, then re-run."
        Write-Host "  For now you can name a model to use once Ollama is available."
        return (Ask "Model name" $default)
    }

    $models = Get-OllamaModels
    if ($models.Count -eq 0) {
        Warn "No Ollama models are installed yet."
        $m = Ask "Model to download now" $default
        [void](Invoke-OllamaPull $m)
        return $m
    }

    Write-Host ""
    Write-Host "  Choose an Ollama model (pick one or pull a new one):"
    $options = @($models) + @("Pull a different model (enter a name)")
    $choice  = Menu -Default 1 -Options $options
    if ($choice -eq $options.Count) {
        $m = Ask "Model name to pull (e.g. llama3.2, qwen3.5, gemma3:4b)" $default
        [void](Invoke-OllamaPull $m)
        return $m
    }
    return $models[$choice - 1]
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir   = Split-Path -Parent $ScriptDir

Clear-Host
Write-Host ""
Hr
Write-Host ""
Write-Host "  SysBot Setup" -ForegroundColor White -NoNewline
Write-Host ""
Hr

# ═══════════════════════════════════════════════════════════════════════════════
# 1. PYTHON
# ═══════════════════════════════════════════════════════════════════════════════
try {
    $pyVer = (& python --version 2>&1).ToString()
    if ($pyVer -match 'Python (\d+)\.(\d+)') {
        if ([int]$Matches[1] -lt 3 -or ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -lt 11)) {
            Die "Python 3.11+ required. Found: $pyVer`n       Download from https://python.org"
        }
    }
    Ok "Python: $pyVer"
} catch {
    Die "Python not found.`n       Install from https://python.org (check 'Add to PATH' during setup)"
}

# ═══════════════════════════════════════════════════════════════════════════════
# 2. INSTALL PACKAGE
# ═══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "  Installing sysbot package ..."
Set-Location $RepoDir
& python -m pip install --quiet .
if ($LASTEXITCODE -ne 0) { Die "pip install failed. Run manually: pip install ." }
Ok "Package installed"

$SysbotBin = $null
$found = Get-Command sysbot -ErrorAction SilentlyContinue
if ($found) {
    $SysbotBin = $found.Source
} else {
    $ScriptsDir = & python -c "import sys, os; print(os.path.join(sys.prefix, 'Scripts'))"
    $candidate  = Join-Path $ScriptsDir "sysbot.exe"
    if (Test-Path $candidate) { $SysbotBin = $candidate }
}
if (-not $SysbotBin) {
    Die "Cannot locate sysbot.exe. Ensure Python's Scripts directory is in PATH, then re-run."
}
Ok "Binary: $SysbotBin"

if ($NoService) {
    Hr
    Ok "Package installed (service setup skipped)."
    Write-Host ""
    Write-Host "  Run manually:  sysbot" -ForegroundColor Gray
    Write-Host ""
    exit 0
}

# ═══════════════════════════════════════════════════════════════════════════════
# 3. SETUP WIZARD
# ═══════════════════════════════════════════════════════════════════════════════
$SkipConfig = $false
$ConfigFile = Join-Path $RepoDir "config.yaml"

if (Test-Path $ConfigFile) {
    Write-Host ""
    $overwrite = AskYN "config.yaml already exists — overwrite with new settings?" $false
    if (-not $overwrite) {
        Write-Host "  Keeping existing config.yaml."
        $SkipConfig = $true
    }
}

if (-not $SkipConfig) {

    # ── LLM backend ───────────────────────────────────────────────────────────
    Section "LLM Backend"
    $llmChoice = Menu -Default 1 -Options @(
        "Ollama    — local, recommended (no API key needed)",
        "OpenAI    — cloud API",
        "vLLM      — self-hosted OpenAI-compatible server",
        "Custom    — any OpenAI-compatible endpoint"
    )

    switch ($llmChoice) {
        2 {
            $LlmBaseUrl = "https://api.openai.com/v1"
            $LlmModel   = Ask "Model" "gpt-4o"
            $LlmApiKey  = Ask "API key (sk-...)" ""
        }
        3 {
            $LlmBaseUrl = Ask "vLLM base URL" "http://localhost:8000/v1"
            $LlmModel   = Ask "Model" "meta-llama/Llama-3.2-8B-Instruct"
            $LlmApiKey  = "vllm"
        }
        4 {
            $LlmBaseUrl = Ask "Base URL" "http://localhost:8000/v1"
            $LlmModel   = Ask "Model" "llama3.2"
            $LlmApiKey  = Ask "API key" "none"
        }
        default {  # 1 — Ollama
            $LlmBaseUrl = "http://localhost:11434/v1"
            $LlmModel   = Select-OllamaModel
            $LlmApiKey  = "ollama"
        }
    }

    # ── How to reach SysBot ───────────────────────────────────────────────────
    Section "How to reach SysBot"
    Write-Host "  You can always chat in this terminal with 'sysbot --provider cli'."
    Write-Host "  Add Telegram or Slack to also message SysBot remotely."
    Write-Host ""
    $msgChoice = Menu -Default 1 -Options @(
        "Terminal only (default)",
        "Telegram",
        "Slack"
    )

    $TgToken = ""; $TgAllowedIds = "[]"; $SlackBot = ""; $SlackApp = ""
    switch ($msgChoice) {
        2 {
            $MsgProvider = "telegram"
            Write-Host ""
            $TgToken  = Ask "Bot token (from @BotFather)" ""
            $rawIds   = Ask "Allowed Telegram user IDs, comma-separated (blank = allow everyone)" ""
            if ($rawIds) {
                $ids          = ($rawIds -split '\s*,\s*') -join ', '
                $TgAllowedIds = "[$ids]"
            }
        }
        3 {
            $MsgProvider = "slack"
            Write-Host ""
            $SlackBot = Ask "Bot token (xoxb-...)" ""
            $SlackApp = Ask "App token (xapp-...)" ""
        }
        default { $MsgProvider = "cli" }
    }

    # ── Write config.yaml ─────────────────────────────────────────────────────
    $config = @"
messaging:
  provider: $MsgProvider

  telegram:
    token: "$TgToken"
    allowed_user_ids: $TgAllowedIds

  slack:
    bot_token: "$SlackBot"
    app_token: "$SlackApp"

llm:
  base_url: "$LlmBaseUrl"
  model: "$LlmModel"
  api_key: "$LlmApiKey"
  temperature: 0.7
  max_tokens: 4096
  timeout: 120.0

mcp:
  tools_dir: "./tools"
  hot_reload: true

agent:
  system_prompt: >
    You are a helpful assistant with access to tools.
    Use tools when they help answer the user's question.
    Be concise and clear.
  max_history: 50
  max_tool_calls: 10

logging:
  level: INFO
  file: logs/sysbot.log
  trace_file: logs/traces.jsonl
"@
    Set-Content -Path $ConfigFile -Value $config -Encoding UTF8
    Ok "config.yaml written"
}

# ── Resolve provider ──────────────────────────────────────────────────────────
# $MsgProvider is set above only when a fresh config was written; if the user
# kept an existing config.yaml, read the provider back from it. Only Telegram and
# Slack need an always-on background service to poll for messages — CLI is an
# interactive terminal session the user starts on demand.
$Provider = $MsgProvider
if (-not $Provider -and (Test-Path $ConfigFile)) {
    $line = Get-Content $ConfigFile | Where-Object { $_ -match '^\s*provider:' } | Select-Object -First 1
    if ($line -match 'provider:\s*"?([a-z]+)"?') { $Provider = $Matches[1] }
}
if (-not $Provider) { $Provider = 'cli' }
$NeedsService = $Provider -in @('telegram', 'slack')

# ── Auto-start ────────────────────────────────────────────────────────────────
$AutoStart = $false
if ($NeedsService) {
    Section "Service"
    Write-Host "  A $Provider bot runs in the background, so it installs as a service."
    Write-Host ""
    $AutoStart = AskYN "Start SysBot automatically after reboot?" $true
}

# ═══════════════════════════════════════════════════════════════════════════════
# 4. SUMMARY + CONFIRM
# ═══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Hr
Write-Host ""
Write-Host "  Summary" -ForegroundColor White
Write-Host ""
if (-not $SkipConfig) {
    Write-Host "  LLM        $LlmModel  ($LlmBaseUrl)"
}
Write-Host "  Provider   $Provider"
if ($NeedsService) {
    $startupLabel = if ($AutoStart) { "enabled — starts at login" } else { "started now, not at login" }
} else {
    $startupLabel = "runs in your terminal (no background service)"
}
Write-Host "  Startup    $startupLabel"
Write-Host "  Config     $ConfigFile"
Write-Host "  Working    $RepoDir"
Write-Host ""

if (-not (AskYN "Apply these settings?" $true)) {
    Write-Host ""
    Write-Host "  Aborted." -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

# ═══════════════════════════════════════════════════════════════════════════════
# 5. TASK SCHEDULER SETUP  (Telegram/Slack only — CLI is interactive)
# ═══════════════════════════════════════════════════════════════════════════════
if ($NeedsService) {
    $TaskName = "SysBot"

    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    $action    = New-ScheduledTaskAction -Execute $SysbotBin -WorkingDirectory $RepoDir
    $settings  = New-ScheduledTaskSettingsSet `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([System.TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew -StartWhenAvailable $true
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

    if ($AutoStart) {
        $trigger = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
            -Settings $settings -Principal $principal -Force | Out-Null
        Ok "Task Scheduler entry created — starts at login"
    } else {
        # Register without a trigger so it can be started manually
        Register-ScheduledTask -TaskName $TaskName -Action $action `
            -Settings $settings -Principal $principal -Force | Out-Null
        Ok "Task Scheduler entry created (no auto-start trigger)"
    }

    Start-ScheduledTask -TaskName $TaskName
    Ok "SysBot started"

    Write-Host ""
    Write-Host "  Manage:"
    Write-Host "    Get-ScheduledTask  -TaskName 'SysBot' | Select-Object State"
    Write-Host "    Stop-ScheduledTask  -TaskName 'SysBot'"
    Write-Host "    Start-ScheduledTask -TaskName 'SysBot'"
    Write-Host "  Or open Task Scheduler (taskschd.msc) and find 'SysBot'."
}

# ── How to use ──────────────────────────────────────────────────────────────
Section "How to use"
switch ($Provider) {
    'telegram' {
        Write-Host "  SysBot is running as a Telegram bot."
        Write-Host ""
        Write-Host "    1. Open Telegram and find the bot you created with @BotFather"
        Write-Host "    2. Send it a message, e.g.  what's my disk usage on / ?"
        Write-Host "    3. Built-in commands:  /help (list tools)  /clear  /history"
        Write-Host ""
        Write-Host "  Prefer the terminal? Start a local chat anytime:"
        Write-Host "    sysbot --provider cli"
    }
    'slack' {
        Write-Host "  SysBot is running as a Slack bot."
        Write-Host ""
        Write-Host "    1. Invite the bot to a channel, or open a direct message with it"
        Write-Host "    2. Send it a message, e.g.  what's my disk usage on / ?"
        Write-Host "    3. Built-in commands:  /help (list tools)  /clear  /history"
        Write-Host ""
        Write-Host "  Prefer the terminal? Start a local chat anytime:"
        Write-Host "    sysbot --provider cli"
    }
    default {  # cli
        Write-Host "  Start chatting in your terminal:"
        Write-Host "    sysbot --provider cli"
        Write-Host ""
        Write-Host "  Then try:"
        Write-Host "    - Ask in plain language    what's my disk usage on / ?"
        Write-Host "    - Run a tool directly      /disk_usage path=/"
        Write-Host "    - List available tools     /help"
        Write-Host "    - Clear the conversation   /clear"
        Write-Host "    - Leave                    type exit"
    }
}

Write-Host ""
Write-Host "  Full usage guide:  docs\usage.md"
Write-Host "  Activity logs:     logs\sysbot.log  and  logs\traces.jsonl"

Hr
Write-Host ""
if ($NeedsService) {
    Write-Host "  SysBot is running." -ForegroundColor Green
} else {
    Write-Host "  SysBot is ready." -ForegroundColor Green
}
Write-Host "  Edit $ConfigFile to adjust any settings."
Write-Host ""
