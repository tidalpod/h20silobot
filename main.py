#!/usr/bin/env python3
"""
Water Bill Tracker Bot

Main entry point for the Telegram bot that tracks water bills from BSA Online.
"""

import asyncio
import logging
import sys

from config import config
from bot.bot import WaterBillBot

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log")
    ]
)

# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def main():
    """Main entry point"""
    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error("Configuration errors:")
        for error in errors:
            logger.error(f"  - {error}")
        sys.exit(1)

    bot = WaterBillBot()

    try:
        await bot.start()

        # Keep running
        logger.info("Bot is running. Press Ctrl+C to stop.")
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
