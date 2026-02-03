"""Blue Deer Bot - Property management notifications via Telegram"""

import logging
from datetime import datetime, date
from typing import Optional, List
from decimal import Decimal

from telegram import BotCommand
from telegram.ext import Application
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class BlueDeerBot:
    """Blue Deer notification bot"""

    def __init__(self, token: str, admin_chat_id: int = None, group_chat_id: int = None,
                 water_bill_threshold: float = 100, recert_reminder_days: int = 30):
        self.token = token
        self.admin_chat_id = admin_chat_id
        self.group_chat_id = group_chat_id
        self.water_bill_threshold = water_bill_threshold
        self.recert_reminder_days = recert_reminder_days
        self.application: Optional[Application] = None
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.db_available = False

    async def start(self):
        """Initialize and start the bot"""
        logger.info("Starting Blue Deer Bot...")

        # Try to initialize database
        try:
            from database.connection import init_db, is_connected

            success = await init_db()

            if success and is_connected():
                self.db_available = True
                logger.info("Database connected")
            else:
                self.db_available = False
                logger.warning("Database not available")
        except Exception as e:
            logger.error(f"Database init failed: {e}")
            self.db_available = False

        # Set up Telegram bot
        logger.info(f"Setting up Blue Deer bot...")
        self.application = Application.builder().token(self.token).build()

        # Store reference to self in bot_data for handlers
        self.application.bot_data['blue_deer_bot'] = self
        self.application.bot_data['db_available'] = self.db_available

        # Set up handlers
        from bluedeer_bot.handlers import setup_handlers
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
        await self.application.initialize()
        await self.application.start()

        # Set up bot commands menu
        commands = [
            BotCommand("start", "🦌 Main menu"),
            BotCommand("status", "📊 Property status overview"),
            BotCommand("recerts", "📅 Upcoming recertifications"),
            BotCommand("bills", "💧 Water bill alerts"),
            BotCommand("notify", "🔔 Send test notification"),
            BotCommand("help", "❓ Help & commands"),
        ]
        await self.application.bot.set_my_commands(commands)

        await self.application.updater.start_polling(drop_pending_updates=True)

        logger.info("=" * 50)
        logger.info("BLUE DEER BOT IS NOW RUNNING!")
        logger.info("=" * 50)

    async def stop(self):
        """Stop the bot"""
        logger.info("Stopping Blue Deer bot...")

        if self.scheduler:
            self.scheduler.shutdown()

        if self.application:
            if self.application.updater.running:
                await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()

        logger.info("Blue Deer bot stopped")

    def _setup_scheduled_jobs(self):
        """Configure scheduled notification jobs"""
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

    async def get_notification_chat_ids(self) -> List[int]:
        """Get list of chat IDs to send notifications to (admins + group)"""
        chat_ids = []

        # Primary admin from config
        if self.admin_chat_id:
            chat_ids.append(self.admin_chat_id)

        # Group chat if configured
        if self.group_chat_id:
            chat_ids.append(self.group_chat_id)

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

    async def send_notification(self, message: str, chat_id: int = None):
        """Send notification to specified chat or all configured chats"""
        if chat_id:
            chat_ids = [chat_id]
        else:
            chat_ids = await self.get_notification_chat_ids()

        if not chat_ids:
            logger.warning("No admin chat IDs configured for notifications")
            return

        for cid in chat_ids:
            try:
                await self.application.bot.send_message(
                    chat_id=cid,
                    text=message,
                    parse_mode="Markdown"
                )
                logger.info(f"Sent notification to {cid}")
            except Exception as e:
                logger.error(f"Failed to send notification to {cid}: {e}")

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
                        if 0 <= days_until <= self.recert_reminder_days:
                            prop = tenant.property_ref
                            reminders.append({
                                "tenant": tenant.name,
                                "property": prop.address if prop else "Unknown",
                                "recert_date": recert_date,
                                "days_until": days_until
                            })

                if reminders:
                    message = "🦌 *Blue Deer - Recertification Reminders*\n\n"
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

            threshold = Decimal(str(self.water_bill_threshold))

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
                    message = f"🦌 *Blue Deer - Water Bill Alerts* (>${self.water_bill_threshold})\n\n"
                    for a in alerts:
                        due_str = a["due_date"].strftime("%b %d") if a["due_date"] else "Unknown"
                        message += f"• *{a['property']}*\n"
                        message += f"  💧 ${a['amount']:.2f} (due {due_str})\n\n"

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
                    message = "🦌 *Blue Deer - Bills Due Soon*\n\n"
                    for b in due_soon:
                        message += f"• *{b['property']}*\n"
                        message += f"  💧 ${b['amount']:.2f}\n"
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
                    message = "🦌 *Blue Deer - Overdue Bills*\n\n"
                    for b in overdue:
                        message += f"• *{b['property']}*\n"
                        message += f"  💧 ${b['amount']:.2f}\n"
                        message += f"  ⚠️ {b['days_overdue']} day{'s' if b['days_overdue'] != 1 else ''} overdue\n\n"

                    await self.send_notification(message)
                    logger.info(f"Sent {len(overdue)} overdue alerts")
                else:
                    logger.info("No overdue alerts needed")

        except Exception as e:
            logger.error(f"Error sending overdue alerts: {e}")

    async def get_recerts_summary(self) -> str:
        """Get summary of upcoming recertifications"""
        if not self.db_available:
            return "Database not available"

        try:
            from database.connection import get_session
            from database.models import Tenant
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload
            from dateutil.relativedelta import relativedelta

            today = date.today()

            async with get_session() as session:
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

                if not tenants:
                    return "No Section 8 tenants with lease dates found."

                upcoming = []
                for tenant in tenants:
                    if tenant.lease_start_date:
                        recert_date = tenant.lease_start_date + relativedelta(months=9)
                        days_until = (recert_date - today).days
                        upcoming.append({
                            "tenant": tenant.name,
                            "property": tenant.property_ref.address if tenant.property_ref else "Unknown",
                            "recert_date": recert_date,
                            "days_until": days_until
                        })

                # Sort by days until recert
                upcoming.sort(key=lambda x: x["days_until"])

                message = "📅 *Upcoming Recertifications*\n\n"
                for r in upcoming[:10]:  # Show top 10
                    if r["days_until"] < 0:
                        urgency = f"🔴 {abs(r['days_until'])} days ago!"
                    elif r["days_until"] == 0:
                        urgency = "⚠️ *TODAY*"
                    elif r["days_until"] <= 7:
                        urgency = f"🔴 {r['days_until']} days"
                    elif r["days_until"] <= 30:
                        urgency = f"🟡 {r['days_until']} days"
                    else:
                        urgency = f"🟢 {r['days_until']} days"

                    message += f"• *{r['tenant']}*\n"
                    message += f"  📍 {r['property'][:30]}\n"
                    message += f"  📅 {r['recert_date'].strftime('%b %d, %Y')} ({urgency})\n\n"

                if len(upcoming) > 10:
                    message += f"_...and {len(upcoming) - 10} more_"

                return message

        except Exception as e:
            logger.error(f"Error getting recerts summary: {e}")
            return f"Error: {str(e)}"

    async def get_bills_summary(self) -> str:
        """Get summary of water bills above threshold"""
        if not self.db_available:
            return "Database not available"

        try:
            from database.connection import get_session
            from database.models import Property
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            threshold = Decimal(str(self.water_bill_threshold))

            async with get_session() as session:
                result = await session.execute(
                    select(Property)
                    .where(Property.is_active == True)
                    .options(selectinload(Property.bills))
                )
                properties = result.scalars().all()

                alerts = []
                total = Decimal("0")

                for prop in properties:
                    if prop.bills:
                        latest_bill = prop.bills[0]
                        if latest_bill.amount_due:
                            total += latest_bill.amount_due
                            if latest_bill.amount_due >= threshold:
                                alerts.append({
                                    "property": prop.address,
                                    "amount": latest_bill.amount_due,
                                    "due_date": latest_bill.due_date
                                })

                # Sort by amount descending
                alerts.sort(key=lambda x: x["amount"], reverse=True)

                message = f"💧 *Water Bills Summary*\n\n"
                message += f"💰 *Total Outstanding:* ${total:,.2f}\n"
                message += f"⚠️ *Above ${self.water_bill_threshold}:* {len(alerts)} properties\n\n"

                if alerts:
                    message += f"*High Balance Properties:*\n"
                    for a in alerts[:10]:
                        due_str = a["due_date"].strftime("%b %d") if a["due_date"] else "N/A"
                        message += f"• {a['property'][:30]}\n"
                        message += f"  💧 ${a['amount']:.2f} (due {due_str})\n\n"

                    if len(alerts) > 10:
                        message += f"_...and {len(alerts) - 10} more_"
                else:
                    message += "_No properties above threshold_"

                return message

        except Exception as e:
            logger.error(f"Error getting bills summary: {e}")
            return f"Error: {str(e)}"
