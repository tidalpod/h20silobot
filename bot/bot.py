"""Main bot class that coordinates scraping and notifications"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config import config
from database.connection import get_session, init_db
from database.models import Property, WaterBill, BillStatus, ScrapingLog, TelegramUser
from scraper.bsa_scraper import BSAScraper

logger = logging.getLogger(__name__)


class WaterBillBot:
    """Main bot coordinator"""

    def __init__(self):
        self.application: Optional[Application] = None
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.scraper: Optional[BSAScraper] = None

    async def start(self):
        """Initialize and start the bot"""
        logger.info("Starting Water Bill Bot...")

        # Initialize database
        await init_db()
        logger.info("Database initialized")

        # Set up Telegram bot
        self.application = Application.builder().token(config.telegram_token).build()

        # Store reference to self in bot_data for handlers
        self.application.bot_data['water_bill_bot'] = self

        # Set up handlers
        from bot.handlers import setup_handlers
        setup_handlers(self.application)

        # Set up scheduler
        self.scheduler = AsyncIOScheduler()
        self._setup_scheduled_jobs()
        self.scheduler.start()
        logger.info("Scheduler started")

        # Start bot
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        logger.info("Bot is running!")

    async def stop(self):
        """Stop the bot"""
        logger.info("Stopping bot...")

        if self.scheduler:
            self.scheduler.shutdown()

        if self.application:
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

        logger.info("Scheduled jobs configured")

    async def scheduled_scrape(self):
        """Run scheduled scraping"""
        logger.info("Running scheduled scrape...")
        try:
            await self.refresh_all_bills()
        except Exception as e:
            logger.error(f"Scheduled scrape failed: {e}")

    async def refresh_all_bills(self):
        """Refresh bill data for all active properties"""
        scrape_log = ScrapingLog(started_at=datetime.utcnow())

        try:
            async with get_session() as session:
                # Get all active properties
                result = await session.execute(
                    select(Property).where(Property.is_active == True)
                )
                properties = result.scalars().all()

                if not properties:
                    logger.info("No properties to scrape")
                    return

                # Start scraper
                async with BSAScraper() as scraper:
                    await scraper.navigate_to_portal()
                    await scraper.login()

                    scraped_count = 0

                    for prop in properties:
                        try:
                            bill_data = await scraper.search_by_account(prop.bsa_account_number)

                            if bill_data:
                                # Update property info if needed
                                if bill_data.address and prop.address.startswith("Pending"):
                                    prop.address = bill_data.address
                                if bill_data.owner_name:
                                    prop.owner_name = bill_data.owner_name

                                # Create new bill record
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

                                # Calculate status
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
            # Log the scrape attempt
            async with get_session() as session:
                session.add(scrape_log)
                await session.commit()

    async def send_due_date_reminders(self):
        """Send reminders for bills due within 7 days"""
        async with get_session() as session:
            # Get properties with bills due soon
            result = await session.execute(
                select(Property)
                .options(selectinload(Property.bills))
                .where(Property.is_active == True)
            )
            properties = result.scalars().all()

            due_soon = []
            for prop in properties:
                latest = prop.latest_bill
                if latest and latest.status == BillStatus.DUE_SOON:
                    due_soon.append((prop, latest))

            if not due_soon:
                return

            # Get users to notify
            result = await session.execute(
                select(TelegramUser).where(TelegramUser.notifications_enabled == True)
            )
            users = result.scalars().all()

            if not users:
                return

            # Build reminder message
            message = "⏰ *Water Bill Reminder*\n\n"
            message += "The following bills are due soon:\n\n"

            for prop, bill in due_soon:
                days_left = (bill.due_date - datetime.now().date()).days if bill.due_date else 0
                message += f"• *{prop.address}*\n"
                message += f"  ${bill.amount_due:,.2f} due in {days_left} days\n\n"

            # Send to all users
            for user in users:
                try:
                    await self.application.bot.send_message(
                        chat_id=user.telegram_id,
                        text=message,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Failed to send reminder to {user.telegram_id}: {e}")

    async def send_overdue_alerts(self):
        """Send alerts for overdue bills"""
        async with get_session() as session:
            result = await session.execute(
                select(Property)
                .options(selectinload(Property.bills))
                .where(Property.is_active == True)
            )
            properties = result.scalars().all()

            overdue = []
            for prop in properties:
                latest = prop.latest_bill
                if latest and latest.status == BillStatus.OVERDUE:
                    overdue.append((prop, latest))

            if not overdue:
                return

            result = await session.execute(
                select(TelegramUser).where(TelegramUser.notifications_enabled == True)
            )
            users = result.scalars().all()

            if not users:
                return

            message = "🔴 *OVERDUE BILLS ALERT*\n\n"

            total = 0
            for prop, bill in overdue:
                total += bill.amount_due
                days_overdue = (datetime.now().date() - bill.due_date).days if bill.due_date else 0
                message += f"• *{prop.address}*\n"
                message += f"  ${bill.amount_due:,.2f} - {days_overdue} days overdue\n\n"

            message += f"*Total Overdue: ${total:,.2f}*"

            for user in users:
                try:
                    await self.application.bot.send_message(
                        chat_id=user.telegram_id,
                        text=message,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Failed to send overdue alert to {user.telegram_id}: {e}")

    async def refresh_single_property(self, property_id: int) -> bool:
        """Refresh bill data for a single property"""
        async with get_session() as session:
            result = await session.execute(
                select(Property).where(Property.id == property_id)
            )
            prop = result.scalar_one_or_none()

            if not prop:
                return False

            async with BSAScraper() as scraper:
                await scraper.navigate_to_portal()
                await scraper.login()

                bill_data = await scraper.search_by_account(prop.bsa_account_number)

                if bill_data:
                    if bill_data.address and prop.address.startswith("Pending"):
                        prop.address = bill_data.address

                    new_bill = WaterBill(
                        property_id=prop.id,
                        amount_due=bill_data.amount_due,
                        due_date=bill_data.due_date,
                        statement_date=bill_data.statement_date,
                        previous_balance=bill_data.previous_balance,
                        current_charges=bill_data.current_charges,
                        raw_data=bill_data.raw_data
                    )
                    new_bill.status = new_bill.calculate_status()
                    session.add(new_bill)
                    await session.commit()
                    return True

        return False
