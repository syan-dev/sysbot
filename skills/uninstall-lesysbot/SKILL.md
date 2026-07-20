---
name: uninstall-lesysbot
description: Remove LeSysBot from a machine — stop and remove the background service, uninstall the Python package, and optionally delete the ~/.lesysbot data directory — via the uninstall script or fully by hand. Use when asked to "uninstall lesysbot", "remove lesysbot", or "clean lesysbot off this machine".
---

# Uninstall LeSysBot

## 1. The uninstall script (preferred)

Run from the cloned repository:

```bash
bash scripts/uninstall.sh                                        # Linux/macOS
```

```powershell
.\scripts\uninstall.ps1                                          # Windows
powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1   # if blocked
```

It undoes everything the installer set up, in order:

1. **Stops and removes the background service** (systemd / launchd / Task
   Scheduler) — skipped with a note for Terminal-only setups. On Linux it also
   offers to disable `loginctl` linger if the installer enabled it.
2. **Offers to remove the wake-up sudoers rule**
   (`/etc/sudoers.d/lesysbot-rtcwake`) — Linux only, present only if one was set
   up for the optional `shutdown-wake` tool (its `setup-sudoers.sh`, or an
   older install wizard).
3. **Uninstalls the `lesysbot` Python package** via pip.
4. **Asks before deleting `~/.lesysbot`** (config, tools, logs; honours
   `LESYSBOT_HOME`). Default is **No** — keeping it means a later re-install
   finds settings and custom tools exactly as left. Answer `y` only for a
   completely clean machine.

Works for both wizard and manual installs — with no service present, step 1
skips itself.

## 2. Manual removal (no repo clone available)

**Stop + remove the service:**

```bash
# Linux (systemd user service)
systemctl --user disable --now lesysbot
rm ~/.config/systemd/user/lesysbot.service
systemctl --user daemon-reload

# macOS (launchd agent)
launchctl unload -w ~/Library/LaunchAgents/com.lesysbot.lesysbot.plist
rm ~/Library/LaunchAgents/com.lesysbot.lesysbot.plist
```

```powershell
# Windows (Task Scheduler)
Unregister-ScheduledTask -TaskName 'LeSysBot' -Confirm:$false
```

**Uninstall the package, then (optionally) the data:**

```bash
pip uninstall lesysbot
rm -rf ~/.lesysbot          # ONLY if the user confirms losing config + custom tools
```

## Before deleting `~/.lesysbot`

Confirm with the user first — it holds their hand-edited `config.yaml`
(possibly with API keys/tokens they have nowhere else), custom tools in
`tools/`, and logs. If they might reinstall later, keep it.

## Related

- Updating instead of removing: [update-lesysbot](../update-lesysbot/SKILL.md).
- Only stopping the bot, not removing it: [manage-service](../manage-service/SKILL.md).
