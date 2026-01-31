"""Telegram bot command handlers"""

import logging
from datetime import datetime
from decimal import Decimal

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

# Conversation states
ADDING_PROPERTY = 1
REMOVING_PROPERTY = 2


def format_currency(amount: Decimal) -> str:
    """Format decimal as currency"""
    return f"${amount:,.2f}"


def format_date(d) -> str:
    """Format date for display"""
    if not d:
        return "N/A"
    return d.strftime("%b %d, %Y")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    db_available = context.bot_data.get('db_available', False)

    # Try to register user if DB available
    if db_available:
        try:
            from database.connection import get_session
            from database.models import TelegramUser
            from sqlalchemy import select

            async with get_session() as session:
                result = await session.execute(
                    select(TelegramUser).where(TelegramUser.telegram_id == user.id)
                )
                db_user = result.scalar_one_or_none()

                if not db_user:
                    db_user = TelegramUser(
                        telegram_id=user.id,
                        username=user.username,
                        first_name=user.first_name
                    )
                    session.add(db_user)
                    await session.commit()
        except Exception as e:
            logger.error(f"Failed to register user: {e}")

    db_status = "✅ Connected" if db_available else "⚠️ Not connected"

    welcome_text = f"""
👋 Welcome to Water Bill Tracker, {user.first_name}!

I help you track water bills for your properties from BSA Online (City of Warren, MI).

*Available Commands:*
/properties - List all tracked properties
/summary - Dashboard of all outstanding bills
/overdue - Show overdue bills only
/refresh - Manually update bill data
/add - Add a new property to track
/remove - Remove a property from tracking
/help - Show this help message

*Status Indicators:*
🟢 Current | 🟡 Due Soon | 🔴 Overdue

*Database:* {db_status}
"""

    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
*Water Bill Tracker - Commands*

📋 *View Bills:*
/properties - List all properties with status
/summary - Overview of all outstanding bills
/overdue - Show only overdue bills
/property <address> - Details for specific property

🔄 *Updates:*
/refresh - Manually fetch latest bill data

➕ *Manage Properties:*
/add - Add new property to track
/remove - Remove a property from tracking

⚙️ *Info:*
/status - Bot status and last update time

*Status Indicators:*
🟢 Current - No action needed
🟡 Due Soon - Due within 7 days
🔴 Overdue - Past due date
✅ Paid - No balance due
"""

    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def properties_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /properties command - list all properties"""
    db_available = context.bot_data.get('db_available', False)

    if not db_available:
        await update.message.reply_text("⚠️ Database not connected. Please check configuration.")
        return

    try:
        from database.connection import get_session
        from database.models import Property, BillStatus
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with get_session() as session:
            result = await session.execute(
                select(Property)
                .options(selectinload(Property.bills))
                .where(Property.is_active == True)
                .order_by(Property.address)
            )
            properties = result.scalars().all()

        if not properties:
            await update.message.reply_text(
                "No properties tracked yet.\nUse /add to add your first property."
            )
            return

        text = "*📍 Your Properties:*\n\n"

        for prop in properties:
            latest = prop.latest_bill
            status_emoji = prop.status_emoji

            if latest:
                amount = format_currency(latest.amount_due)
                due = format_date(latest.due_date)
                text += f"{status_emoji} *{prop.address}*\n"
                text += f"   Balance: {amount} | Due: {due}\n\n"
            else:
                text += f"⚪ *{prop.address}*\n"
                text += f"   No bill data yet\n\n"

        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error in properties_command: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /summary command - dashboard view"""
    db_available = context.bot_data.get('db_available', False)

    if not db_available:
        await update.message.reply_text("⚠️ Database not connected.")
        return

    try:
        from database.connection import get_session
        from database.models import Property, BillStatus
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with get_session() as session:
            result = await session.execute(
                select(Property)
                .options(selectinload(Property.bills))
                .where(Property.is_active == True)
            )
            properties = result.scalars().all()

        if not properties:
            await update.message.reply_text("No properties tracked. Use /add to get started.")
            return

        total_due = Decimal("0")
        overdue_count = 0
        due_soon_count = 0
        current_count = 0

        overdue_props = []
        due_soon_props = []

        for prop in properties:
            latest = prop.latest_bill
            if latest:
                total_due += latest.amount_due

                if latest.status == BillStatus.OVERDUE:
                    overdue_count += 1
                    overdue_props.append((prop, latest))
                elif latest.status == BillStatus.DUE_SOON:
                    due_soon_count += 1
                    due_soon_props.append((prop, latest))
                elif latest.status == BillStatus.CURRENT:
                    current_count += 1

        text = f"""
