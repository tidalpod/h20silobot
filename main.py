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

# Configure logging (stdout only for Railway)
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

    # Log environment check
    logger.info(f"TELEGRAM_BOT_TOKEN set: {bool(os.getenv('TELEGRAM_BOT_TOKEN'))}")
    logger.info(f"DATABASE_URL set: {bool(os.getenv('DATABASE_URL'))}")

    # Import after logging setup
    from config import config
    from bot.bot import BlueDeerBot

    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error("Configuration errors:")
        for error in errors:
            logger.error(f"  - {error}")
        logger.error("Exiting due to configuration errors")
        sys.exit(1)

    logger.info("Configuration validated successfully")

    bot = BlueDeerBot()

    try:
        logger.info("Initializing bot...")
        await bot.start()
        logger.info("Bot started successfully!")
        logger.info("Waiting for messages...")

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
