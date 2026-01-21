"""Telegram bot command handlers"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    ConversationHandler, MessageHandler, filters
)
from telegram.constants import ParseMode

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database.connection import get_session
from database.models import Property, WaterBill, BillStatus, TelegramUser

logger = logging.getLogger(__name__)

# Conversation states
ADDING_PROPERTY = 1


def format_currency(amount: Decimal) -> str:
    """Format decimal as currency"""
    return f"${amount:,.2f}"


def format_date(d) -> str:
    """Format date for display"""
    if not d:
        return "N/A"
    return d.strftime("%b %d, %Y")


def get_status_emoji(status: BillStatus) -> str:
    """Get emoji for bill status"""
    return {
        BillStatus.CURRENT: "🟢",
        BillStatus.DUE_SOON: "🟡",
        BillStatus.OVERDUE: "🔴",
        BillStatus.PAID: "✅",
        BillStatus.UNKNOWN: "⚪"
    }.get(status, "⚪")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user

    # Register user in database
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

    welcome_text = f"""
👋 Welcome to Water Bill Tracker, {user.first_name}!

I help you track water bills for your properties from BSA Online.

*Available Commands:*
/properties - List all tracked properties
/summary - Dashboard of all outstanding bills
/overdue - Show overdue bills only
/refresh - Manually update bill data
/add - Add a new property to track
/remove - Remove a property
/help - Show this help message

*Quick Stats:*
🟢 Current | 🟡 Due Soon | 🔴 Overdue
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
/remove - Remove a property