📊 *Bill Summary Dashboard*

💰 *Total Outstanding:* {format_currency(total_due)}

*Status Breakdown:*
🔴 Overdue: {overdue_count}
🟡 Due Soon: {due_soon_count}
🟢 Current: {current_count}
📍 Total Properties: {len(properties)}
"""

        if overdue_props:
            text += "\n*⚠️ Overdue Bills:*\n"
            for prop, bill in overdue_props:
                text += f"• {prop.address}: {format_currency(bill.amount_due)}\n"

        if due_soon_props:
            text += "\n*⏰ Due Soon:*\n"
            for prop, bill in due_soon_props:
                text += f"• {prop.address}: Due {format_date(bill.due_date)}\n"

        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error in summary_command: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def overdue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /overdue command - show only overdue bills"""
    db_available = context.bot_data.get('db_available', False)

    if not db_available:
        await update.message.reply_text("⚠️ Database not connected.")
        return

    try:
        from database.connection import get_session
        from database.models import Property, BillStatus
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with get_session() as session:
            result = await session.execute(
                select(Property)
                .options(selectinload(Property.bills))
                .where(Property.is_active == True)
            )
            properties = result.scalars().all()

        overdue_props = []
        for prop in properties:
            latest = prop.latest_bill
            if latest and latest.status == BillStatus.OVERDUE:
                overdue_props.append((prop, latest))

        if not overdue_props:
            await update.message.reply_text("✅ No overdue bills! You're all caught up.")
            return

        text = f"🔴 *Overdue Bills ({len(overdue_props)})*\n\n"

        total_overdue = Decimal("0")
        for prop, bill in overdue_props:
            days_overdue = (datetime.now().date() - bill.due_date).days if bill.due_date else 0
            total_overdue += bill.amount_due

            text += f"*{prop.address}*\n"
            text += f"Amount: {format_currency(bill.amount_due)}\n"
            text += f"Due: {format_date(bill.due_date)} ({days_overdue} days ago)\n\n"

        text += f"*Total Overdue: {format_currency(total_overdue)}*"

        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error in overdue_command: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /refresh command - manually trigger bill update"""
    await update.message.reply_text("🔄 Fetching latest bill data...\n\nThis may take a moment.")

    bot = context.bot_data.get('water_bill_bot')

    if bot and bot.db_available:
        try:
            await bot.refresh_all_bills()
            await update.message.reply_text("✅ Bill data updated successfully!")
        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            await update.message.reply_text(f"❌ Update failed: {str(e)}")
    else:
        await update.message.reply_text("⚠️ Database not available. Cannot refresh.")


async def add_property_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /add command - start adding a property"""
    db_available = context.bot_data.get('db_available', False)

    if not db_available:
        await update.message.reply_text("⚠️ Database not connected. Cannot add properties.")
        return ConversationHandler.END

    await update.message.reply_text(
        "📍 *Add New Property*\n\n"
        "Please enter the BSA Online account number for the property:\n\n"
        "Example: `302913026`\n\n"
        "Use /cancel to cancel.",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADDING_PROPERTY


async def add_property_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle account number input for adding property"""
    account_number = update.message.text.strip()

    if len(account_number) < 4:
        await update.message.reply_text("Invalid account number. Please try again.")
        return ADDING_PROPERTY

    try:
        from database.connection import get_session
        from database.models import Property
        from sqlalchemy import select

        async with get_session() as session:
            result = await session.execute(
                select(Property).where(Property.bsa_account_number == account_number)
            )
            existing = result.scalar_one_or_none()

            if existing:
                await update.message.reply_text(
                    f"This account is already being tracked:\n{existing.address}"
                )
                return ConversationHandler.END

            new_prop = Property(
                bsa_account_number=account_number,
                address=f"Pending lookup: {account_number}"
            )
            session.add(new_prop)
            await session.commit()

            await update.message.reply_text(
                f"✅ Property added with account: `{account_number}`\n\n"
                "Use /refresh to fetch bill data.",
                parse_mode=ParseMode.MARKDOWN
            )

    except Exception as e:
        logger.error(f"Error adding property: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")

    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing conversation"""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END


async def remove_property_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /remove command - start removing a property"""
    db_available = context.bot_data.get('db_available', False)

    if not db_available:
        await update.message.reply_text("⚠️ Database not connected. Cannot remove properties.")
        return

    try:
        from database.connection import get_session
        from database.models import Property
        from sqlalchemy import select

        async with get_session() as session:
            result = await session.execute(
                select(Property)
                .where(Property.is_active == True)
                .order_by(Property.address)
            )
            properties = result.scalars().all()

        if not properties:
            await update.message.reply_text(
                "No properties to remove.\nUse /add to add properties first."
            )
            return

        # Create inline keyboard with property options
        keyboard = []
        for prop in properties:
            # Truncate address if too long for button
            display_addr = prop.address[:40] + "..." if len(prop.address) > 40 else prop.address
            keyboard.append([
                InlineKeyboardButton(
                    display_addr,
                    callback_data=f"remove_prop_{prop.id}"
                )
            ])

        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="remove_cancel")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "🗑️ *Remove Property*\n\n"
            "Select the property you want to remove:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        logger.error(f"Error in remove_property_start: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def remove_property_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle property selection for removal"""
    query = update.callback_query
    await query.answer()

    if query.data == "remove_cancel":
        await query.edit_message_text("Operation cancelled.")
        return

    if query.data.startswith("remove_prop_"):
        prop_id = int(query.data.replace("remove_prop_", ""))

        try:
            from database.connection import get_session
            from database.models import Property
            from sqlalchemy import select

            async with get_session() as session:
                result = await session.execute(
                    select(Property).where(Property.id == prop_id)
                )
                prop = result.scalar_one_or_none()

            if not prop:
                await query.edit_message_text("❌ Property not found.")
                return

            # Show confirmation
            keyboard = [
                [
                    InlineKeyboardButton("✅ Yes, Remove", callback_data=f"confirm_remove_{prop_id}"),
                    InlineKeyboardButton("❌ Cancel", callback_data="remove_cancel")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await query.edit_message_text(
                f"⚠️ *Confirm Removal*\n\n"
                f"Are you sure you want to remove this property?\n\n"
                f"*Address:* {prop.address}\n"
                f"*Account:* `{prop.bsa_account_number}`\n\n"
                f"This will stop tracking bills for this property.",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.error(f"Error in remove_property_callback: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")


async def remove_property_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle confirmation of property removal"""
    query = update.callback_query
    await query.answer()

    if query.data == "remove_cancel":
        await query.edit_message_text("Operation cancelled.")
        return

    if query.data.startswith("confirm_remove_"):
        prop_id = int(query.data.replace("confirm_remove_", ""))

        try:
            from database.connection import get_session
            from database.models import Property
            from sqlalchemy import select

            async with get_session() as session:
                result = await session.execute(
                    select(Property).where(Property.id == prop_id)
                )
                prop = result.scalar_one_or_none()

                if not prop:
                    await query.edit_message_text("❌ Property not found.")
                    return

                address = prop.address
                # Soft delete - set is_active to False
                prop.is_active = False
                await session.commit()

            await query.edit_message_text(
                f"✅ *Property Removed*\n\n"
                f"*{address}* has been removed from tracking.\n\n"
                f"Use /add to add it back if needed.",
                parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.error(f"Error in remove_property_confirm: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    db_available = context.bot_data.get('db_available', False)

    text = f"""
⚙️ *Bot Status*

Database: {"✅ Connected" if db_available else "❌ Not connected"}
Bot: ✅ Running
"""

    if db_available:
        try:
            from database.connection import get_session
            from database.models import Property, ScrapingLog
            from sqlalchemy import select, func

            async with get_session() as session:
                result = await session.execute(
                    select(func.count(Property.id)).where(Property.is_active == True)
                )
                prop_count = result.scalar()

                result = await session.execute(
                    select(ScrapingLog)
                    .order_by(ScrapingLog.started_at.desc())
                    .limit(1)
                )
                last_scrape = result.scalar_one_or_none()

            text += f"Properties Tracked: {prop_count}\n"

            if last_scrape:
                status = "✅ Success" if last_scrape.success else "❌ Failed"
                text += f"Last Scrape: {last_scrape.started_at.strftime('%b %d, %Y %H:%M')}\n"
                text += f"Scrape Status: {status}\n"

        except Exception as e:
            text += f"\n_Error getting stats: {e}_"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


def setup_handlers(application):
    """Set up all bot handlers"""

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("properties", properties_command))
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CommandHandler("overdue", overdue_command))
    application.add_handler(CommandHandler("refresh", refresh_command))
    application.add_handler(CommandHandler("status", status_command))

    # Add property conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_property_start)],
        states={
            ADDING_PROPERTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_property_account)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )
    application.add_handler(add_conv)

    # Remove property command and callbacks
    application.add_handler(CommandHandler("remove", remove_property_start))
    application.add_handler(CallbackQueryHandler(remove_property_callback, pattern="^remove_"))
    application.add_handler(CallbackQueryHandler(remove_property_confirm, pattern="^confirm_remove_"))

    logger.info("Bot handlers configured")
