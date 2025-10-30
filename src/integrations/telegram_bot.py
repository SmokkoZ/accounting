"""
Telegram Bot implementation for the Surebet Accounting System.

This module handles:
- Receiving screenshots via Telegram
- Saving screenshots locally
- Creating placeholder bet records
- Command handlers for bot interaction
"""

import asyncio
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from src.core.config import Config
from src.core.database import get_db_connection
from src.utils.datetime_helpers import utc_now_iso
from src.utils.logging_config import get_logger

# Configure structured logging
logger = get_logger(__name__)


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

        self.application = Application.builder().token(self.bot_token).build()
        self._setup_handlers()
        self._setup_signal_handlers()

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

        # Photo message handler with rate limiting
        self.application.add_handler(
            MessageHandler(filters.PHOTO, self._rate_limited(self._photo_message))
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
            user_id = update.effective_user.id
            current_time = time.time()

            # Check if user has exceeded rate limit
            if current_time - self._user_last_command[user_id] < self._rate_limit_seconds:
                remaining = self._rate_limit_seconds - (
                    current_time - self._user_last_command[user_id]
                )
                await update.message.reply_text(
                    f"Rate limit exceeded. Please wait {remaining:.1f} seconds before trying again."
                )
                logger.warning("rate_limit_exceeded", user_id=user_id, remaining_seconds=remaining)
                return

            # Update last command time and execute handler
            self._user_last_command[user_id] = current_time
            await handler(update, context)

        return wrapped

    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command."""
        try:
            await update.message.reply_text("Surebet Bot Ready")
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

You can also send screenshots directly to create bet records.
            """.strip()
            await update.message.reply_text(help_text)
            logger.info("help_command_handled", user_id=update.effective_user.id)
        except Exception as e:
            logger.error("help_command_error", error=str(e), user_id=update.effective_user.id)

    async def _register_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /register command."""
        try:
            chat_id = str(update.effective_chat.id)
            user_id = update.effective_user.id

            # Parse command arguments
            args = context.args
            if len(args) != 2:
                await update.message.reply_text(
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
                await update.message.reply_text(
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
                await update.message.reply_text(
                    f"Chat {chat_id} successfully registered for {associate_alias} at {bookmaker_name}"
                )
                print(f"✅ Chat {chat_id} registered: {associate_alias} @ {bookmaker_name}")
            else:
                await update.message.reply_text(
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
                await update.message.reply_text("An error occurred during registration.")
            except Exception as reply_error:
                logger.error(
                    "register_command_reply_error",
                    error=str(reply_error),
                    user_id=update.effective_user.id,
                )

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

            # Insert or update registration
            cursor.execute(
                """
                INSERT OR REPLACE INTO chat_registrations 
                (chat_id, associate_id, bookmaker_id, updated_at_utc)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, associate["id"], bookmaker["id"], utc_now_iso()),
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
                    b.bookmaker_name
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
                return {
                    "associate_id": result["associate_id"],
                    "bookmaker_id": result["bookmaker_id"],
                    "associate_alias": result["associate_alias"],
                    "bookmaker_name": result["bookmaker_name"],
                }
            return None

        except Exception as e:
            logger.error("get_registration_error", error=str(e), chat_id=chat_id)
            return None

    async def _photo_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle photo messages."""
        try:
            chat_id = str(update.effective_chat.id)
            message_id = update.message.message_id
            user_id = update.effective_user.id

            # Get registration for this chat
            registration = self._get_registration(chat_id)

            # Reject unknown chat IDs
            if not registration:
                await update.message.reply_text(
                    "This chat is not registered. Please use /register <associate_alias> <bookmaker_name> first."
                )
                logger.warning(
                    "photo_message_unregistered_chat",
                    user_id=user_id,
                    chat_id=chat_id,
                    message_id=message_id,
                )
                return

            # Get the highest resolution photo
            photo_file = await update.message.photo[-1].get_file()

            # Generate filename with timestamp (including milliseconds), associate alias, and bookmaker name
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]  # Include milliseconds
            associate_alias = registration["associate_alias"]
            bookmaker_name = registration["bookmaker_name"]
            filename = f"{timestamp}_{associate_alias}_{bookmaker_name}.png"

            # Ensure screenshots directory exists
            screenshot_dir = Path(Config.SCREENSHOT_DIR)
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            # Handle file naming collisions
            screenshot_path = screenshot_dir / filename
            counter = 1
            while screenshot_path.exists():
                filename = f"{timestamp}_{associate_alias}_{bookmaker_name}_{counter}.png"
                screenshot_path = screenshot_dir / filename
                counter += 1

            # Save screenshot
            await photo_file.download_to_drive(screenshot_path)

            # Create bet record in database
            # Store relative path if possible, otherwise absolute path
            try:
                relative_path = screenshot_path.relative_to(Path.cwd())
                stored_path = str(relative_path)
            except ValueError:
                # If not relative to cwd, store absolute path
                stored_path = str(screenshot_path)

            bet_id = self._create_bet_record(
                associate_id=registration["associate_id"],
                bookmaker_id=registration["bookmaker_id"],
                chat_id=chat_id,
                message_id=str(message_id),
                screenshot_path=stored_path,
            )

            # Trigger OCR pipeline asynchronously (placeholder for Story 1.2)
            await self._trigger_ocr_pipeline(bet_id)

            # Reply to sender
            await update.message.reply_text("Processing screenshot...")

            print(f"📸 Screenshot received from user {user_id} | Bet ID: {bet_id}")
            print(f"   Saved to: {screenshot_path.name}")

            logger.info(
                "photo_message_handled",
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                bet_id=bet_id,
                screenshot_path=str(screenshot_path),
            )

        except Exception as e:
            logger.error("photo_message_error", error=str(e), user_id=update.effective_user.id)
            try:
                await update.message.reply_text(
                    "An error occurred while processing your screenshot. Please try again."
                )
            except Exception as reply_error:
                logger.error(
                    "photo_message_reply_error",
                    error=str(reply_error),
                    user_id=update.effective_user.id,
                )

    def _create_bet_record(
        self,
        associate_id: int,
        bookmaker_id: int,
        chat_id: str,
        message_id: str,
        screenshot_path: str,
    ) -> int:
        """
        Create a bet record in the database.

        Args:
            associate_id: ID of the associate
            bookmaker_id: ID of the bookmaker
            chat_id: Telegram chat ID
            message_id: Telegram message ID
            screenshot_path: Path to the saved screenshot

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
                    created_at_utc,
                    updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
