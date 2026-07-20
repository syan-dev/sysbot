# Running LeSysBot as a Service

This guide covers keeping LeSysBot running in the background — managing the
service the installer created, setting one up by hand, auto-start on boot,
and reading logs — on Linux, macOS, and Windows.

**Installing and uninstalling LeSysBot itself** (the wizard, every prompt,
manual setup) is covered in [Getting Started](getting-started.md); this page
picks up where that leaves off.

---

## 1. What the installer sets up

When you choose **Telegram or Slack** in the install wizard, it registers a
background service — systemd on Linux, launchd on macOS, Task Scheduler on
Windows — that runs from **`~/.lesysbot`**, restarts on failure, and (if you
chose auto-start) starts on boot. The **CLI** provider installs no service:
it's an interactive session you start on demand with `lesysbot --provider cli`.

The working rhythm for a service install:

```bash
$EDITOR ~/.lesysbot/config.yaml       # change settings
systemctl --user restart lesysbot     # apply them (Linux; see the tables below)
```

Re-running the installer stops and replaces an existing service, so a changed
model or provider takes effect. To remove everything, run
`scripts/uninstall.sh` / `scripts/uninstall.ps1` — walkthrough in
[Getting Started §10](getting-started.md#10-uninstalling).

### One instance per bot

Two copies of the same bot would fight over the same updates (Telegram answers
`409 Conflict` to both), so LeSysBot takes an OS-level lock per bot token at
startup: launching a second Telegram/Slack instance — typically `lesysbot` in a
terminal while the service is running — refuses with a message naming the
running PID instead of starting. Stop the service first if you really want a
foreground run. The lock is released automatically when the process exits,
crash included, and `lesysbot --provider cli` doesn't poll, so an interactive
session always runs fine alongside the service.

### The startup notice

With Telegram or Slack, LeSysBot pings you as soon as it comes up — and since
the service starts at boot, that doubles as a "the machine just woke up"
message. The notice is a short system report: CPU temperature, GPU
temperature, disk usage, and internet speed, each included only if this
machine can answer (no NVIDIA driver → no GPU line, and so on).

It's on by default. Telegram sends to `messaging.startup_notice.notify`,
falling back to `allowed_user_ids`; Slack has no equivalent default, so put a
channel id in `notify`. Set `startup_notice.enabled: false` to turn it off,
or `speedtest: false` to skip the speed measurement (it downloads a few MB on
every boot). All keys are in the
[configuration reference](configuration.md#2-full-reference).

---

## 2. Managing the service

### 2.1 Linux (systemd)

| Action | Command |
|---|---|
| Check status | `systemctl --user status lesysbot` |
| Start / Stop | `systemctl --user start lesysbot` / `stop lesysbot` |
| Restart (apply config edits) | `systemctl --user restart lesysbot` |
| Enable / disable auto-start | `systemctl --user enable lesysbot` / `disable lesysbot` |
| Remove service | `systemctl --user disable lesysbot && rm ~/.config/systemd/user/lesysbot.service && systemctl --user daemon-reload` |

### 2.2 macOS (launchd)

| Action | Command |
|---|---|
| Check status | `launchctl list \| grep lesysbot` |
| Start / Stop | `launchctl start com.lesysbot.lesysbot` / `stop com.lesysbot.lesysbot` |
| Restart (apply config edits) | `launchctl kickstart -k gui/$(id -u)/com.lesysbot.lesysbot` |
| Remove agent | `launchctl unload -w ~/Library/LaunchAgents/com.lesysbot.lesysbot.plist && rm ~/Library/LaunchAgents/com.lesysbot.lesysbot.plist` |

### 2.3 Windows (Task Scheduler)

| Action | Command (PowerShell) |
|---|---|
| Check status | `Get-ScheduledTask -TaskName 'LeSysBot' \| Select-Object State` |
| Start / Stop | `Start-ScheduledTask -TaskName 'LeSysBot'` / `Stop-ScheduledTask …` |
| Remove | `Unregister-ScheduledTask -TaskName 'LeSysBot' -Confirm:$false` |

Or use the **Task Scheduler** GUI (`taskschd.msc`) — the task is named `LeSysBot`.

---

## 3. Setting up a service manually

Use this section if you installed manually (no wizard) or need a custom setup.
In every variant, the key rule is the same: **the service must run from the
directory holding your `config.yaml` and `tools/`** — `~/.lesysbot` for a
standard install.

### 3.1 Linux — systemd user service

Create `~/.config/systemd/user/lesysbot.service`:

```ini
[Unit]
Description=LeSysBot — local AI assistant with tools
After=network.target

[Service]
Type=simple
WorkingDirectory=%h/.lesysbot
ExecStart=/home/you/.local/bin/lesysbot
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Set `ExecStart` to the output of `which lesysbot` (`%h` expands to your home).
Then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now lesysbot
```

### 3.2 macOS — launchd agent

Create `~/Library/LaunchAgents/com.lesysbot.lesysbot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.lesysbot.lesysbot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/lesysbot</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/you/.lesysbot</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/Users/you/Library/Logs/lesysbot/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/you/Library/Logs/lesysbot/stderr.log</string>
</dict>
</plist>
```

Replace `/usr/local/bin/lesysbot` with `which lesysbot` and `you` with your
username, then:

```bash
mkdir -p ~/Library/Logs/lesysbot
launchctl load -w ~/Library/LaunchAgents/com.lesysbot.lesysbot.plist
```

### 3.3 Windows — Task Scheduler

In PowerShell as your regular user (not Administrator):

```powershell
$bin     = (Get-Command lesysbot).Source
$workdir = Join-Path $HOME ".lesysbot"   # folder holding config.yaml / tools\

$action   = New-ScheduledTaskAction -Execute $bin -WorkingDirectory $workdir
$trigger  = New-ScheduledTaskTrigger -AtLogon -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([System.TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -StartWhenAvailable $true
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest

Register-ScheduledTask -TaskName "LeSysBot" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
Start-ScheduledTask -TaskName "LeSysBot"
```

### 3.4 Quick one-off alternatives (no service)

For a throwaway background run, skip the service machinery:

```bash
nohup lesysbot > logs/lesysbot-stdout.log 2>&1 &     # Linux/macOS; stop: pkill -f lesysbot
screen -S lesysbot -d -m lesysbot                    # or tmux new-session -d -s lesysbot "lesysbot"
```

```powershell
Start-Process lesysbot -WindowStyle Hidden          # Windows; stop: Stop-Process -Name lesysbot
```

---

## 4. Auto-start on boot

- **Linux** — the systemd user service starts at **login**. To also start at
  **boot** (before any login): `loginctl enable-linger $USER`
  (undo with `disable-linger`).
- **macOS** — the LaunchAgent (`RunAtLoad`) starts at login; nothing more
  needed. For a pre-login system service, place the plist in
  `/Library/LaunchDaemons/` and load it with `sudo launchctl`.
- **Windows** — the `AtLogon` trigger starts LeSysBot when you log in. For a
  pre-login service on a headless server, use [NSSM](https://nssm.cc):
  `nssm install LeSysBot "C:\path\to\lesysbot.exe"`.

---

## 5. Viewing logs

**Service logs** (stdout/stderr of the process):

```bash
journalctl --user -u lesysbot -f            # Linux — live tail (-n 100 for recent)
tail -f ~/Library/Logs/lesysbot/stderr.log  # macOS
```

On Windows, check Task Scheduler history or Event Viewer → Windows Logs →
Application.

**LeSysBot's own logs**, written to `logs/` next to the active config
(`~/.lesysbot/logs/` for an installed setup):

```bash
tail -f ~/.lesysbot/logs/lesysbot.log        # plain-text application log
tail -f ~/.lesysbot/logs/traces.jsonl      # per-request traces (what the LLM decided)
```

Both rotate daily and are configurable — level, rotation, or `null` to disable
— see [Configuration §2](configuration.md#2-full-reference); the trace format
is in [Configuration §6](configuration.md#6-traces-log-format).

---

## 6. Troubleshooting

### `lesysbot: command not found`

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

- **Ollama not running** — start Ollama before LeSysBot, or point `llm.base_url`
  at a backend that is up.
- **Wrong `WorkingDirectory`** — the service must run from the directory
  containing `config.yaml` and `tools/` (normally `~/.lesysbot`).
- **Bad credentials** — a Telegram/Slack token that's wrong or revoked; fix it
  in `~/.lesysbot/config.yaml` and restart.

### Script permission errors

```bash
chmod +x scripts/install.sh scripts/uninstall.sh          # Linux/macOS
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1   # Windows
```
