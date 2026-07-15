"""Password vault handlers for the Blue Deer Telegram bot.

PIN-gated, admin-only, private-chat only. Passwords are stored plaintext
in the DB; the PIN (bcrypt-hashed) is the sole access control alongside
the admin whitelist. Trade-off chosen for simplicity — see the design spec.

Wiring:
    from bluedeer_bot import vault
    vault.register(application)
"""

import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from telegram import (
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)

UNLOCK_TTL_MINUTES = 10
LOCKOUT_MINUTES = 15
MAX_FAILED_ATTEMPTS = 5
PIN_LENGTH = 6
MAX_LABEL_LEN = 120


# ── admin gate ──────────────────────────────────────────────────────

def _allowed_user_ids() -> set:
    """Whitelist of Telegram user IDs allowed to access the vault.

    Reads BLUEDEER_VAULT_USER_IDS (comma-separated). Falls back to
    BLUEDEER_ADMIN_TELEGRAM_ID for backward compatibility with the
    single-admin setup. Silently drops non-integer tokens.
    """
    ids: set = set()
    raw = os.getenv("BLUEDEER_VAULT_USER_IDS", "").strip()
    if raw:
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                ids.add(int(token))
            except ValueError:
                logger.warning(f"Vault: ignoring non-int BLUEDEER_VAULT_USER_IDS entry: {token!r}")
    admin = os.getenv("BLUEDEER_ADMIN_TELEGRAM_ID", "").strip()
    if admin:
        try:
            ids.add(int(admin))
        except ValueError:
            pass
    return ids


def _is_admin(update: Update) -> bool:
    user = update.effective_user
    if user is None:
        return False
    return user.id in _allowed_user_ids()


def _is_private(update: Update) -> bool:
    chat = update.effective_chat
    return chat is not None and chat.type == "private"


# ── audit log ───────────────────────────────────────────────────────

async def _log_access(session, user_id: int, action: str, entry_id: Optional[int] = None, entry_label: Optional[str] = None) -> None:
    """Best-effort audit log. Failures are logged and swallowed."""
    from database.models import VaultAccessLog
    try:
        session.add(VaultAccessLog(
            telegram_user_id=user_id,
            action=action,
            entry_id=entry_id,
            entry_label=entry_label,
        ))
    except Exception as e:
        logger.warning(f"Vault: failed to write access log: {e}")


# ── session state (in-memory, per user) ─────────────────────────────

def _is_unlocked(context: ContextTypes.DEFAULT_TYPE) -> bool:
    ts = context.user_data.get("vault_unlocked_at")
    if not isinstance(ts, datetime):
        return False
    return datetime.utcnow() - ts < timedelta(minutes=UNLOCK_TTL_MINUTES)


