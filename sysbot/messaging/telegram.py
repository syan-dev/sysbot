from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from sysbot.core.config import TelegramConfig
from sysbot.messaging.base import MessageHandler as BotHandler, MessagingAdapter

logger = logging.getLogger(__name__)

_MAX_MSG_LEN = 4000  # Telegram hard limit is 4096; leave headroom


class TelegramAdapter(MessagingAdapter):
    def __init__(self, config: TelegramConfig) -> None:
        self._config = config
        self._app: Application | None = None
        # Pending confirmation callbacks keyed by callback_id
        self._pending: dict[str, asyncio.Event] = {}
        self._confirmed: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Confirmation via inline keyboard buttons
    # ------------------------------------------------------------------

    async def confirm(
        self,
        user_id: str,
        tool_name: str,
        prompt: str,
        args: dict[str, Any],
    ) -> bool:
        if not self._app:
            return True

        callback_id = uuid.uuid4().hex[:8]
        event = asyncio.Event()
        self._pending[callback_id] = event

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes", callback_data=f"confirm:{callback_id}:yes"),
                InlineKeyboardButton("❌ No", callback_data=f"confirm:{callback_id}:no"),
            ]
        ])

        lines = [f"⚠️ *{prompt}*", f"Tool: `{tool_name}`"]
        if args:
            args_lines = "\n".join(f"  • {k}: `{v}`" for k, v in args.items())
            lines.append(f"Args:\n{args_lines}")

        text = "\n".join(lines)
        try:
            await self._app.bot.send_message(
                chat_id=int(user_id),
                text=text,
                reply_markup=keyboard,
                parse_mode="Markdown",
            )
        except BadRequest:
            # Tool args with Markdown-hostile characters (lone "_", "*", …) must
            # not kill the prompt — the user would never get asked and the
            # confirmation would time out. Resend plain.
            await self._app.bot.send_message(
                chat_id=int(user_id), text=text, reply_markup=keyboard
            )

        try:
            await asyncio.wait_for(event.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            self._pending.pop(callback_id, None)
            logger.warning("Confirmation timed out for %s/%s", tool_name, callback_id)
            return False
        finally:
            self._pending.pop(callback_id, None)

        return self._confirmed.pop(callback_id, False)

    # ------------------------------------------------------------------
    # Adapter lifecycle
    # ------------------------------------------------------------------

    async def start(self, handler: BotHandler) -> None:
        # concurrent_updates(True) is REQUIRED for the confirmation flow: confirm()
        # blocks on_message awaiting a button press, and PTB processes updates
        # sequentially by default — so the callback-query update carrying that press
        # would queue *behind* the very handler waiting on it, deadlocking until the
        # 120s timeout fires (Telegram then rejects the now-stale callback as "too old").
        self._app = (
            Application.builder()
            .token(self._config.token)
            .concurrent_updates(True)
            .build()
        )
        allowed = set(self._config.allowed_user_ids)

        def _authorized(user_id: str) -> bool:
            return not allowed or int(user_id) in allowed

        async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.effective_user:
                return
            user_id = str(update.effective_user.id)
            if not _authorized(user_id):
                await update.message.reply_text("Unauthorized.")
                return

            text = update.message.text or ""

            # /start is a Telegram convention — give a friendly greeting
            if text.strip() in ("/start", f"/start@{ctx.bot.username}"):
                await update.message.reply_text(
                    "👋 Hi\\! I'm *SysBot*\\.\n\n"
                    "Send me a message to chat with the AI, or use `/help` to "
                    "see available tool commands \\(no LLM needed\\)\\.",
                    parse_mode="MarkdownV2",
                )
                return

            reply = await handler(user_id, text)
            for chunk in _split(reply):
                await _reply_safe(update.message, chunk)

        async def on_callback_query(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            query = update.callback_query
            if not query:
                return
            try:
                await query.answer()
            except BadRequest as exc:
                # Stale tap (e.g. an old prompt tapped after Telegram expired the
                # query): nothing to confirm anymore — drop it without a traceback.
                logger.debug("Ignoring stale callback query: %s", exc)
                return
            data = query.data or ""
            if not data.startswith("confirm:"):
                return
            parts = data.split(":", 2)
            if len(parts) != 3:
                return
            _, callback_id, choice = parts
            if callback_id in self._pending:
                self._confirmed[callback_id] = choice == "yes"
                self._pending[callback_id].set()
            status = "✅ Confirmed" if choice == "yes" else "❌ Cancelled"
            if query.message:
                try:
                    # query.message.text is rendered plain text — re-parsing it as
                    # Markdown fails on e.g. the "_" in `power_off` (BadRequest),
                    # which would silently drop this ack and leave the buttons up.
                    # Keep the original entities instead: the old text is an
                    # unchanged prefix, so their offsets stay valid.
                    await query.edit_message_text(
                        f"{query.message.text}\n\n{status}",
                        entities=query.message.entities,
                    )
                except Exception:
                    pass  # message may have been deleted

        async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            # One place for unhandled errors so PTB stops logging
            # "No error handlers are registered" with a bare traceback.
            logger.warning("Telegram update error: %s", ctx.error)

        # Route ALL text messages (including /commands) to on_message so
        # the agent's slash-command handler can process them without LLM.
        self._app.add_handler(MessageHandler(filters.TEXT, on_message))
        self._app.add_handler(CallbackQueryHandler(on_callback_query))
        self._app.add_error_handler(on_error)

        logger.info("Telegram bot starting (polling)...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

        # python-telegram-bot v20+ removed Updater.idle(); keep the coroutine
        # alive until cancelled (e.g. Ctrl-C), then shut down gracefully.
        try:
            await asyncio.Event().wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def send(self, user_id: str, text: str) -> None:
        if self._app:
            for chunk in _split(text):
                await self._app.bot.send_message(chat_id=int(user_id), text=chunk)


async def _reply_safe(message: Message, text: str) -> None:
    """Reply with Markdown, falling back to plain text if the LLM output
    isn't valid Telegram Markdown (which would otherwise drop the message)."""
    try:
        await message.reply_text(text, parse_mode="Markdown")
    except BadRequest:
        await message.reply_text(text)


def _split(text: str, max_len: int = _MAX_MSG_LEN) -> list[str]:
    """Split a long string into chunks that fit Telegram's message size limit.

    Empty/whitespace-only input yields no chunks — Telegram rejects empty
    messages ("Message text is empty"), which would otherwise drop silently."""
    if not text.strip():
        return []
    if len(text) <= max_len:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:max_len])
        text = text[max_len:]
    return chunks
