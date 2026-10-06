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


def get_main_menu_keyboard():
    """Get the main menu inline keyboard"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Summary", callback_data="menu_summary"),
            InlineKeyboardButton("📍 Properties", callback_data="menu_properties")
        ],
        [
            InlineKeyboardButton("🔴 Overdue", callback_data="menu_overdue"),
            InlineKeyboardButton("🔄 Refresh", callback_data="menu_refresh")
        ],
        [
            InlineKeyboardButton("➕ Add Property", callback_data="menu_add"),
            InlineKeyboardButton("🗑️ Remove", callback_data="menu_remove")
        ],
        [
            InlineKeyboardButton("⚙️ Status", callback_data="menu_status"),
            InlineKeyboardButton("❓ Help", callback_data="menu_help")
        ]
    ])


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
👋 *Welcome to Water Bill Tracker, {user.first_name}!*

I help you track water bills for your properties from BSA Online (City of Warren, MI).

*Status Indicators:*
🟢 Current | 🟡 Due Soon | 🔴 Overdue | ✅ Paid

*Database:* {db_status}

_Select an option below to get started:_
"""

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu_keyboard()
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle main menu button callbacks"""
    query = update.callback_query
    await query.answer()

    action = query.data.replace("menu_", "")

    if action == "summary":
        await show_summary(query, context)
    elif action == "properties":
        await show_properties(query, context)
    elif action == "overdue":
        await show_overdue(query, context)
    elif action == "refresh":
        await do_refresh(query, context)
    elif action == "add":
        await query.edit_message_text(
            "📍 *Add New Property*\n\n"
            "Send the *street address* or *account number*:\n\n"
            "Examples:\n"
            "• `3040 Alvina` (address)\n"
            "• `302913026` (account #)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="back_to_menu")
            ]])
        )
        context.user_data['awaiting_property_input'] = True
    elif action == "remove":
        await show_remove_menu(query, context)
    elif action == "status":
        await show_status(query, context)
    elif action == "help":
        await show_help(query, context)


async def back_to_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back to menu button"""
    query = update.callback_query
    await query.answer()

    # Clear any pending states
    context.user_data.pop('awaiting_account', None)
    context.user_data.pop('awaiting_property_input', None)

    user = update.effective_user
    db_available = context.bot_data.get('db_available', False)
    db_status = "✅ Connected" if db_available else "⚠️ Not connected"

    welcome_text = f"""
👋 *Water Bill Tracker*

*Status Indicators:*
🟢 Current | 🟡 Due Soon | 🔴 Overdue | ✅ Paid

*Database:* {db_status}

_Select an option below:_
"""

    await query.edit_message_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu_keyboard()
    )


