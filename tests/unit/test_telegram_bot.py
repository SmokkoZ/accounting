"""
Unit tests for Telegram Bot functionality.

Tests cover:
- Command handlers (/start, /help, /register)
- Photo message handling
- Database operations
- Error handling
"""

import asyncio
import os
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Update, Message, User, Chat
from telegram.ext import ContextTypes

from src.integrations.telegram_bot import TelegramBot
from src.services.funding_transaction_service import FundingTransactionError


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    with patch("src.integrations.telegram_bot.Config") as mock:
        mock.TELEGRAM_BOT_TOKEN = "test_token_12345"
        mock.SCREENSHOT_DIR = tempfile.mkdtemp()
        yield mock


@pytest.fixture
def mock_db_connection():
    """Mock database connection."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = {"id": 1}
    mock_cursor.lastrowid = 123
    mock_conn.close = MagicMock()
    return mock_conn


@pytest.fixture
def mock_db_connection_with_registration():
    """Mock database connection with registration data."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    # Mock associate query
    associate_result = {"id": 1}
    bookmaker_result = {"id": 2}
    registration_result = {
        "associate_id": 1,
        "bookmaker_id": 2,
        "associate_alias": "Alice",
        "bookmaker_name": "Bet365",
    }

    # Configure fetchone to return different results based on query
    def fetchone_side_effect():
        # This will be called multiple times, return appropriate results
        if not hasattr(fetchone_side_effect, "call_count"):
            fetchone_side_effect.call_count = 0

        fetchone_side_effect.call_count += 1

        if fetchone_side_effect.call_count == 1:  # First associate query
            return associate_result
        elif fetchone_side_effect.call_count == 2:  # Bookmaker query
            return bookmaker_result
        elif fetchone_side_effect.call_count == 3:  # Registration query
            return registration_result
        return None

    mock_cursor.fetchone.side_effect = fetchone_side_effect
    mock_cursor.lastrowid = 123
    mock_conn.close = MagicMock()
    return mock_conn


@pytest.fixture
def mock_update():
    """Create a mock Telegram Update object."""
    mock_update = MagicMock(spec=Update)
    mock_user = MagicMock(spec=User)
    mock_user.id = 12345
    mock_chat = MagicMock(spec=Chat)
    mock_chat.id = 67890
    mock_message = MagicMock(spec=Message)
    mock_message.reply_text = AsyncMock()
    mock_message.photo = [MagicMock()]  # Mock photo array
    mock_message.message_id = 999
    mock_update.effective_user = mock_user
    mock_update.effective_chat = mock_chat
    mock_update.message = mock_message
    return mock_update


@pytest.fixture
def mock_context():
    """Create a mock Telegram Context object."""
    mock_context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    mock_context.args = []
    return mock_context


@pytest.fixture
def telegram_bot(mock_config):
    """Create a TelegramBot instance for testing."""
    return TelegramBot()


class TestTelegramBotInitialization:
    """Test Telegram bot initialization."""

    def test_bot_initialization_with_token(self, mock_config):
        """Test bot initializes successfully with valid token."""
        bot = TelegramBot()
        assert bot.bot_token == "test_token_12345"
        assert bot.application is not None

    def test_bot_initialization_fails_without_token(self):
        """Test bot initialization fails without token."""
        with patch("src.integrations.telegram_bot.Config") as mock:
            mock.TELEGRAM_BOT_TOKEN = None
            with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN not configured"):
                TelegramBot()


class TestPendingConfirmationParsing:
    """Validate parsing logic for text-based confirmations."""

    def test_parse_confirm_with_stake_and_win(self, telegram_bot):
        result = telegram_bot._parse_pending_confirmation_text("ingest \u20ac25 win=$40")
        assert result["action"] == "confirm"
        assert result["stake_amount"] == Decimal("25")
        assert result["stake_currency"] == "EUR"
        assert result["win_amount"] == Decimal("40")
        assert result["win_currency"] == "USD"

    def test_parse_discard_command(self, telegram_bot):
        result = telegram_bot._parse_pending_confirmation_text("#skip")
        assert result["action"] == "discard"
        assert result["stake_amount"] is None
        assert result["win_amount"] is None

    def test_parse_amount_only_message(self, telegram_bot):
        result = telegram_bot._parse_pending_confirmation_text("30.5 win=45.1")
        assert result["action"] == "amount_only"
        assert result["stake_amount"] == Decimal("30.5")
        assert result["win_amount"] == Decimal("45.1")

    def test_parse_amount_invalid_raises(self, telegram_bot):
        with pytest.raises(ValueError):
            telegram_bot._parse_amount_token("abc123xyz")


