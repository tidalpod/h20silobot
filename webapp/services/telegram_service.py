"""Telegram notification service for sending alerts via Blue Deer bot"""

import logging
import os
from typing import List

import aiohttp
from sqlalchemy import select

logger = logging.getLogger(__name__)


class TelegramService:
    """Service for sending Telegram notifications to authorized Blue Deer users"""

    def __init__(self):
        self.token = os.getenv("BLUEDEER_BOT_TOKEN", "")
        self.admin_chat_id = os.getenv("BLUEDEER_ADMIN_TELEGRAM_ID", "")
        self.group_chat_id = os.getenv("BLUEDEER_GROUP_CHAT_ID", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    async def get_notification_chat_ids(self) -> List[int]:
        """Get list of chat IDs to send notifications to (admins + group)"""
        chat_ids = []

        if self.admin_chat_id:
            try:
                chat_ids.append(int(self.admin_chat_id))
            except ValueError:
                pass

        if self.group_chat_id:
            try:
                chat_ids.append(int(self.group_chat_id))
            except ValueError:
                pass

        # Also get admins from TelegramUser table
        try:
            from database.connection import get_session, is_connected
            from database.models import TelegramUser

            if is_connected():
                async with get_session() as session:
                    result = await session.execute(
                        select(TelegramUser).where(
                            TelegramUser.is_admin == True,
                            TelegramUser.notifications_enabled == True
                        )
                    )
                    users = result.scalars().all()
                    for user in users:
                        if user.telegram_id not in chat_ids:
                            chat_ids.append(user.telegram_id)
        except Exception as e:
            logger.error(f"Error getting admin chat IDs: {e}")

        return chat_ids

    async def send_message(self, text: str, chat_id: int = None):
        """Send a Telegram message to a specific chat or all authorized users"""
        if not self.is_configured:
            logger.warning("Telegram service not configured (no BLUEDEER_BOT_TOKEN)")
            return

        if chat_id:
            chat_ids = [chat_id]
        else:
            chat_ids = await self.get_notification_chat_ids()

        if not chat_ids:
            logger.warning("No chat IDs configured for Telegram notifications")
            return

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        async with aiohttp.ClientSession() as http_session:
            for cid in chat_ids:
                try:
                    async with http_session.post(url, json={
                        "chat_id": cid,
                        "text": text,
                        "parse_mode": "Markdown",
                    }) as resp:
                        if resp.status == 200:
                            logger.info(f"Sent Telegram notification to {cid}")
                        else:
                            body = await resp.text()
                            logger.error(f"Telegram API error for {cid}: {resp.status} {body}")
                except Exception as e:
                    logger.error(f"Failed to send Telegram notification to {cid}: {e}")


# Global service instance
telegram_service = TelegramService()
