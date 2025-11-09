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

from telegram import (
    CopyTextButton,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    __version__ as telegram_version,
)
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
from src.services.bookmaker_balance_service import BookmakerBalanceService
from src.utils.datetime_helpers import format_utc_iso, utc_now_iso
from src.utils.logging_config import get_logger

# Configure structured logging
logger = get_logger(__name__)

# Hardcoded default global admin user IDs (can be extended via env)
# Stefano (primary admin): 1571540653
DEFAULT_ADMIN_USER_IDS: set[int] = {1571540653}
ADMIN_CONFIRMATION_TTL_SECONDS = 300  # 5 minutes
PENDING_CONFIRMATION_TTL_SECONDS = 60 * 60  # 60 minutes
OVERRIDE_REQUEST_TTL_SECONDS = 300  # 5 minutes
MAX_MANUAL_AMOUNT = Decimal("1000000")
CURRENCY_SYMBOL_MAP = {
    "\u20ac": "EUR",
    "$": "USD",
    "\u00a3": "GBP",
}
CONFIRM_KEYWORDS = {"yes", "ingest", "#bet", "confirm"}
DISCARD_KEYWORDS = {"no", "skip", "discard", "#skip"}
BALANCE_CONFIRM_KEYWORDS = {"ok", "okay", "correct"}
BALANCE_MESSAGE_PATTERN = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{2}) "
    r"Balance: (?P<balance>[-\d.,]+) (?P<currency>[A-Z]{3}), "
    r"pending balance: (?P<pending>[-\d.,]+) (?P<pending_currency>[A-Z]{3})\.$"
)
ADMIN_APPROVAL_KEYWORDS = ("approve", "confirm")
ADMIN_PRIMARY_APPROVAL_KEYWORD = ADMIN_APPROVAL_KEYWORDS[0]
ADMIN_APPROVAL_PATTERN = re.compile(
    "(?:%s)(?:\\s+(\\d{6}))?" % "|".join(ADMIN_APPROVAL_KEYWORDS),
    re.IGNORECASE,
)


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
        self._pending_override_requests: Dict[str, Dict[str, Any]] = {}

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

    @staticmethod
    def _create_copy_button(label: str, value: Optional[str]) -> Optional[InlineKeyboardButton]:
        """Return a copy-to-clipboard inline button when supported."""
        if not value:
            return None
        try:
            return InlineKeyboardButton(text=label, copy_text=CopyTextButton(text=str(value)))
        except TypeError:
            # Older Telegram clients may not support copy buttons yet.
            return None

    @classmethod
    def _build_copy_markup(cls, value: Optional[str], *, label: str) -> Optional[InlineKeyboardMarkup]:
        """Return a single-button markup for copy interactions."""
        button = cls._create_copy_button(label, value)
        if not button:
            return None
        return InlineKeyboardMarkup([[button]])

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
        self.application.add_handler(
            MessageHandler(
                filters.Document.IMAGE,
                self._rate_limited(self._document_message),
            )
        )

        # Chat migration events (group -> supergroup)
        self.application.add_handler(
            MessageHandler(
                filters.StatusUpdate.MIGRATE,
                self._rate_limited(self._handle_chat_migration),
            )
        )

        # Callback handler for confirmation buttons
        self.application.add_handler(
            CallbackQueryHandler(
                self._rate_limited(self._pending_photo_callback),
                pattern=r"^(confirm|discard):",
            )
        )
        self.application.add_handler(
            CallbackQueryHandler(
                self._rate_limited(self._handle_stake_prompt_callback),
                pattern=r"^stake_prompt:",
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
            help_text = (
                "Surebet assistant menu\n"
                "\n"
                "Balance & snapshots\n"
                "- /register <associate> <bookmaker>: link this chat for balance + pending drops\n"
                "- Reply with ok/okay/correct to a balance snapshot to log the latest report\n"
                "- /help: show this menu\n"
                "\n"
                "Banking & funding\n"
                "- deposit <amount> | /deposit <amount>\n"
                "- withdraw <amount> | /withdraw <amount>\n"
                "- approve (or /confirm): finalize a pending admin deposit/withdrawal within 5 minutes\n"
                "\n"
                "Chat tools\n"
                "- /chat_id: display + copy the current chat ID\n"
                "- /start: recap what the assistant can do\n"
                "\n"
                "Admin tools\n"
                "- /list_associates, /list_bookmakers, /add_associate, /add_bookmaker\n"
                "- /list_chats, /unregister_chat, /broadcast, /version, /health"
            )
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

            text = f"Current chat ID: {chat_id}\nTap 'Copy chat ID' or long-press if the button is missing."
            reply_markup = self._build_copy_markup(str(chat_id), label="Copy chat ID")
            kwargs = {"reply_markup": reply_markup} if reply_markup else {}
            await self._invoke(message.reply_text, text, **kwargs)
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
        """Handle /confirm for admin approval finalization."""
        message = self._get_effective_message(update)
        args = context.args or []
        token = args[0] if args else None

        chat_id = str(update.effective_chat.id) if update.effective_chat else None
        if not chat_id:
            if message:
                await self._invoke(message.reply_text, "Unable to confirm outside of a chat context.")
            return

        await self._process_admin_confirmation(
            token=token,
            chat_id=chat_id,
            user_id=update.effective_user.id if update.effective_user else None,
            message=message,
        )

    async def _maybe_handle_balance_confirmation(
        self,
        update: Update,
        text: str,
    ) -> bool:
        """Capture 'ok/okay/correct' replies to balance snapshots and log confirmation."""
        if not text or text.strip().lower() not in BALANCE_CONFIRM_KEYWORDS:
            return False

        message = self._get_effective_message(update)
        if not message:
            return False

        reply_message = getattr(message, "reply_to_message", None)
        reply_text = getattr(reply_message, "text", None)
        reply_author = getattr(reply_message, "from_user", None)
        if not reply_text or not reply_author or not getattr(reply_author, "is_bot", False):
            return False

        snapshot = self._parse_balance_snapshot_text(reply_text)
        if not snapshot:
            return False

        chat = update.effective_chat
        chat_id = str(chat.id) if chat else None
        if not chat_id:
            return False

        registration = self._get_registration(chat_id)
        if not registration:
            return False

        amount, currency = snapshot
        try:
            with BookmakerBalanceService() as balance_service:
                balance_service.update_reported_balance(
                    associate_id=registration["associate_id"],
                    bookmaker_id=registration["bookmaker_id"],
                    balance_native=amount,
                    native_currency=currency,
                    note=f"telegram-confirm:{chat_id}",
                )
        except Exception as exc:
            if message:
                await self._invoke(
                    message.reply_text,
                    "Could not record that confirmation. Please try again once the issue is resolved.",
                )
            logger.error(
                "balance_confirmation_failed",
                chat_id=chat_id,
                associate_id=registration["associate_id"],
                bookmaker_id=registration["bookmaker_id"],
                error=str(exc),
                exc_info=True,
            )
            return True

        formatted_amount = amount.quantize(Decimal("0.01"))
        if message:
            await self._invoke(
                message.reply_text,
                (
                    f"Thanks! Logged {formatted_amount} {currency} for "
                    f"{registration['bookmaker_name']}."
                ),
            )

        logger.info(
            "balance_confirmation_recorded",
            chat_id=chat_id,
            associate_id=registration["associate_id"],
            bookmaker_id=registration["bookmaker_id"],
            amount=str(amount),
            currency=currency,
        )
        return True

    @staticmethod
    def _parse_balance_snapshot_text(text: Optional[str]) -> Optional[Tuple[Decimal, str]]:
        """Extract balance amount + currency from the standard balance snapshot message."""
        if not text:
            return None
        match = BALANCE_MESSAGE_PATTERN.match(text.strip())
        if not match:
            return None
        raw_amount = match.group("balance").replace(",", "")
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation:
            return None
        currency = match.group("currency")
        return amount, currency

    @staticmethod
    def _is_security_prompt_message(message) -> bool:
        """True when the replied-to bot message is a funding security check."""
        if not message:
            return False
        text = getattr(message, "text", None)
        if not text:
            return False
        lowered = text.lower()
        return "security check" in lowered and "finalize" in lowered

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

        message = self._get_effective_message(update)
        reply_message = message.reply_to_message if message else None
        chat = update.effective_chat
        chat_id = str(chat.id) if chat else None
        user_id = update.effective_user.id if update.effective_user else None

        if not chat_id:
            return False

        override_key = self._override_request_key(chat_id, user_id)
        if override_key:
            self._cleanup_override_requests()
            override_request = self._pending_override_requests.get(override_key)
            if override_request and message:
                should_clear = await self._handle_override_request_text(
                    request=override_request,
                    message=message,
                    chat_id=chat_id,
                    user_id=user_id,
                    text=text,
                    context=context,
                )
                if should_clear:
                    self._pending_override_requests.pop(override_key, None)
                return True

        if not parsed:
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
            if parsed["action"] == "confirm" and self._is_security_prompt_message(reply_message):
                await self._process_admin_confirmation(
                    token=None,
                    chat_id=chat_id,
                    user_id=user_id,
                    message=message,
                )
                return True
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

        tokens = [t for t in cleaned.split() if t]
        if not tokens:
            return None

        first_token = tokens[0].lower()
        win_match = re.search(r"win\s*=\s*([^\s]+)", cleaned, re.IGNORECASE)
        win_token = win_match.group(1) if win_match else None

        action = None
        stake_token = None

        if first_token in CONFIRM_KEYWORDS:
            action = "confirm"
            stake_token = self._extract_stake_token(tokens[1:])
        elif first_token in DISCARD_KEYWORDS:
            action = "discard"
        else:
            first_word = tokens[0].lower()
            first_is_amount = self._looks_like_amount_token(tokens[0])
            first_is_stake_keyword = first_word.startswith("stake")
            first_is_win_keyword = first_word.startswith("win=")

            if win_token or first_is_amount or first_is_stake_keyword or first_is_win_keyword:
                action = "amount_only"
                stake_token = self._extract_stake_token(tokens)
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

    @staticmethod
    def _override_request_key(chat_id: Optional[str], user_id: Optional[int]) -> Optional[str]:
        if not chat_id or user_id is None:
            return None
        return f"{chat_id}:{user_id}"

    def _cleanup_override_requests(self) -> None:
        now = time.time()
        expired = [
            key
            for key, ctx in self._pending_override_requests.items()
            if ctx.get("expires_at", 0) <= now
        ]
        for key in expired:
            self._pending_override_requests.pop(key, None)

    def _register_override_request(
        self,
        *,
        chat_id: Optional[str],
        user_id: Optional[int],
        pending_id: int,
        mode: str,
    ) -> Optional[str]:
        key = self._override_request_key(chat_id, user_id)
        if not key:
            return None
        self._cleanup_override_requests()
        self._pending_override_requests[key] = {
            "pending_id": pending_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "mode": mode,
            "created_at": utc_now_iso(),
            "expires_at": time.time() + OVERRIDE_REQUEST_TTL_SECONDS,
        }
        return key

    @staticmethod
    def _strip_keyword_value(token: str, keyword: str) -> Optional[str]:
        """Return the value portion when token starts with keyword (supports = or :)."""
        if not token:
            return None
        lowered = token.lower()
        keyword_lower = keyword.lower()
        if lowered == keyword_lower:
            return ""
        for delimiter in ("=", ":"):
            prefix = f"{keyword_lower}{delimiter}"
            if lowered.startswith(prefix):
                return token[len(prefix) :]
        return None

    def _extract_stake_token(self, tokens: List[str]) -> Optional[str]:
        """Locate a stake token supporting 'stake 50' or plain numeric formats."""
        if not tokens:
            return None

        for idx, token in enumerate(tokens):
            if not token:
                continue

            stripped = self._strip_keyword_value(token, "stake")
            if stripped is not None:
                if stripped:
                    return stripped
                # bare 'stake' keyword – look ahead for the next usable amount token
                for lookahead in tokens[idx + 1 :]:
                    if not lookahead or lookahead.lower().startswith("win=") or lookahead.lower() == "stake":
                        continue
                    return lookahead
                return None

            if token.lower().startswith("win="):
                continue

            if self._looks_like_amount_token(token):
                return token

        return None

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
            if await self._maybe_handle_balance_confirmation(update, text):
                return

            if await self._maybe_handle_pending_text(update, context, text):
                return

            token = self._parse_admin_confirmation(text)
            if token is not None:
                await self._process_admin_confirmation(
                    token=token or None,
                    chat_id=chat_id,
                    user_id=user_id,
                    message=message,
                )
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
        """
        Parse admin confirmation text.

        Returns:
            - "" when the user simply typed/issued `approve` (or legacy `confirm`)
            - 6-digit token string when explicitly provided (legacy behaviour)
            - None when the text does not represent an admin confirmation
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return None
        match = ADMIN_APPROVAL_PATTERN.fullmatch(cleaned)
        if not match:
            return None
        token = match.group(1)
        return token if token else ""

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
            "created_at_ts": time.time(),
            "expires_at": time.time() + ADMIN_CONFIRMATION_TTL_SECONDS,
        }
        self._pending_admin_confirmations[token] = context

        if message:
            bookmaker_segment = f"{context['bookmaker_name']} " if context["bookmaker_name"] else ""
            minutes = max(1, ADMIN_CONFIRMATION_TTL_SECONDS // 60)
            await self._invoke(
                message.reply_text,
                (
                    f"Security check: reply with '{ADMIN_PRIMARY_APPROVAL_KEYWORD}' within {minutes} minute(s) "
                    f"to finalize {command_type} {amount_decimal} {currency} "
                    f"{bookmaker_segment}recorded. (Legacy 'confirm' still works.)"
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

    def _find_pending_admin_confirmation(
        self,
        *,
        chat_id: str,
        user_id: Optional[int],
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Return the latest pending admin confirmation for the chat/user."""
        matches = [
            (token, ctx)
            for token, ctx in self._pending_admin_confirmations.items()
            if ctx.get("chat_id") == chat_id
        ]
        if user_id is not None:
            user_matches = [
                (token, ctx)
                for token, ctx in matches
                if ctx.get("user_id") in (user_id, None)
            ]
            if user_matches:
                matches = user_matches
        if not matches:
            return None, None
        token, context = max(
            matches,
            key=lambda item: item[1].get("created_at_ts", 0.0),
        )
        return token, context

    async def _process_admin_confirmation(
        self,
        *,
        token: Optional[str],
        chat_id: str,
        user_id: Optional[int],
        message,
    ) -> None:
        """Process admin confirmation requests."""
        cleaned_token = token.strip() if token else None

        self._cleanup_expired_confirmations()
        matched_token: Optional[str] = None
        context: Optional[Dict[str, Any]] = None

        if cleaned_token:
            context = self._pending_admin_confirmations.get(cleaned_token)
            matched_token = cleaned_token
        else:
            matched_token, context = self._find_pending_admin_confirmation(
                chat_id=chat_id,
                user_id=user_id,
            )

        if not context:
            if message:
                response = (
                    "Confirmation code is invalid or expired. Please resend the command."
                    if cleaned_token
                    else "No pending Telegram approvals for this chat. Please resend the deposit/withdrawal command."
                )
                await self._invoke(message.reply_text, response)
            logger.warning(
                "funding_admin_confirmation_invalid",
                chat_id=chat_id,
                user_id=user_id,
                token=cleaned_token,
                reason="missing" if cleaned_token else "no_pending",
            )
            return

        if cleaned_token and context["chat_id"] != chat_id:
            if message:
                await self._invoke(message.reply_text, "This confirmation belongs to a different chat.")
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
                await self._invoke(
                    message.reply_text,
                    "Only the admin who submitted the command can confirm it.",
                )
            logger.warning(
                "funding_admin_confirmation_invalid",
                chat_id=chat_id,
                user_id=user_id,
                token=matched_token,
                reason="user_mismatch",
            )
            return

        ledger_id = await self._record_admin_transaction(context, message)
        if ledger_id and matched_token:
            self._pending_admin_confirmations.pop(matched_token, None)
            logger.info(
                "funding_admin_confirmation_completed",
                chat_id=chat_id,
                user_id=user_id,
                token=matched_token,
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

        photo = message.photo[-1] if message.photo else None
        if not photo:
            return

        try:
            file_obj = await photo.get_file()
            await self._process_incoming_media(
                update=update,
                context=context,
                message=message,
                file_obj=file_obj,
                extension_hint=".png",
                media_label="photo",
            )
        except Exception as e:
            await self._handle_media_error(e, update, message, label="photo")

    async def _document_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle image documents (send-as-file screenshots)."""
        message = update.message
        if not message or not update.effective_chat:
            return

        document = getattr(message, "document", None)
        if not document:
            return

        mime_type = (document.mime_type or "").lower()
        filename = document.file_name or ""
        extension = Path(filename).suffix if filename else None
        if not (
            mime_type.startswith("image/")
            or (extension and extension.lower() in {".png", ".jpg", ".jpeg", ".webp"})
        ):
            return

        try:
            file_obj = await document.get_file()
            await self._process_incoming_media(
                update=update,
                context=context,
                message=message,
                file_obj=file_obj,
                extension_hint=extension or ".png",
                media_label="document",
            )
        except Exception as e:
            await self._handle_media_error(e, update, message, label="document")

    async def _process_incoming_media(
        self,
        *,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message,
        file_obj,
        extension_hint: Optional[str],
        media_label: str,
    ) -> None:
        """Shared logic for handling incoming screenshots regardless of transport."""
        chat = update.effective_chat
        if not chat:
            return

        chat_id = str(chat.id)
        message_id = message.message_id
        user_id = update.effective_user.id if update.effective_user else None

        registration = self._get_registration(chat_id)
        if not registration:
            await self._invoke(
                message.reply_text,
                "This chat is not registered. Please use /register <associate_alias> <bookmaker_name> first.",
            )
            logger.warning(
                "media_message_unregistered_chat",
                media=media_label,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
            )
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        associate_alias = registration["associate_alias"]
        bookmaker_name = registration["bookmaker_name"]
        extension = (extension_hint or ".png").lower()
        if not extension.startswith("."):
            extension = f".{extension}"

        screenshot_dir = Path(Config.SCREENSHOT_DIR)
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{timestamp}_{associate_alias}_{bookmaker_name}{extension}"
        screenshot_path = screenshot_dir / filename
        counter = 1
        while screenshot_path.exists():
            filename = f"{timestamp}_{associate_alias}_{bookmaker_name}_{counter}{extension}"
            screenshot_path = screenshot_dir / filename
            counter += 1

        await file_obj.download_to_drive(screenshot_path)

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
        print(f"[Telegram] Pending {media_label} from user {user_id} | Ref #{ref}")
        print(f"           Saved to: {screenshot_path.name}")

        logger.info(
            "media_message_pending",
            media=media_label,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            pending_id=pending["id"],
            screenshot_path=str(screenshot_path),
        )

    async def _handle_media_error(self, error: Exception, update: Update, message, label: str) -> None:
        """Common fallback when media ingestion fails."""
        logger.error(
            "media_message_error",
            media=label,
            error=str(error),
            user_id=update.effective_user.id if update.effective_user else None,
        )
        try:
            await self._invoke(
                message.reply_text,
                "An error occurred while queuing your screenshot. Please try again.",
            )
        except Exception as reply_error:
            logger.error(
                "media_message_reply_error",
                media=label,
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
        buttons = [
            [
                InlineKeyboardButton("Ingest ✅", callback_data=f"confirm:{token}"),
                InlineKeyboardButton("Discard 🗑️", callback_data=f"discard:{token}"),
            ],
            [InlineKeyboardButton("Stake Override ✏️", callback_data=f"stake_prompt:{token}")],
        ]
        copy_button = self._create_copy_button("Copy Ref", f"Ref #{token[:6].upper()}")
        if copy_button:
            buttons.append([copy_button])
        return InlineKeyboardMarkup(buttons)

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

    def _get_pending_photo_by_id(self, pending_id: int) -> Optional[Dict[str, Any]]:
        """Fetch pending record by primary key."""
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM pending_photos
            WHERE id = ?
            """,
            (pending_id,),
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

    async def _handle_chat_migration(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle chat_id changes when groups migrate to supergroups."""
        message = self._get_effective_message(update)
        if not message:
            return

        migrate_to = getattr(message, "migrate_to_chat_id", None)
        migrate_from = getattr(message, "migrate_from_chat_id", None)

        old_chat_id = None
        new_chat_id = None

        if migrate_to:
            # Group upgraded to supergroup
            new_chat_id = str(migrate_to)
            chat = getattr(message, "chat", None)
            if chat and getattr(chat, "id", None) is not None:
                old_chat_id = str(chat.id)
        elif migrate_from:
            # Channel linked back to group or downgrade
            old_chat_id = str(migrate_from)
            chat = getattr(message, "chat", None)
            if chat and getattr(chat, "id", None) is not None:
                new_chat_id = str(chat.id)

        if not old_chat_id or not new_chat_id:
            return

        if self._migrate_chat_registration(old_chat_id, new_chat_id):
            logger.info(
                "chat_registration_migrated",
                old_chat_id=old_chat_id,
                new_chat_id=new_chat_id,
            )
            notice = (
                "This chat was upgraded and now has a new ID. "
                "I've moved the registration so screenshots continue working."
            )
            try:
                await self._invoke(message.reply_text, notice)
            except Exception:
                try:
                    await context.bot.send_message(chat_id=new_chat_id, text=notice)
                except Exception:
                    logger.warning(
                        "chat_registration_migration_notice_failed",
                        chat_id=new_chat_id,
                    )

    def _migrate_chat_registration(self, old_chat_id: str, new_chat_id: str) -> bool:
        """Update registration and pending photos to reference the new chat ID."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            now = utc_now_iso()

            cursor.execute(
                """
                UPDATE chat_registrations
                SET chat_id = ?, updated_at_utc = ?
                WHERE chat_id = ?
                """,
                (new_chat_id, now, old_chat_id),
            )
            updated = cursor.rowcount > 0

            cursor.execute(
                """
                UPDATE pending_photos
                SET chat_id = ?, updated_at_utc = ?
                WHERE chat_id = ?
                """,
                (new_chat_id, now, old_chat_id),
            )

            conn.commit()
            conn.close()
            if updated:
                return True

        except Exception as exc:
            logger.error(
                "chat_registration_migration_failed",
                old_chat_id=old_chat_id,
                new_chat_id=new_chat_id,
                error=str(exc),
            )
        return False

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

    async def _handle_stake_prompt_callback(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Initiate a stake override prompt via inline button."""
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()
        token = query.data.split(":", 1)[1]
        pending = self._get_pending_photo_by_token(token)
        if not pending:
            if query.message:
                await self._invoke(
                    query.message.reply_text,
                    "That screenshot was already processed or expired.",
                )
            return

        user_id = query.from_user.id if query.from_user else None
        chat_id = pending.get("chat_id")
        key = self._register_override_request(
            chat_id=chat_id,
            user_id=user_id,
            pending_id=int(pending["id"]),
            mode="update" if pending.get("bet_id") else "confirm",
        )

        prompt_text = (
            f"Send the stake override for Ref #{token[:6].upper()}."
            " Example: 'stake 50 win=140' or '50 win=140'."
        )
        reply_markup = ForceReply(selective=True)
        prompt_message = None
        if query.message:
            prompt_message = await self._invoke(query.message.reply_text, prompt_text, reply_markup=reply_markup)
        elif chat_id:
            prompt_message = await context.bot.send_message(chat_id=chat_id, text=prompt_text, reply_markup=reply_markup)

        if key and prompt_message and hasattr(prompt_message, "message_id"):
            self._pending_override_requests[key]["prompt_message_id"] = prompt_message.message_id

        logger.info(
            "pending_override_prompt_started",
            chat_id=chat_id,
            user_id=user_id,
            pending_id=pending["id"],
            ref=token[:6].upper(),
        )

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
                copy_value=f"Ref #{pending['confirmation_token'][:6].upper()}",
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

        if manual_stake or manual_win:
            self._apply_manual_overrides_to_bet(
                bet_id=bet_id,
                manual_stake=manual_stake,
                manual_stake_currency=manual_stake_currency,
                manual_win=manual_win,
                manual_win_currency=manual_win_currency,
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
            copy_value=f"Ref #{ref}",
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
                copy_value=f"Ref #{pending['confirmation_token'][:6].upper()}",
            )
            return

        self._update_pending_photo(pending["id"], status="discarded")
        self._delete_file_if_exists(pending.get("screenshot_path"))

        await self._send_pending_status_message(
            reply_message,
            chat_id,
            None,  # type: ignore[arg-type]
            f"Discarded Ref #{pending['confirmation_token'][:6].upper()} and deleted the screenshot.",
            copy_value=f"Ref #{pending['confirmation_token'][:6].upper()}",
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

    async def _handle_override_request_text(
        self,
        *,
        request: Dict[str, Any],
        message,
        chat_id: str,
        user_id: Optional[int],
        text: str,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> bool:
        """Process text input that was requested via the Stake Override button."""
        if request.get("expires_at", 0) <= time.time():
            await self._invoke(
                message.reply_text,
                "That override request expired. Tap the Stake Override button again.",
            )
            return True

        try:
            parsed = self._parse_pending_confirmation_text(text)
        except ValueError as exc:
            await self._invoke(message.reply_text, str(exc))
            return False

        if not parsed or (not parsed.get("stake_amount") and not parsed.get("win_amount")):
            await self._invoke(
                message.reply_text,
                "Please provide a stake amount (optionally win=...) for the override.",
            )
            return False

        pending = self._get_pending_photo_by_id(int(request["pending_id"]))
        if not pending:
            await self._invoke(
                message.reply_text,
                "I could not find that screenshot anymore. Please resend the photo.",
            )
            return True

        overrides = {
            "stake_amount": parsed.get("stake_amount"),
            "stake_currency": parsed.get("stake_currency"),
            "win_amount": parsed.get("win_amount"),
            "win_currency": parsed.get("win_currency"),
        }

        if pending.get("bet_id"):
            await self._handle_manual_override_update(
                pending=pending,
                overrides=overrides,
                reply_message=message,
            )
        else:
            await self._handle_pending_confirmation(
                pending=pending,
                overrides=overrides,
                reply_message=message,
                chat_id=chat_id,
                context=context,
            )

        logger.info(
            "pending_override_request_completed",
            chat_id=chat_id,
            user_id=user_id,
            pending_id=pending["id"],
        )
        return True

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
        columns = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(bets)").fetchall()
        }

        set_clauses: List[str] = []
        params: List[Optional[str]] = []

        def add_simple(column: str, value: Optional[str]) -> None:
            if column in columns:
                set_clauses.append(f"{column} = ?")
                params.append(value)

        # Always try to persist manual override fields when supported.
        add_simple("manual_stake_override", manual_stake)
        add_simple("manual_stake_currency", manual_stake_currency)
        add_simple("manual_potential_win_override", manual_win)
        add_simple("manual_potential_win_currency", manual_win_currency)

        if manual_stake is not None:
            add_simple("stake_original", manual_stake)
            add_simple("stake_amount", manual_stake)
            if "stake_currency" in columns:
                set_clauses.append("stake_currency = COALESCE(?, stake_currency)")
                params.append(manual_stake_currency)
            if "currency" in columns:
                set_clauses.append("currency = COALESCE(?, currency)")
                params.append(manual_stake_currency)

        if manual_win is not None:
            add_simple("payout", manual_win)

        if "updated_at_utc" in columns:
            set_clauses.append("updated_at_utc = ?")
            params.append(utc_now_iso())

        if not set_clauses:
            conn.close()
            return

        params.append(bet_id)

        cursor.execute(
            f"""
            UPDATE bets
            SET {", ".join(set_clauses)}
            WHERE id = ?
            """,
            tuple(params),
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
                    reply_markup=self._build_copy_markup(f"Ref #{ref}", label="Copy Ref"),
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
        *,
        copy_value: Optional[str] = None,
    ) -> None:
        """Send a status update either by replying or via direct chat message."""
        reply_markup = self._build_copy_markup(copy_value, label="Copy Ref") if copy_value else None
        kwargs = {"reply_markup": reply_markup} if reply_markup else {}
        if reply_message:
            await self._invoke(reply_message.reply_text, text, **kwargs)
            return
        if context:
            await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)


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
    async def _process_incoming_media(
        self,
        *,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        message,
        file_obj,
        extension_hint: Optional[str],
        media_label: str,
    ) -> None:
        """Shared logic for handling incoming screenshots regardless of transport."""
        chat = update.effective_chat
        if not chat:
            return

        chat_id = str(chat.id)
        message_id = message.message_id
        user_id = update.effective_user.id if update.effective_user else None

        registration = self._get_registration(chat_id)
        if not registration:
            await self._invoke(
                message.reply_text,
                "This chat is not registered. Please use /register <associate_alias> <bookmaker_name> first.",
            )
            logger.warning(
                "media_message_unregistered_chat",
                media=media_label,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
            )
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        associate_alias = registration["associate_alias"]
        bookmaker_name = registration["bookmaker_name"]
        extension = (extension_hint or ".png").lower()
        if not extension.startswith("."):
            extension = f".{extension}"

        screenshot_dir = Path(Config.SCREENSHOT_DIR)
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{timestamp}_{associate_alias}_{bookmaker_name}{extension}"
        screenshot_path = screenshot_dir / filename
        counter = 1
        while screenshot_path.exists():
            filename = f"{timestamp}_{associate_alias}_{bookmaker_name}_{counter}{extension}"
            screenshot_path = screenshot_dir / filename
            counter += 1

        await file_obj.download_to_drive(screenshot_path)

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
        print(f"[Telegram] Pending {media_label} from user {user_id} | Ref #{ref}")
        print(f"           Saved to: {screenshot_path.name}")

        logger.info(
            "media_message_pending",
            media=media_label,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            pending_id=pending["id"],
            screenshot_path=str(screenshot_path),
        )
