---
name: gpu-temp
description: Report NVIDIA GPU temperature(s) via nvidia-smi
platforms: [linux, windows]
requires: [nvidia-smi]
---
# gpu-temp

Reports each NVIDIA GPU's temperature in °C.

**Runs on:** Linux · Windows  ·  **Needs:** `nvidia-smi` on PATH (NVIDIA driver)

On macOS, or on a machine without an NVIDIA driver, the tool stays listed but
returns a short explanation instead of running.

## Tools
- `/gpu_temp` — e.g. `GPU0: 47°C, GPU1: 51°C`.

## Copy-paste
Drop this `gpu-temp/` folder into your `~/.lesysbot/tools/` and restart LeSysBot.
