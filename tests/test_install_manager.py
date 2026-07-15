import io
import json

import pytest
from rich.console import Console

from sysbot.mcp import ToolRegistry
from sysbot.install.errors import ToolInstallError
from sysbot.install.manager import ToolInstaller
from sysbot.install.spec import ToolSource
from tests.install_utils import SHA, FakeFetcher, make_github_zip, package_files


def _console() -> Console:
    return Console(file=io.StringIO(), width=200, record=True)


def _manager(tmp_path, fetcher, confirm=lambda _msg: True):
    return ToolInstaller(
        tmp_path / "tools",
        tmp_path / "tools.lock.json",
        fetcher,
        confirm=confirm,
        console=_console(),
    )


def _repo_zip(*names: str, extra: dict[str, str] | None = None) -> bytes:
    files: dict[str, str] = dict(extra or {})
    for name in names:
        for rel, content in package_files(name).items():
            files[f"{name}/{rel}"] = content
    return make_github_zip("repo-HEAD", files)


HEAD_URL = "https://codeload.github.com/acme/repo/zip/HEAD"


def test_install_multi_package(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha", "beta")})
    mgr = _manager(tmp_path, fetcher)
    installed = mgr.install(ToolSource("acme", "repo"), yes=True)

    assert installed == ["alpha", "beta"]
    assert (tmp_path / "tools" / "alpha" / "tool.py").exists()
    assert (tmp_path / "tools" / "beta" / "README.md").exists()

    lock = json.loads((tmp_path / "tools.lock.json").read_text())["tools"]
    assert lock["alpha"]["repo"] == "acme/repo"
    assert lock["alpha"]["subdir"] == "alpha"
    assert lock["alpha"]["commit"] == SHA
    assert lock["alpha"]["version"] == "1.2.0"
    # No stray staging dirs left behind.
    assert not list(tmp_path.glob(".sysbot-stage-*"))


def test_install_subdir_single_package(tmp_path):
    files = {f"tools/gpu/{rel}": c for rel, c in package_files("gpu").items()}
    fetcher = FakeFetcher({HEAD_URL: make_github_zip("repo-HEAD", files)})
    mgr = _manager(tmp_path, fetcher)
    installed = mgr.install(ToolSource("acme", "repo", subdir="tools/gpu"), yes=True)

    assert installed == ["gpu"]
    lock = json.loads((tmp_path / "tools.lock.json").read_text())["tools"]
    assert lock["gpu"]["subdir"] == "tools/gpu"


def test_install_only_filter(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha", "beta")})
    mgr = _manager(tmp_path, fetcher)
    installed = mgr.install(ToolSource("acme", "repo"), only=["beta"], yes=True)
    assert installed == ["beta"]
    assert not (tmp_path / "tools" / "alpha").exists()

    with pytest.raises(ToolInstallError, match="not found"):
        mgr.install(ToolSource("acme", "repo"), only=["nope"], yes=True)


def test_install_empty_repo_errors(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: make_github_zip("repo-HEAD", {"README.md": "hi"})})
    mgr = _manager(tmp_path, fetcher)
    with pytest.raises(ToolInstallError, match="No tool packages"):
        mgr.install(ToolSource("acme", "repo"), yes=True)


def test_install_declined_confirmation(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher, confirm=lambda _msg: False)
    assert mgr.install(ToolSource("acme", "repo")) == []
    assert not (tmp_path / "tools" / "alpha").exists()
    assert not list(tmp_path.glob(".sysbot-stage-*"))


def test_collision_with_unmanaged_dir(tmp_path):
    (tmp_path / "tools" / "alpha").mkdir(parents=True)
    (tmp_path / "tools" / "alpha" / "tool.py").write_text("mine = 1")
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher)

    with pytest.raises(ToolInstallError, match="--force"):
        mgr.install(ToolSource("acme", "repo"), yes=True)
    assert (tmp_path / "tools" / "alpha" / "tool.py").read_text() == "mine = 1"

    mgr.install(ToolSource("acme", "repo"), yes=True, force=True)
    assert "hello" in (tmp_path / "tools" / "alpha" / "tool.py").read_text()


def test_reinstall_of_managed_package(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher)
    mgr.install(ToolSource("acme", "repo"), yes=True)
    first = json.loads((tmp_path / "tools.lock.json").read_text())["tools"]["alpha"]

    # Same name again — owned by the lock, so no --force needed.
    mgr.install(ToolSource("acme", "repo"), yes=True)
    second = json.loads((tmp_path / "tools.lock.json").read_text())["tools"]["alpha"]
    assert second["installed_at"] == first["installed_at"]


def test_requirements_hint_without_flag(tmp_path):
    fetcher = FakeFetcher(
        {HEAD_URL: _repo_zip("alpha", extra={"alpha/requirements.txt": "httpx\n"})}
    )
    mgr = _manager(tmp_path, fetcher)
    mgr.install(ToolSource("acme", "repo"), yes=True)
    out = mgr.console.export_text()
    assert "pip install -r" in out
    assert (tmp_path / "tools" / "alpha" / "requirements.txt").exists()


def test_list_installed_and_unmanaged(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher)
    mgr.install(ToolSource("acme", "repo"), yes=True)
    (tmp_path / "tools" / "seeded").mkdir()

    rows = {r["name"]: r for r in mgr.list_installed()}
    assert rows["alpha"]["managed"] is True and rows["alpha"]["present"] is True
    assert rows["seeded"]["managed"] is False

    # Deleted on disk but still in the lock → flagged missing.
    import shutil

    shutil.rmtree(tmp_path / "tools" / "alpha")
    rows = {r["name"]: r for r in mgr.list_installed()}
    assert rows["alpha"]["present"] is False


def test_info(tmp_path):
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher)
    mgr.install(ToolSource("acme", "repo"), yes=True)
    info = mgr.info("alpha")
    assert info["repo"] == "acme/repo"
    assert "tool.py" in info["files"]

    with pytest.raises(ToolInstallError, match="No tool package"):
        mgr.info("nope")


def test_registry_remove_plus_drop_entries_clears_lock(tmp_path):
    """Removal contract: registry deletes the package, drop_entries cleans the lock."""
    from sysbot.install.lockfile import drop_entries

    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher)
    mgr.install(ToolSource("acme", "repo"), yes=True)

    registry = ToolRegistry()
    registry.load_directory(tmp_path / "tools")
    info = registry.remove_tool("hello")
    assert not (tmp_path / "tools" / "alpha").exists()
    assert drop_entries(tmp_path / "tools.lock.json", [info["unit"]]) == ["alpha"]
    assert json.loads((tmp_path / "tools.lock.json").read_text())["tools"] == {}


def test_installed_package_loads_in_registry(tmp_path):
    """Contract with the existing loader: an installed package's tools register."""
    fetcher = FakeFetcher({HEAD_URL: _repo_zip("alpha")})
    mgr = _manager(tmp_path, fetcher)
    mgr.install(ToolSource("acme", "repo"), yes=True)

    registry = ToolRegistry()
    registry.load_directory(tmp_path / "tools")
    assert "hello" in registry.names