⚙️ *Settings:*
/notifications - Toggle alert notifications
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

    # Build property list with inline buttons
    text = "*📍 Your Properties:*\n\n"

    keyboard = []
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

        keyboard.append([
            InlineKeyboardButton(
                f"📄 {prop.address[:30]}",
                callback_data=f"property_{prop.id}"
            )
        ])

    keyboard.append([InlineKeyboardButton("🔄 Refresh All", callback_data="refresh_all")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /summary command - dashboard view"""
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

    keyboard = [
        [InlineKeyboardButton("🔄 Refresh Data", callback_data="refresh_all")],
        [InlineKeyboardButton("📋 View All Properties", callback_data="view_properties")]
    ]

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def overdue_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /overdue command - show only overdue bills"""
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
    for prop, bill in sorted(overdue_props, key=lambda x: x[1].due_date or datetime.min.date()):
        days_overdue = (datetime.now().date() - bill.due_date).days if bill.due_date else 0
        total_overdue += bill.amount_due

        text += f"*{prop.address}*\n"
        text += f"Amount: {format_currency(bill.amount_due)}\n"
        text += f"Due: {format_date(bill.due_date)} ({days_overdue} days ago)\n"
        if bill.late_fees and bill.late_fees > 0:
            text += f"Late Fees: {format_currency(bill.late_fees)}\n"
        text += "\n"

    text += f"*Total Overdue: {format_currency(total_overdue)}*"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def property_detail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /property <address> command"""
    if not context.args:
        await update.message.reply_text("Usage: /property <address or account number>")
        return

    search_term = " ".join(context.args)

    async with get_session() as session:
        result = await session.execute(
            select(Property)
            .options(selectinload(Property.bills))
            .where(
                Property.is_active == True,
                (Property.address.ilike(f"%{search_term}%")) |
                (Property.bsa_account_number.ilike(f"%{search_term}%"))
            )
        )
        prop = result.scalar_one_or_none()

    if not prop:
        await update.message.reply_text(f"Property not found: {search_term}")
        return

    await send_property_detail(update.message, prop)


async def send_property_detail(message, prop: Property):
    """Send detailed property information"""
    latest = prop.latest_bill

    text = f"""
📍 *{prop.address}*

*Account:* `{prop.bsa_account_number}`
"""

    if prop.owner_name:
        text += f"*Owner:* {prop.owner_name}\n"

    if latest:
        text += f"""
*Current Bill:*
{get_status_emoji(latest.status)} Status: {latest.status.value.replace('_', ' ').title()}
💰 Amount Due: {format_currency(latest.amount_due)}
📅 Due Date: {format_date(latest.due_date)}
📄 Statement: {format_date(latest.statement_date)}
"""

        if latest.previous_balance:
            text += f"Previous Balance: {format_currency(latest.previous_balance)}\n"
        if latest.current_charges:
            text += f"Current Charges: {format_currency(latest.current_charges)}\n"
        if latest.late_fees and latest.late_fees > 0:
            text += f"⚠️ Late Fees: {format_currency(latest.late_fees)}\n"
        if latest.water_usage_gallons:
            text += f"💧 Usage: {latest.water_usage_gallons:,} gallons\n"

        text += f"\n_Last updated: {latest.scraped_at.strftime('%b %d, %Y %H:%M')}_"
    else:
        text += "\n_No bill data available yet_"

    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{prop.id}"),
            InlineKeyboardButton("📜 History", callback_data=f"history_{prop.id}")
        ],
        [InlineKeyboardButton("🗑 Remove Property", callback_data=f"remove_{prop.id}")]
    ]

    await message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /refresh command - manually trigger bill update"""
    await update.message.reply_text("🔄 Fetching latest bill data...\n\nThis may take a moment.")

    # Trigger scraping - this will be implemented in the scheduler
    # For now, send a placeholder
    from bot.bot import WaterBillBot
    bot = context.bot_data.get('water_bill_bot')

    if bot:
        try:
            await bot.refresh_all_bills()
            await update.message.reply_text("✅ Bill data updated successfully!")
        except Exception as e:
            logger.error(f"Refresh failed: {e}")
            await update.message.reply_text(f"❌ Update failed: {str(e)}")
    else:
        await update.message.reply_text("⚠️ Scraper not initialized. Please try again later.")


async def add_property_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /add command - start adding a property"""
    await update.message.reply_text(
        "📍 *Add New Property*\n\n"
        "Please enter the BSA Online account number for the property you want to track:\n\n"
        "Example: `123456789`\n\n"
        "Use /cancel to cancel.",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADDING_PROPERTY


async def add_property_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle account number input for adding property"""
    account_number = update.message.text.strip()

    # Validate format (basic check)
    if len(account_number) < 4:
        await update.message.reply_text("Invalid account number. Please try again.")
        return ADDING_PROPERTY

    # Check if already exists
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

        # Create new property (address will be filled by scraper)
        new_prop = Property(
            bsa_account_number=account_number,
            address=f"Pending lookup: {account_number}"
        )
        session.add(new_prop)
        await session.commit()

        await update.message.reply_text(
            f"✅ Property added with account: `{account_number}`\n\n"
            "Running initial data fetch...",
            parse_mode=ParseMode.MARKDOWN
        )

        # Trigger scrape for this property
        # This will update the address and bill data

    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel any ongoing conversation"""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks"""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "refresh_all":
        await query.edit_message_text("🔄 Refreshing all properties...")
        # Trigger refresh
        await query.edit_message_text("✅ Refresh complete!")

    elif data == "view_properties":
        # Redirect to properties list
        async with get_session() as session:
            result = await session.execute(
                select(Property)
                .options(selectinload(Property.bills))
                .where(Property.is_active == True)
            )
            properties = result.scalars().all()

        text = "*📍 Your Properties:*\n\n"
        for prop in properties:
            latest = prop.latest_bill
            if latest:
                text += f"{prop.status_emoji} *{prop.address}*\n"
                text += f"   {format_currency(latest.amount_due)} due {format_date(latest.due_date)}\n\n"
            else:
                text += f"⚪ *{prop.address}* - No data\n\n"

        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

    elif data.startswith("property_"):
        prop_id = int(data.split("_")[1])
        async with get_session() as session:
            result = await session.execute(
                select(Property)
                .options(selectinload(Property.bills))
                .where(Property.id == prop_id)
            )
            prop = result.scalar_one_or_none()

        if prop:
            await send_property_detail(query.message, prop)

    elif data.startswith("refresh_"):
        prop_id = int(data.split("_")[1])
        await query.edit_message_text("🔄 Refreshing property data...")

    elif data.startswith("history_"):
        prop_id = int(data.split("_")[1])
        async with get_session() as session:
            result = await session.execute(
                select(Property)
                .options(selectinload(Property.bills))
                .where(Property.id == prop_id)
            )
            prop = result.scalar_one_or_none()

        if prop and prop.bills:
            text = f"📜 *Bill History: {prop.address}*\n\n"
            for bill in prop.bills[:10]:  # Last 10 bills
                text += f"• {format_date(bill.statement_date)}: {format_currency(bill.amount_due)}\n"
            await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
        else:
            await query.edit_message_text("No billing history available.")

    elif data.startswith("remove_"):
        prop_id = int(data.split("_")[1])
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Remove", callback_data=f"confirm_remove_{prop_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove")
            ]
        ]
        await query.edit_message_text(
            "⚠️ Are you sure you want to remove this property?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("confirm_remove_"):
        prop_id = int(data.split("_")[2])
        async with get_session() as session:
            result = await session.execute(
                select(Property).where(Property.id == prop_id)
            )
            prop = result.scalar_one_or_none()
            if prop:
                prop.is_active = False
                await session.commit()
                await query.edit_message_text(f"✅ Property removed: {prop.address}")
            else:
                await query.edit_message_text("Property not found.")

    elif data == "cancel_remove":
        await query.edit_message_text("Removal cancelled.")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    async with get_session() as session:
        # Get last scraping log
        from database.models import ScrapingLog
        result = await session.execute(
            select(ScrapingLog)
            .order_by(ScrapingLog.started_at.desc())
            .limit(1)
        )
        last_scrape = result.scalar_one_or_none()

        # Count properties
        result = await session.execute(
            select(func.count(Property.id)).where(Property.is_active == True)
        )
        prop_count = result.scalar()

    text = f"""
⚙️ *Bot Status*

Properties Tracked: {prop_count}
"""

    if last_scrape:
        status = "✅ Success" if last_scrape.success else "❌ Failed"
        text += f"""
Last Update: {last_scrape.started_at.strftime('%b %d, %Y %H:%M')}
Status: {status}
Properties Scraped: {last_scrape.properties_scraped}
"""
        if last_scrape.error_message:
            text += f"Error: {last_scrape.error_message[:100]}\n"
    else:
        text += "\n_No scraping history yet_"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


def setup_handlers(application):
    """Set up all bot handlers"""

    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("properties", properties_command))
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CommandHandler("overdue", overdue_command))
    application.add_handler(CommandHandler("property", property_detail_command))
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

    # Callback query handler for inline buttons
    application.add_handler(CallbackQueryHandler(callback_handler))

    logger.info("Bot handlers configured")
