"""Blue Deer Telegram bot command handlers"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


def get_main_menu_keyboard():
    """Get the main menu inline keyboard"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 Status", callback_data="menu_status"),
            InlineKeyboardButton("🏗️ Inspections", callback_data="menu_inspections")
        ],
        [
            InlineKeyboardButton("📅 Recerts", callback_data="menu_recerts"),
            InlineKeyboardButton("💧 Bills", callback_data="menu_bills")
        ],
        [
            InlineKeyboardButton("🔔 Test Alert", callback_data="menu_test"),
            InlineKeyboardButton("❓ Help", callback_data="menu_help")
        ]
    ])


async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /chatid command - shows the chat ID for this chat"""
    chat = update.effective_chat

    await update.message.reply_text(
        f"📍 *Chat Info*\n\n"
        f"*Chat ID:* `{chat.id}`\n"
        f"*Type:* {chat.type}\n"
        f"*Title:* {chat.title or 'N/A'}\n\n"
        f"_Add this ID to `BLUEDEER_GROUP_CHAT_ID` to receive group notifications._",
        parse_mode=ParseMode.MARKDOWN
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    db_available = context.bot_data.get('db_available', False)

    # Register user for notifications
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
                        first_name=user.first_name,
                        notifications_enabled=True
                    )
                    session.add(db_user)
                    await session.commit()
                    logger.info(f"Registered new user: {user.id}")
        except Exception as e:
            logger.error(f"Failed to register user: {e}")

    db_status = "✅ Connected" if db_available else "⚠️ Offline"

    welcome_text = f"""
🦌 *Welcome to Blue Deer, {user.first_name}!*

I send you notifications about your properties:
• 🏗️ Inspection date alerts
• 📅 Recertification reminders
• 💧 Water bill alerts
• ⚠️ Overdue bill warnings

*Database:* {db_status}
*Your Telegram ID:* `{user.id}`

_Select an option below:_
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

    if action == "status":
        await show_status(query, context)
    elif action == "inspections":
        await show_inspections(query, context)
    elif action == "recerts":
        await show_recerts(query, context)
    elif action == "bills":
        await show_bills(query, context)
    elif action == "test":
        await send_test_notification(query, context)
    elif action == "help":
        await show_help(query, context)


async def back_to_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back to menu button"""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    db_available = context.bot_data.get('db_available', False)
    db_status = "✅ Connected" if db_available else "⚠️ Offline"

    welcome_text = f"""
🦌 *Blue Deer*

*Database:* {db_status}

_Select an option:_
"""

    await query.edit_message_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_main_menu_keyboard()
    )


async def show_status(query, context: ContextTypes.DEFAULT_TYPE):
    """Show property status overview"""
    db_available = context.bot_data.get('db_available', False)

    if not db_available:
        await query.edit_message_text(
            "⚠️ Database not connected.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="back_to_menu")
            ]])
        )
        return

    try:
        from database.connection import get_session
        from database.models import Property, Tenant
        from sqlalchemy import select, func
        from sqlalchemy.orm import selectinload

        async with get_session() as session:
            # Count properties
            result = await session.execute(
                select(func.count(Property.id)).where(Property.is_active == True)
            )
            prop_count = result.scalar()

            # Count active tenants
            result = await session.execute(
                select(func.count(Tenant.id)).where(Tenant.is_active == True)
            )
            tenant_count = result.scalar()

            # Count Section 8 tenants
            result = await session.execute(
                select(func.count(Tenant.id)).where(
                    Tenant.is_active == True,
                    Tenant.is_section8 == True
                )
            )
            section8_count = result.scalar()

            # Get total water bill amount
            result = await session.execute(
                select(Property)
                .where(Property.is_active == True)
                .options(selectinload(Property.bills))
            )
            properties = result.scalars().all()

            total_bills = sum(
                float(p.bills[0].amount_due) if p.bills and p.bills[0].amount_due else 0
                for p in properties
            )

        text = f"""
📊 *Blue Deer Status*

🏠 *Properties:* {prop_count}
👥 *Tenants:* {tenant_count}
🏛️ *Section 8:* {section8_count}

💧 *Total Water Bills:* ${total_bills:,.2f}

