"""Shared authorization gate for Telegram bot commands and callbacks."""

from __future__ import annotations

import logging
import os
from functools import wraps

from telegram.ext import ConversationHandler


logger = logging.getLogger(__name__)


def configured_admin_ids() -> set[int]:
    """Return the explicit Telegram user allowlist from environment variables."""
    values: set[int] = set()
    for name in (
        "BLUEDEER_BOT_USER_IDS",
        "BLUEDEER_VAULT_USER_IDS",
        "BLUEDEER_ADMIN_TELEGRAM_ID",
        "TELEGRAM_ADMIN_USER_IDS",
    ):
        for token in os.getenv(name, "").split(","):
            token = token.strip()
            if not token:
                continue
            try:
                values.add(int(token))
            except ValueError:
                logger.warning("Ignoring invalid Telegram user ID in %s", name)
    return values


async def is_authorized(update, context) -> bool:
    """Authorize an explicitly allowlisted user or an active DB administrator."""
    user = update.effective_user
    if user is None:
        return False
    if user.id in configured_admin_ids():
        return True
    if not context.bot_data.get("db_available", False):
        return False

    try:
        from database.connection import get_session
        from database.models import TelegramUser
        from sqlalchemy import select

        async with get_session() as session:
            result = await session.execute(
                select(TelegramUser.id).where(
                    TelegramUser.telegram_id == user.id,
                    TelegramUser.is_admin.is_(True),
                )
            )
            return result.scalar_one_or_none() is not None
    except Exception:
        logger.exception("Telegram authorization lookup failed")
        return False


async def _deny(update) -> None:
    if update.callback_query is not None:
        await update.callback_query.answer("Not authorized.", show_alert=True)
    elif update.effective_message is not None:
        await update.effective_message.reply_text("Not authorized.")


def admin_only(callback):
    """Wrap a python-telegram-bot callback with a fail-closed admin check."""
    @wraps(callback)
    async def wrapped(update, context):
        if not await is_authorized(update, context):
            await _deny(update)
            return ConversationHandler.END
        return await callback(update, context)

    return wrapped