async def show_summary(query, context: ContextTypes.DEFAULT_TYPE):
    """Show summary via callback"""
    db_available = context.bot_data.get('db_available', False)

    if not db_available:
        await query.edit_message_text(
            "⚠️ Database not connected.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )
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
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Property", callback_data="menu_add")],
                [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
            ])
            await query.edit_message_text(
                "📊 *Summary*\n\nNo properties tracked yet.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
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
            for prop, bill in overdue_props[:3]:  # Show top 3
                text += f"• {prop.address[:30]}: {format_currency(bill.amount_due)}\n"
            if len(overdue_props) > 3:
                text += f"_...and {len(overdue_props) - 3} more_\n"

        if due_soon_props:
            text += "\n*⏰ Due Soon:*\n"
            for prop, bill in due_soon_props[:3]:
                text += f"• {prop.address[:30]}: {format_date(bill.due_date)}\n"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔴 View Overdue", callback_data="menu_overdue"),
                InlineKeyboardButton("📍 Properties", callback_data="menu_properties")
            ],
            [
                InlineKeyboardButton("🔄 Refresh Data", callback_data="menu_refresh")
            ],
            [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
        ])

        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    except Exception:
        logger.exception("Error in show_summary")
        await query.edit_message_text(
            "❌ Something went wrong. Please try again.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )


async def show_properties(query, context: ContextTypes.DEFAULT_TYPE):
    """Show properties list via callback with clickable items"""
    db_available = context.bot_data.get('db_available', False)

    if not db_available:
        await query.edit_message_text(
            "⚠️ Database not connected.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )
        return

    try:
        from database.connection import get_session
        from database.models import Property
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
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Property", callback_data="menu_add")],
                [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
            ])
            await query.edit_message_text(
                "📍 *Your Properties*\n\nNo properties tracked yet.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        text = "*📍 Your Properties*\n\n_Tap a property to view details:_\n"

        keyboard = []
        for prop in properties:
            latest = prop.latest_bill
            status_emoji = prop.status_emoji
            if latest:
                amount = format_currency(latest.amount_due)
                display = f"{status_emoji} {prop.address[:25]} - {amount}"
            else:
                display = f"⚪ {prop.address[:35]}"

            keyboard.append([
                InlineKeyboardButton(display, callback_data=f"prop_{prop.id}")
            ])

        keyboard.append([
            InlineKeyboardButton("➕ Add", callback_data="menu_add"),
            InlineKeyboardButton("🗑️ Remove", callback_data="menu_remove")
        ])
        keyboard.append([InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception:
        logger.exception("Error in show_properties")
        await query.edit_message_text(
            "❌ Something went wrong. Please try again.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )


async def show_property_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed view of a single property"""
    query = update.callback_query
    await query.answer()

    prop_id = int(query.data.replace("prop_", ""))

    try:
        from database.connection import get_session
        from database.models import Property
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with get_session() as session:
            result = await session.execute(
                select(Property)
                .options(selectinload(Property.bills))
                .where(Property.id == prop_id)
            )
            prop = result.scalar_one_or_none()

        if not prop:
            await query.edit_message_text(
                "❌ Property not found.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Back to Properties", callback_data="menu_properties")
                ]])
            )
            return

        text = f"""
📍 *Property Details*

*Address:* {prop.address}
*Account:* `{prop.bsa_account_number}`
"""

        if prop.owner_name:
            text += f"*Owner:* {prop.owner_name}\n"

        latest = prop.latest_bill
        if latest:
            text += f"""
━━━━━━━━━━━━━━━━━━
*Latest Bill*

{prop.status_emoji} *Status:* {latest.status.value.replace('_', ' ').title()}
💰 *Amount Due:* {format_currency(latest.amount_due)}
📅 *Due Date:* {format_date(latest.due_date)}
"""
            if latest.previous_balance:
                text += f"📊 *Previous Balance:* {format_currency(latest.previous_balance)}\n"
            if latest.current_charges:
                text += f"📝 *Current Charges:* {format_currency(latest.current_charges)}\n"
            if latest.water_usage_gallons:
                text += f"💧 *Water Usage:* {latest.water_usage_gallons:,} gallons\n"
            if latest.scraped_at:
                text += f"\n_Last updated: {latest.scraped_at.strftime('%b %d, %Y %H:%M')}_"

            # Show bill history count
            if len(prop.bills) > 1:
                text += f"\n\n📜 _{len(prop.bills)} bills in history_"
        else:
            text += "\n_No bill data yet. Tap Refresh to fetch._"

        # Build BSA Online payment URL
        bsa_url = f"https://bsaonline.com/OnlinePayment/OnlinePaymentSearch?PaymentApplicationType=10&uid=305"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pay on BSA Online", url=bsa_url)],
            [
                InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_prop_{prop.id}"),
                InlineKeyboardButton("🗑️ Remove", callback_data=f"remove_prop_{prop.id}")
            ],
            [InlineKeyboardButton("« Back to Properties", callback_data="menu_properties")],
            [InlineKeyboardButton("« Main Menu", callback_data="back_to_menu")]
        ])

        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    except Exception:
        logger.exception("Error in show_property_detail")
        await query.edit_message_text(
            "❌ Something went wrong. Please try again.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )


async def show_overdue(query, context: ContextTypes.DEFAULT_TYPE):
    """Show overdue bills via callback"""
    db_available = context.bot_data.get('db_available', False)

    if not db_available:
        await query.edit_message_text(
            "⚠️ Database not connected.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )
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
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 View Summary", callback_data="menu_summary")],
                [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
            ])
            await query.edit_message_text(
                "✅ *No Overdue Bills!*\n\nYou're all caught up.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        total_overdue = Decimal("0")
        text = f"🔴 *Overdue Bills ({len(overdue_props)})*\n\n"

        keyboard = []
        for prop, bill in overdue_props:
            days_overdue = (datetime.now().date() - bill.due_date).days if bill.due_date else 0
            total_overdue += bill.amount_due

            text += f"*{prop.address[:35]}*\n"
            text += f"💰 {format_currency(bill.amount_due)} • ⏰ {days_overdue} days overdue\n\n"

            # Add clickable button for each
            keyboard.append([
                InlineKeyboardButton(
                    f"📍 {prop.address[:30]}",
                    callback_data=f"prop_{prop.id}"
                )
            ])

        text += f"━━━━━━━━━━━━━━━━━━\n*Total Overdue: {format_currency(total_overdue)}*"

        keyboard.append([InlineKeyboardButton("🔄 Refresh All", callback_data="menu_refresh")])
        keyboard.append([InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")])

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception:
        logger.exception("Error in show_overdue")
        await query.edit_message_text(
            "❌ Something went wrong. Please try again.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )


async def do_refresh(query, context: ContextTypes.DEFAULT_TYPE):
    """Perform refresh via callback"""
    await query.edit_message_text(
        "🔄 *Refreshing...*\n\nFetching latest bill data from BSA Online.\nThis may take a moment.",
        parse_mode=ParseMode.MARKDOWN
    )

    bot = context.bot_data.get('water_bill_bot')

    if bot and bot.db_available:
        try:
            await bot.refresh_all_bills()
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 View Summary", callback_data="menu_summary")],
                [InlineKeyboardButton("📍 View Properties", callback_data="menu_properties")],
                [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
            ])
            await query.edit_message_text(
                "✅ *Refresh Complete!*\n\nBill data has been updated.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        except Exception:
            logger.exception("Refresh failed")
            await query.edit_message_text(
                "❌ *Refresh Failed*\n\nPlease try again later.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
                ]])
            )
    else:
        await query.edit_message_text(
            "⚠️ Database not available. Cannot refresh.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )


async def show_remove_menu(query, context: ContextTypes.DEFAULT_TYPE):
    """Show remove property menu via callback"""
    db_available = context.bot_data.get('db_available', False)

    if not db_available:
        await query.edit_message_text(
            "⚠️ Database not connected.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )
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
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Property", callback_data="menu_add")],
                [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
            ])
            await query.edit_message_text(
                "🗑️ *Remove Property*\n\nNo properties to remove.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        keyboard = []
        for prop in properties:
            display_addr = prop.address[:40] + "..." if len(prop.address) > 40 else prop.address
            keyboard.append([
                InlineKeyboardButton(display_addr, callback_data=f"remove_prop_{prop.id}")
            ])

        keyboard.append([InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")])

        await query.edit_message_text(
            "🗑️ *Remove Property*\n\n_Select the property to remove:_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception:
        logger.exception("Error in show_remove_menu")
        await query.edit_message_text(
            "❌ Something went wrong. Please try again.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )


async def show_status(query, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status via callback"""
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

        except Exception:
            logger.exception("Error getting bot status stats")
            text += "\n_Stats are temporarily unavailable._"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Data", callback_data="menu_refresh")],
        [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
    ])

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def show_help(query, context: ContextTypes.DEFAULT_TYPE):
    """Show help via callback"""
    help_text = """
*Water Bill Tracker - Help*

📋 *View Bills:*
• Summary - Overview dashboard
• Properties - List all properties
• Overdue - Show overdue only

🔄 *Updates:*
• Refresh - Fetch latest data

➕ *Manage:*
• Add - Track new property
• Remove - Stop tracking

*Status Indicators:*
🟢 Current - No action needed
🟡 Due Soon - Due within 7 days
🔴 Overdue - Past due date
✅ Paid - No balance due

_Tap any property to see details!_
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
    ])

    await query.edit_message_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def handle_property_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle address or account number input for adding property via menu"""
    if not context.user_data.get('awaiting_property_input'):
        return  # Not expecting input

    user_input = update.message.text.strip()
    context.user_data.pop('awaiting_property_input', None)

    if len(user_input) < 3:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="menu_add")],
            [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
        ])
        await update.message.reply_text(
            "❌ Input too short. Please enter a valid address or account number.",
            reply_markup=keyboard
        )
        return

    # Detect if input is account number (all digits) or address (contains letters)
    is_account_number = user_input.replace(" ", "").isdigit()

    try:
        from database.connection import get_session
        from database.models import Property
        from sqlalchemy import select

        # Show searching message
        search_type = "account number" if is_account_number else "address"
        status_msg = await update.message.reply_text(
            f"🔍 *Searching BSA Online...*\n\nLooking up {search_type}: `{user_input}`",
            parse_mode=ParseMode.MARKDOWN
        )

        # Import and use scraper
        from scraper.bsa_scraper import BSAScraper

        bill_data = None
        async with BSAScraper() as scraper:
            if is_account_number:
                bill_data = await scraper.search_by_account(user_input)
            else:
                bill_data = await scraper.search_by_address(user_input)

        if not bill_data or not bill_data.account_number:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Try Again", callback_data="menu_add")],
                [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
            ])
            await status_msg.edit_text(
                f"❌ *Property Not Found*\n\n"
                f"No property found for: `{user_input}`\n\n"
                f"Please check the {search_type} and try again.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        # Check if already tracked
        async with get_session() as session:
            result = await session.execute(
                select(Property).where(Property.bsa_account_number == bill_data.account_number)
            )
            existing = result.scalar_one_or_none()

            if existing:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"📍 View Property", callback_data=f"prop_{existing.id}")],
                    [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
                ])
                await status_msg.edit_text(
                    f"⚠️ *Already Tracked*\n\n"
                    f"This property is already being tracked:\n\n"
                    f"*Address:* {existing.address}\n"
                    f"*Account:* `{existing.bsa_account_number}`",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
                return

            # Add the new property with scraped data
            new_prop = Property(
                bsa_account_number=bill_data.account_number,
                address=bill_data.address or f"Property {bill_data.account_number}",
                owner_name=bill_data.owner_name
            )
            session.add(new_prop)
            await session.commit()
            prop_id = new_prop.id

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📍 View Property", callback_data=f"prop_{prop_id}")],
            [InlineKeyboardButton("🔄 Refresh All", callback_data="menu_refresh")],
            [InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]
        ])

        await status_msg.edit_text(
            f"✅ *Property Added!*\n\n"
            f"*Address:* {bill_data.address}\n"
            f"*Account:* `{bill_data.account_number}`\n"
            f"*Amount Due:* ${bill_data.amount_due:,.2f}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    except Exception:
        logger.exception("Error adding property")
        await update.message.reply_text(
            "❌ *Error Adding Property*\n\nPlease try again later.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Try Again", callback_data="menu_add"),
                InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")
            ]])
        )


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
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Property", callback_data="menu_add")],
                [InlineKeyboardButton("📊 Summary", callback_data="menu_summary")]
            ])
            await update.message.reply_text(
                "📍 *Your Properties*\n\nNo properties tracked yet.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        text = "*📍 Your Properties*\n\n_Tap a property for details:_\n"

        keyboard = []
        for prop in properties:
            latest = prop.latest_bill
            status_emoji = prop.status_emoji

            if latest:
                amount = format_currency(latest.amount_due)
                display = f"{status_emoji} {prop.address[:25]} - {amount}"
            else:
                display = f"⚪ {prop.address[:35]}"

            keyboard.append([
                InlineKeyboardButton(display, callback_data=f"prop_{prop.id}")
            ])

        keyboard.append([
            InlineKeyboardButton("➕ Add", callback_data="menu_add"),
            InlineKeyboardButton("🗑️ Remove", callback_data="menu_remove")
        ])
        keyboard.append([
            InlineKeyboardButton("📊 Summary", callback_data="menu_summary"),
            InlineKeyboardButton("🔄 Refresh", callback_data="menu_refresh")
        ])

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception:
        logger.exception("Error in properties_command")
        await update.message.reply_text("❌ Something went wrong. Please try again.")


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
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Property", callback_data="menu_add")]
            ])
            await update.message.reply_text(
                "📊 *Summary*\n\nNo properties tracked yet.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
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
            for prop, bill in overdue_props[:3]:
                text += f"• {prop.address[:30]}: {format_currency(bill.amount_due)}\n"
            if len(overdue_props) > 3:
                text += f"_...and {len(overdue_props) - 3} more_\n"

        if due_soon_props:
            text += "\n*⏰ Due Soon:*\n"
            for prop, bill in due_soon_props[:3]:
                text += f"• {prop.address[:30]}: {format_date(bill.due_date)}\n"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔴 View Overdue", callback_data="menu_overdue"),
                InlineKeyboardButton("📍 Properties", callback_data="menu_properties")
            ],
            [
                InlineKeyboardButton("🔄 Refresh Data", callback_data="menu_refresh"),
                InlineKeyboardButton("➕ Add", callback_data="menu_add")
            ]
        ])

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    except Exception:
        logger.exception("Error in summary_command")
        await update.message.reply_text("❌ Something went wrong. Please try again.")


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
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 View Summary", callback_data="menu_summary")],
                [InlineKeyboardButton("📍 Properties", callback_data="menu_properties")]
            ])
            await update.message.reply_text(
                "✅ *No Overdue Bills!*\n\nYou're all caught up.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        text = f"🔴 *Overdue Bills ({len(overdue_props)})*\n\n"

        total_overdue = Decimal("0")
        keyboard = []
        for prop, bill in overdue_props:
            days_overdue = (datetime.now().date() - bill.due_date).days if bill.due_date else 0
            total_overdue += bill.amount_due

            text += f"*{prop.address[:35]}*\n"
            text += f"💰 {format_currency(bill.amount_due)} • ⏰ {days_overdue} days overdue\n\n"

            keyboard.append([
                InlineKeyboardButton(f"📍 {prop.address[:30]}", callback_data=f"prop_{prop.id}")
            ])

        text += f"━━━━━━━━━━━━━━━━━━\n*Total Overdue: {format_currency(total_overdue)}*"

        keyboard.append([InlineKeyboardButton("🔄 Refresh All", callback_data="menu_refresh")])
        keyboard.append([
            InlineKeyboardButton("📊 Summary", callback_data="menu_summary"),
            InlineKeyboardButton("📍 Properties", callback_data="menu_properties")
        ])

        await update.message.reply_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except Exception:
        logger.exception("Error in overdue_command")
        await update.message.reply_text("❌ Something went wrong. Please try again.")


async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /refresh command - manually trigger bill update"""
    await update.message.reply_text("🔄 *Refreshing...*\n\nFetching latest bill data from BSA Online.", parse_mode=ParseMode.MARKDOWN)

    bot = context.bot_data.get('water_bill_bot')

    if bot and bot.db_available:
        try:
            await bot.refresh_all_bills()
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 View Summary", callback_data="menu_summary")],
                [InlineKeyboardButton("📍 View Properties", callback_data="menu_properties")]
            ])
            await update.message.reply_text(
                "✅ *Refresh Complete!*\n\nBill data has been updated.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        except Exception:
            logger.exception("Refresh failed")
            await update.message.reply_text("❌ *Refresh Failed*\n\nPlease try again later.", parse_mode=ParseMode.MARKDOWN)
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
        "Send the *street address* or *account number*:\n\n"
        "Examples:\n"
        "• `3040 Alvina` (address)\n"
        "• `302913026` (account #)\n\n"
        "Use /cancel to cancel.",
        parse_mode=ParseMode.MARKDOWN
    )
    return ADDING_PROPERTY


async def add_property_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle address or account number input for adding property via /add command"""
    user_input = update.message.text.strip()

    if len(user_input) < 3:
        await update.message.reply_text("Input too short. Please enter a valid address or account number.")
        return ADDING_PROPERTY

    # Detect if input is account number (all digits) or address (contains letters)
    is_account_number = user_input.replace(" ", "").isdigit()
    search_type = "account number" if is_account_number else "address"

    try:
        from database.connection import get_session
        from database.models import Property
        from sqlalchemy import select

        # Show searching message
        status_msg = await update.message.reply_text(
            f"🔍 *Searching BSA Online...*\n\nLooking up {search_type}: `{user_input}`",
            parse_mode=ParseMode.MARKDOWN
        )

        # Import and use scraper
        from scraper.bsa_scraper import BSAScraper

        bill_data = None
        async with BSAScraper() as scraper:
            if is_account_number:
                bill_data = await scraper.search_by_account(user_input)
            else:
                bill_data = await scraper.search_by_address(user_input)

        if not bill_data or not bill_data.account_number:
            await status_msg.edit_text(
                f"❌ *Property Not Found*\n\n"
                f"No property found for: `{user_input}`\n\n"
                f"Please check the {search_type} and try again with /add",
                parse_mode=ParseMode.MARKDOWN
            )
            return ConversationHandler.END

        # Check if already tracked
        async with get_session() as session:
            result = await session.execute(
                select(Property).where(Property.bsa_account_number == bill_data.account_number)
            )
            existing = result.scalar_one_or_none()

            if existing:
                await status_msg.edit_text(
                    f"⚠️ *Already Tracked*\n\n"
                    f"This property is already being tracked:\n\n"
                    f"*Address:* {existing.address}\n"
                    f"*Account:* `{existing.bsa_account_number}`",
                    parse_mode=ParseMode.MARKDOWN
                )
                return ConversationHandler.END

            # Add the new property with scraped data
            new_prop = Property(
                bsa_account_number=bill_data.account_number,
                address=bill_data.address or f"Property {bill_data.account_number}",
                owner_name=bill_data.owner_name
            )
            session.add(new_prop)
            await session.commit()

        await status_msg.edit_text(
            f"✅ *Property Added!*\n\n"
            f"*Address:* {bill_data.address}\n"
            f"*Account:* `{bill_data.account_number}`\n"
            f"*Amount Due:* ${bill_data.amount_due:,.2f}\n\n"
            f"Use /properties to view all properties.",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception:
        logger.exception("Error adding property")
        await update.message.reply_text("❌ Something went wrong. Please try again.")

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

    except Exception:
        logger.exception("Error in remove_property_start")
        await update.message.reply_text("❌ Something went wrong. Please try again.")


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

        except Exception:
            logger.exception("Error in remove_property_callback")
            await query.edit_message_text("❌ Something went wrong. Please try again.")


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

        except Exception:
            logger.exception("Error in remove_property_confirm")
            await query.edit_message_text("❌ Something went wrong. Please try again.")


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

        except Exception:
            logger.exception("Error getting bot status stats")
            text += "\n_Stats are temporarily unavailable._"

    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


def setup_handlers(application):
    """Set up all bot handlers"""
    from telegram_access import admin_only

    # Command handlers
    application.add_handler(CommandHandler("start", admin_only(start_command)))
    application.add_handler(CommandHandler("help", admin_only(help_command)))
    application.add_handler(CommandHandler("properties", admin_only(properties_command)))
    application.add_handler(CommandHandler("summary", admin_only(summary_command)))
    application.add_handler(CommandHandler("overdue", admin_only(overdue_command)))
    application.add_handler(CommandHandler("refresh", admin_only(refresh_command)))
    application.add_handler(CommandHandler("status", admin_only(status_command)))

    # Add property conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", admin_only(add_property_start))],
        states={
            ADDING_PROPERTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_only(add_property_account))],
        },
        fallbacks=[CommandHandler("cancel", admin_only(cancel_command))],
    )
    application.add_handler(add_conv)

    # Interactive menu callbacks
    application.add_handler(CallbackQueryHandler(admin_only(menu_callback), pattern="^menu_"))
    application.add_handler(CallbackQueryHandler(admin_only(back_to_menu_callback), pattern="^back_to_menu$"))
    application.add_handler(CallbackQueryHandler(admin_only(show_property_detail), pattern="^prop_\\d+$"))

    # Remove property callbacks
    application.add_handler(CommandHandler("remove", admin_only(remove_property_start)))
    application.add_handler(CallbackQueryHandler(admin_only(remove_property_callback), pattern="^remove_"))
    application.add_handler(CallbackQueryHandler(admin_only(remove_property_confirm), pattern="^confirm_remove_"))

    # Handle text input for menu-based add property (address or account number)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        admin_only(handle_property_input)
    ))

    logger.info("Bot handlers configured")