def _mark_unlocked(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data["vault_unlocked_at"] = datetime.utcnow()


def _clear_flow(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear any in-progress flow state (setup, unlock, add). Preserves unlock timestamp."""
    for key in ("vault_state", "vault_setup_pin", "vault_add"):
        context.user_data.pop(key, None)


def _lock(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("vault_unlocked_at", None)
    _clear_flow(context)


# ── MarkdownV2 escaping ─────────────────────────────────────────────

_MDV2_SPECIALS = r"_*[]()~`>#+-=|{}.!\\"


def _md2(text: str) -> str:
    return "".join("\\" + c if c in _MDV2_SPECIALS else c for c in text)


# ── DB helpers ──────────────────────────────────────────────────────

async def _get_pin_row(session):
    from database.models import VaultPin
    from sqlalchemy import select
    result = await session.execute(select(VaultPin).where(VaultPin.id == 1))
    return result.scalar_one_or_none()


def _valid_pin(pin: str) -> bool:
    return bool(re.fullmatch(rf"\d{{{PIN_LENGTH}}}", pin))


# ── UI ──────────────────────────────────────────────────────────────

def _main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔑 List", callback_data="vault:list"),
        InlineKeyboardButton("➕ Add", callback_data="vault:add"),
        InlineKeyboardButton("🔒 Lock", callback_data="vault:lock"),
    ]])


async def _try_delete(message):
    """Best-effort deletion of a Telegram message. Never raises."""
    try:
        await message.delete()
    except Exception as e:
        logger.warning(f"Vault: failed to delete message: {e}")


# ── Handlers ────────────────────────────────────────────────────────

async def vault_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: /vault"""
    if not _is_admin(update):
        await update.effective_message.reply_text("Not authorized.")
        return
    if not _is_private(update):
        await update.effective_message.reply_text("Send /vault in a private chat with me.")
        return
    if not context.bot_data.get("db_available", False):
        await update.message.reply_text("🔐 Vault is offline — DB unavailable.")
        return

    _clear_flow(context)  # any stale add/setup state gets wiped

    from database.connection import get_session
    async with get_session() as session:
        pin_row = await _get_pin_row(session)

    if pin_row is None:
        # First-run setup
        context.user_data["vault_state"] = "setup_1"
        await update.message.reply_text(
            f"No vault PIN yet. Send a {PIN_LENGTH}-digit PIN to create one.",
            reply_markup=ForceReply(selective=True),
        )
        return

    now = datetime.utcnow()
    if pin_row.locked_until and pin_row.locked_until > now:
        mins = int((pin_row.locked_until - now).total_seconds() / 60) + 1
        await update.message.reply_text(f"🔒 Locked. Try again in ~{mins} min.")
        return

    if _is_unlocked(context):
        await update.message.reply_text("🔐 Vault menu:", reply_markup=_main_menu_kb())
        return

    context.user_data["vault_state"] = "unlock"
    await update.message.reply_text(
        f"Send your {PIN_LENGTH}-digit PIN.",
        reply_markup=ForceReply(selective=True),
    )


async def vault_lock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/vault_lock — clears the current session."""
    if not _is_admin(update):
        await update.effective_message.reply_text("Not authorized.")
        return
    _lock(context)
    await update.message.reply_text("🔒 Locked.")


async def vault_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process text sent while a vault flow is in progress. No-op otherwise."""
    if not _is_admin(update) or not _is_private(update):
        return
    state = context.user_data.get("vault_state")
    if not state:
        return

    text = (update.message.text or "").strip()
    chat_id = update.effective_chat.id

    # Delete the user's message immediately to keep the chat clean
    await _try_delete(update.message)

    if state == "setup_1":
        if not _valid_pin(text):
            await context.bot.send_message(
                chat_id,
                f"❌ Invalid. Send a {PIN_LENGTH}-digit PIN.",
                reply_markup=ForceReply(selective=True),
            )
            return
        context.user_data["vault_setup_pin"] = text
        context.user_data["vault_state"] = "setup_2"
        await context.bot.send_message(
            chat_id,
            "Confirm your PIN.",
            reply_markup=ForceReply(selective=True),
        )
        return

    if state == "setup_2":
        first = context.user_data.pop("vault_setup_pin", None)
        _clear_flow(context)
        if first != text:
            await context.bot.send_message(chat_id, "❌ Mismatch. Start again with /vault.")
            return
        from database.connection import get_session
        from database.models import VaultPin
        pin_hash = bcrypt.hashpw(text.encode(), bcrypt.gensalt()).decode()
        async with get_session() as session:
            session.add(VaultPin(id=1, pin_hash=pin_hash, failed_attempts=0))
            await session.commit()
        await context.bot.send_message(chat_id, "✅ Vault created. Use /vault to unlock.")
        return

    if state == "unlock":
        _clear_flow(context)
        from database.connection import get_session
        async with get_session() as session:
            pin_row = await _get_pin_row(session)
            if pin_row is None:
                await context.bot.send_message(chat_id, "No PIN set. Use /vault to set one.")
                return
            if bcrypt.checkpw(text.encode(), pin_row.pin_hash.encode()):
                pin_row.failed_attempts = 0
                pin_row.locked_until = None
                await session.commit()
                _mark_unlocked(context)
                await context.bot.send_message(chat_id, "🔓 Unlocked.", reply_markup=_main_menu_kb())
                return
            pin_row.failed_attempts = (pin_row.failed_attempts or 0) + 1
            if pin_row.failed_attempts >= MAX_FAILED_ATTEMPTS:
                pin_row.locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                pin_row.failed_attempts = 0
                await session.commit()
                await context.bot.send_message(
                    chat_id, f"🔒 Too many wrong PINs. Locked for {LOCKOUT_MINUTES} min."
                )
                return
            remaining = MAX_FAILED_ATTEMPTS - pin_row.failed_attempts
            await session.commit()
        await context.bot.send_message(chat_id, f"❌ Wrong PIN. {remaining} attempt(s) left.")
        return

    # Add-flow
    if state == "add_label":
        if not text or len(text) > MAX_LABEL_LEN:
            await context.bot.send_message(
                chat_id,
                f"❌ Label must be 1–{MAX_LABEL_LEN} chars. Send again.",
                reply_markup=ForceReply(selective=True),
            )
            return
        add = context.user_data.setdefault("vault_add", {})
        add["label"] = text
        context.user_data["vault_state"] = "add_username"
        await context.bot.send_message(
            chat_id,
            "Send the username (or `-` to skip).",
            reply_markup=ForceReply(selective=True),
        )
        return

    if state == "add_username":
        add = context.user_data.setdefault("vault_add", {})
        add["username"] = "" if text == "-" else text
        context.user_data["vault_state"] = "add_password"
        await context.bot.send_message(
            chat_id,
            "Send the password.",
            reply_markup=ForceReply(selective=True),
        )
        return

    if state == "add_password":
        add = context.user_data.pop("vault_add", {}) or {}
        context.user_data.pop("vault_state", None)
        from database.connection import get_session
        from database.models import VaultEntry
        async with get_session() as session:
            entry = VaultEntry(
                label=add.get("label", ""),
                username=add.get("username") or None,
                password=text,
            )
            session.add(entry)
            await session.flush()
            await _log_access(session, update.effective_user.id, "add", entry.id, entry.label)
            await session.commit()
        # Refresh TTL since they just acted
        _mark_unlocked(context)
        await context.bot.send_message(
            chat_id,
            f"✅ Saved: {add.get('label')}",
            reply_markup=_main_menu_kb(),
        )
        return


async def vault_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle vault:* button presses."""
    query = update.callback_query
    if not _is_admin(update):
        await query.answer("Not authorized.", show_alert=True)
        return
    await query.answer()

    if not _is_unlocked(context):
        await query.edit_message_text("🔒 Vault is locked. Send /vault to unlock.")
        return

    _mark_unlocked(context)  # refresh TTL on any action

    data = query.data or ""
    parts = data.split(":", 2)
    action = parts[1] if len(parts) >= 2 else ""
    arg = parts[2] if len(parts) >= 3 else ""

    from database.connection import get_session
    from database.models import VaultEntry
    from sqlalchemy import select

    if action == "menu":
        await query.edit_message_text("🔐 Vault menu:", reply_markup=_main_menu_kb())
        return

    if action == "list":
        async with get_session() as session:
            result = await session.execute(
                select(VaultEntry).order_by(VaultEntry.label.asc())
            )
            entries = result.scalars().all()
        if not entries:
            await query.edit_message_text("No entries yet.", reply_markup=_main_menu_kb())
            return
        rows = []
        for e in entries:
            title = e.label if not e.username else f"{e.label} — {e.username}"
            if len(title) > 60:
                title = title[:57] + "…"
            rows.append([InlineKeyboardButton(title, callback_data=f"vault:get:{e.id}")])
        rows.append([InlineKeyboardButton("« Menu", callback_data="vault:menu")])
        await query.edit_message_text("🔐 Entries:", reply_markup=InlineKeyboardMarkup(rows))
        return

    if action == "add":
        context.user_data["vault_state"] = "add_label"
        context.user_data["vault_add"] = {}
        await context.bot.send_message(
            update.effective_chat.id,
            "Send the label (e.g., 'BSA Water').",
            reply_markup=ForceReply(selective=True),
        )
        return

    if action == "lock":
        _lock(context)
        await query.edit_message_text("🔒 Locked.")
        return

    if action == "get":
        try:
            entry_id = int(arg)
        except ValueError:
            return
        async with get_session() as session:
            result = await session.execute(select(VaultEntry).where(VaultEntry.id == entry_id))
            entry = result.scalar_one_or_none()
            if entry is None:
                await query.edit_message_text("Entry not found.", reply_markup=_main_menu_kb())
                return
            await _log_access(session, update.effective_user.id, "read", entry.id, entry.label)
            await session.commit()
        text = (
            f"🏦 *{_md2(entry.label)}*\n"
            f"User: `{_md2(entry.username or '—')}`\n"
            f"Pass: ||{_md2(entry.password)}||"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Delete", callback_data=f"vault:delask:{entry.id}"),
            InlineKeyboardButton("« Back", callback_data="vault:list"),
        ]])
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb)
        return

    if action == "delask":
        try:
            entry_id = int(arg)
        except ValueError:
            return
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Yes, delete", callback_data=f"vault:delyes:{entry_id}"),
            InlineKeyboardButton("Cancel", callback_data="vault:list"),
        ]])
        await query.edit_message_text("Delete this entry?", reply_markup=kb)
        return

    if action == "delyes":
        try:
            entry_id = int(arg)
        except ValueError:
            return
        async with get_session() as session:
            result = await session.execute(select(VaultEntry).where(VaultEntry.id == entry_id))
            entry = result.scalar_one_or_none()
            if entry is not None:
                await _log_access(session, update.effective_user.id, "delete", entry.id, entry.label)
                await session.delete(entry)
                await session.commit()
        await query.edit_message_text("🗑 Deleted.", reply_markup=_main_menu_kb())
        return


def register(application):
    """Register vault handlers on the given Application."""
    application.add_handler(CommandHandler("vault", vault_command))
    application.add_handler(CommandHandler("vault_lock", vault_lock_command))
    application.add_handler(CallbackQueryHandler(vault_callback, pattern="^vault:"))
    # Text handler: only acts when a vault flow state is set. Ignores other text.
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, vault_text_handler))
