from __future__ import annotations

import logging
from typing import Any

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from sysbot.core.config import SlackConfig
from sysbot.messaging.base import MessageHandler as BotHandler, MessagingAdapter

logger = logging.getLogger(__name__)


class SlackAdapter(MessagingAdapter):
    def __init__(self, config: SlackConfig) -> None:
        self._config = config
        self._app = AsyncApp(token=config.bot_token)

    async def start(self, handler: BotHandler) -> None:
        app = self._app

        @app.message()
        async def on_message(message: dict, say: Any) -> None:
            user_id = message.get("user", "unknown")
            text = message.get("text", "")
            reply = await handler(user_id, text)
            await say(reply)

        logger.info("Slack bot starting (Socket Mode)...")
        socket_handler = AsyncSocketModeHandler(app, self._config.app_token)
        await socket_handler.start_async()

    async def send(self, user_id: str, text: str) -> None:
        await self._app.client.chat_postMessage(channel=user_id, text=text)
