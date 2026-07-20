"""Tool package metadata — README frontmatter + package discovery.

Metadata comes from the README frontmatter and filenames only; package code is
**never imported** here (importing would execute arbitrary code before the user
has consented to the install).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Loader-compatible package names: the registry ignores dirs starting with `.`/`_`.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_FRONTMATTER_RE = re.compile(r"\A\s*---\s*\n(.*?)\n\s*---\s*(?:\n|\Z)", re.DOTALL)

# Subdirectories that are never tool packages.
_SKIP_DIRS = ("__pycache__", "tests", "docs")


def parse_frontmatter(text: str) -> dict:
    """YAML frontmatter (leading ``---`` block) as a dict; ``{}`` on any failure."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class ToolPackage:
    """A tool folder package found in an extracted archive (or on disk)."""

    path: Path
    name: str
    description: str = ""
    version: str | None = None
    tool_files: list[str] = field(default_factory=list)
    has_requirements: bool = False


def _qualifies(directory: Path) -> bool:
    """True when *directory* directly contains a non-underscore .py file —
    the same rule the registry loader uses to treat a dir as a tool package."""
    return any(
        p.suffix == ".py" and not p.name.startswith("_")
        for p in directory.iterdir()
        if p.is_file()
    )


def _package_from(directory: Path, default_name: str) -> ToolPackage:
    fm: dict = {}
    readme = directory / "README.md"
    if readme.is_file():
        fm = parse_frontmatter(readme.read_text(encoding="utf-8", errors="replace"))
    version = fm.get("version")
    return ToolPackage(
        path=directory,
        name=str(fm.get("name") or default_name),
        description=str(fm.get("description") or ""),
        version=str(version) if version is not None else None,
        tool_files=sorted(
            p.name
            for p in directory.iterdir()
            if p.is_file() and p.suffix == ".py" and not p.name.startswith("_")
        ),
        has_requirements=(directory / "requirements.txt").is_file(),
    )


def discover_packages(root: Path, default_name: str) -> list[ToolPackage]:
    """Find tool packages in an extracted tree.

    *root* itself is the package when it directly holds tool ``.py`` files
    (single-package repo, named *default_name*); otherwise packages are the
    qualifying immediate subdirectories of ``root/tools`` when that folder
    yields any (collection repos keep packages under ``tools/``, like the
    core repo), else of *root* itself.
    """
    if _qualifies(root):
        return [_package_from(root, default_name)]
    tools_dir = root / "tools"
    if tools_dir.is_dir():
        packages = _scan_subdirs(tools_dir)
        if packages:
            return packages
    return _scan_subdirs(root)


def _scan_subdirs(root: Path) -> list[ToolPackage]:
    packages = []
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        if sub.name.startswith((".", "_")) or sub.name in _SKIP_DIRS:
            continue
        if _qualifies(sub):
            packages.append(_package_from(sub, sub.name))
    return packages
