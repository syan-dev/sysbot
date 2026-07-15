"""Install tool folder packages from GitHub.

Installing means extracting the package(s) from a GitHub zipball into the
bot's ``tools_dir`` (one atomic directory move, so a running bot's hot reload
sees a single clean change) and recording provenance in the tools lock file
(``tools.lock.json``) so ``sysbot tools list/info/remove`` know where an
installed package came from.
"""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from rich.console import Console

from sysbot.core.paths import force_rmtree as _rmtree
from sysbot.install.archive import extract_tree, zip_commit_sha
from sysbot.install.errors import ToolInstallError
from sysbot.install.fetch import Fetcher, UrllibFetcher, download_zipball
from sysbot.install.lockfile import LOCK_KEY, JsonState
from sysbot.install.meta import NAME_RE, ToolPackage, discover_packages, parse_frontmatter
from sysbot.install.spec import ToolSource

STAGE_PREFIX = ".sysbot-stage-"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_confirm(message: str) -> bool:
    from rich.prompt import Confirm

    try:
        return Confirm.ask(message, default=False)
    except EOFError:  # non-interactive stdin — require --yes
        return False


class ToolInstaller:
    def __init__(
        self,
        tools_dir: Path,
        lock_path: Path,
        fetcher: Fetcher | None = None,
        *,
        confirm: Callable[[str], bool] | None = None,
        console: Console | None = None,
    ) -> None:
        self.tools_dir = Path(tools_dir)
        self._lock = JsonState(Path(lock_path), LOCK_KEY)
        self._fetcher = fetcher or UrllibFetcher()
        self._confirm = confirm or _default_confirm
        self.console = console or Console()

    # -- install --------------------------------------------------------------

    def install(
        self,
        src: ToolSource,
        *,
        only: list[str] | None = None,
        force: bool = False,
        yes: bool = False,
        install_deps: bool = False,
    ) -> list[str]:
        """Install the package(s) at *src* into ``tools_dir``; returns their names."""
        self.console.print(f"Fetching [bold]{src}[/bold]…")
        data = download_zipball(self._fetcher, src)
        commit = zip_commit_sha(data)

        self.tools_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=self.tools_dir.parent)
        )
        try:
            extract_tree(data, src.subdir, staging)
            default_name = (src.subdir or src.repo).rstrip("/").rsplit("/", 1)[-1]
            packages = discover_packages(staging, default_name)
            packages = self._select(packages, only, src)
            self._validate(packages)

            lock = self._lock.load()
            self._check_collisions(packages, lock, force)
            self._print_plan(src, commit, packages)

            prompt = (
                f"Install {len(packages)} tool package(s) from {src.slug}"
                f"{f' @ {commit[:12]}' if commit else ''}? "
                "Tool packages run arbitrary code as your user"
            )
            if not yes and not self._confirm(prompt):
                self.console.print("Aborted.")
                return []

            installed: list[str] = []
            for pkg in packages:
                target = self.tools_dir / pkg.name
                if target.exists():
                    _rmtree(target)
                rel = pkg.path.relative_to(staging)
                pkg_subdir = "/".join(
                    p for p in [src.subdir or "", str(rel) if str(rel) != "." else ""] if p
                ) or None
                shutil.move(str(pkg.path), str(target))
                prev = lock.get(pkg.name, {})
                lock[pkg.name] = {
                    "repo": src.slug,
                    "subdir": pkg_subdir,
                    "requested_ref": src.ref,
                    "commit": commit,
                    "version": pkg.version,
                    "description": pkg.description,
                    "installed_at": prev.get("installed_at") or _now(),
                    "updated_at": _now(),
                }
                self._lock.save(lock)
                installed.append(pkg.name)
                self.console.print(f"[green]✔[/green] Installed [bold]{pkg.name}[/bold] → {target}")
                if pkg.has_requirements:
                    self._handle_requirements(target, install_deps)

            self.console.print(
                "A running SysBot with hot_reload picks new tools up automatically; "
                "otherwise restart it. Type /help in the chat to see them."
            )
            return installed
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def _select(
        self, packages: list[ToolPackage], only: list[str] | None, src: ToolSource
    ) -> list[ToolPackage]:
        if not packages:
            raise ToolInstallError(
                f"No tool packages found in {src} — expected a `tool.py` (plus README.md) "
                "in the repo root or in per-tool subdirectories."
            )
        if not only:
            return packages
        by_name = {p.name: p for p in packages}
        missing = [n for n in only if n not in by_name]
        if missing:
            raise ToolInstallError(
                f"Package(s) {', '.join(missing)} not found in {src.slug}. "
                f"Available: {', '.join(sorted(by_name))}"
            )
        return [by_name[n] for n in only]

    def _validate(self, packages: list[ToolPackage]) -> None:
        seen: set[str] = set()
        for pkg in packages:
            if not NAME_RE.match(pkg.name):
                raise ToolInstallError(
                    f"Invalid package name {pkg.name!r} — must match {NAME_RE.pattern} "
                    "(the tool loader ignores names starting with '.' or '_')"
                )
            if pkg.name in seen:
                raise ToolInstallError(f"Duplicate package name in archive: {pkg.name!r}")
            seen.add(pkg.name)

    def _check_collisions(
        self, packages: list[ToolPackage], lock: dict[str, Any], force: bool
    ) -> None:
        conflicts = [
            p.name
            for p in packages
            if (self.tools_dir / p.name).exists() and p.name not in lock
        ]
        if conflicts and not force:
            raise ToolInstallError(
                f"tools dir already has {', '.join(conflicts)} (not installed by "
                "`sysbot tools install`) — pass --force to overwrite."
            )

    def _print_plan(
        self, src: ToolSource, commit: str | None, packages: list[ToolPackage]
    ) -> None:
        pin = commit[:12] if commit else (src.ref or "HEAD")
        self.console.print(f"\n[bold]{src.slug}[/bold] @ {pin}")
        for pkg in packages:
            ver = f" v{pkg.version}" if pkg.version else ""
            self.console.print(f"  [bold]{pkg.name}[/bold]{ver} — {pkg.description or '(no description)'}")
            self.console.print(f"    files: {', '.join(pkg.tool_files)}")
            if pkg.has_requirements:
                self.console.print("    has requirements.txt (pip deps)")
            self.console.print(f"    → {self.tools_dir / pkg.name}")

    def _handle_requirements(self, target: Path, install_deps: bool) -> None:
        req = target / "requirements.txt"
        if install_deps:
            import subprocess
            import sys

            self.console.print(f"requirements.txt:\n{req.read_text()}")
            self.console.print("Installing pip dependencies…")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req)], check=True
            )
        else:
            self.console.print(
                f"[yellow]![/yellow] {target.name} has pip dependencies — install them with:\n"
                f"    python -m pip install -r {req}\n"
                "  (or re-run the install with --install-deps)"
            )

    # -- list / info ----------------------------------------------------------

    def list_installed(self) -> list[dict[str, Any]]:
        """Lock entries reconciled with the filesystem, plus unmanaged tool dirs."""
        lock = self._lock.load()
        rows = []
        for name in sorted(lock):
            entry = dict(lock[name])
            entry["name"] = name
            entry["managed"] = True
            entry["present"] = (self.tools_dir / name).is_dir()
            rows.append(entry)
        if self.tools_dir.is_dir():
            for sub in sorted(self.tools_dir.iterdir()):
                if (
                    sub.is_dir()
                    and not sub.name.startswith((".", "_"))
                    and sub.name != "__pycache__"
                    and sub.name not in lock
                ):
                    rows.append({"name": sub.name, "managed": False, "present": True})
        return rows

    def info(self, name: str) -> dict[str, Any]:
        lock = self._lock.load()
        target = self.tools_dir / name
        if name not in lock and not target.is_dir():
            raise ToolInstallError(f"No tool package named {name!r} (see `sysbot tools list`)")
        entry: dict[str, Any] = dict(lock.get(name, {}))
        entry["name"] = name
        entry["managed"] = name in lock
        entry["present"] = target.is_dir()
        entry["path"] = str(target)
        if target.is_dir():
            readme = target / "README.md"
            if readme.is_file():
                fm = parse_frontmatter(readme.read_text(encoding="utf-8", errors="replace"))
                entry.setdefault("description", fm.get("description", ""))
                entry["platforms"] = fm.get("platforms")
                entry["requires"] = fm.get("requires")
            entry["files"] = sorted(p.name for p in target.iterdir() if p.is_file())
        return entry