class TestCommandHandlers:
    """Test command handlers."""

    @pytest.mark.asyncio
    async def test_start_command(self, telegram_bot, mock_update, mock_context):
        """Test /start command handler."""
        await telegram_bot._start_command(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once_with("Surebet Bot Ready")

    @pytest.mark.asyncio
    async def test_help_command(self, telegram_bot, mock_update, mock_context):
        """Test /help command handler."""
        await telegram_bot._help_command(mock_update, mock_context)
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Available commands:" in call_args
        assert "/start" in call_args
        assert "/help" in call_args
        assert "/register" in call_args

    # ------------------------------------------------------------------
    # Funding text command parsing
    # ------------------------------------------------------------------

    def test_parse_funding_command_valid(self, telegram_bot):
        assert telegram_bot._parse_funding_command("deposit 500") == ("DEPOSIT", 500.0)
        assert telegram_bot._parse_funding_command("Withdraw 250.75") == ("WITHDRAWAL", 250.75)
        assert telegram_bot._parse_funding_command("  deposit   1  ") == ("DEPOSIT", 1.0)

    def test_parse_funding_command_invalid(self, telegram_bot):
        # Not a funding command
        assert telegram_bot._parse_funding_command("hello world") is None
        # Invalid amounts
        with pytest.raises(ValueError):
            telegram_bot._parse_funding_command("deposit 0")
        with pytest.raises(ValueError):
            telegram_bot._parse_funding_command("withdraw -10")

    @pytest.mark.asyncio
    async def test_text_message_unregistered_chat(self, telegram_bot, mock_update, mock_context):
        # Ensure message text
        mock_update.message.text = "deposit 10"

        # Patch registration lookup to None
        with patch.object(TelegramBot, "_get_registration", return_value=None):
            await telegram_bot._text_message(mock_update, mock_context)

        # Should instruct to register
        mock_update.message.reply_text.assert_called()
        args = mock_update.message.reply_text.call_args[0][0]
        assert "not registered" in args.lower()

    @pytest.mark.asyncio
    async def test_text_message_admin_path_requires_confirmation(self, telegram_bot, mock_update, mock_context):
        mock_update.message.text = "deposit 12.5"
        telegram_bot.admin_user_ids.add(mock_update.effective_user.id)

        registration = {
            "associate_id": 1,
            "bookmaker_id": 2,
            "associate_alias": "Alice",
            "bookmaker_name": "Bet365",
            "associate_is_admin": False,
        }

        with patch.object(TelegramBot, "_get_registration", return_value=registration), \
             patch.object(TelegramBot, "_get_associate_home_currency", return_value="EUR"), \
             patch.object(telegram_bot, "_generate_admin_token", return_value="123456"):
            await telegram_bot._text_message(mock_update, mock_context)

        mock_update.message.reply_text.assert_called()
        text = mock_update.message.reply_text.call_args[0][0]
        assert "Security check" in text
        assert "123456" in text
        assert "123456" in telegram_bot._pending_admin_confirmations

    @pytest.mark.asyncio
    async def test_admin_confirmation_flow_records_ledger(self, telegram_bot, mock_update, mock_context):
        mock_update.message.text = "deposit 25"
        telegram_bot.admin_user_ids.add(mock_update.effective_user.id)
        chat_id = str(mock_update.effective_chat.id)

        registration = {
            "associate_id": 1,
            "bookmaker_id": 2,
            "associate_alias": "Alice",
            "bookmaker_name": "Bet365",
            "associate_is_admin": False,
        }

        with patch.object(TelegramBot, "_get_registration", return_value=registration), \
             patch.object(TelegramBot, "_get_associate_home_currency", return_value="EUR"), \
             patch.object(telegram_bot, "_generate_admin_token", return_value="654321"):
            await telegram_bot._text_message(mock_update, mock_context)

        assert "654321" in telegram_bot._pending_admin_confirmations

        with patch("src.services.funding_transaction_service.FundingTransactionService") as mock_svc:
            instance = mock_svc.return_value.__enter__.return_value
            instance.record_transaction.return_value = "L999"
            await telegram_bot._process_admin_confirmation(
                token="654321",
                chat_id=chat_id,
                user_id=mock_update.effective_user.id,
                message=mock_update.message,
            )

        assert instance.record_transaction.called
        assert "654321" not in telegram_bot._pending_admin_confirmations
        assert mock_update.message.reply_text.call_args_list[-1][0][0].startswith("Approved:")

    @pytest.mark.asyncio
    async def test_admin_confirmation_handles_fx_failure(self, telegram_bot, mock_update, mock_context):
        mock_update.message.text = "deposit 50"
        telegram_bot.admin_user_ids.add(mock_update.effective_user.id)
        chat_id = str(mock_update.effective_chat.id)

        registration = {
            "associate_id": 1,
            "bookmaker_id": 2,
            "associate_alias": "Alice",
            "bookmaker_name": "Bet365",
            "associate_is_admin": False,
        }

        with patch.object(TelegramBot, "_get_registration", return_value=registration), \
             patch.object(TelegramBot, "_get_associate_home_currency", return_value="EUR"), \
             patch.object(telegram_bot, "_generate_admin_token", return_value="777777"):
            await telegram_bot._text_message(mock_update, mock_context)

        with patch("src.services.funding_transaction_service.FundingTransactionService") as mock_svc:
            instance = mock_svc.return_value.__enter__.return_value
            instance.record_transaction.side_effect = FundingTransactionError("FX lookup failed")
            await telegram_bot._process_admin_confirmation(
                token="777777",
                chat_id=chat_id,
                user_id=mock_update.effective_user.id,
                message=mock_update.message,
            )

        # Context should remain so admin can retry
        assert "777777" in telegram_bot._pending_admin_confirmations
        assert "Approval failed" in mock_update.message.reply_text.call_args_list[-1][0][0]

    @pytest.mark.asyncio
    async def test_text_message_associate_path_creates_draft(self, telegram_bot, mock_update, mock_context):
        mock_update.message.text = "withdraw 15"

        registration = {
            "associate_id": 5,
            "bookmaker_id": 9,
            "associate_alias": "Bob",
            "bookmaker_name": "PinBet",
            "associate_is_admin": False,
        }

        with patch.object(TelegramBot, "_get_registration", return_value=registration), \
             patch.object(TelegramBot, "_get_associate_home_currency", return_value="GBP"), \
             patch("src.services.funding_service.FundingService") as mock_service_cls:
            mock_service = mock_service_cls.return_value
            mock_service.create_funding_draft.return_value = "draft-xyz"

            await telegram_bot._text_message(mock_update, mock_context)

            mock_service.create_funding_draft.assert_called_once()
            kwargs = mock_service.create_funding_draft.call_args.kwargs
            assert kwargs["source"] == "telegram"
            assert kwargs["chat_id"] == str(mock_update.effective_chat.id)
            assert kwargs["event_type"] == "WITHDRAWAL"

        assert mock_update.message.reply_text.call_args_list[-1][0][0].startswith("Submitted for approval")

    @pytest.mark.asyncio
    async def test_register_command_success(self, telegram_bot, mock_update, mock_context):
        """Test /register command with valid arguments."""
        mock_context.args = ["Alice", "Bet365"]

        # Create a fresh mock connection for this test
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # Set up the expected sequence of database queries
        # 1st call: validate associate exists
        # 2nd call: validate bookmaker exists
        # 3rd call: get associate ID for storage
        # 4th call: get bookmaker ID for storage
        mock_cursor.fetchone.side_effect = [
            {"id": 1},  # Associate validation
            {"id": 2},  # Bookmaker validation
            {"id": 1},  # Associate ID for storage
            {"id": 2},  # Bookmaker ID for storage
        ]
        mock_conn.commit = MagicMock()
        mock_conn.close = MagicMock()

        with patch("src.integrations.telegram_bot.get_db_connection", return_value=mock_conn):
            await telegram_bot._register_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Chat 67890 successfully registered for Alice at Bet365" in call_args

    @pytest.mark.asyncio
    async def test_register_command_invalid_args(self, telegram_bot, mock_update, mock_context):
        """Test /register command with invalid arguments."""
        mock_context.args = ["Alice"]  # Missing bookmaker

        await telegram_bot._register_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Usage: /register <associate_alias> <bookmaker_name>" in call_args

    @pytest.mark.asyncio
    async def test_register_command_invalid_entities(
        self, telegram_bot, mock_update, mock_context, mock_db_connection
    ):
        """Test /register command with invalid associate/bookmaker."""
        mock_context.args = ["InvalidUser", "InvalidBookmaker"]
        mock_db_connection.cursor.return_value.fetchone.return_value = None  # No results found

        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection,
        ):
            await telegram_bot._register_command(mock_update, mock_context)

        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Invalid associate 'InvalidUser' or bookmaker 'InvalidBookmaker'" in call_args


