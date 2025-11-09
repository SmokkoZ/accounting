"""
Telegram Bot implementation for the Surebet Accounting System.

This module handles:
- Receiving screenshots via Telegram
- Saving screenshots locally
- Creating placeholder bet records
- Command handlers for bot interaction
"""

import asyncio
import inspect
import os
import platform
import re
import secrets
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, __version__ as telegram_version
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from src.core.config import Config
from src.core.database import get_db_connection
from src.utils.datetime_helpers import format_utc_iso, utc_now_iso
from src.utils.logging_config import get_logger

# Configure structured logging
logger = get_logger(__name__)

# Hardcoded default global admin user IDs (can be extended via env)
# Stefano (primary admin): 1571540653
DEFAULT_ADMIN_USER_IDS: set[int] = {1571540653}
ADMIN_CONFIRMATION_TTL_SECONDS = 300  # 5 minutes
PENDING_CONFIRMATION_TTL_SECONDS = 60 * 60  # 60 minutes
MAX_MANUAL_AMOUNT = Decimal("1000000")
CURRENCY_SYMBOL_MAP = {
    "\u20ac": "EUR",
    "$": "USD",
    "\u00a3": "GBP",
}
CONFIRM_KEYWORDS = {"yes", "ingest", "#bet", "confirm"}
DISCARD_KEYWORDS = {"no", "skip", "discard", "#skip"}


