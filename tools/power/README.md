---
name: power
description: Reboot, power off (scheduled 1 minute out, cancellable), or cancel a pending shutdown
platforms: all
requires: []
---
# power

Power control for the host machine. The right command is chosen per OS
(`shutdown` everywhere; scheduled via logind/polkit on systemd Linux), so it
runs everywhere — though it may need elevated privileges.

Reboot/power-off are **scheduled 1 minute out**, not immediate: an instant
poweroff would kill SysBot before its reply reaches you, so a remote
(Telegram/Slack) user would never see whether the command was accepted. The
delay guarantees the acknowledgment arrives — and leaves a window to abort
with `/cancel_shutdown`.

**Runs on:** Linux · macOS · Windows  ·  **Needs:** nothing (may need sudo/admin)

## Tools (all require confirmation)
- `/reboot` — restart in 1 minute (cancellable).
- `/power_off` — shut down in 1 minute (cancellable).
- `/cancel_shutdown` — cancel a pending shutdown/reboot.

These are destructive and prompt for confirmation when the LLM triggers them.

## Copy-paste
Drop this `power/` folder into your `~/.sysbot/tools/` and restart SysBot.