class TestPhotoMessageHandling:
    """Test photo message handling."""

    @pytest.mark.asyncio
    async def test_photo_message_success(
        self,
        telegram_bot,
        mock_update,
        mock_context,
        mock_db_connection_with_registration,
    ):
        """Test successful photo message handling with valid registration."""
        # Mock photo file download
        mock_photo_file = MagicMock()
        mock_photo_file.download_to_drive = AsyncMock()
        mock_update.message.photo[-1].get_file = AsyncMock(return_value=mock_photo_file)

        # Mock _get_registration to return valid registration
        registration = {
            "associate_id": 1,
            "bookmaker_id": 2,
            "associate_alias": "Alice",
            "bookmaker_name": "Bet365",
        }

        with patch.object(telegram_bot, "_get_registration", return_value=registration):
            with patch(
                "src.integrations.telegram_bot.get_db_connection",
                return_value=mock_db_connection_with_registration,
            ):
                with patch("pathlib.Path.mkdir"):
                    with patch("pathlib.Path.exists", return_value=False):
                        await telegram_bot._photo_message(mock_update, mock_context)

        # Verify screenshot was downloaded
        mock_photo_file.download_to_drive.assert_called_once()

        # Verify database insertion
        mock_db_connection_with_registration.cursor.return_value.execute.assert_called()
        mock_db_connection_with_registration.commit.assert_called_once()

        # Verify reply message contains confirmation prompt and buttons
        mock_update.message.reply_text.assert_called_once()
        prompt_text = mock_update.message.reply_text.call_args[0][0]
        assert "Screenshot saved for Alice / Bet365" in prompt_text
        assert "Auto-discard after 60 minutes" in prompt_text
        assert "reply_markup" in mock_update.message.reply_text.call_args.kwargs

    @pytest.mark.asyncio
    async def test_photo_message_unregistered_chat(self, telegram_bot, mock_update, mock_context):
        """Test photo message handling for unregistered chat."""
        # Mock _get_registration to return None (unregistered)
        with patch.object(telegram_bot, "_get_registration", return_value=None):
            await telegram_bot._photo_message(mock_update, mock_context)

        # Verify rejection message
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "This chat is not registered" in call_args

    @pytest.mark.asyncio
    async def test_photo_message_with_filename_collision(
        self,
        telegram_bot,
        mock_update,
        mock_context,
        mock_db_connection_with_registration,
    ):
        """Test photo message handling with file naming collision."""
        # Mock photo file download
        mock_photo_file = MagicMock()
        mock_photo_file.download_to_drive = AsyncMock()
        mock_update.message.photo[-1].get_file = AsyncMock(return_value=mock_photo_file)

        # Mock _get_registration to return valid registration
        registration = {
            "associate_id": 1,
            "bookmaker_id": 2,
            "associate_alias": "Alice",
            "bookmaker_name": "Bet365",
        }

        # Mock file exists to simulate collision on first attempt
        exists_calls = [True, False]  # First file exists, second doesn't

        with patch.object(telegram_bot, "_get_registration", return_value=registration):
            with patch(
                "src.integrations.telegram_bot.get_db_connection",
                return_value=mock_db_connection_with_registration,
            ):
                with patch("pathlib.Path.mkdir"):
                    with patch("pathlib.Path.exists", side_effect=exists_calls):
                        await telegram_bot._photo_message(mock_update, mock_context)

        # Verify screenshot was downloaded
        mock_photo_file.download_to_drive.assert_called_once()

        # Verify reply message
        mock_update.message.reply_text.assert_called_once()
        prompt_text = mock_update.message.reply_text.call_args[0][0]
        assert "Screenshot saved for Alice / Bet365" in prompt_text
        assert "Auto-discard after 60 minutes" in prompt_text

    @pytest.mark.asyncio
    async def test_photo_message_error_handling(self, telegram_bot, mock_update, mock_context):
        """Test photo message error handling."""
        # Mock photo file to raise exception
        mock_photo_file = MagicMock()
        mock_photo_file.download_to_drive = AsyncMock(side_effect=Exception("Download failed"))
        mock_update.message.photo[-1].get_file = AsyncMock(return_value=mock_photo_file)

        # Mock _get_registration to return valid registration
        registration = {
            "associate_id": 1,
            "bookmaker_id": 2,
            "associate_alias": "Alice",
            "bookmaker_name": "Bet365",
        }

        with patch.object(telegram_bot, "_get_registration", return_value=registration):
            with patch("pathlib.Path.mkdir"):
                with patch("pathlib.Path.exists", return_value=False):
                    await telegram_bot._photo_message(mock_update, mock_context)

        # Verify error reply
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "An error occurred while queuing your screenshot" in call_args