class TelegramBot:
    """Telegram Bot for screenshot ingestion."""

    def __init__(self):
        """Initialize the Telegram bot."""
        self.bot_token = Config.TELEGRAM_BOT_TOKEN
        if not self.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")

        # Rate limiting: Track last command time per user
        self._user_last_command: Dict[int, float] = defaultdict(float)
        self._rate_limit_seconds = 2  # Minimum seconds between commands

        # Global admin users (hardcoded defaults + env-configured)
        self.admin_user_ids: set[int] = set(DEFAULT_ADMIN_USER_IDS)
        if Config.TELEGRAM_ADMIN_USER_IDS:
            self.admin_user_ids.update(Config.TELEGRAM_ADMIN_USER_IDS)

        # Admin confirmation state
        self._pending_admin_confirmations: Dict[str, Dict[str, Any]] = {}

        self.application = Application.builder().token(self.bot_token).build()
        self._setup_handlers()
        self._schedule_jobs()
        self._setup_signal_handlers()

    @staticmethod
    async def _invoke(func: Callable[..., Any], *args, **kwargs):
        """Invoke a callable and await the result if it is awaitable."""
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            await result
        return result

    @staticmethod
    def _get_effective_message(update: Update):
        """Safely extract the effective message from an update."""
        primary = getattr(update, "message", None)
        if primary is not None and hasattr(primary, "reply_text"):
            return primary
        message = getattr(update, "effective_message", None)
        if message is not None and hasattr(message, "reply_text"):
            return message
        return primary or message

    def _setup_handlers(self) -> None:
        """Set up command and message handlers."""
        # Command handlers with rate limiting
        self.application.add_handler(
            CommandHandler("start", self._rate_limited(self._start_command))
        )
        self.application.add_handler(CommandHandler("help", self._rate_limited(self._help_command)))
        self.application.add_handler(
            CommandHandler("register", self._rate_limited(self._register_command))
        )
        self.application.add_handler(
            CommandHandler("chat_id", self._rate_limited(self._chat_id_command))
        )
        self.application.add_handler(
            CommandHandler(
                "list_associates", self._rate_limited(self._list_associates_command)
            )
        )
        self.application.add_handler(
            CommandHandler(
                "list_bookmakers", self._rate_limited(self._list_bookmakers_command)
            )
        )
        self.application.add_handler(
            CommandHandler("add_associate", self._rate_limited(self._add_associate_command))
        )
        self.application.add_handler(
            CommandHandler("add_bookmaker", self._rate_limited(self._add_bookmaker_command))
        )
        self.application.add_handler(
            CommandHandler("list_chats", self._rate_limited(self._list_chats_command))
        )
        self.application.add_handler(
            CommandHandler("unregister_chat", self._rate_limited(self._unregister_chat_command))
        )
        self.application.add_handler(
            CommandHandler("broadcast", self._rate_limited(self._broadcast_command))
        )
        self.application.add_handler(
            CommandHandler("version", self._rate_limited(self._version_command))
        )
        self.application.add_handler(
            CommandHandler("health", self._rate_limited(self._health_command))
        )
        self.application.add_handler(
            CommandHandler("confirm", self._rate_limited(self._confirm_command))
        )

        # Funding: slash commands and plain text commands
        self.application.add_handler(
            CommandHandler("deposit", self._rate_limited(self._deposit_command))
        )
        self.application.add_handler(
            CommandHandler("withdraw", self._rate_limited(self._withdraw_command))
        )
        self.application.add_handler(
            MessageHandler(filters.TEXT & (~filters.COMMAND), self._rate_limited(self._text_message))
        )

        # Photo message handler with rate limiting
        self.application.add_handler(
            MessageHandler(filters.PHOTO, self._rate_limited(self._photo_message))
        )

        # Callback handler for confirmation buttons
        self.application.add_handler(
            CallbackQueryHandler(
                self._rate_limited(self._pending_photo_callback),
                pattern=r"^(confirm|discard):",
            )
        )

    def _schedule_jobs(self) -> None:
        """Schedule recurring background jobs."""
        if not self.application.job_queue:
            return

        self.application.job_queue.run_repeating(
            self._expire_pending_photos_job,
            interval=300,
            first=300,
            name="pending-photo-cleanup",
        )

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        # Note: run_polling() handles SIGINT/SIGTERM automatically
        # Custom signal handlers removed to avoid event loop conflicts
        pass

    def _rate_limited(self, handler):
        """
        Decorator to apply rate limiting to handlers.

        Args:
            handler: The handler function to wrap

        Returns:
            Wrapped handler with rate limiting
        """

        async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            user = update.effective_user
            user_id = user.id if user else None

            if user_id is not None:
                current_time = time.time()
                delta = current_time - self._user_last_command[user_id]
                if delta < self._rate_limit_seconds:
                    remaining = self._rate_limit_seconds - delta
                    message = self._get_effective_message(update)
                    if message:
                        await self._invoke(message.reply_text, 
                            f"Rate limit exceeded. Please wait {remaining:.1f} seconds before trying again."
                        )
                    elif update.callback_query:
                        await update.callback_query.answer(
                            f"Rate limited. Wait {remaining:.1f}s.", show_alert=True
                        )
                    logger.warning(
                        "rate_limit_exceeded", user_id=user_id, remaining_seconds=remaining
                    )
                    return

                self._user_last_command[user_id] = current_time

            await handler(update, context)

        return wrapped

    def _is_admin_chat(self, chat_id: str) -> bool:
        if Config.TELEGRAM_ADMIN_CHAT_ID and chat_id == Config.TELEGRAM_ADMIN_CHAT_ID:
            return True

        registration = self._get_registration(chat_id)
        return bool(registration and registration.get("associate_is_admin"))

    async def _ensure_admin(self, update: Update) -> bool:
        chat = update.effective_chat
        user = update.effective_user
        chat_id = str(chat.id) if chat else None
        user_id = user.id if user else None

        # Allow if the user is a global admin (works in any chat)
        if user_id is not None and user_id in self.admin_user_ids:
            return True

        # Fallback: allow if the chat is an admin chat or registered to an admin associate
        if chat_id and self._is_admin_chat(chat_id):
            return True

        message = self._get_effective_message(update)
        if message:
            await self._invoke(message.reply_text, "This command is restricted to administrators.")

        logger.warning("admin_command_denied", chat_id=chat_id, user_id=user_id)
        return False

    def _fetch_associates(self) -> List[Dict]:
        try:
            conn = get_db_connection()
            rows = conn.execute(
                """
                SELECT display_alias, home_currency, is_admin
                FROM associates
                ORDER BY display_alias
                """
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error("fetch_associates_error", error=str(e))
            return []

    def _fetch_bookmakers_for_associate(self, associate_alias: str) -> List[Dict]:
        try:
            conn = get_db_connection()
            rows = conn.execute(
                """
                SELECT b.bookmaker_name
                FROM bookmakers b
                JOIN associates a ON b.associate_id = a.id
                WHERE a.display_alias = ?
                ORDER BY b.bookmaker_name
                """,
                (associate_alias,),
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(
                "fetch_bookmakers_for_associate_error",
                error=str(e),
                associate_alias=associate_alias,
            )
            return []

    def _fetch_all_bookmakers(self) -> List[Dict]:
        try:
            conn = get_db_connection()
            rows = conn.execute(
                """
                SELECT b.bookmaker_name, a.display_alias AS associate_alias
                FROM bookmakers b
                JOIN associates a ON b.associate_id = a.id
                ORDER BY a.display_alias, b.bookmaker_name
                """
            ).fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error("fetch_all_bookmakers_error", error=str(e))
            return []

    def _get_active_chat_ids(self) -> List[str]:
        try:
            conn = get_db_connection()
            rows = conn.execute(
                """
                SELECT chat_id
                FROM chat_registrations
                WHERE is_active = TRUE
                """
            ).fetchall()
            conn.close()
            return [row["chat_id"] for row in rows]
        except Exception as e:
            logger.error("fetch_active_chats_error", error=str(e))
            return []

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command."""
        try:
            await self._invoke(update.message.reply_text, "Surebet Bot Ready")
            print(f"📨 /start command from user {update.effective_user.id}")
            logger.info("start_command_handled", user_id=update.effective_user.id)
        except Exception as e:
            logger.error("start_command_error", error=str(e), user_id=update.effective_user.id)

    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command."""
        try:
            help_text = """
Available commands:
/start - Start the bot
/help - Show this help message
/register <associate_alias> <bookmaker_name> - Register this chat for a specific associate and bookmaker
/chat_id - Show the current chat ID

Funding commands:
deposit <amount>, withdraw <amount>
/deposit <amount>, /withdraw <amount>

You can also send screenshots directly to create bet records.

Admin commands:
/list_associates, /list_bookmakers, /add_associate, /add_bookmaker,
/list_chats, /unregister_chat, /broadcast, /version, /health
            """.strip()
            await self._invoke(update.message.reply_text, help_text)
            logger.info("help_command_handled", user_id=update.effective_user.id)
        except Exception as e:
            logger.error("help_command_error", error=str(e), user_id=update.effective_user.id)

    async def _chat_id_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /chat_id command."""
        chat_id: Optional[int] = None
        user_id: Optional[int] = None
        try:
            if update.effective_user:
                user_id = update.effective_user.id
            chat = update.effective_chat
            message = self._get_effective_message(update)
            if chat:
                chat_id = chat.id

            if not message:
                logger.warning("chat_id_command_missing_message", user_id=user_id, chat_id=chat_id)
                return

            if chat_id is None:
                await self._invoke(message.reply_text, "Unable to determine chat ID.")
                logger.warning("chat_id_command_no_chat", user_id=user_id)
                return

            await self._invoke(message.reply_text, f"Current chat ID: {chat_id}")
            logger.info("chat_id_command_handled", user_id=user_id, chat_id=chat_id)
        except Exception as e:
            logger.error("chat_id_command_error", error=str(e), user_id=user_id, chat_id=chat_id)

    async def _register_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /register command."""
        try:
            chat_id = str(update.effective_chat.id)
            user_id = update.effective_user.id

            # Parse command arguments
            args = context.args
            if len(args) != 2:
                await self._invoke(update.message.reply_text, 
                    "Usage: /register <associate_alias> <bookmaker_name>\n"
                    "Example: /register Alice Bet365"
                )
                logger.warning(
                    "register_command_invalid_args",
                    user_id=user_id,
                    args_count=len(args),
                )
                return

            associate_alias, bookmaker_name = args

            # Validate associate and bookmaker exist
            if not self._validate_associate_and_bookmaker(associate_alias, bookmaker_name):
                await self._invoke(update.message.reply_text, 
                    f"Invalid associate '{associate_alias}' or bookmaker '{bookmaker_name}'. "
                    "Please check the names and try again."
                )
                logger.warning(
                    "register_command_invalid_entities",
                    user_id=user_id,
                    associate_alias=associate_alias,
                    bookmaker_name=bookmaker_name,
                )
                return

            # Store registration in database
            if self._store_registration(chat_id, associate_alias, bookmaker_name):
                await self._invoke(update.message.reply_text, 
                    f"Chat {chat_id} successfully registered for {associate_alias} at {bookmaker_name}"
                )
                print(f"✅ Chat {chat_id} registered: {associate_alias} @ {bookmaker_name}")
            else:
                await self._invoke(update.message.reply_text, 
                    "Failed to store registration. Please try again later."
                )

            logger.info(
                "register_command_handled",
                user_id=user_id,
                chat_id=chat_id,
                associate_alias=associate_alias,
                bookmaker_name=bookmaker_name,
            )

        except Exception as e:
            logger.error("register_command_error", error=str(e), user_id=update.effective_user.id)
            try:
                await self._invoke(update.message.reply_text, "An error occurred during registration.")
            except Exception as reply_error:
                logger.error(
                    "register_command_reply_error",
                    error=str(reply_error),
                    user_id=update.effective_user.id,
                )

    async def _list_associates_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._ensure_admin(update):
            return

        associates = self._fetch_associates()
        message = self._get_effective_message(update)
        if not associates:
            if message:
                await self._invoke(message.reply_text, "No associates configured yet.")
            return

        lines = ["Associates:"]
        for associate in associates:
            role = "admin" if associate.get("is_admin") else "member"
            lines.append(
                f"• {associate['display_alias']} ({associate['home_currency']}) - {role}"
            )

        if message:
            await self._invoke(message.reply_text, "\n".join(lines))

    async def _list_bookmakers_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._ensure_admin(update):
            return

        message = self._get_effective_message(update)
        alias_filter = " ".join(context.args) if context.args else None

        if alias_filter:
            bookmakers = self._fetch_bookmakers_for_associate(alias_filter)
            if not bookmakers:
                if message:
                    await self._invoke(message.reply_text, 
                        f"No bookmakers found for associate '{alias_filter}'."
                    )
                return
            lines = [f"Bookmakers for {alias_filter}:"]
            for bookmaker in bookmakers:
                lines.append(f"• {alias_filter} -> {bookmaker['bookmaker_name']}")
        else:
            bookmakers = self._fetch_all_bookmakers()
            if not bookmakers:
                if message:
                    await self._invoke(message.reply_text, "No bookmakers configured yet.")
                return
            lines = ["Bookmakers:"]
            for bookmaker in bookmakers:
                lines.append(
                    f"• {bookmaker['associate_alias']} -> {bookmaker['bookmaker_name']}"
                )

        if message:
            await self._invoke(message.reply_text, "\n".join(lines))

    async def _add_associate_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._ensure_admin(update):
            return

        message = self._get_effective_message(update)
        args = context.args
        if not args:
            if message:
                await self._invoke(message.reply_text, "Usage: /add_associate <alias> [currency]")
            return

        alias = args[0]
        currency = args[1].upper() if len(args) > 1 else "EUR"

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            now = utc_now_iso()

            existing = cursor.execute(
                "SELECT id, is_admin FROM associates WHERE display_alias = ?", (alias,)
            ).fetchone()

            if existing:
                cursor.execute(
                    """
                    UPDATE associates
                    SET home_currency = ?, updated_at_utc = ?
                    WHERE id = ?
                    """,
                    (currency, now, existing["id"]),
                )
                action = "updated"
            else:
                cursor.execute(
                    """
                    INSERT INTO associates (
                        display_alias,
                        home_currency,
                        is_admin,
                        created_at_utc,
                        updated_at_utc
                    ) VALUES (?, ?, FALSE, ?, ?)
                    """,
                    (alias, currency, now, now),
                )
                action = "created"

            conn.commit()
            conn.close()

            if message:
                await self._invoke(message.reply_text, 
                    f"Associate '{alias}' {action} with currency {currency}."
                )
            logger.info("associate_saved", alias=alias, currency=currency, action=action)

        except Exception as e:
            logger.error("add_associate_error", alias=alias, error=str(e), exc_info=True)
            if message:
                await self._invoke(message.reply_text, "Failed to save associate. See logs for details.")

    async def _add_bookmaker_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._ensure_admin(update):
            return

        message = self._get_effective_message(update)
        args = context.args
        if len(args) < 2:
            if message:
                await self._invoke(message.reply_text, 
                    "Usage: /add_bookmaker <associate_alias> <bookmaker_name>"
                )
            return

        associate_alias = args[0]
        bookmaker_name = " ".join(args[1:])

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            now = utc_now_iso()

            cursor.execute(
                "SELECT id FROM associates WHERE display_alias = ?",
                (associate_alias,),
            )
            associate = cursor.fetchone()
            if not associate:
                conn.close()
                if message:
                    await self._invoke(message.reply_text, 
                        f"Associate '{associate_alias}' not found."
                    )
                return

            cursor.execute(
                """
                INSERT INTO bookmakers (
                    associate_id,
                    bookmaker_name,
                    created_at_utc,
                    updated_at_utc
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(associate_id, bookmaker_name) DO UPDATE SET
                    updated_at_utc = excluded.updated_at_utc
                """,
                (associate["id"], bookmaker_name, now, now),
            )

            conn.commit()
            conn.close()

            if message:
                await self._invoke(message.reply_text, 
                    f"Bookmaker '{bookmaker_name}' saved for {associate_alias}."
                )
            logger.info(
                "bookmaker_saved", associate_alias=associate_alias, bookmaker_name=bookmaker_name
            )

        except Exception as e:
            logger.error(
                "add_bookmaker_error",
                associate_alias=associate_alias,
                bookmaker_name=bookmaker_name,
                error=str(e),
                exc_info=True,
            )
            if message:
                await self._invoke(message.reply_text, "Failed to save bookmaker. See logs for details.")

    async def _list_chats_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._ensure_admin(update):
            return

        message = self._get_effective_message(update)
        try:
            conn = get_db_connection()
            rows = conn.execute(
                """
                SELECT
                    cr.chat_id,
                    cr.is_active,
                    a.display_alias AS associate_alias,
                    b.bookmaker_name,
                    cr.updated_at_utc
                FROM chat_registrations cr
                JOIN associates a ON cr.associate_id = a.id
                JOIN bookmakers b ON cr.bookmaker_id = b.id
                ORDER BY cr.is_active DESC, a.display_alias, b.bookmaker_name
                """
            ).fetchall()
            conn.close()
        except Exception as e:
            logger.error("list_chats_error", error=str(e), exc_info=True)
            if message:
                await self._invoke(message.reply_text, "Failed to load chat registrations.")
            return

        if not rows:
            if message:
                await self._invoke(message.reply_text, "No chat registrations found.")
            return

        lines = ["Chat registrations:"]
        for row in rows:
            status = "active" if row["is_active"] else "inactive"
            lines.append(
                f"• {row['chat_id']} -> {row['associate_alias']} / {row['bookmaker_name']} ({status})"
            )

        if message:
            await self._invoke(message.reply_text, "\n".join(lines))

    async def _unregister_chat_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._ensure_admin(update):
            return

        message = self._get_effective_message(update)
        target_chat = context.args[0] if context.args else str(update.effective_chat.id)

        if self._deactivate_registration(target_chat):
            if message:
                await self._invoke(message.reply_text, f"Chat {target_chat} unregistered.")
            logger.info("chat_unregistered", chat_id=target_chat)
        else:
            if message:
                await self._invoke(message.reply_text, 
                    f"No active registration found for chat {target_chat}."
                )

    async def _broadcast_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._ensure_admin(update):
            return

        message = self._get_effective_message(update)
        if not context.args:
            if message:
                await self._invoke(message.reply_text, "Usage: /broadcast <message>")
            return

        text = " ".join(context.args)
        chat_ids = self._get_active_chat_ids()
        if not chat_ids:
            if message:
                await self._invoke(message.reply_text, "No active chats to broadcast to.")
            return

        sent = 0
        failures: List[Tuple[str, str]] = []

        for chat_id in chat_ids:
            try:
                try:
                    target_chat: int | str = int(chat_id)
                except ValueError:
                    target_chat = chat_id

                await self._invoke(context.bot.send_message, chat_id=target_chat, text=text)
                sent += 1
            except Exception as e:
                failures.append((chat_id, str(e)))
                logger.error("broadcast_error", chat_id=chat_id, error=str(e), exc_info=True)

        summary = [f"Broadcast sent to {sent} chat(s)."]
        if failures:
            summary.append(f"Failed: {len(failures)}")

        if message:
            await self._invoke(message.reply_text, "\n".join(summary))

    async def _version_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._ensure_admin(update):
            return

        message = self._get_effective_message(update)
        info_lines = [
            "Surebet Telegram Bot",
            f"• python-telegram-bot: {telegram_version}",
            f"• Python: {platform.python_version()}",
            f"• Platform: {platform.platform()}",
            f"• Screenshot dir: {Config.SCREENSHOT_DIR}",
            f"• Database: {Config.DB_PATH}",
        ]

        if message:
            await self._invoke(message.reply_text, "\n".join(info_lines))

    async def _health_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not await self._ensure_admin(update):
            return

        message = self._get_effective_message(update)
        issues: List[str] = []

        screenshot_dir = Path(Config.SCREENSHOT_DIR)
        if not screenshot_dir.exists():
            issues.append(f"Screenshot dir missing: {screenshot_dir}")

        try:
            conn = get_db_connection()
            conn.execute("SELECT 1")
            conn.close()
        except Exception as e:
            issues.append(f"Database error: {e}")

        if not Config.TELEGRAM_BOT_TOKEN:
            issues.append("TELEGRAM_BOT_TOKEN missing from configuration")

        if issues:
            if message:
                await self._invoke(message.reply_text, "\n".join(["Health check issues:"] + issues))
        else:
            if message:
                await self._invoke(message.reply_text, "All systems nominal.")


    def _validate_associate_and_bookmaker(self, associate_alias: str, bookmaker_name: str) -> bool:
        """
        Validate that associate and bookmaker exist in the database.

        Args:
            associate_alias: The associate's display alias
            bookmaker_name: The bookmaker name

        Returns:
            True if both exist, False otherwise
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Check if associate exists
            cursor.execute("SELECT id FROM associates WHERE display_alias = ?", (associate_alias,))
            associate = cursor.fetchone()

            if not associate:
                conn.close()
                return False

            # Check if bookmaker exists for this associate
            cursor.execute(
                """
                SELECT b.id FROM bookmakers b
                JOIN associates a ON b.associate_id = a.id
                WHERE a.display_alias = ? AND b.bookmaker_name = ?
                """,
                (associate_alias, bookmaker_name),
            )
            bookmaker = cursor.fetchone()

            conn.close()
            return bookmaker is not None

        except Exception as e:
            logger.error(
                "validate_associate_bookmaker_error",
                error=str(e),
                associate_alias=associate_alias,
                bookmaker_name=bookmaker_name,
            )
            return False

    def _store_registration(self, chat_id: str, associate_alias: str, bookmaker_name: str) -> bool:
        """
        Store chat registration in database.

        Args:
            chat_id: Telegram chat ID
            associate_alias: Associate's display alias
            bookmaker_name: Bookmaker name

        Returns:
            True if registration was stored successfully, False otherwise
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Get associate and bookmaker IDs
            cursor.execute("SELECT id FROM associates WHERE display_alias = ?", (associate_alias,))
            associate = cursor.fetchone()

            if not associate:
                conn.close()
                return False

            cursor.execute(
                """
                SELECT b.id FROM bookmakers b
                JOIN associates a ON b.associate_id = a.id
                WHERE a.display_alias = ? AND b.bookmaker_name = ?
                """,
                (associate_alias, bookmaker_name),
            )
            bookmaker = cursor.fetchone()

            if not bookmaker:
                conn.close()
                return False

            now = utc_now_iso()

            # Insert or update registration, always reactivating the chat
            cursor.execute(
                """
                INSERT INTO chat_registrations (
                    chat_id,
                    associate_id,
                    bookmaker_id,
                    is_active,
                    created_at_utc,
                    updated_at_utc
                ) VALUES (?, ?, ?, TRUE, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    associate_id = excluded.associate_id,
                    bookmaker_id = excluded.bookmaker_id,
                    is_active = TRUE,
                    updated_at_utc = excluded.updated_at_utc
                """,
                (chat_id, associate["id"], bookmaker["id"], now, now),
            )

            conn.commit()
            conn.close()

            logger.info(
                "registration_stored",
                chat_id=chat_id,
                associate_alias=associate_alias,
                bookmaker_name=bookmaker_name,
            )

            return True

        except Exception as e:
            logger.error(
                "store_registration_error",
                error=str(e),
                chat_id=chat_id,
                associate_alias=associate_alias,
                bookmaker_name=bookmaker_name,
            )
            return False

    def _get_registration(self, chat_id: str) -> Optional[Dict]:
        """
        Get registration details for a chat ID.

        Args:
            chat_id: Telegram chat ID

        Returns:
            Dictionary with associate_id, bookmaker_id, associate_alias, and bookmaker_name if found, None otherwise
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    cr.associate_id,
                    cr.bookmaker_id,
                    a.display_alias as associate_alias,
                    b.bookmaker_name,
                    a.home_currency as home_currency,
                    a.is_admin as associate_is_admin
                FROM chat_registrations cr
                JOIN associates a ON cr.associate_id = a.id
                JOIN bookmakers b ON cr.bookmaker_id = b.id
                WHERE cr.chat_id = ? AND cr.is_active = TRUE
                """,
                (chat_id,),
            )
            result = cursor.fetchone()

            conn.close()

            if result:
                row = dict(result)
                return {
                    "associate_id": row["associate_id"],
                    "bookmaker_id": row["bookmaker_id"],
                    "associate_alias": row["associate_alias"],
                    "bookmaker_name": row["bookmaker_name"],
                    "home_currency": row.get("home_currency"),
                    "associate_is_admin": bool(row.get("associate_is_admin", False)),
                }
            return None

        except Exception as e:
            logger.error("get_registration_error", error=str(e), chat_id=chat_id)
            return None

    def _deactivate_registration(self, chat_id: str) -> bool:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE chat_registrations
                SET is_active = FALSE, updated_at_utc = ?
                WHERE chat_id = ? AND is_active = TRUE
                """,
                (utc_now_iso(), chat_id),
            )
            conn.commit()
            conn.close()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error("deactivate_registration_error", chat_id=chat_id, error=str(e))
            return False

    # ---------------------------------------------------------------------
    # Funding: Slash and Text command handlers and helpers
    # ---------------------------------------------------------------------
    async def _deposit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /deposit <amount> as a funding command."""
        message = self._get_effective_message(update)
        args = context.args or []
        if len(args) != 1:
            if message:
                await self._invoke(message.reply_text, "Usage: /deposit <amount>")
            return
        try:
            amount = Decimal(args[0])
            if amount <= 0:
                raise ValueError("Amount must be positive")
            await self._execute_funding_flow(
                command_type="DEPOSIT",
                amount_decimal=amount,
                chat_id=str(update.effective_chat.id),
                user_id=update.effective_user.id if update.effective_user else None,
                message=message,
            )
        except Exception:
            if message:
                await self._invoke(message.reply_text, "Invalid amount. Usage: /deposit <amount>")

    async def _withdraw_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /withdraw <amount> as a funding command."""
        message = self._get_effective_message(update)
        args = context.args or []
        if len(args) != 1:
            if message:
                await self._invoke(message.reply_text, "Usage: /withdraw <amount>")
            return
        try:
            amount = Decimal(args[0])
            if amount <= 0:
                raise ValueError("Amount must be positive")
            await self._execute_funding_flow(
                command_type="WITHDRAWAL",
                amount_decimal=amount,
                chat_id=str(update.effective_chat.id),
                user_id=update.effective_user.id if update.effective_user else None,
                message=message,
            )
        except Exception:
            if message:
                await self._invoke(message.reply_text, "Invalid amount. Usage: /withdraw <amount>")

    async def _confirm_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /confirm <code> for admin approval two-factor."""
        message = self._get_effective_message(update)
        args = context.args or []
        if len(args) != 1:
            if message:
                await self._invoke(message.reply_text, "Usage: /confirm <code>")
            return

        chat_id = str(update.effective_chat.id) if update.effective_chat else None
        if not chat_id:
            if message:
                await self._invoke(message.reply_text, "Unable to confirm outside of a chat context.")
            return

        await self._process_admin_confirmation(
            token=args[0],
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else None,
            message=message,
        )

    async def _maybe_handle_pending_text(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
    ) -> bool:
        """Intercept confirmation/discard commands that reference pending screenshots."""
        parsed = None
        try:
            parsed = self._parse_pending_confirmation_text(text)
        except ValueError as exc:
            message = self._get_effective_message(update)
            if message:
                await self._invoke(message.reply_text, str(exc))
            return True

        if not parsed:
            return False

        message = self._get_effective_message(update)
        reply_message = message.reply_to_message if message else None
        chat = update.effective_chat
        chat_id = str(chat.id) if chat else None

        if not chat_id:
            return False

        if parsed["action"] in ("confirm", "discard") and not reply_message:
            if message:
                await self._invoke(
                    message.reply_text,
                    "Please reply to the screenshot confirmation message so I know which photo to use.",
                )
            return True

        if not reply_message:
            return False

        pending = self._get_pending_photo_by_reference(chat_id, reply_message.message_id)
        if not pending:
            if message:
                await self._invoke(
                    message.reply_text,
                    "I could not match that reply to a pending screenshot. Please reply directly to the bot's prompt.",
                )
            return True

        overrides = {
            "stake_amount": parsed.get("stake_amount"),
            "stake_currency": parsed.get("stake_currency"),
            "win_amount": parsed.get("win_amount"),
            "win_currency": parsed.get("win_currency"),
        }

        if parsed["action"] == "confirm":
            await self._handle_pending_confirmation(
                pending=pending,
                overrides=overrides,
                reply_message=message,
                chat_id=chat_id,
                context=context,
            )
        elif parsed["action"] == "discard":
            await self._handle_pending_discard(
                pending=pending,
                reply_message=message,
                chat_id=chat_id,
            )
        else:
            await self._handle_manual_override_update(
                pending=pending,
                overrides=overrides,
                reply_message=message,
            )

        return True

    def _parse_pending_confirmation_text(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse confirmation/discard commands and optional stake/win overrides."""
        cleaned = (text or "").strip()
        if not cleaned:
            return None

        tokens = cleaned.split()
        if not tokens:
            return None

        first_token = tokens[0].lower()
        win_match = re.search(r"win\s*=\s*([^\s]+)", cleaned, re.IGNORECASE)
        win_token = win_match.group(1) if win_match else None

        action = None
        stake_token = None

        if first_token in CONFIRM_KEYWORDS:
            action = "confirm"
            stake_token = next((t for t in tokens[1:] if not t.lower().startswith("win=")), None)
        elif first_token in DISCARD_KEYWORDS:
            action = "discard"
        else:
            if win_token or self._looks_like_amount_token(tokens[0]):
                action = "amount_only"
                stake_token = tokens[0] if not tokens[0].lower().startswith("win=") else None
            else:
                return None

        stake_amount = stake_currency = None
        win_amount = win_currency = None

        if stake_token:
            stake_amount, stake_currency = self._parse_amount_token(stake_token)
        if win_token:
            win_amount, win_currency = self._parse_amount_token(win_token)

        return {
            "action": action,
            "stake_amount": stake_amount,
            "stake_currency": stake_currency,
            "win_amount": win_amount,
            "win_currency": win_currency,
        }

    def _parse_amount_token(self, token: str) -> Tuple[Decimal, Optional[str]]:
        """Convert a raw token like '€25.5' or '25usd' into Decimal + currency."""
        cleaned = token.strip()
        if not cleaned:
            raise ValueError("Amount token was empty.")

        currency = None
        if cleaned[0] in CURRENCY_SYMBOL_MAP:
            currency = CURRENCY_SYMBOL_MAP[cleaned[0]]
            cleaned = cleaned[1:]
        if cleaned and cleaned[-1] in CURRENCY_SYMBOL_MAP:
            currency = currency or CURRENCY_SYMBOL_MAP[cleaned[-1]]
            cleaned = cleaned[:-1]

        match = re.match(r"([0-9]+(?:[.,][0-9]+)?)", cleaned)
        if not match:
            raise ValueError("Invalid amount format. Use numbers like 25 or €25.50.")
        number = match.group(1).replace(",", ".")
        rest = cleaned[match.end():].strip()
        if rest:
            if rest.isalpha():
                currency = currency or rest.upper()
            else:
                raise ValueError("Invalid currency suffix. Use symbols or 3-letter codes.")

        try:
            value = Decimal(number)
        except InvalidOperation as exc:
            raise ValueError("Could not parse the amount you provided.") from exc

        self._validate_amount_range(value)
        return value, currency

    @staticmethod
    def _looks_like_amount_token(token: str) -> bool:
        """Heuristic to detect stake/win tokens in messages."""
        if not token:
            return False
        token = token.strip()
        if not token:
            return False
        if token[0] in CURRENCY_SYMBOL_MAP or token[-1] in CURRENCY_SYMBOL_MAP:
            return True
        return any(ch.isdigit() for ch in token)

    @staticmethod
    def _decimal_to_str(value: Optional[Decimal]) -> Optional[str]:
        """Format manual overrides consistently."""
        if value is None:
            return None
        return f"{value.quantize(Decimal('0.01'))}"

    def _validate_amount_range(self, amount: Decimal) -> None:
        """Ensure manual overrides stay within reasonable bounds."""
        if amount <= 0:
            raise ValueError("Amounts must be positive.")
        if amount > MAX_MANUAL_AMOUNT:
            raise ValueError(f"Amounts cannot exceed {MAX_MANUAL_AMOUNT}.")

    async def _text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle plain text messages for funding commands.

        Supported commands (case-insensitive):
        - deposit <amount>
        - withdraw <amount>
        """
        chat_id = str(update.effective_chat.id)
        user_id = update.effective_user.id if update.effective_user else None
        text = (update.message.text or "").strip() if update.message else ""
        message = self._get_effective_message(update)

        try:
            if await self._maybe_handle_pending_text(update, context, text):
                return

            token = self._parse_admin_confirmation(text)
            if token:
                await self._process_admin_confirmation(token, chat_id, user_id, message)
                return

            parsed = self._parse_funding_command(text)
            if not parsed:
                return

            command_type, amount = parsed  # 'DEPOSIT' | 'WITHDRAWAL', float
            await self._execute_funding_flow(
                command_type=command_type,
                amount_decimal=Decimal(str(amount)),
                chat_id=chat_id,
                user_id=user_id,
                message=message,
            )

        except ValueError:
            if message:
                await self._invoke(
                    message.reply_text,
                    "Invalid amount. Usage: 'deposit <amount>' or 'withdraw <amount>'",
                )
        except Exception as e:
            if message:
                try:
                    await self._invoke(
                        message.reply_text,
                        "An error occurred while processing your request.",
                    )
                except Exception:
                    pass
            logger.error(
                "funding_text_error",
                chat_id=chat_id,
                user_id=user_id,
                text=text,
                error=str(e),
                exc_info=True,
            )

    @staticmethod
    def _parse_funding_command(text: str) -> Optional[tuple[str, float]]:
        """Parse a funding command from text.

        Returns (command_type, amount) where command_type is 'DEPOSIT' or 'WITHDRAWAL'.
        Returns None if not matched. Raises ValueError for invalid amount.
        """

        m = re.match(r"^\s*(deposit|withdraw)\s+(-?[0-9]+(?:\.[0-9]+)?)\s*$", text, re.IGNORECASE)
        if not m:
            return None
        cmd = m.group(1).strip().lower()
        amount_str = m.group(2)
        amount = float(amount_str)
        if amount <= 0:
            raise ValueError("Amount must be positive")
        return ("DEPOSIT" if cmd == "deposit" else "WITHDRAWAL", amount)

    @staticmethod
    def _parse_admin_confirmation(text: str) -> Optional[str]:
        """Parse admin confirmation text into a 6-digit token."""
        if not text:
            return None
        match = re.fullmatch(r"(?:confirm|approve)\s+(\d{6})", text.strip(), re.IGNORECASE)
        if not match:
            return None
        return match.group(1)

    def _get_associate_home_currency(self, associate_id: int) -> Optional[str]:
        """Fetch associate home_currency from DB."""
        try:
            conn = get_db_connection()
            row = conn.execute(
                "SELECT home_currency FROM associates WHERE id = ?",
                (associate_id,),
            ).fetchone()
            conn.close()
            return row["home_currency"] if row and ("home_currency" in row.keys()) else None
        except Exception as e:
            logger.error(
                "fetch_associate_home_currency_error",
                associate_id=associate_id,
                error=str(e),
            )
            return None

    async def _execute_funding_flow(
        self,
        command_type: str,
        amount_decimal,
        chat_id: str,
        user_id: Optional[int],
        message,
    ) -> None:
        """Shared funding flow used by text and slash commands."""
        # Registration required
        registration = self._get_registration(chat_id)
        if not registration:
            if message:
                await self._invoke(
                    message.reply_text,
                    "This chat is not registered. Please use /register <associate_alias> <bookmaker_name> first.",
                )
            logger.warning(
                "funding_text_unregistered_chat",
                chat_id=chat_id,
                user_id=user_id,
                command_type=command_type,
                amount=str(amount_decimal),
            )
            return

        associate_id = int(registration["associate_id"])
        bookmaker_id = int(registration["bookmaker_id"])
        bookmaker_name = registration.get("bookmaker_name") or ""
        currency = self._get_associate_home_currency(associate_id) or "EUR"
        note = f"telegram:{chat_id}"

        # Approval path
        is_admin_user = user_id in self.admin_user_ids if user_id is not None else False
        is_admin_chat = bool(registration.get("associate_is_admin", False))
        approval_path = "admin" if (is_admin_user or is_admin_chat) else "associate"

        if approval_path == "admin":
            await self._require_admin_confirmation(
                registration=registration,
                command_type=command_type,
                amount_decimal=amount_decimal,
                currency=currency,
                chat_id=chat_id,
                user_id=user_id,
                message=message,
                note=note,
            )
            return

        # Draft approval path
        from src.services.funding_service import FundingError, FundingService

        svc = FundingService()
        try:
            draft_id = svc.create_funding_draft(
                associate_id=associate_id,
                bookmaker_id=bookmaker_id,
                event_type=command_type,
                amount_native=amount_decimal,
                currency=currency,
                note=note,
                associate_alias=registration.get("associate_alias"),
                bookmaker_name=registration.get("bookmaker_name"),
                source="telegram",
                chat_id=chat_id,
            )
        except FundingError as exc:
            if message:
                await self._invoke(
                    message.reply_text,
                    f"Unable to submit for approval: {exc}",
                )
            logger.error(
                "funding_draft_creation_failed",
                chat_id=chat_id,
                user_id=user_id,
                associate_id=associate_id,
                bookmaker_id=bookmaker_id,
                type=command_type,
                amount=str(amount_decimal),
                currency=currency,
                approval_path=approval_path,
                error=str(exc),
            )
            return
        finally:
            svc.close()

        if message:
            await self._invoke(
                message.reply_text,
                f"Submitted for approval: {command_type} {amount_decimal} {currency}.",
            )

        logger.info(
            "funding_text_submitted",
            chat_id=chat_id,
            user_id=user_id,
            associate_id=associate_id,
            bookmaker_id=bookmaker_id,
            type=command_type,
            amount=str(amount_decimal),
            currency=currency,
            approval_path=approval_path,
            draft_id=draft_id,
        )

    def _generate_admin_token(self) -> str:
        """Generate a 6-digit confirmation token."""
        return f"{secrets.randbelow(1_000_000):06d}"

    def _cleanup_expired_confirmations(self) -> None:
        """Remove expired admin confirmation tokens."""
        now = time.time()
        expired_tokens = [
            token
            for token, ctx in self._pending_admin_confirmations.items()
            if ctx.get("expires_at", 0) <= now
        ]
        for token in expired_tokens:
            self._pending_admin_confirmations.pop(token, None)

    async def _require_admin_confirmation(
        self,
        *,
        registration: Dict[str, Any],
        command_type: str,
        amount_decimal: Decimal,
        currency: str,
        chat_id: str,
        user_id: Optional[int],
        message,
        note: str,
    ) -> None:
        """Store admin confirmation request and send OTP instructions."""
        self._cleanup_expired_confirmations()
        token = self._generate_admin_token()
        context = {
            "token": token,
            "chat_id": chat_id,
            "user_id": user_id,
            "associate_id": int(registration["associate_id"]),
            "associate_alias": registration.get("associate_alias"),
            "bookmaker_id": int(registration["bookmaker_id"]),
            "bookmaker_name": registration.get("bookmaker_name") or "",
            "command_type": command_type,
            "amount": amount_decimal,
            "currency": currency,
            "note": note,
            "created_at": utc_now_iso(),
            "expires_at": time.time() + ADMIN_CONFIRMATION_TTL_SECONDS,
        }
        self._pending_admin_confirmations[token] = context

        if message:
            bookmaker_segment = f"{context['bookmaker_name']} " if context["bookmaker_name"] else ""
            minutes = max(1, ADMIN_CONFIRMATION_TTL_SECONDS // 60)
            await self._invoke(
                message.reply_text,
                (
                    f"Security check: confirm code {token} to finalize {command_type} "
                    f"{amount_decimal} {currency} {bookmaker_segment}recorded. "
                    f"Reply with \"confirm {token}\" within {minutes} minute(s)."
                ),
            )

        logger.info(
            "funding_admin_confirmation_required",
            chat_id=chat_id,
            user_id=user_id,
            associate_id=context["associate_id"],
            bookmaker_id=context["bookmaker_id"],
            type=command_type,
            amount=str(amount_decimal),
            currency=currency,
            token=token,
        )

    async def _process_admin_confirmation(
        self,
        token: str,
        chat_id: str,
        user_id: Optional[int],
        message,
    ) -> None:
        """Process OTP confirmation from admin users."""
        cleaned_token = token.strip()
        if not cleaned_token:
            if message:
                await self._invoke(message.reply_text, "Confirmation code missing. Usage: confirm <code>")
            return

        self._cleanup_expired_confirmations()
        context = self._pending_admin_confirmations.get(cleaned_token)
        if not context:
            if message:
                await self._invoke(message.reply_text, "Confirmation code is invalid or expired. Please resend the command.")
            logger.warning(
                "funding_admin_confirmation_invalid",
                chat_id=chat_id,
                user_id=user_id,
                token=cleaned_token,
                reason="missing",
            )
            return

        if context["chat_id"] != chat_id:
            if message:
                await self._invoke(message.reply_text, "This confirmation code belongs to a different chat.")
            logger.warning(
                "funding_admin_confirmation_invalid",
                chat_id=chat_id,
                expected_chat=context["chat_id"],
                token=cleaned_token,
                reason="chat_mismatch",
            )
            return

        original_user = context.get("user_id")
        if original_user is not None and original_user != user_id:
            if message:
                await self._invoke(message.reply_text, "Only the admin who submitted the command can confirm this code.")
            logger.warning(
                "funding_admin_confirmation_invalid",
                chat_id=chat_id,
                user_id=user_id,
                token=cleaned_token,
                reason="user_mismatch",
            )
            return

        ledger_id = await self._record_admin_transaction(context, message)
        if ledger_id:
            self._pending_admin_confirmations.pop(cleaned_token, None)
            logger.info(
                "funding_admin_confirmation_completed",
                chat_id=chat_id,
                user_id=user_id,
                token=cleaned_token,
                ledger_id=ledger_id,
            )

    async def _record_admin_transaction(self, context: Dict[str, Any], message) -> Optional[str]:
        """Record admin transaction and send responses with error handling."""
        from src.services.funding_transaction_service import (
            FundingTransaction,
            FundingTransactionError,
            FundingTransactionService,
        )

        try:
            with FundingTransactionService() as svc:
                ledger_id = svc.record_transaction(
                    FundingTransaction(
                        associate_id=context["associate_id"],
                        bookmaker_id=context["bookmaker_id"],
                        transaction_type=context["command_type"],
                        amount_native=context["amount"],
                        native_currency=context["currency"],
                        note=context["note"],
                        created_by="telegram_bot",
                    )
                )
        except FundingTransactionError as exc:
            if message:
                await self._invoke(
                    message.reply_text,
                    f"Approval failed: {exc}. Please try again once the issue is resolved.",
                )
            logger.warning(
                "funding_admin_confirmation_failed",
                associate_id=context["associate_id"],
                bookmaker_id=context["bookmaker_id"],
                type=context["command_type"],
                amount=str(context["amount"]),
                currency=context["currency"],
                reason=str(exc),
            )
            return None
        except Exception as exc:  # pragma: no cover - defensive path
            if message:
                await self._invoke(
                    message.reply_text,
                    "Unexpected error while recording the transaction. Please retry.",
                )
            logger.error(
                "funding_admin_confirmation_error",
                associate_id=context["associate_id"],
                bookmaker_id=context["bookmaker_id"],
                type=context["command_type"],
                amount=str(context["amount"]),
                currency=context["currency"],
                error=str(exc),
                exc_info=True,
            )
            return None

        bookmaker_segment = f"{context['bookmaker_name']} " if context["bookmaker_name"] else ""
        if message:
            await self._invoke(
                message.reply_text,
                f"Approved: {context['command_type']} {context['amount']} {context['currency']} {bookmaker_segment}recorded",
            )

        logger.info(
            "funding_text_recorded",
            chat_id=context["chat_id"],
            user_id=context["user_id"],
            associate_id=context["associate_id"],
            bookmaker_id=context["bookmaker_id"],
            type=context["command_type"],
            amount=str(context["amount"]),
            currency=context["currency"],
            approval_path="admin",
            ledger_id=ledger_id,
        )
        return str(ledger_id)

    async def _photo_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming screenshot messages by queuing them for confirmation."""
        message = update.message
        if not message or not update.effective_chat:
            return

        try:
            chat_id = str(update.effective_chat.id)
            message_id = message.message_id
            user_id = update.effective_user.id if update.effective_user else None

            registration = self._get_registration(chat_id)
            if not registration:
                await self._invoke(
                    message.reply_text,
                    "This chat is not registered. Please use /register <associate_alias> <bookmaker_name> first.",
                )
                logger.warning(
                    "photo_message_unregistered_chat",
                    user_id=user_id,
                    chat_id=chat_id,
                    message_id=message_id,
                )
                return

            photo = message.photo[-1]
            photo_file = await photo.get_file()

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            associate_alias = registration["associate_alias"]
            bookmaker_name = registration["bookmaker_name"]
            filename = f"{timestamp}_{associate_alias}_{bookmaker_name}.png"

            screenshot_dir = Path(Config.SCREENSHOT_DIR)
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            screenshot_path = screenshot_dir / filename
            counter = 1
            while screenshot_path.exists():
                filename = f"{timestamp}_{associate_alias}_{bookmaker_name}_{counter}.png"
                screenshot_path = screenshot_dir / filename
                counter += 1

            await photo_file.download_to_drive(screenshot_path)

            try:
                relative_path = screenshot_path.relative_to(Path.cwd())
                stored_path = str(relative_path)
            except ValueError:
                stored_path = str(screenshot_path)

            pending = self._create_pending_photo_entry(
                chat_id=chat_id,
                user_id=user_id,
                registration=registration,
                photo_message_id=str(message_id),
                screenshot_path=stored_path,
            )

            prompt_message = await self._invoke(
                message.reply_text,
                self._build_confirmation_prompt(pending),
                reply_markup=self._build_confirmation_keyboard(pending["confirmation_token"]),
            )

            if prompt_message and hasattr(prompt_message, "message_id"):
                self._update_pending_prompt_message(pending["id"], prompt_message.message_id)

            ref = pending["confirmation_token"][:6].upper()
            print(f"[Telegram] Pending screenshot from user {user_id} | Ref #{ref}")
            print(f"           Saved to: {screenshot_path.name}")

            logger.info(
                "photo_message_pending",
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                pending_id=pending["id"],
                screenshot_path=str(screenshot_path),
            )

        except Exception as e:
            logger.error(
                "photo_message_error",
                error=str(e),
                user_id=update.effective_user.id if update.effective_user else None,
            )
            try:
                await self._invoke(
                    message.reply_text,
                    "An error occurred while queuing your screenshot. Please try again.",
                )
            except Exception as reply_error:
                logger.error(
                    "photo_message_reply_error",
                    error=str(reply_error),
                    user_id=update.effective_user.id if update.effective_user else None,
                )

    def _build_confirmation_prompt(self, pending: Dict[str, Any]) -> str:
        """Create a human-friendly confirmation prompt tied to the pending screenshot."""
        alias = pending.get("associate_alias") or "associate"
        bookmaker = pending.get("bookmaker_name") or "bookmaker"
        ref = pending["confirmation_token"][:6].upper()
        ttl_minutes = PENDING_CONFIRMATION_TTL_SECONDS // 60
        return "\n".join(
            [
                f"Screenshot saved for {alias} / {bookmaker}",
                f"Ref #{ref}. Tap a button or reply to THIS message:",
                " - ingest 50 or #bet 50 win=140 (stake & optional win)",
                " - discard or #skip to drop it",
                f"Auto-discard after {ttl_minutes} minutes if you do nothing.",
            ]
        )

    def _build_confirmation_keyboard(self, token: str) -> InlineKeyboardMarkup:
        """Build inline keyboard for ingest/discard confirmation."""
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Ingest ✅", callback_data=f"confirm:{token}"),
                    InlineKeyboardButton("Discard 🗑️", callback_data=f"discard:{token}"),
                ]
            ]
        )

    def _create_pending_photo_entry(
        self,
        *,
        chat_id: str,
        user_id: Optional[int],
        registration: Dict[str, Any],
        photo_message_id: str,
        screenshot_path: str,
    ) -> Dict[str, Any]:
        """Persist pending screenshot metadata while awaiting confirmation."""
        expires_at = format_utc_iso(
            datetime.now(timezone.utc) + timedelta(seconds=PENDING_CONFIRMATION_TTL_SECONDS)
        )
        now_iso = utc_now_iso()
        conn = get_db_connection()
        cursor = conn.cursor()

        token: Optional[str] = None
        pending_id: Optional[int] = None

        while True:
            candidate = secrets.token_urlsafe(4)
            try:
                cursor.execute(
                    """
                    INSERT INTO pending_photos (
                        chat_id,
                        user_id,
                        associate_id,
                        bookmaker_id,
                        associate_alias,
                        bookmaker_name,
                        home_currency,
                        screenshot_path,
                        photo_message_id,
                        confirmation_token,
                        expires_at_utc,
                        created_at_utc,
                        updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chat_id,
                        user_id,
                        registration["associate_id"],
                        registration["bookmaker_id"],
                        registration.get("associate_alias"),
                        registration.get("bookmaker_name"),
                        registration.get("home_currency"),
                        screenshot_path,
                        photo_message_id,
                        candidate,
                        expires_at,
                        now_iso,
                        now_iso,
                    ),
                )
            except sqlite3.IntegrityError:
                # Token collision: generate a new one
                continue
            token = candidate
            pending_id = cursor.lastrowid
            break

        conn.commit()
        conn.close()

        return {
            "id": pending_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "associate_alias": registration.get("associate_alias"),
            "bookmaker_name": registration.get("bookmaker_name"),
            "confirmation_token": token,
            "screenshot_path": screenshot_path,
            "home_currency": registration.get("home_currency"),
        }

    def _update_pending_prompt_message(self, pending_id: int, prompt_message_id: int) -> None:
        """Persist the Telegram message id for threading confirmations."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE pending_photos
            SET prompt_message_id = ?, updated_at_utc = ?
            WHERE id = ?
            """,
            (str(prompt_message_id), utc_now_iso(), pending_id),
        )
        conn.commit()
        conn.close()

    def _get_pending_photo_by_reference(self, chat_id: str, message_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a pending record by chat and replied message id."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM pending_photos
            WHERE chat_id = ?
              AND status IN ('pending', 'confirmed')
              AND (photo_message_id = ? OR prompt_message_id = ?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (chat_id, str(message_id), str(message_id)),
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def _get_pending_photo_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Fetch pending record by confirmation token."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM pending_photos WHERE confirmation_token = ?",
            (token,),
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def _update_pending_photo(self, pending_id: int, **fields: Any) -> None:
        """Generic helper to update pending photo columns."""
        if not fields:
            return
        columns = ", ".join(f"{key} = ?" for key in fields.keys())
        values = list(fields.values())
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE pending_photos SET {columns}, updated_at_utc = ? WHERE id = ?",
            (*values, utc_now_iso(), pending_id),
        )
        conn.commit()
        conn.close()

    async def _pending_photo_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline button callbacks for pending screenshots."""
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()
        action, token = query.data.split(":", 1)
        pending = self._get_pending_photo_by_token(token)

        if not pending:
            if query.message:
                await self._invoke(
                    query.message.reply_text,
                    "That screenshot was already processed or expired.",
                )
            await query.edit_message_reply_markup(reply_markup=None)
            return

        if action == "confirm":
            await self._handle_pending_confirmation(
                pending=pending,
                overrides={
                    "stake_amount": None,
                    "stake_currency": None,
                    "win_amount": None,
                    "win_currency": None,
                },
                reply_message=query.message,
                chat_id=pending["chat_id"],
                context=context,
            )
        elif action == "discard":
            await self._handle_pending_discard(
                pending=pending,
                reply_message=query.message,
                chat_id=pending["chat_id"],
            )

        await query.edit_message_reply_markup(reply_markup=None)

    async def _handle_pending_confirmation(
        self,
        *,
        pending: Dict[str, Any],
        overrides: Dict[str, Optional[Decimal]],
        reply_message,
        chat_id: str,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Confirm a pending screenshot and enqueue it for processing."""
        if pending.get("status") not in ("pending", "confirmed") or pending.get("bet_id"):
            await self._send_pending_status_message(
                reply_message,
                chat_id,
                context,
                f"Ref #{pending['confirmation_token'][:6].upper()} already processed.",
            )
            return

        manual_stake = self._decimal_to_str(overrides.get("stake_amount"))
        manual_stake_currency = overrides.get("stake_currency") or pending.get("home_currency") or "EUR"
        if not manual_stake:
            manual_stake_currency = None

        manual_win = self._decimal_to_str(overrides.get("win_amount"))
        manual_win_currency = overrides.get("win_currency") or manual_stake_currency
        if not manual_win:
            manual_win_currency = None

        try:
            bet_id = self._create_bet_record(
                associate_id=pending["associate_id"],
                bookmaker_id=pending["bookmaker_id"],
                chat_id=chat_id,
                message_id=pending.get("photo_message_id") or "",
                screenshot_path=pending["screenshot_path"],
                manual_stake_override=manual_stake,
                manual_stake_currency=manual_stake_currency,
                manual_win_override=manual_win,
                manual_win_currency=manual_win_currency,
            )
        except Exception as exc:
            logger.error(
                "pending_confirmation_create_bet_failed",
                pending_id=pending["id"],
                error=str(exc),
                exc_info=True,
            )
            await self._send_pending_status_message(
                reply_message,
                chat_id,
                context,
                "Could not create bet record. Please retry later.",
            )
            return

        self._update_pending_photo(
            pending["id"],
            status="confirmed",
            bet_id=bet_id,
            stake_override=manual_stake,
            stake_currency=manual_stake_currency,
            win_override=manual_win,
            win_currency=manual_win_currency,
        )

        await self._trigger_ocr_pipeline(bet_id)

        ref = pending["confirmation_token"][:6].upper()
        details = [f"Queued Ref #{ref} (Bet ID {bet_id})."]
        if manual_stake:
            details.append(f"Stake override: {manual_stake_currency or ''} {manual_stake}".strip())
        if manual_win:
            details.append(f"Potential win override: {manual_win_currency or ''} {manual_win}".strip())
        else:
            details.append("Reply here with 'stake 50 win=140' if you need to override amounts.")

        await self._send_pending_status_message(
            reply_message,
            chat_id,
            context,
            " ".join(details),
        )

        logger.info(
            "pending_confirmation_ingested",
            pending_id=pending["id"],
            bet_id=bet_id,
            ref=ref,
        )

    async def _handle_pending_discard(
        self,
        *,
        pending: Dict[str, Any],
        reply_message,
        chat_id: str,
    ) -> None:
        """Discard a pending screenshot and delete its file."""
        if pending.get("bet_id"):
            await self._send_pending_status_message(
                reply_message,
                chat_id,
                None,  # type: ignore[arg-type]
                f"Ref #{pending['confirmation_token'][:6].upper()} already ingested; cannot discard.",
            )
            return

        self._update_pending_photo(pending["id"], status="discarded")
        self._delete_file_if_exists(pending.get("screenshot_path"))

        await self._send_pending_status_message(
            reply_message,
            chat_id,
            None,  # type: ignore[arg-type]
            f"Discarded Ref #{pending['confirmation_token'][:6].upper()} and deleted the screenshot.",
        )

        logger.info("pending_confirmation_discarded", pending_id=pending["id"])

    async def _handle_manual_override_update(
        self,
        *,
        pending: Dict[str, Any],
        overrides: Dict[str, Optional[Decimal]],
        reply_message,
    ) -> None:
        """Apply manual overrides to an already-created bet."""
        bet_id = pending.get("bet_id")
        if not bet_id:
            await self._invoke(
                reply_message.reply_text,
                "Please confirm the screenshot first using 'ingest' or the button.",
            )
            return

        if not overrides.get("stake_amount") and not overrides.get("win_amount"):
            await self._invoke(
                reply_message.reply_text,
                "Provide a stake amount or win= value when updating overrides.",
            )
            return

        manual_stake = self._decimal_to_str(overrides.get("stake_amount"))
        manual_stake_currency = overrides.get("stake_currency") or pending.get("home_currency") or "EUR"
        if not manual_stake:
            manual_stake_currency = None

        manual_win = self._decimal_to_str(overrides.get("win_amount"))
        manual_win_currency = overrides.get("win_currency") or manual_stake_currency
        if not manual_win:
            manual_win_currency = None

        self._apply_manual_overrides_to_bet(
            bet_id=bet_id,
            manual_stake=manual_stake,
            manual_stake_currency=manual_stake_currency,
            manual_win=manual_win,
            manual_win_currency=manual_win_currency,
        )

        self._update_pending_photo(
            pending["id"],
            stake_override=manual_stake,
            stake_currency=manual_stake_currency,
            win_override=manual_win,
            win_currency=manual_win_currency,
        )

        await self._invoke(
            reply_message.reply_text,
            "Manual overrides updated.",
        )

    def _apply_manual_overrides_to_bet(
        self,
        *,
        bet_id: int,
        manual_stake: Optional[str],
        manual_stake_currency: Optional[str],
        manual_win: Optional[str],
        manual_win_currency: Optional[str],
    ) -> None:
        """Persist manual stake/win overrides on the bet record."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE bets
            SET manual_stake_override = ?,
                manual_stake_currency = ?,
                manual_potential_win_override = ?,
                manual_potential_win_currency = ?,
                updated_at_utc = ?
            WHERE id = ?
            """,
            (
                manual_stake,
                manual_stake_currency,
                manual_win,
                manual_win_currency,
                utc_now_iso(),
                bet_id,
            ),
        )
        conn.commit()
        conn.close()

    def _delete_file_if_exists(self, path_value: Optional[str]) -> None:
        """Remove screenshot file from disk if it still exists."""
        if not path_value:
            return
        try:
            target = Path(path_value)
            if not target.is_absolute():
                target = Path.cwd() / target
            if target.exists():
                target.unlink()
        except Exception as exc:
            logger.warning("pending_file_delete_failed", path=path_value, error=str(exc))

    async def _expire_pending_photos_job(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Background job to expire pending confirmations after the TTL."""
        expired = self._expire_pending_records()
        if not expired:
            return

        for record in expired:
            ref = record["confirmation_token"][:6].upper()
            self._delete_file_if_exists(record.get("screenshot_path"))
            try:
                await context.bot.send_message(
                    chat_id=record["chat_id"],
                    text=f"Timed out waiting for confirmation of Ref #{ref}. Screenshot discarded.",
                )
            except Exception as exc:  # pragma: no cover - log only
                logger.warning("pending_expiry_notify_failed", chat_id=record["chat_id"], error=str(exc))

    def _expire_pending_records(self) -> List[Dict[str, Any]]:
        """Mark expired pending photos and return their details."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM pending_photos
            WHERE status = 'pending' AND expires_at_utc <= ?
            """,
            (utc_now_iso(),),
        )
        rows = cursor.fetchall()
        if not rows:
            conn.close()
            return []

        for row in rows:
            cursor.execute(
                "UPDATE pending_photos SET status = 'expired', updated_at_utc = ? WHERE id = ?",
                (utc_now_iso(), row["id"]),
            )

        conn.commit()
        conn.close()
        return [dict(row) for row in rows]

    async def _send_pending_status_message(
        self,
        reply_message,
        chat_id: str,
        context: Optional[ContextTypes.DEFAULT_TYPE],
        text: str,
    ) -> None:
        """Send a status update either by replying or via direct chat message."""
        if reply_message:
            await self._invoke(reply_message.reply_text, text)
            return
        if context:
            await context.bot.send_message(chat_id=chat_id, text=text)


    def _create_bet_record(
        self,
        associate_id: int,
        bookmaker_id: int,
        chat_id: str,
        message_id: str,
        screenshot_path: str,
        manual_stake_override: Optional[str] = None,
        manual_stake_currency: Optional[str] = None,
        manual_win_override: Optional[str] = None,
        manual_win_currency: Optional[str] = None,
    ) -> int:
        """
        Create a bet record in the database.

        Args:
            associate_id: ID of the associate
            bookmaker_id: ID of the bookmaker
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            screenshot_path: Path to the saved screenshot
            manual_stake_override: Optional manual stake amount provided by user
            manual_stake_currency: Currency for manual stake override
            manual_win_override: Optional manual potential win override
            manual_win_currency: Currency for manual potential win override

        Returns:
            The ID of the created bet record
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO bets (
                    associate_id,
                    bookmaker_id,
                    status,
                    stake_eur,
                    odds,
                    screenshot_path,
                    telegram_message_id,
                    ingestion_source,
                    manual_stake_override,
                    manual_stake_currency,
                    manual_potential_win_override,
                    manual_potential_win_currency,
                    created_at_utc,
                    updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    associate_id,
                    bookmaker_id,
                    "incoming",
                    "0.00",  # Placeholder stake (will be filled by OCR)
                    "1.00",  # Placeholder odds (will be filled by OCR)
                    screenshot_path,
                    message_id,
                    "telegram",
                    manual_stake_override,
                    manual_stake_currency,
                    manual_win_override,
                    manual_win_currency,
                    utc_now_iso(),
                    utc_now_iso(),
                ),
            )

            bet_id = cursor.lastrowid
            conn.commit()
            conn.close()

            logger.info(
                "bet_record_created",
                bet_id=bet_id,
                associate_id=associate_id,
                bookmaker_id=bookmaker_id,
                chat_id=chat_id,
                message_id=message_id,
                screenshot_path=screenshot_path,
            )

            return bet_id

        except Exception as e:
            logger.error(
                "create_bet_record_error",
                error=str(e),
                associate_id=associate_id,
                bookmaker_id=bookmaker_id,
                chat_id=chat_id,
                message_id=message_id,
                screenshot_path=screenshot_path,
            )
            raise

    async def _trigger_ocr_pipeline(self, bet_id: int) -> None:
        """
        Trigger OCR pipeline asynchronously for the given bet.

        This method runs the GPT-4o extraction pipeline on the bet's screenshot.

        Args:
            bet_id: ID of the bet to process with OCR
        """
        logger.info("ocr_pipeline_triggered", bet_id=bet_id)

        try:
            # Import here to avoid circular dependency
            from src.services.bet_ingestion import BetIngestionService

            # Run extraction in a separate thread to avoid blocking
            import asyncio
            from functools import partial

            loop = asyncio.get_event_loop()
            service = BetIngestionService()

            # Run extraction in thread pool executor
            await loop.run_in_executor(None, partial(service.process_bet_extraction, bet_id))

            service.close()

            logger.info("ocr_pipeline_completed", bet_id=bet_id)

        except Exception as e:
            logger.error("ocr_pipeline_error", bet_id=bet_id, error=str(e), exc_info=True)
            # Don't raise - extraction failure shouldn't crash the bot
            # Bet will remain in "incoming" status for manual processing

    def run(self) -> None:
        """Start the bot in polling mode."""
        try:
            logger.info("bot_starting", token_prefix=self.bot_token[:10] + "...")
            print(f"\n{'='*60}")
            print(f"🤖 Telegram Bot Starting...")
            print(f"{'='*60}")
            print(f"Bot Token: {self.bot_token[:10]}...")
            print(f"Screenshot Directory: {Config.SCREENSHOT_DIR}")
            print(f"Database: {Config.DB_PATH}")
            print(f"\n✅ Bot is now running and listening for messages!")
            print(f"Press Ctrl+C to stop the bot\n")
            print(f"{'='*60}\n")

            # run_polling() is a blocking call that handles the event loop internally
            self.application.run_polling(drop_pending_updates=True)
        except KeyboardInterrupt:
            logger.info("bot_shutdown_keyboard_interrupt")
            print(f"\n{'='*60}")
            print(f"🛑 Bot stopped by user")
            print(f"{'='*60}\n")
        except Exception as e:
            logger.error("bot_run_error", error=str(e))
            raise


def main() -> None:
    """Main entry point for running the bot."""
    try:
        # Validate configuration
        Config.validate()

        # Create and run bot
        bot = TelegramBot()
        bot.run()
    except KeyboardInterrupt:
        logger.info("bot_shutdown_keyboard_interrupt")
    except Exception as e:
        logger.error("bot_main_error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
