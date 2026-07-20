---
name: cpu-temp
description: Report current CPU temperature(s) via Linux /sys thermal sensors
platforms: [linux]
requires: []
---
# cpu-temp

Reports the CPU temperature in °C — the hottest sensor plus a per-sensor
breakdown.

**Runs on:** Linux  ·  **Needs:** nothing (reads `/sys` directly)

Reads `/sys/class/thermal/thermal_zone*` and `/sys/class/hwmon` (`coretemp` on
Intel, `k10temp` on AMD, …). On a machine with no exposed sensors it says so
instead of failing. macOS and Windows have no comparable interface without
admin tooling, so there the tool stays listed but returns a short explanation.

## Tools
- `/cpu_temp` — e.g. `CPU temperature: 54°C (hottest sensor)`.

## Copy-paste
Drop this `cpu-temp/` folder into your `~/.lesysbot/tools/` and restart LeSysBot.
