"""Setup wizard: step chain navigation, config writing, seeding, services.

Drives the wizard through a scripted FakeUI — no terminal, no subprocesses
(service functions get a recording runner), hermetic via LESYSBOT_HOME/HOME
monkeypatching like the rest of the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from lesysbot.setup import apply as apply_mod
from lesysbot.setup import wizard
from lesysbot.setup.wizard import SetupAborted, WizardState

DEFAULT = object()  # scripted answer meaning "accept the offered default"


class FakeUI:
    interactive = True

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []  # (kind, label, offered_default)
        self.eof = False

    def _pop(self, kind, label, default):
        self.calls.append((kind, label, default))
        assert self.answers, f"wizard asked more than scripted: {kind} {label!r}"
        expect_kind, value = self.answers.pop(0)
        assert expect_kind == kind, (
            f"script expected {expect_kind!r} next, wizard asked {kind} {label!r}"
        )
        return default if value is DEFAULT else value

    def menu(self, title, options, default=1):
        return self._pop("menu", title, default)

    def text(self, prompt, default=""):
        return self._pop("text", prompt, default)

    def confirm_yn(self, prompt, default=True):
        return self._pop("confirm", prompt, default)

    def say(self, *_args, **_kw):
        pass

    note = ok = warn = say


def custom_llm_answers(url="http://x:1/v1", model="m1", key="k1"):
    return [("menu", 4), ("text", url), ("text", model), ("text", key)]


def test_back_from_messaging_preserves_llm_answers():
    ui = FakeUI(
        [
            *custom_llm_answers(),
            ("menu", 4),           # messaging: ← Back
            ("menu", DEFAULT),     # LLM menu re-shown, default = Custom (4)
            ("text", DEFAULT),     # previous answers offered as defaults
            ("text", DEFAULT),
            ("text", DEFAULT),
            ("menu", 1),           # Terminal only
        ]
    )
    st = WizardState()
    wizard.run_steps(ui, st, 1)
    assert st.llm_choice == 4
    assert (st.llm_base_url, st.llm_model, st.llm_api_key) == ("http://x:1/v1", "m1", "k1")
    assert st.msg_provider == "cli"
    assert st.needs_service is False
    # The revisited LLM menu offered the previous choice as its default…
    revisit_menu = [c for c in ui.calls if c[0] == "menu" and c[1].startswith("Step 1")][1]
    assert revisit_menu[2] == 4
    # …and the revisited prompts offered the previous answers.
    revisit_url = [c for c in ui.calls if c[0] == "text"][3]
    assert revisit_url[2] == "http://x:1/v1"


def test_backend_switch_clears_followup_answers():
    ui = FakeUI(
        [
            *custom_llm_answers(),
            ("menu", 4),           # messaging: ← Back
            ("menu", 3),           # switch backend to vLLM
            ("text", DEFAULT),     # base URL — must offer the vLLM default
            ("text", DEFAULT),     # model — must offer the vLLM default
            ("menu", 1),           # Terminal only
        ]
    )
    st = WizardState()
    wizard.run_steps(ui, st, 1)
    assert st.llm_base_url == "http://localhost:8000/v1"
    assert st.llm_model == "meta-llama/Llama-3.2-8B-Instruct"
    assert st.llm_api_key == "vllm"
    vllm_url_prompt = [c for c in ui.calls if c[0] == "text"][3]
    assert vllm_url_prompt[2] == "http://localhost:8000/v1"  # not the stale custom URL


def test_esc_at_prompt_reshows_step_menu():
    ui = FakeUI(
        [
            ("menu", 4),
            ("text", None),        # Esc at Base URL → back to this step's menu
            ("menu", 4),
            ("text", "http://y/v1"),
            ("text", "m"),
            ("text", "k"),
            ("menu", 1),
        ]
    )
    st = WizardState()
    wizard.run_steps(ui, st, 1)
    assert st.llm_base_url == "http://y/v1"
    assert len([c for c in ui.calls if c[0] == "menu" and c[1].startswith("Step 1")]) == 2


def test_telegram_ids_validated_and_esc_backs_out():
    ui = FakeUI(
        [
            *custom_llm_answers(),
            ("menu", 2),           # Telegram
            ("text", "tok"),
            ("text", "abc"),       # invalid IDs → re-asked
            ("text", None),        # Esc at IDs → back to messaging menu
            ("menu", 2),           # Telegram again (token remembered)
            ("text", DEFAULT),
            ("text", "42, 43"),    # spaces stripped, then valid
            ("menu", 2),           # service: start now only
        ]
    )
    st = WizardState()
    wizard.run_steps(ui, st, 1)
    assert st.msg_provider == "telegram"
    assert st.tg_token == "tok"
    assert st.tg_allowed_ids == "[42, 43]"
    assert st.auto_start is False
    assert st.needs_service is True


def test_telegram_ids_eof_aborts():
    ui = FakeUI([*custom_llm_answers(), ("menu", 2), ("text", "tok"), ("text", "")])
    ui.eof = True  # piped input has run dry; "" is invalid and can never improve
    st = WizardState()
    with pytest.raises(SetupAborted):
        wizard.run_steps(ui, st, 1)


def test_summary_change_reach_and_apply(tmp_path):
    st = WizardState(llm_choice=4, llm_base_url="u", llm_model="m", llm_api_key="k")
    ui = FakeUI(
        [
            ("menu", 3),           # summary: Change how to reach LeSysBot
            ("menu", 3),           # messaging: Slack
            ("text", "xoxb"),
            ("text", "xapp"),
            ("menu", 1),           # service: start now + reboot
            ("menu", 1),           # summary: Apply
        ]
    )
    assert wizard.step_summary(ui, st, tmp_path) is True
    assert st.msg_provider == "slack"
    assert st.auto_start is True
    # With a service pending, the summary menu grows the startup entry.
    summary_menus = [c for c in ui.calls if c[0] == "menu" and c[1] == "Ready?"]
    assert len(summary_menus) == 2


def test_summary_quit_without_writing(tmp_path):
    st = WizardState()
    ui = FakeUI([("menu", 4)])  # no service → Quit is option 4
    assert wizard.step_summary(ui, st, tmp_path) is False


def test_write_config_roundtrip(tmp_path):
    st = WizardState(
        llm_base_url="http://x/v1",
        llm_model="mm",
        llm_api_key="kk",
        msg_provider="telegram",
        tg_token="t0k",
        tg_allowed_ids="[1, 2]",
    )
    path = apply_mod.write_config(st, tmp_path)
    cfg = yaml.safe_load(path.read_text())
    assert cfg["messaging"]["provider"] == "telegram"
    assert cfg["messaging"]["telegram"]["token"] == "t0k"
    assert cfg["messaging"]["telegram"]["allowed_user_ids"] == [1, 2]
    assert cfg["llm"]["base_url"] == "http://x/v1"
    assert cfg["llm"]["model"] == "mm"
    assert cfg["mcp"]["tools_dir"] == "./tools"


def test_read_provider(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("messaging:\n  provider: slack\n")
    assert apply_mod.read_provider(cfg) == "slack"
    cfg.write_text("# nothing\n")
    assert apply_mod.read_provider(cfg) == "cli"


def test_seed_tools_copies_once_and_skips_pycache(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tools" / "demo").mkdir(parents=True)
    (repo / "tools" / "demo" / "tool.py").write_text("x = 1\n")
    (repo / "tools" / "__pycache__").mkdir()
    data = tmp_path / "home"
    data.mkdir()
    assert apply_mod.seed_tools(repo, data) is True
    assert (data / "tools" / "demo" / "tool.py").exists()
    assert not (data / "tools" / "__pycache__").exists()
    # Never clobber an existing tools dir on re-install.
    assert apply_mod.seed_tools(repo, data) is False
    assert apply_mod.seed_tools(None, data) is False


class Recorder:
    def __init__(self, returncode=0):
        self.calls = []
        self.returncode = returncode

    def __call__(self, cmd, **_kw):
        self.calls.append(cmd)
        import subprocess

        return subprocess.CompletedProcess(cmd, self.returncode, stdout="", stderr="")


def test_setup_service_linux_writes_unit_and_enables(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    st = WizardState(auto_start=True)
    runner = Recorder()
    ui = FakeUI([])
    apply_mod.setup_service_linux(ui, st, Path("/data"), runner=runner)
    unit = tmp_path / ".config" / "systemd" / "user" / "lesysbot.service"
    assert unit.exists()
    assert "WorkingDirectory=/data" in unit.read_text()
    flat = [" ".join(c) for c in runner.calls]
    assert any("enable lesysbot" in c for c in flat)
    assert any("restart lesysbot" in c for c in flat)


def test_remove_stale_service_linux_confirm_no_keeps_unit(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    unit = tmp_path / ".config" / "systemd" / "user" / "lesysbot.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("[Unit]\n")
    runner = Recorder(returncode=1)  # is-active probe: not running
    ui = FakeUI([("confirm", False)])
    apply_mod.remove_stale_service_linux(ui, runner=runner)
    assert unit.exists()
    ui = FakeUI([("confirm", True)])
    apply_mod.remove_stale_service_linux(ui, runner=runner)
    assert not unit.exists()


def test_cli_run_fresh_config(tmp_path, monkeypatch):
    import argparse

    from lesysbot.setup import cli as setup_cli

    monkeypatch.setenv("LESYSBOT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path))  # keep stale-service checks hermetic
    ui = FakeUI(
        [
            *custom_llm_answers(),
            ("menu", 1),           # Terminal only
            ("menu", 1),           # summary: Apply
        ]
    )
    monkeypatch.setattr("lesysbot.setup.ui.make_ui", lambda: ui)
    args = argparse.Namespace(command="setup", repo=None)
    assert setup_cli.run(args) == 0
    cfg = yaml.safe_load((tmp_path / "home" / "config.yaml").read_text())
    assert cfg["messaging"]["provider"] == "cli"
    assert cfg["llm"]["model"] == "m1"


def test_cli_run_keeps_existing_config(tmp_path, monkeypatch):
    import argparse

    from lesysbot.setup import cli as setup_cli

    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("messaging:\n  provider: cli\n")
    monkeypatch.setenv("LESYSBOT_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path))
    ui = FakeUI(
        [
            ("confirm", False),    # don't overwrite
            ("confirm", True),     # apply
        ]
    )
    monkeypatch.setattr("lesysbot.setup.ui.make_ui", lambda: ui)
    args = argparse.Namespace(command="setup", repo=None)
    assert setup_cli.run(args) == 0
    assert (home / "config.yaml").read_text() == "messaging:\n  provider: cli\n"
