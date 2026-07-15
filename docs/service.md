# Running SysBot as a Service

This guide covers keeping SysBot running in the background — managing the
service the installer created, setting one up by hand, auto-start on boot,
and reading logs — on Linux, macOS, and Windows.

**Installing and uninstalling SysBot itself** (the wizard, every prompt,
manual setup) is covered in [Getting Started](getting-started.md); this page
picks up where that leaves off.

---

## 1. What the installer sets up

When you choose **Telegram or Slack** in the install wizard, it registers a
background service — systemd on Linux, launchd on macOS, Task Scheduler on
Windows — that runs from **`~/.sysbot`**, restarts on failure, and (if you
chose auto-start) starts on boot. The **CLI** provider installs no service:
it's an interactive session you start on demand with `sysbot --provider cli`.

The working rhythm for a service install:

```bash
$EDITOR ~/.sysbot/config.yaml       # change settings
systemctl --user restart sysbot     # apply them (Linux; see the tables below)
```

Re-running the installer stops and replaces an existing service, so a changed
model or provider takes effect. To remove everything, run
`scripts/uninstall.sh` / `scripts/uninstall.ps1` — walkthrough in
[Getting Started §10](getting-started.md#10-uninstalling).

---

## 2. Managing the service

### 2.1 Linux (systemd)

| Action | Command |
|---|---|
| Check status | `systemctl --user status sysbot` |
| Start / Stop | `systemctl --user start sysbot` / `stop sysbot` |
| Restart (apply config edits) | `systemctl --user restart sysbot` |
| Enable / disable auto-start | `systemctl --user enable sysbot` / `disable sysbot` |
| Remove service | `systemctl --user disable sysbot && rm ~/.config/systemd/user/sysbot.service && systemctl --user daemon-reload` |

### 2.2 macOS (launchd)

| Action | Command |
|---|---|
| Check status | `launchctl list \| grep sysbot` |
| Start / Stop | `launchctl start com.sysbot.sysbot` / `stop com.sysbot.sysbot` |
| Restart (apply config edits) | `launchctl kickstart -k gui/$(id -u)/com.sysbot.sysbot` |
| Remove agent | `launchctl unload -w ~/Library/LaunchAgents/com.sysbot.sysbot.plist && rm ~/Library/LaunchAgents/com.sysbot.sysbot.plist` |

### 2.3 Windows (Task Scheduler)

| Action | Command (PowerShell) |
|---|---|
| Check status | `Get-ScheduledTask -TaskName 'SysBot' \| Select-Object State` |
| Start / Stop | `Start-ScheduledTask -TaskName 'SysBot'` / `Stop-ScheduledTask …` |
| Remove | `Unregister-ScheduledTask -TaskName 'SysBot' -Confirm:$false` |

Or use the **Task Scheduler** GUI (`taskschd.msc`) — the task is named `SysBot`.

---

## 3. Setting up a service manually

Use this section if you installed manually (no wizard) or need a custom setup.
In every variant, the key rule is the same: **the service must run from the
directory holding your `config.yaml` and `tools/`** — `~/.sysbot` for a
standard install.

### 3.1 Linux — systemd user service

Create `~/.config/systemd/user/sysbot.service`:

```ini
[Unit]
Description=SysBot — local AI assistant with tools
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/.sysbot
ExecStart=/home/you/.local/bin/sysbot
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Set `ExecStart` to the output of `which sysbot` (`%h` expands to your home).
Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now sysbot
```

### 3.2 macOS — launchd agent

Create `~/Library/LaunchAgents/com.sysbot.sysbot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.sysbot.sysbot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/sysbot</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/you/.sysbot</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/you/Library/Logs/sysbot/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/you/Library/Logs/sysbot/stderr.log</string>
</dict>
</plist>
```

Replace `/usr/local/bin/sysbot` with `which sysbot` and `you` with your
username, then:

```bash
mkdir -p ~/Library/Logs/sysbot
launchctl load -w ~/Library/LaunchAgents/com.sysbot.sysbot.plist
```

### 3.3 Windows — Task Scheduler

In PowerShell as your regular user (not Administrator):

```powershell
$bin     = (Get-Command sysbot).Source
$workdir = Join-Path $HOME ".sysbot"   # folder holding config.yaml / tools\

$action   = New-ScheduledTaskAction -Execute $bin -WorkingDirectory $workdir
$trigger  = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([System.TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -StartWhenAvailable $true
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask -TaskName "SysBot" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
Start-ScheduledTask -TaskName "SysBot"
```

### 3.4 Quick one-off alternatives (no service)

For a throwaway background run, skip the service machinery:

```bash
nohup sysbot > logs/sysbot-stdout.log 2>&1 &     # Linux/macOS; stop: pkill -f sysbot
screen -S sysbot -d -m sysbot                    # or tmux new-session -d -s sysbot "sysbot"
```

```powershell
Start-Process sysbot -WindowStyle Hidden          # Windows; stop: Stop-Process -Name sysbot
```

---

## 4. Auto-start on boot

- **Linux** — the systemd user service starts at **login**. To also start at
  **boot** (before any login): `loginctl enable-linger $USER`
  (undo with `disable-linger`).
- **macOS** — the LaunchAgent (`RunAtLoad`) starts at login; nothing more
  needed. For a pre-login system service, place the plist in
  `/Library/LaunchDaemons/` and load it with `sudo launchctl`.
- **Windows** — the `AtLogon` trigger starts SysBot when you log in. For a
  pre-login service on a headless server, use [NSSM](https://nssm.cc):
  `nssm install SysBot "C:\path\to\sysbot.exe"`.

---

## 5. Viewing logs

**Service logs** (stdout/stderr of the process):

```bash
journalctl --user -u sysbot -f            # Linux — live tail (-n 100 for recent)
tail -f ~/Library/Logs/sysbot/stderr.log  # macOS
```

On Windows, check Task Scheduler history or Event Viewer → Windows Logs →
Application.

**SysBot's own logs**, written to `logs/` next to the active config
(`~/.sysbot/logs/` for an installed setup):

```bash
tail -f ~/.sysbot/logs/sysbot.log        # plain-text application log
tail -f ~/.sysbot/logs/traces.jsonl      # per-request traces (what the LLM decided)
```

Both rotate daily and are configurable — level, rotation, or `null` to disable
— see [Configuration §2](configuration.md#2-full-reference); the trace format
is in [Configuration §6](configuration.md#6-traces-log-format).

---

## 6. Troubleshooting

### `sysbot: command not found`

pip installed the binary somewhere not on your PATH:

```bash
python -m site --user-scripts    # e.g. /home/you/.local/bin
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

On Windows, ensure Python's `Scripts` directory is in PATH (re-run the Python
installer and tick **Add to PATH**).

### Service starts but exits immediately

Check the service logs (above) for the real error. Common causes:

- **Ollama not running** — start Ollama before SysBot, or point `llm.base_url`
  at a backend that is up.
- **Wrong `WorkingDirectory`** — the service must run from the directory
  containing `config.yaml` and `tools/` (normally `~/.sysbot`).
- **Bad credentials** — a Telegram/Slack token that's wrong or revoked; fix it
  in `~/.sysbot/config.yaml` and restart.

### Script permission errors

```bash
chmod +x scripts/install.sh scripts/uninstall.sh          # Linux/macOS
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1   # Windows
```
