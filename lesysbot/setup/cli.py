"""`lesysbot setup` — argument wiring and the top-level setup flow.

The install scripts bootstrap (Python check + pip install) and then exec this
command; it also runs standalone at any time to reconfigure an existing
install. Flow: fresh config → wizard chain + summary (nothing written until
Apply); existing config kept → only the service question. Then bundled-tools
seeding (never clobbers), platform service setup for Telegram/Slack, or
stale-service cleanup for Terminal-only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from lesysbot.core.paths import user_dir


def register_subcommand(subparsers: argparse._SubParsersAction) -> None:
    setup = subparsers.add_parser(
        "setup",
        help="Interactive setup wizard — configure LLM, messaging, and the service",
    )
    setup.add_argument(
        "--repo",
        default=None,
        help="Repo checkout to seed bundled tools/ from (passed by the install scripts)",
    )


def run(args: argparse.Namespace) -> int:
    from lesysbot.setup import apply, wizard
    from lesysbot.setup.ui import make_ui

    ui = make_ui()
    data_dir = user_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    repo_dir = Path(args.repo).resolve() if getattr(args, "repo", None) else None
    config_file = data_dir / "config.yaml"

    ui.say("\n  [bold]LeSysBot Setup[/bold]")
    ui.say("  " + "─" * 50)

    keep_config = False
    if config_file.exists():
        ui.say("")
        keep_config = not ui.confirm_yn(
            f"{config_file} already exists — overwrite with new settings?", default=False
        )
        if keep_config:
            ui.note("Keeping existing config.yaml.")

    if not keep_config:
        # Fresh config: LLM → messaging → service steps with back/forward
        # navigation, then a summary menu that can jump back into any step.
        # config.yaml is only written once the summary's Apply is chosen.
        st = wizard.WizardState()
        wizard.run_steps(ui, st, 1)
        if not wizard.step_summary(ui, st, data_dir):
            ui.say("\n  [yellow]Aborted — nothing was written.[/yellow]")
            ui.note("(The lesysbot package itself remains installed — re-run `lesysbot setup` anytime.)")
            return 0
        provider = st.msg_provider
        needs_service = st.needs_service
        apply.write_config(st, data_dir)
        ui.ok(f"config.yaml written to {config_file}")
    else:
        # Existing config kept — read the provider back from it. Only Telegram
        # and Slack need an always-on background service; only the service
        # question applies here, so there is no step navigation.
        st = wizard.WizardState()
        provider = apply.read_provider(config_file)
        st.msg_provider = provider
        needs_service = st.needs_service = provider in ("telegram", "slack")
        st.auto_start = False
        if needs_service:
            ui.say(f"\n  A {provider} bot runs in the background, so it installs as a service.\n")
            st.auto_start = ui.confirm_yn("Start LeSysBot automatically after reboot?", default=True)

        wizard.show_summary(ui, st, data_dir)
        if not ui.confirm_yn("Apply these settings?", default=True):
            ui.say("\n  [yellow]Aborted.[/yellow]")
            return 0

    if apply.seed_tools(repo_dir, data_dir):
        ui.ok(f"tools copied to {data_dir / 'tools'}")

    if needs_service:
        ui.say("")
        apply.setup_service(ui, st, data_dir)
    else:
        # Terminal-only: no daemon needed. Clean up any leftover service so it
        # doesn't keep running in the background with stale settings.
        apply.remove_stale_service(ui)

    apply.print_epilogue(ui, provider, needs_service, data_dir)
    return 0