class TestDatabaseOperations:
    """Test database operations."""

    def test_validate_associate_and_bookmaker_success(self, telegram_bot, mock_db_connection):
        """Test successful validation of associate and bookmaker."""
        # Mock database queries to return results
        mock_db_connection.cursor.return_value.fetchone.side_effect = [
            {"id": 1},  # Associate exists
            {"id": 1},  # Bookmaker exists
        ]

        # Mock connection close method
        mock_db_connection.close = MagicMock()

        # Patch the get_db_connection function to return our mock
        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection,
        ):
            result = telegram_bot._validate_associate_and_bookmaker("Alice", "Bet365")

        assert result is True

    def test_validate_associate_and_bookmaker_no_associate(self, telegram_bot, mock_db_connection):
        """Test validation when associate doesn't exist."""
        # Mock database query to return None for associate
        mock_db_connection.cursor.return_value.fetchone.return_value = None

        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection,
        ):
            result = telegram_bot._validate_associate_and_bookmaker("InvalidUser", "Bet365")

        assert result is False

    def test_validate_associate_and_bookmaker_no_bookmaker(self, telegram_bot, mock_db_connection):
        """Test validation when bookmaker doesn't exist."""
        # Mock database queries
        mock_db_connection.cursor.return_value.fetchone.side_effect = [
            {"id": 1},  # Associate exists
            None,  # Bookmaker doesn't exist
        ]

        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection,
        ):
            result = telegram_bot._validate_associate_and_bookmaker("Alice", "InvalidBookmaker")

        assert result is False

    def test_create_bet_record(self, telegram_bot, mock_db_connection):
        """Test creating bet record."""
        mock_db_connection.cursor.return_value.lastrowid = 456

        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection,
        ):
            bet_id = telegram_bot._create_bet_record(
                associate_id=1,
                bookmaker_id=2,
                chat_id="67890",
                message_id="999",
                screenshot_path="/path/to/screenshot.png",
            )

        assert bet_id == 456
        mock_db_connection.cursor.return_value.execute.assert_called_once()
        mock_db_connection.commit.assert_called_once()
        mock_db_connection.close.assert_called_once()


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.mark.asyncio
    async def test_rate_limiting_allows_first_command(
        self, telegram_bot, mock_update, mock_context
    ):
        """Test that rate limiting allows the first command."""
        # Set up a mock handler to track if it was called
        mock_handler = AsyncMock()

        # Wrap the handler with rate limiting
        wrapped_handler = telegram_bot._rate_limited(mock_handler)

        # Call the wrapped handler
        await wrapped_handler(mock_update, mock_context)

        # Verify the original handler was called
        mock_handler.assert_called_once_with(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_rate_limiting_blocks_rapid_commands(
        self, telegram_bot, mock_update, mock_context
    ):
        """Test that rate limiting blocks rapid commands."""
        # Set up a mock handler that doesn't call reply_text itself
        mock_handler = AsyncMock()

        # Wrap the handler with rate limiting
        wrapped_handler = telegram_bot._rate_limited(mock_handler)

        # Call the wrapped handler twice rapidly
        await wrapped_handler(mock_update, mock_context)
        await wrapped_handler(mock_update, mock_context)

        # Verify the original handler was called only once
        mock_handler.assert_called_once()

        # Verify rate limit message was sent (only the rate limit message)
        mock_update.message.reply_text.assert_called_once()
        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Rate limit exceeded" in call_args


class TestRegistrationStorage:
    """Test registration storage functionality."""

    def test_store_registration_success(self, telegram_bot, mock_db_connection_with_registration):
        """Test successful registration storage."""
        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection_with_registration,
        ):
            result = telegram_bot._store_registration("67890", "Alice", "Bet365")

        assert result is True
        mock_db_connection_with_registration.commit.assert_called_once()
        mock_db_connection_with_registration.close.assert_called_once()

    def test_store_registration_failure(self, telegram_bot, mock_db_connection):
        """Test registration storage failure when associate doesn't exist."""
        # Mock database to return None for associate query
        mock_db_connection.cursor.return_value.fetchone.return_value = None

        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection,
        ):
            result = telegram_bot._store_registration("67890", "InvalidUser", "Bet365")

        assert result is False

    def test_get_registration_success(self, telegram_bot, mock_db_connection):
        """Test successful registration retrieval."""
        mock_db_connection.cursor.return_value.fetchone.return_value = {
            "associate_id": 1,
            "bookmaker_id": 2,
            "associate_alias": "Alice",
            "bookmaker_name": "Bet365",
        }

        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection,
        ):
            result = telegram_bot._get_registration("67890")

        assert result is not None
        assert result["associate_id"] == 1
        assert result["bookmaker_id"] == 2
        assert result["associate_alias"] == "Alice"
        assert result["bookmaker_name"] == "Bet365"

    def test_get_registration_not_found(self, telegram_bot, mock_db_connection):
        """Test registration retrieval when not found."""
        # Mock database to return None
        mock_db_connection.cursor.return_value.fetchone.return_value = None

        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection,
        ):
            result = telegram_bot._get_registration("67890")

        assert result is None

    def test_create_bet_record_error(self, telegram_bot, mock_db_connection):
        """Test error handling when creating bet record."""
        mock_db_connection.cursor.return_value.execute.side_effect = Exception("Database error")

        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection,
        ):
            with pytest.raises(Exception, match="Database error"):
                telegram_bot._create_bet_record(
                    associate_id=1,
                    bookmaker_id=2,
                    chat_id="67890",
                    message_id="999",
                    screenshot_path="/path/to/screenshot.png",
                )

    def test_create_bet_record_with_manual_overrides(self, telegram_bot, mock_db_connection):
        """Ensure manual overrides are persisted when provided."""
        mock_cursor = mock_db_connection.cursor.return_value
        mock_cursor.lastrowid = 77

        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            return_value=mock_db_connection,
        ):
            bet_id = telegram_bot._create_bet_record(
                associate_id=1,
                bookmaker_id=2,
                chat_id="67890",
                message_id="999",
                screenshot_path="/path.png",
                manual_stake_override="25.00",
                manual_stake_currency="EUR",
                manual_win_override="40.00",
                manual_win_currency="EUR",
            )

        assert bet_id == 77
        args = mock_cursor.execute.call_args[0][1]
        assert "25.00" in args
        assert "40.00" in args
        mock_db_connection.commit.assert_called_once()


