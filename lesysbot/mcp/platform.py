"""Cross-platform gating for tools.

A tool may declare which OSes it runs on (``platforms``) and which external
executables it needs on PATH (``requires``). ``availability()`` checks both
against the current machine and returns a human-readable reason when a tool can't
run here, so the registry can register an "explaining stub" instead of a tool that
would fail cryptically.
"""
from __future__ import annotations

import platform
import shutil

# platform.system() → our short OS names.
_OS_NAMES = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}

# Pretty labels for messages.
_OS_LABELS = {"linux": "Linux", "macos": "macOS", "windows": "Windows"}


def current_os() -> str:
    """Return the current OS as one of 'linux' | 'macos' | 'windows'.

    Falls back to a lower-cased platform.system() for anything else (e.g. BSD).
    """
    return _OS_NAMES.get(platform.system(), platform.system().lower())


def _label(os_name: str) -> str:
    return _OS_LABELS.get(os_name, os_name)


def availability(
    platforms: list[str] | None,
    requires: list[str] | None,
) -> tuple[bool, str | None]:
    """Check whether a tool can run on this machine.

    Returns ``(ok, reason)``. ``ok`` is True when the tool can run here and
    ``reason`` is None; otherwise ``ok`` is False and ``reason`` is a one-line
    explanation suitable for showing to the user.
    """
    if platforms:
        wanted = [p.lower() for p in platforms]
        here = current_os()
        if here not in wanted:
            runs_on = ", ".join(_label(p) for p in wanted)
            return False, f"not supported on {_label(here)} (runs on: {runs_on})"

    for binary in requires or []:
        if shutil.which(binary) is None:
            return False, f"requires '{binary}' on PATH (not found)"

    return True, None
