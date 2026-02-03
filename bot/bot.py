"""Blue Deer Bot - Property management notifications via Telegram"""

import logging
from datetime import datetime, date
from typing import Optional, List
from decimal import Decimal

from telegram import BotCommand
from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import config

logger = logging.getLogger(__name__)


class BlueDeerBot:
    """Main bot coordinator"""

    def __init__(self):
        self.application: Optional[Application] = None
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.db_available = False

    async def start(self):
        """Initialize and start the bot"""
        logger.info("Starting Blue Deer Bot...")

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
        self.application.bot_data['blue_deer_bot'] = self
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
        """Configure scheduled notification jobs"""
        # Daily scrape at 6 AM
        self.scheduler.add_job(
            self.scheduled_scrape,
            CronTrigger(hour=6, minute=0),
            id="daily_scrape",
            name="Daily bill scrape"
        )

        # Recertification reminders at 8 AM
        self.scheduler.add_job(
            self.send_recert_reminders,
            CronTrigger(hour=8, minute=0),
            id="recert_reminders",
            name="Recertification reminders"
        )

        # Water bill threshold alerts at 9 AM
        self.scheduler.add_job(
            self.send_water_bill_alerts,
            CronTrigger(hour=9, minute=0),
            id="water_bill_alerts",
            name="Water bill threshold alerts"
        )

        # Due date reminders at 9:30 AM
        self.scheduler.add_job(
            self.send_due_date_reminders,
            CronTrigger(hour=9, minute=30),
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
        if not self.db_available:
            return
        logger.info("Running scheduled scrape...")
        try:
            await self.refresh_all_bills()
        except Exception as e:
            logger.error(f"Scheduled scrape failed: {e}")

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

    async def get_admin_chat_ids(self) -> List[int]:
        """Get list of admin Telegram IDs to send notifications to"""
        chat_ids = []

        # Primary admin from config
        if config.admin_telegram_id:
            chat_ids.append(config.admin_telegram_id)

        # Also get admins from TelegramUser table
        try:
            from database.connection import get_session
            from database.models import TelegramUser
            from sqlalchemy import select

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

    async def send_notification(self, message: str):
        """Send notification to all admins"""
        chat_ids = await self.get_admin_chat_ids()

        if not chat_ids:
            logger.warning("No admin chat IDs configured for notifications")
            return

        for chat_id in chat_ids:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="Markdown"
                )
                logger.info(f"Sent notification to {chat_id}")
            except Exception as e:
                logger.error(f"Failed to send notification to {chat_id}: {e}")

    async def send_recert_reminders(self):
        """Send reminders for upcoming recertifications"""
        if not self.db_available:
            return

        logger.info("Checking for upcoming recertifications...")

        try:
            from database.connection import get_session
            from database.models import Tenant, Property
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from dateutil.relativedelta import relativedelta

            today = date.today()
            reminder_days = config.recert_reminder_days

            async with get_session() as session:
                # Get active Section 8 tenants with lease dates
                result = await session.execute(
                    select(Tenant)
                    .where(
                        Tenant.is_active == True,
                        Tenant.is_section8 == True,
                        Tenant.lease_start_date != None
                    )
                    .options(selectinload(Tenant.property_ref))
                )
                tenants = result.scalars().all()

                reminders = []

                for tenant in tenants:
                    if tenant.lease_start_date:
                        # Recert eligible date is 9 months after lease start
                        recert_date = tenant.lease_start_date + relativedelta(months=9)
                        days_until = (recert_date - today).days

                        # Send reminder if within the reminder window
                        if 0 <= days_until <= reminder_days:
                            prop = tenant.property_ref
                            reminders.append({
                                "tenant": tenant.name,
                                "property": prop.address if prop else "Unknown",
                                "recert_date": recert_date,
                                "days_until": days_until
                            })

                if reminders:
                    message = "🔔 *Recertification Reminders*\n\n"
                    for r in reminders:
                        if r["days_until"] == 0:
                            urgency = "⚠️ *TODAY*"
                        elif r["days_until"] <= 7:
                            urgency = f"🔴 {r['days_until']} days"
                        elif r["days_until"] <= 14:
                            urgency = f"🟡 {r['days_until']} days"
                        else:
                            urgency = f"🟢 {r['days_until']} days"

                        message += f"• *{r['tenant']}*\n"
                        message += f"  📍 {r['property']}\n"
                        message += f"  📅 Recert eligible: {r['recert_date'].strftime('%b %d, %Y')}\n"
                        message += f"  ⏰ {urgency}\n\n"

                    await self.send_notification(message)
                    logger.info(f"Sent {len(reminders)} recert reminders")
                else:
                    logger.info("No recert reminders needed")

        except Exception as e:
            logger.error(f"Error sending recert reminders: {e}")

    async def send_water_bill_alerts(self):
        """Send alerts for water bills exceeding threshold"""
        if not self.db_available:
            return

        logger.info("Checking for water bills above threshold...")

        try:
            from database.connection import get_session
            from database.models import Property, WaterBill
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            threshold = Decimal(str(config.water_bill_threshold))

            async with get_session() as session:
                result = await session.execute(
                    select(Property)
                    .where(Property.is_active == True)
                    .options(selectinload(Property.bills))
                )
                properties = result.scalars().all()

                alerts = []

                for prop in properties:
                    if prop.bills:
                        latest_bill = prop.bills[0]
                        if latest_bill.amount_due and latest_bill.amount_due >= threshold:
                            alerts.append({
                                "property": prop.address,
                                "amount": latest_bill.amount_due,
                                "due_date": latest_bill.due_date
                            })

                if alerts:
                    message = f"💧 *Water Bill Alerts* (>${config.water_bill_threshold})\n\n"
                    for a in alerts:
                        due_str = a["due_date"].strftime("%b %d") if a["due_date"] else "Unknown"
                        message += f"• *{a['property']}*\n"
                        message += f"  💰 ${a['amount']:.2f} (due {due_str})\n\n"

                    await self.send_notification(message)
                    logger.info(f"Sent {len(alerts)} water bill alerts")
                else:
                    logger.info("No water bill alerts needed")

        except Exception as e:
            logger.error(f"Error sending water bill alerts: {e}")

    async def send_due_date_reminders(self):
        """Send reminders for bills due within 7 days"""
        if not self.db_available:
            return

        logger.info("Checking for bills due soon...")

        try:
            from database.connection import get_session
            from database.models import Property, BillStatus
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            async with get_session() as session:
                result = await session.execute(
                    select(Property)
                    .where(Property.is_active == True)
                    .options(selectinload(Property.bills))
                )
                properties = result.scalars().all()

                due_soon = []
                today = date.today()

                for prop in properties:
                    if prop.bills:
                        latest_bill = prop.bills[0]
                        if latest_bill.due_date:
                            days_until = (latest_bill.due_date - today).days
                            if 0 < days_until <= 7 and latest_bill.amount_due and latest_bill.amount_due > 0:
                                due_soon.append({
                                    "property": prop.address,
                                    "amount": latest_bill.amount_due,
                                    "due_date": latest_bill.due_date,
                                    "days_until": days_until
                                })

                if due_soon:
                    message = "📅 *Bills Due Soon*\n\n"
                    for b in due_soon:
                        message += f"• *{b['property']}*\n"
                        message += f"  💰 ${b['amount']:.2f}\n"
                        message += f"  📅 Due in {b['days_until']} day{'s' if b['days_until'] != 1 else ''} ({b['due_date'].strftime('%b %d')})\n\n"

                    await self.send_notification(message)
                    logger.info(f"Sent {len(due_soon)} due date reminders")
                else:
                    logger.info("No due date reminders needed")

        except Exception as e:
            logger.error(f"Error sending due date reminders: {e}")

    async def send_overdue_alerts(self):
        """Send alerts for overdue bills"""
        if not self.db_available:
            return

        logger.info("Checking for overdue bills...")

        try:
            from database.connection import get_session
            from database.models import Property
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            async with get_session() as session:
                result = await session.execute(
                    select(Property)
                    .where(Property.is_active == True)
                    .options(selectinload(Property.bills))
                )
                properties = result.scalars().all()

                overdue = []
                today = date.today()

                for prop in properties:
                    if prop.bills:
                        latest_bill = prop.bills[0]
                        if latest_bill.due_date:
                            days_overdue = (today - latest_bill.due_date).days
                            if days_overdue > 0 and latest_bill.amount_due and latest_bill.amount_due > 0:
                                overdue.append({
                                    "property": prop.address,
                                    "amount": latest_bill.amount_due,
                                    "due_date": latest_bill.due_date,
                                    "days_overdue": days_overdue
                                })

                if overdue:
                    message = "🔴 *Overdue Bills*\n\n"
                    for b in overdue:
                        message += f"• *{b['property']}*\n"
                        message += f"  💰 ${b['amount']:.2f}\n"
                        message += f"  ⚠️ {b['days_overdue']} day{'s' if b['days_overdue'] != 1 else ''} overdue\n\n"

                    await self.send_notification(message)
                    logger.info(f"Sent {len(overdue)} overdue alerts")
                else:
                    logger.info("No overdue alerts needed")

        except Exception as e:
            logger.error(f"Error sending overdue alerts: {e}")
