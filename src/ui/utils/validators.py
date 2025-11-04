"""Input validation utilities for Streamlit UI forms.

Provides validators for:
- Currency codes (ISO 4217)
- Associate aliases
- Bookmaker names
- JSON format validation
"""

from typing import Tuple, Optional
import sqlite3
import json

# Valid ISO 4217 currency codes supported by the system
VALID_CURRENCIES = [
    "EUR",  # Euro
    "GBP",  # British Pound
    "USD",  # US Dollar
    "AUD",  # Australian Dollar
    "CAD",  # Canadian Dollar
    "CHF",  # Swiss Franc
    "JPY",  # Japanese Yen
    "CNY",  # Chinese Yuan
]


def validate_currency(currency_code: str) -> Tuple[bool, str]:
    """Validate currency code against supported ISO codes.

    Args:
        currency_code: Currency code to validate (e.g., "EUR", "USD")

    Returns:
        Tuple of (is_valid: bool, error_message: str)
        If valid, error_message is empty string.
    """
    if not currency_code:
        return False, "Currency code is required"

    currency_upper = currency_code.strip().upper()

    if currency_upper not in VALID_CURRENCIES:
        return False, f"Invalid currency code. Supported: {', '.join(VALID_CURRENCIES)}"

    return True, ""


def validate_alias(
    alias: str, exclude_id: Optional[int] = None, db_connection: Optional[sqlite3.Connection] = None
) -> Tuple[bool, str]:
    """Validate associate alias for uniqueness and format.

    Args:
        alias: Display alias to validate
        exclude_id: Optional associate ID to exclude from uniqueness check (for edits)
        db_connection: Database connection for uniqueness check

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    if not alias or not alias.strip():
        return False, "Alias is required"

    alias_stripped = alias.strip()

    if len(alias_stripped) > 50:
        return False, "Alias too long (max 50 characters)"

    # Check uniqueness if database connection provided
    if db_connection:
        cursor = db_connection.cursor()
        if exclude_id:
            cursor.execute(
                "SELECT COUNT(*) FROM associates WHERE display_alias = ? AND id != ?",
                (alias_stripped, exclude_id),
            )
        else:
            cursor.execute(
                "SELECT COUNT(*) FROM associates WHERE display_alias = ?",
                (alias_stripped,),
            )

        count = cursor.fetchone()[0]
        if count > 0:
            return False, "Alias already exists"

    return True, ""


def validate_multibook_chat_id(chat_id: Optional[str]) -> Tuple[bool, str]:
    """Validate Telegram multibook chat ID format.

    Args:
        chat_id: Optional Telegram chat ID

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    if not chat_id or not chat_id.strip():
        return True, ""  # Optional field

    chat_id_stripped = chat_id.strip()

    # Telegram chat IDs can be negative for groups/channels
    if not chat_id_stripped.lstrip("-").isdigit():
        return False, "Chat ID must be a number (e.g., 123456789 or -100123456789)"

    return True, ""


def validate_json(json_string: Optional[str]) -> Tuple[bool, str]:
    """Validate JSON string format.

    Args:
        json_string: JSON string to validate (optional)

    Returns:
        Tuple of (is_valid: bool, error_message: str)
        Returns (True, "") for empty/None input (optional field)
    """
    if not json_string or not json_string.strip():
        return True, ""  # Empty is valid (optional field)

    try:
        json.loads(json_string)
        return True, ""
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {str(e)}"


def validate_balance_amount(amount_str: str) -> Tuple[bool, str]:
    """Validate balance amount is positive with max 2 decimals.

    Args:
        amount_str: String representation of balance amount

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    from decimal import Decimal, InvalidOperation

    if not amount_str or not amount_str.strip():
        return False, "Balance amount is required"

    try:
        amount = Decimal(amount_str.strip())
    except (InvalidOperation, ValueError):
        return False, "Invalid amount format"

    if amount <= 0:
        return False, "Balance must be positive"

    # Check max 2 decimal places
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return False, "Max 2 decimal places"

    return True, ""


def validate_currency_code(currency_code: str) -> bool:
    """Simple currency code validation for drawer components.
    
    Args:
        currency_code: Currency code to validate
        
    Returns:
        True if valid, False otherwise
    """
    is_valid, _ = validate_currency(currency_code)
    return is_valid


def validate_decimal_input(amount_str: str) -> Optional[object]:
    """Validate and convert decimal string input.
    
    Args:
        amount_str: String representation of decimal amount
        
    Returns:
        Decimal object if valid, None otherwise
    """
    from decimal import Decimal, InvalidOperation
    
    if not amount_str or not amount_str.strip():
        return None
        
    try:
        return Decimal(amount_str.strip())
    except (InvalidOperation, ValueError):
        return None