*Notification Schedule:*
• 7:00 AM - Inspection alerts
• 8:00 AM - Recert reminders
• 9:00 AM - High bill alerts
• 9:30 AM - Due soon reminders
• 10:00 AM - Overdue alerts
"""

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📅 Recerts", callback_data="menu_recerts"),
                InlineKeyboardButton("💧 Bills", callback_data="menu_bills")
            ],
            [InlineKeyboardButton("« Back", callback_data="back_to_menu")]
        ])

        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error in show_status: {e}")
        await query.edit_message_text(
            f"❌ Error: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="back_to_menu")
            ]])
        )


async def show_inspections(query, context: ContextTypes.DEFAULT_TYPE):
    """Show upcoming inspections"""
    bot = context.bot_data.get('blue_deer_bot')

    if not bot:
        await query.edit_message_text(
            "⚠️ Bot not initialized.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="back_to_menu")
            ]])
        )
        return

    message = await bot.get_inspections_summary()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu_inspections")],
        [InlineKeyboardButton("« Back", callback_data="back_to_menu")]
    ])

    await query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def show_recerts(query, context: ContextTypes.DEFAULT_TYPE):
    """Show upcoming recertifications"""
    bot = context.bot_data.get('blue_deer_bot')

    if not bot:
        await query.edit_message_text(
            "⚠️ Bot not initialized.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="back_to_menu")
            ]])
        )
        return

    message = await bot.get_recerts_summary()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu_recerts")],
        [InlineKeyboardButton("« Back", callback_data="back_to_menu")]
    ])

    await query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def show_bills(query, context: ContextTypes.DEFAULT_TYPE):
    """Show water bill summary"""
    bot = context.bot_data.get('blue_deer_bot')

    if not bot:
        await query.edit_message_text(
            "⚠️ Bot not initialized.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="back_to_menu")
            ]])
        )
        return

    message = await bot.get_bills_summary()

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu_bills")],
        [InlineKeyboardButton("« Back", callback_data="back_to_menu")]
    ])

    await query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def send_test_notification(query, context: ContextTypes.DEFAULT_TYPE):
    """Send a test notification"""
    bot = context.bot_data.get('blue_deer_bot')
    user = query.from_user

    if not bot:
        await query.edit_message_text(
            "⚠️ Bot not initialized.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("« Back", callback_data="back_to_menu")
            ]])
        )
        return

    # Send test notification to this user
    test_message = f"""
🦌 *Blue Deer Test Notification*

✅ Notifications are working!

This is a test alert sent to verify your notification setup.

*Your Telegram ID:* `{user.id}`
_Add this ID to BLUEDEER_ADMIN_TELEGRAM_ID to receive scheduled alerts._
"""

    await bot.send_notification(test_message, chat_id=user.id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("« Back", callback_data="back_to_menu")]
    ])

    await query.edit_message_text(
        "✅ *Test notification sent!*\n\nCheck your messages.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )


async def show_help(query, context: ContextTypes.DEFAULT_TYPE):
    """Show help"""
    help_text = """
🦌 *Blue Deer - Help*

*What I Do:*
I automatically send you notifications about your properties managed in the Blue Deer web app.

*Notifications:*
🏗️ *Inspections* - Alerts at 7 days, 3 days, 1 day before, and day-of
📅 *Recertifications* - Reminders when Section 8 recerts are due
💧 *Water Bills* - Alerts when bills exceed threshold
⚠️ *Overdue* - Warnings for past-due bills

*Commands:*
/start - Main menu
/status - Property overview
/inspections - View upcoming inspections
/recerts - View upcoming recertifications
/bills - View water bill alerts
/notify - Send test notification
/help - This help message

*Setup:*
Add your Telegram ID to the environment variable `BLUEDEER_ADMIN_TELEGRAM_ID` to receive scheduled notifications.
"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("« Back", callback_data="back_to_menu")]
    ])

    await query.edit_message_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    # Create a fake query object to reuse show_status
    class FakeQuery:
        async def edit_message_text(self, text, **kwargs):
            await update.message.reply_text(text, **kwargs)

    await show_status(FakeQuery(), context)


async def inspections_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /inspections command"""
    bot = context.bot_data.get('blue_deer_bot')

    if not bot:
        await update.message.reply_text("⚠️ Bot not initialized.")
        return

    message = await bot.get_inspections_summary()
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def recerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /recerts command"""
    bot = context.bot_data.get('blue_deer_bot')

    if not bot:
        await update.message.reply_text("⚠️ Bot not initialized.")
        return

    message = await bot.get_recerts_summary()
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def bills_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /bills command"""
    bot = context.bot_data.get('blue_deer_bot')

    if not bot:
        await update.message.reply_text("⚠️ Bot not initialized.")
        return

    message = await bot.get_bills_summary()
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def notify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /notify command - send test notification"""
    bot = context.bot_data.get('blue_deer_bot')
    user = update.effective_user

    if not bot:
        await update.message.reply_text("⚠️ Bot not initialized.")
        return

    test_message = f"""
🦌 *Blue Deer Test Notification*

✅ Notifications are working!

*Your Telegram ID:* `{user.id}`
_Add this ID to BLUEDEER_ADMIN_TELEGRAM_ID to receive scheduled alerts._
"""

    await bot.send_notification(test_message, chat_id=user.id)
    await update.message.reply_text("✅ Test notification sent!")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = """
🦌 *Blue Deer - Commands*

/start - Main menu
/status - Property overview
/inspections - Upcoming inspections
/recerts - Upcoming recertifications
/bills - Water bill alerts
/notify - Send test notification
/help - This help message

*Webapp:* bluedeer.space
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


def setup_handlers(application):
    """Set up all bot handlers"""
    # Command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("chatid", chatid_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("inspections", inspections_command))
    application.add_handler(CommandHandler("recerts", recerts_command))
    application.add_handler(CommandHandler("bills", bills_command))
    application.add_handler(CommandHandler("notify", notify_command))
    application.add_handler(CommandHandler("help", help_command))

    # Menu callbacks
    application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
    application.add_handler(CallbackQueryHandler(back_to_menu_callback, pattern="^back_to_menu$"))

    logger.info("Blue Deer handlers configured")
