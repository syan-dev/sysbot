from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from rich.logging import RichHandler

from sysbot.core.agent import Agent
from sysbot.core.config import Settings


def _setup_logging(
    verbose: bool, log_file: str | None = None, interactive: bool = False
) -> None:
    # Console level: verbose → DEBUG; interactive CLI → WARNING (keep the chat
    # clean — no httpx/watchfiles/"Tools loaded" INFO spam); otherwise INFO.
    # The root logger stays at DEBUG so the file handler always captures detail.
    console_level = (
        logging.DEBUG if verbose else logging.WARNING if interactive else logging.INFO
    )
    console = RichHandler(rich_tracebacks=True, show_path=False)
    console.setLevel(console_level)
    handlers: list[logging.Handler] = [console]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
        handlers.append(fh)
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

    await adapter.start(agent.handle)


def main() -> None:
    parser = argparse.ArgumentParser(description="SysBot — local LLM + tools bot")
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
    args = parser.parse_args()

    settings = Settings.load(args.config)
    if args.provider:
        settings.messaging.provider = args.provider
    if args.model:
        settings.llm.model = args.model
    if args.base_url:
        settings.llm.base_url = args.base_url

    # Anchor relative paths to the app directory. For a normal run this is the
    # current working directory (no change); for a frozen .exe it's the folder
    # containing the executable, so tools/ and logs/ resolve next to it.
    from sysbot.core.paths import anchor

    settings.mcp.tools_dir = anchor(settings.mcp.tools_dir)
    if settings.logging.file:
        settings.logging.file = anchor(settings.logging.file)
    if settings.logging.trace_file:
        settings.logging.trace_file = anchor(settings.logging.trace_file)

    _setup_logging(
        args.verbose,
        settings.logging.file,
        interactive=(settings.messaging.provider == "cli"),
    )

    try:
        asyncio.run(_run(settings))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
