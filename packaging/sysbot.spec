# PyInstaller spec for SysBot — build with:  pyinstaller packaging/sysbot.spec
#
# Produces a one-folder distribution in dist/sysbot/ containing sysbot.exe and an
# _internal/ folder. The build script (scripts/build-exe.ps1) then drops a
# default config.yaml and a tools/ folder next to the exe to make a ready-to-ship
# package. See docs/building-windows-exe.md.
#
# Set the env var SYSBOT_BUILD_ONEFILE=1 to produce a single sysbot.exe instead.

import os

from PyInstaller.utils.hooks import collect_all

ONEFILE = os.environ.get("SYSBOT_BUILD_ONEFILE") == "1"
SKIP_PROVIDERS = os.environ.get("SYSBOT_BUILD_SKIP_PROVIDERS") == "1"

datas = []
binaries = []
hiddenimports = []


def _bundle(pkg, optional=False):
    """Collect everything a dependency needs. Optional packages (telegram/slack)
    are skipped with a warning if they aren't installed, so the build never breaks."""
    try:
        d, b, h = collect_all(pkg)
    except Exception as exc:  # noqa: BLE001 — build-time best effort
        if optional:
            print(f"[sysbot.spec] optional package {pkg!r} not bundled: {exc}")
            return
        raise
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# Core runtime — always required.
for _pkg in ("sysbot", "openai", "pydantic", "pydantic_settings", "yaml", "rich", "watchfiles"):
    _bundle(_pkg)

# Optional providers / tool dependencies — bundled if present on the build machine
# so a single exe can serve CLI, Telegram and Slack. Set SYSBOT_BUILD_SKIP_PROVIDERS=1
# for a smaller CLI-only executable.
if not SKIP_PROVIDERS:
    for _pkg in ("telegram", "slack_bolt", "aiohttp", "httpx"):
        _bundle(_pkg, optional=True)


a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "ruff"],
    noarchive=False,
)

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="sysbot",
        console=True,
        disable_windowed_traceback=False,
        upx=False,
        icon=None,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="sysbot",
        console=True,
        disable_windowed_traceback=False,
        upx=False,
        icon=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        name="sysbot",
        upx=False,
    )
