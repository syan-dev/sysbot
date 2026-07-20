"""CPU temperature — reads Linux thermal sensors from /sys.

Uses /sys/class/thermal zones plus /sys/class/hwmon devices (coretemp on
Intel, k10temp on AMD, …), so it needs no extra binary and no pip dependency.
Linux-only: macOS and Windows expose no comparable interface without admin
tooling, so there the tool stays listed but explains itself instead of running.
Call it in chat or directly with `/cpu_temp`.
"""
from __future__ import annotations

from pathlib import Path

from lesysbot.mcp import tool

_THERMAL_DIR = Path("/sys/class/thermal")
_HWMON_DIR = Path("/sys/class/hwmon")

# Sensor names that indicate a CPU reading (thermal zone `type` / hwmon `name`).
_CPU_HINTS = ("cpu", "x86_pkg_temp", "coretemp", "k10temp", "zenpower", "soc", "pkg", "acpitz")


def _read_millideg(path: Path) -> float | None:
    try:
        value = int(path.read_text().strip()) / 1000.0
    except (OSError, ValueError):
        return None
    # Dead/disconnected sensors report absurd values (-273, 6553.5, …).
    return value if -20.0 < value < 150.0 else None


def _read_sensors() -> list[tuple[str, float]]:
    readings: list[tuple[str, float]] = []
    for zone in sorted(_THERMAL_DIR.glob("thermal_zone*")):
        try:
            name = (zone / "type").read_text().strip()
        except OSError:
            continue
        temp = _read_millideg(zone / "temp")
        if temp is not None:
            readings.append((name, temp))
    for hwmon in sorted(_HWMON_DIR.glob("hwmon*")):
        try:
            name = (hwmon / "name").read_text().strip()
        except OSError:
            continue
        for temp_file in sorted(hwmon.glob("temp*_input")):
            temp = _read_millideg(temp_file)
            if temp is not None:
                readings.append((name, temp))
    return readings


@tool(
    description="Report current CPU temperature(s) in °C from Linux thermal sensors",
    platforms=["linux"],
)
async def cpu_temp() -> str:
    """Return the hottest CPU sensor plus a per-sensor breakdown."""
    readings = _read_sensors()
    if not readings:
        return "No temperature sensors found (nothing under /sys/class/thermal or /sys/class/hwmon)."

    cpu_ish = [(n, t) for n, t in readings if any(h in n.lower() for h in _CPU_HINTS)]
    shown = cpu_ish or readings

    # Multi-core hwmon chips expose one temp*_input per core — collapse per chip.
    by_name: dict[str, list[float]] = {}
    for name, temp in shown:
        by_name.setdefault(name, []).append(temp)

    hottest = max(t for _, t in shown)
    lines = [f"CPU temperature: {hottest:.0f}°C (hottest sensor)"]
    for name, temps in by_name.items():
        suffix = f" (max of {len(temps)} readings)" if len(temps) > 1 else ""
        lines.append(f"  {name}: {max(temps):.0f}°C{suffix}")
    return "\n".join(lines)
