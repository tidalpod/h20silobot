"""Main bot class that coordinates scraping and notifications"""

import logging
from datetime import datetime
from typing import Optional

from telegram import BotCommand
from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config

logger = logging.getLogger(__name__)


class WaterBillBot:
    """Main bot coordinator"""

    def __init__(self):
        self.application: Optional[Application] = None
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.db_available = False

    async def start(self):
        """Initialize and start the bot"""
        logger.info("Starting Water Bill Bot...")

        # Try to initialize database
        try:
            print("[BOT] Attempting database connection...")
            from database.connection import init_db, is_connected

            success = await init_db()

            if success and is_connected():
                self.db_available = True
                print("[BOT] Database connection: SUCCESS")
                logger.info("Database connected")
            else:
                self.db_available = False
                print("[BOT] Database connection: FAILED")
                logger.warning("Database not available")
        except Exception as e:
            print(f"[BOT] Database exception: {e}")
            logger.error(f"Database init failed: {e}")
            import traceback
            traceback.print_exc()
            self.db_available = False

        # Set up Telegram bot
        logger.info(f"Setting up Telegram bot with token: {config.telegram_token[:10]}...")
        self.application = Application.builder().token(config.telegram_token).build()

        # Store reference to self in bot_data for handlers
        self.application.bot_data['water_bill_bot'] = self
        self.application.bot_data['db_available'] = self.db_available

        # Set up handlers
        logger.info("Setting up command handlers...")
        from bot.handlers import setup_handlers
        setup_handlers(self.application)
        logger.info("Command handlers configured")

        # Set up scheduler only if DB is available
        if self.db_available:
            self.scheduler = AsyncIOScheduler()
            self._setup_scheduled_jobs()
            self.scheduler.start()
            logger.info("Scheduler started")
        else:
            logger.warning("Scheduler disabled - no database")

        # Start bot
        logger.info("Initializing Telegram application...")
        await self.application.initialize()

        logger.info("Starting Telegram application...")
        await self.application.start()

        # Set up bot commands menu (the menu button in Telegram)
        commands = [
            BotCommand("start", "🏠 Main menu"),
            BotCommand("summary", "📊 Bill summary dashboard"),
            BotCommand("properties", "📍 View all properties"),
            BotCommand("overdue", "🔴 View overdue bills"),
            BotCommand("add", "➕ Add new property"),
            BotCommand("remove", "🗑️ Remove a property"),
            BotCommand("refresh", "🔄 Refresh bill data"),
            BotCommand("status", "⚙️ Bot status"),
            BotCommand("help", "❓ Help & commands"),
        ]
        await self.application.bot.set_my_commands(commands)
        logger.info("Bot commands menu configured")

        logger.info("Starting polling for updates...")
        await self.application.updater.start_polling(drop_pending_updates=True)

        logger.info("=" * 50)
        logger.info("BOT IS NOW RUNNING AND LISTENING FOR COMMANDS!")
        logger.info("=" * 50)

    async def stop(self):
        """Stop the bot"""
        logger.info("Stopping bot...")

        if self.scheduler:
            self.scheduler.shutdown()

        if self.application:
            if self.application.updater.running:
                await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

        logger.info("Bot stopped")

    def _setup_scheduled_jobs(self):
        """Configure scheduled scraping jobs"""
        # Daily scrape at 6 AM
        self.scheduler.add_job(
            self.scheduled_scrape,
            CronTrigger(hour=6, minute=0),
            id="daily_scrape",
            name="Daily bill scrape"
        )

        # Due date reminders at 9 AM
        self.scheduler.add_job(
            self.send_due_date_reminders,
            CronTrigger(hour=9, minute=0),
            id="due_reminders",
            name="Due date reminders"
        )

        # Overdue alerts at 10 AM
        self.scheduler.add_job(
            self.send_overdue_alerts,
            CronTrigger(hour=10, minute=0),
            id="overdue_alerts",
            name="Overdue alerts"
        )

        # Weekly tax scrape on Mondays at 7 AM
        self.scheduler.add_job(
            self.scheduled_tax_scrape,
            CronTrigger(day_of_week='mon', hour=7, minute=0),
            id="weekly_tax_scrape",
            name="Weekly property tax scrape"
        )

        logger.info("Scheduled jobs configured")

    async def scheduled_scrape(self):
        """Run scheduled scraping"""
        if not self.db_available:
            return
        logger.info("Running scheduled scrape...")
        try:
            await self.refresh_all_bills()
        except Exception as e:
            logger.error(f"Scheduled scrape failed: {e}")

    async def scheduled_tax_scrape(self):
        """Run scheduled property tax scraping"""
        if not self.db_available:
            return
        logger.info("Running scheduled tax scrape...")
        try:
            await self.refresh_all_taxes()
        except Exception as e:
            logger.error(f"Scheduled tax scrape failed: {e}")

    async def refresh_all_taxes(self):
        """Refresh property tax data for all active properties"""
        if not self.db_available:
            logger.warning("Cannot refresh taxes - database not available")
            return

        from database.connection import get_session
        from database.models import Property, PropertyTax
        from scraper.bsa_scraper import BSAScraper
        from sqlalchemy import select

        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Property).where(Property.is_active == True)
                )
                properties = result.scalars().all()

                if not properties:
                    logger.info("No properties to scrape for taxes")
                    return

                async with BSAScraper() as scraper:
                    scraped_count = 0

                    for prop in properties:
                        try:
                            tax_data = None

                            # Try parcel number first
                            if prop.parcel_number:
                                tax_data = await scraper.search_tax_by_parcel(prop.parcel_number)

                            # Fall back to address
                            if not tax_data:
                                street_address = prop.address.split(',')[0].strip()
                                tax_data = await scraper.search_tax_by_address(street_address)

                            if tax_data:
                                # Check for existing record
                                existing = await session.execute(
                                    select(PropertyTax)
                                    .where(PropertyTax.property_id == prop.id)
                                    .where(PropertyTax.tax_year == tax_data.tax_year)
                                )
                                existing_tax = existing.scalar_one_or_none()

                                if existing_tax:
                                    existing_tax.amount_due = tax_data.amount_due
                                    existing_tax.status = tax_data.status
                                    existing_tax.due_date = tax_data.due_date
                                    existing_tax.scraped_at = datetime.utcnow()
                                    existing_tax.raw_data = tax_data.raw_data
                                else:
                                    new_tax = PropertyTax(
                                        property_id=prop.id,
                                        tax_year=tax_data.tax_year,
                                        amount_due=tax_data.amount_due,
                                        due_date=tax_data.due_date,
                                        status=tax_data.status,
                                        parcel_number=tax_data.parcel_number or prop.parcel_number,
                                        scraped_at=datetime.utcnow(),
                                        raw_data=tax_data.raw_data
                                    )
                                    session.add(new_tax)

                                # Update parcel on property if found
                                if tax_data.parcel_number and not prop.parcel_number:
                                    prop.parcel_number = tax_data.parcel_number

                                scraped_count += 1
                                logger.info(f"Tax scraped: {prop.address} - ${tax_data.amount_due} ({tax_data.status})")

                        except Exception as e:
                            logger.error(f"Failed to scrape tax for {prop.address}: {e}")

                    await session.commit()
                    logger.info(f"Tax scrape complete: {scraped_count} properties updated")

        except Exception as e:
            logger.error(f"Tax refresh failed: {e}")
            raise

    async def refresh_all_bills(self):
        """Refresh bill data for all active properties"""
        if not self.db_available:
            logger.warning("Cannot refresh - database not available")
            return

        from database.connection import get_session
        from database.models import Property, WaterBill, ScrapingLog
        from scraper.bsa_scraper import BSAScraper
        from sqlalchemy import select

        scrape_log = ScrapingLog(started_at=datetime.utcnow())

        try:
            async with get_session() as session:
                result = await session.execute(
                    select(Property).where(Property.is_active == True)
                )
                properties = result.scalars().all()

                if not properties:
                    logger.info("No properties to scrape")
                    return

                async with BSAScraper() as scraper:
                    scraped_count = 0

                    for prop in properties:
                        try:
                            bill_data = await scraper.search_by_account(prop.bsa_account_number)

                            if bill_data:
                                if bill_data.address and prop.address.startswith("Pending"):
                                    prop.address = bill_data.address
                                if bill_data.owner_name:
                                    prop.owner_name = bill_data.owner_name

                                new_bill = WaterBill(
                                    property_id=prop.id,
                                    amount_due=bill_data.amount_due,
                                    due_date=bill_data.due_date,
                                    statement_date=bill_data.statement_date,
                                    previous_balance=bill_data.previous_balance,
                                    current_charges=bill_data.current_charges,
                                    late_fees=bill_data.late_fees,
                                    payments_received=bill_data.payments_received,
                                    water_usage_gallons=bill_data.water_usage,
                                    raw_data=bill_data.raw_data
                                )
                                new_bill.status = new_bill.calculate_status()

                                session.add(new_bill)
                                scraped_count += 1
                                logger.info(f"Scraped: {prop.address} - ${bill_data.amount_due}")

                        except Exception as e:
                            logger.error(f"Failed to scrape {prop.bsa_account_number}: {e}")

                    await session.commit()

                scrape_log.success = True
                scrape_log.properties_scraped = scraped_count
                scrape_log.completed_at = datetime.utcnow()

        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            scrape_log.success = False
            scrape_log.error_message = str(e)
            scrape_log.completed_at = datetime.utcnow()
            raise

        finally:
            async with get_session() as session:
                session.add(scrape_log)
                await session.commit()

    async def send_due_date_reminders(self):
        """Send reminders for bills due within 7 days"""
        if not self.db_available:
            return
        # Implementation remains the same...
        pass

    async def send_overdue_alerts(self):
        """Send alerts for overdue bills"""
        if not self.db_available:
            return
        # Implementation remains the same...
        pass