class TestOCRPipelineTrigger:
    """Test OCR pipeline trigger functionality."""

    @pytest.mark.asyncio
    async def test_trigger_ocr_pipeline_placeholder(self, telegram_bot):
        """Test OCR pipeline trigger placeholder logs correctly."""
        # This is a placeholder for Story 1.2, just verify it doesn't raise exceptions
        await telegram_bot._trigger_ocr_pipeline(123)
        # If we get here without exceptions, the test passes


class TestErrorHandling:
    """Test error handling in various scenarios."""

    @pytest.mark.asyncio
    async def test_start_command_error(self, telegram_bot, mock_update, mock_context):
        """Test error handling in start command."""
        mock_update.message.reply_text.side_effect = Exception("API error")

        # Should not raise exception, should handle gracefully
        await telegram_bot._start_command(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_help_command_error(self, telegram_bot, mock_update, mock_context):
        """Test error handling in help command."""
        mock_update.message.reply_text.side_effect = Exception("API error")

        # Should not raise exception, should handle gracefully
        await telegram_bot._help_command(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_register_command_error(self, telegram_bot, mock_update, mock_context):
        """Test error handling in register command."""
        mock_context.args = ["Alice", "Bet365"]
        mock_update.message.reply_text.side_effect = [
            Exception("API error"),
            Exception("Reply error"),
        ]

        with patch(
            "src.integrations.telegram_bot.get_db_connection",
            side_effect=Exception("DB error"),
        ):
            # Should not raise exception, should handle gracefully
            await telegram_bot._register_command(mock_update, mock_context)


class TestSignalHandling:
    """Test signal handling for graceful shutdown."""

    def test_signal_handler_setup(self, telegram_bot):
        """Test that bot initialization completes successfully."""
        # run_polling() handles SIGINT/SIGTERM internally
        # This test verifies successful initialization
        assert telegram_bot.application is not None
