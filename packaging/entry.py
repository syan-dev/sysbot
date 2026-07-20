"""PyInstaller entry point.

PyInstaller freezes a *script*, not a module, so this thin wrapper just calls
the real CLI entry point. Keep it minimal — everything else lives in the package.
"""
from lesysbot.__main__ import main

if __name__ == "__main__":
    main()
