"""Tool install system: fetch tool folder packages from GitHub into the tools dir.

Submodules are imported lazily by the CLI; keep this init dependency-free so
importing :mod:`sysbot.install` stays cheap for the bot process.
"""

__all__ = ["ToolInstallError"]

from sysbot.install.errors import ToolInstallError
