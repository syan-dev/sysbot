from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

from sysbot.core.agent import Agent
from sysbot.core.config import LogConfig, Settings


def _setup_logging(verbose: bool, log_cfg: LogConfig, interactive: bool = False) -> None:
    # Baseline level comes from config (`logging.level`); `-v` forces DEBUG.
    base = getattr(logging, str(log_cfg.level).upper(), logging.INFO)
    # Interactive CLI keeps the console at WARNING+ (no httpx/watchfiles/"Tools
    # loaded" INFO interrupting the chat); the daemons honour the config level.
    if verbose:
        console_level = logging.DEBUG
    elif interactive:
        console_level = max(base, logging.WARNING)
    else:
        console_level = base

    console = RichHandler(rich_tracebacks=True, show_path=False)
    console.setLevel(console_level)
    handlers: list[logging.Handler] = [console]

    if log_cfg.file:
        Path(log_cfg.file).parent.mkdir(parents=True, exist_ok=True)
        # Time-based rotation: roll over per `when` (default midnight) and keep
        # `backup_count` dated files (e.g. sysbot.log.2026-06-21) so it can't grow
        # without bound.
        fh = TimedRotatingFileHandler(
            log_cfg.file,
            when=log_cfg.when,
            backupCount=log_cfg.backup_count,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG if verbose else base)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
        handlers.append(fh)

    # Root at DEBUG so handlers decide what they emit (each has its own level).
    logging.basicConfig(level=logging.DEBUG, format="%(message)s", handlers=handlers)


async def _run(settings: Settings) -> None:
    agent = Agent(settings)
    await agent.setup()

    provider = settings.messaging.provider

    if provider == "cli":
        from sysbot.messaging.cli import CLIAdapter
        adapter = CLIAdapter()

    elif provider == "telegram":
        from sysbot.messaging.telegram import TelegramAdapter
        adapter = TelegramAdapter(settings.messaging.telegram)

    elif provider == "slack":
        from sysbot.messaging.slack import SlackAdapter
        adapter = SlackAdapter(settings.messaging.slack)

    else:
        print(f"Unknown messaging provider: {provider}", file=sys.stderr)
        sys.exit(1)

    # Wire the adapter's confirmation UI into the agent so tools marked
    # confirm=True will prompt the user before executing.
    agent.set_confirm_fn(adapter.confirm)

    # The messaging adapter is the primary service; the dashboard (web UI) runs
    # as a background task beside it. When the adapter finishes — e.g. the CLI
    # user types `exit`, or a daemon is cancelled — the background tasks are
    # cancelled so the process exits cleanly instead of hanging on a
    # forever-running service.
    background: list[asyncio.Task] = []

    if settings.dashboard.enabled:
        from sysbot.dashboard import Dashboard
        background.append(asyncio.create_task(Dashboard(agent, settings).start()))

    try:
        await adapter.start(agent.handle)
    finally:
        for task in background:
            task.cancel()
        if background:
            await asyncio.gather(*background, return_exceptions=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sysbot", description="SysBot — local LLM + tools bot")
    parser.add_argument("-c", "--config", default=None, help="Path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "--provider",
        choices=["cli", "telegram", "slack"],
        default=None,
        help="Override messaging provider",
    )
    parser.add_argument("--model", default=None, help="Override LLM model name")
    parser.add_argument("--base-url", default=None, help="Override LLM base URL")
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Serve the web dashboard (manage tools, check LLM health) alongside the bot",
    )

    # Optional subcommands (`sysbot tools …`) — bare `sysbot [flags]` still
    # runs the bot.
    from sysbot.mcp.cli import register_subcommands

    subparsers = parser.add_subparsers(dest="command", metavar="{tools}")
    register_subcommands(subparsers)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if getattr(args, "command", None):
        from sysbot.mcp.cli import run as run_tool_cli

        sys.exit(run_tool_cli(args))

    settings = Settings.load(args.config)
    if args.provider:
        settings.messaging.provider = args.provider
    if args.model:
        settings.llm.model = args.model
    if args.base_url:
        settings.llm.base_url = args.base_url
    if args.dashboard:
        settings.dashboard.enabled = True

    # Anchor relative tools/log/state paths next to the active config (shared
    # with the `sysbot tools` CLI so both resolve the same tools dir).
    from sysbot.core.config import resolve_paths

    resolve_paths(settings)

    _setup_logging(
        args.verbose,
        settings.logging,
        interactive=(settings.messaging.provider == "cli"),
    )

    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
