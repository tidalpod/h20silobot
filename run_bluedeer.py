#!/usr/bin/env python3
"""
Blue Deer Bot

Telegram bot for property management notifications.
Sends alerts for recertifications, water bills, and more.
"""

import asyncio
import logging
import sys
import os

from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main():
    """Main entry point"""
    logger.info("=" * 50)
    logger.info("Blue Deer Bot Starting...")
    logger.info("=" * 50)

    # Get configuration from environment
    token = os.getenv("BLUEDEER_BOT_TOKEN")
    admin_id = os.getenv("BLUEDEER_ADMIN_TELEGRAM_ID", "")
    water_threshold = float(os.getenv("WATER_BILL_THRESHOLD", "100"))
    recert_days = int(os.getenv("RECERT_REMINDER_DAYS", "30"))

    if not token:
        logger.error("BLUEDEER_BOT_TOKEN is required")
        sys.exit(1)

    logger.info(f"BLUEDEER_BOT_TOKEN set: {bool(token)}")
    logger.info(f"BLUEDEER_ADMIN_TELEGRAM_ID: {admin_id or 'Not set'}")
    logger.info(f"WATER_BILL_THRESHOLD: ${water_threshold}")
    logger.info(f"RECERT_REMINDER_DAYS: {recert_days}")

    from bluedeer_bot.bot import BlueDeerBot

    bot = BlueDeerBot(
        token=token,
        admin_chat_id=int(admin_id) if admin_id else None,
        water_bill_threshold=water_threshold,
        recert_reminder_days=recert_days
    )

    try:
        await bot.start()

        # Keep running
        while True:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.exception(f"Bot crashed: {e}")
    finally:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
