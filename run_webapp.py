#!/usr/bin/env python3
"""
H2O Silo Web Application Entry Point

Run the FastAPI web application for property management.

Usage:
    python run_webapp.py

Or with uvicorn directly:
    uvicorn webapp.main:app --reload --port 8000
"""

import asyncio
import logging
import sys

import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def main():
    """Run the web application"""
    from webapp.config import web_config

    # Validate configuration
    errors = web_config.validate()
    if errors:
        for error in errors:
            logger.warning(f"Config warning: {error}")

    logger.info(f"Starting H2O Silo Web App on {web_config.host}:{web_config.port}")
    logger.info(f"Debug mode: {web_config.debug}")

    # Service status
    if web_config.has_twilio:
        logger.info("Twilio SMS: Configured")
    else:
        logger.warning("Twilio SMS: Not configured")

    if web_config.has_sendgrid:
        logger.info("SendGrid Email: Configured")
    elif web_config.has_smtp:
        logger.info("SMTP Email: Configured")
    else:
        logger.warning("Email: Not configured")

    # Run the app
    uvicorn.run(
        "webapp.main:app",
        host=web_config.host,
        port=web_config.port,
        reload=web_config.debug,
        log_level="info" if not web_config.debug else "debug",
    )


if __name__ == "__main__":
    main()
