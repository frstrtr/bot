"""Configuration loader for the bot.

Supports loading from .env file (preferred) with XML fallback for backwards compatibility.
"""
import os
import json
import logging
from typing import List, Dict, Set, Optional

# Try to load dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

from aiogram import Bot, Dispatcher
from aiogram.enums import ContentType
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

# Initialize logger
LOGGER = logging.getLogger(__name__)

# Define global variables
CHANNEL_IDS: List[int] = []
ADMIN_AUTOREPORTS: Optional[int] = None
TECHNO_LOGGING: Optional[int] = None
TECHNO_ORIGINALS: Optional[int] = None
TECHNO_UNHANDLED: Optional[int] = None
ADMIN_AUTOBAN: Optional[int] = None
ADMIN_MANBAN: Optional[int] = None
ADMIN_SUSPICIOUS: Optional[int] = None
TECHNO_RESTART: Optional[int] = None
TECHNO_IN: Optional[int] = None
TECHNO_OUT: Optional[int] = None
ADMIN_USER_ID: Optional[int] = None
SUPERADMIN_GROUP_ID: Optional[int] = None
TECHNO_NAMES: Optional[int] = None
CHANNEL_NAMES: List[str] = []
SPAM_TRIGGERS: List[str] = []
ALLOWED_FORWARD_CHANNELS: List[Dict] = []
ADMIN_GROUP_ID: Optional[int] = None
TECHNOLOG_GROUP_ID: Optional[int] = None
ALLOWED_FORWARD_CHANNEL_IDS: Set[int] = set()
MAX_TELEGRAM_MESSAGE_LENGTH: int = 4096
BOT_NAME: Optional[str] = None
BOT_USERID: Optional[int] = None
LOG_GROUP: Optional[str] = None
LOG_GROUP_NAME: Optional[str] = None
TECHNOLOG_GROUP: Optional[str] = None
TECHNOLOG_GROUP_NAME: Optional[str] = None
DP: Optional[Dispatcher] = None
BOT: Optional[Bot] = None
ALLOWED_UPDATES: List[str] = []
CHANNEL_DICT: Dict[int, str] = {}
ALLOWED_CONTENT_TYPES: List[ContentType] = []
API_TOKEN: Optional[str] = None
TECHNO_ADMIN: Optional[int] = None
ADMIN_ORDERS: Optional[int] = None
TELEGRAM_CHANNEL_BOT_ID: int = 136817688  # Telegram @Channel_bot ID
P2P_SERVER_URL: str = "http://localhost:8081"

# Established user detection settings (for skipping missed join banner)
ESTABLISHED_USER_MIN_MESSAGES: int = 10  # Minimum messages to be considered established
ESTABLISHED_USER_FIRST_MSG_DAYS: int = 90  # First message must be older than this (days)

# Threshold for flagging very new accounts (very high user IDs)
HIGH_USER_ID_THRESHOLD: int = 8_400_000_000


def _get_env_or_none(key: str) -> Optional[str]:
    """Get environment variable or return None."""
    value = os.getenv(key)
    return value if value else None


def _get_env_int(key: str, default: Optional[int] = None) -> Optional[int]:
    """Get environment variable as integer."""
    value = os.getenv(key)
    if value:
        try:
            return int(value)
        except ValueError:
            LOGGER.warning("Invalid integer value for %s: %s", key, value)
    return default


def _get_env_list(key: str, separator: str = ",") -> List[str]:
    """Get environment variable as list of strings."""
    value = os.getenv(key)
    if value:
        return [item.strip() for item in value.split(separator) if item.strip()]
    return []


def _get_env_int_list(key: str, separator: str = ",") -> List[int]:
    """Get environment variable as list of integers."""
    value = os.getenv(key)
    if value:
        result = []
        for item in value.split(separator):
            item = item.strip()
            if item:
                try:
                    result.append(int(item))
                except ValueError:
                    LOGGER.warning("Invalid integer in list for %s: %s", key, item)
        return result
    return []


def _get_env_json(key: str, default: Optional[list] = None) -> list:
    """Get environment variable as JSON-parsed list."""
    value = os.getenv(key)
    if value:
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            LOGGER.warning("Invalid JSON for %s: %s", key, e)
    return default if default is not None else []


def _get_allowed_content_types() -> List[ContentType]:
    """Get the list of allowed content types."""
    return [
        ContentType.TEXT,
        ContentType.AUDIO,
        ContentType.DOCUMENT,
        ContentType.GAME,
        ContentType.PHOTO,
        ContentType.STICKER,
        ContentType.VIDEO,
        ContentType.VIDEO_NOTE,
        ContentType.VOICE,
        ContentType.CONTACT,
        ContentType.LOCATION,
        ContentType.VENUE,
        ContentType.POLL,
        ContentType.DICE,
        ContentType.INVOICE,
        ContentType.SUCCESSFUL_PAYMENT,
        ContentType.CONNECTED_WEBSITE,
        ContentType.MIGRATE_TO_CHAT_ID,
        ContentType.MIGRATE_FROM_CHAT_ID,
    ]


def load_from_env() -> bool:
    """Load configuration from .env file.
    
    Returns:
        True if loaded successfully, False otherwise.
    """
    global CHANNEL_IDS, ADMIN_AUTOREPORTS, TECHNO_LOGGING, TECHNO_ORIGINALS, TECHNO_UNHANDLED
    global ADMIN_AUTOBAN, ADMIN_MANBAN, TECHNO_RESTART, TECHNO_IN, TECHNO_OUT, ADMIN_USER_ID, TECHNO_NAMES
    global CHANNEL_NAMES, SPAM_TRIGGERS, ADMIN_SUSPICIOUS, TECHNO_ADMIN, ADMIN_ORDERS
    global ALLOWED_FORWARD_CHANNELS, ADMIN_GROUP_ID, TECHNOLOG_GROUP_ID, SUPERADMIN_GROUP_ID
    global ALLOWED_FORWARD_CHANNEL_IDS, MAX_TELEGRAM_MESSAGE_LENGTH
    global BOT_NAME, BOT_USERID, LOG_GROUP, LOG_GROUP_NAME, TECHNOLOG_GROUP, TECHNOLOG_GROUP_NAME
    global DP, BOT, ALLOWED_UPDATES, CHANNEL_DICT, ALLOWED_CONTENT_TYPES
    global API_TOKEN, TELEGRAM_CHANNEL_BOT_ID, P2P_SERVER_URL
    global ESTABLISHED_USER_MIN_MESSAGES, ESTABLISHED_USER_FIRST_MSG_DAYS
    global HIGH_USER_ID_THRESHOLD

    # Check if BOT_TOKEN is set (required for .env mode)
    API_TOKEN = _get_env_or_none("BOT_TOKEN")
    if not API_TOKEN:
        return False

    LOGGER.info("Loading configuration from .env file")

    # Bot credentials
    BOT_NAME = _get_env_or_none("BOT_NAME") or "unknown_bot"
    BOT_USERID = int(API_TOKEN.split(":")[0])

    # Admin settings
    ADMIN_USER_ID = _get_env_int("ADMIN_USER_ID")
    SUPERADMIN_GROUP_ID = _get_env_int("SUPERADMIN_GROUP_ID")

    # Admin group
    ADMIN_GROUP_ID = _get_env_int("ADMIN_GROUP_ID")
    LOG_GROUP = str(ADMIN_GROUP_ID) if ADMIN_GROUP_ID else None
    LOG_GROUP_NAME = _get_env_or_none("ADMIN_GROUP_NAME") or "Admin Group"

    # Technolog group
    TECHNOLOG_GROUP_ID = _get_env_int("TECHNOLOG_GROUP_ID")
    TECHNOLOG_GROUP = str(TECHNOLOG_GROUP_ID) if TECHNOLOG_GROUP_ID else None
    TECHNOLOG_GROUP_NAME = _get_env_or_none("TECHNOLOG_GROUP_NAME") or "Technolog Group"

    # Admin group thread IDs
    ADMIN_AUTOREPORTS = _get_env_int("ADMIN_AUTOREPORTS", 1)
    ADMIN_AUTOBAN = _get_env_int("ADMIN_AUTOBAN", 1)
    ADMIN_MANBAN = _get_env_int("ADMIN_MANBAN", 1)
    ADMIN_SUSPICIOUS = _get_env_int("ADMIN_SUSPICIOUS", 1)
    ADMIN_ORDERS = _get_env_int("ADMIN_ORDERS", 1)

    # Technolog group thread IDs
    TECHNO_LOGGING = _get_env_int("TECHNO_LOGGING", 1)
    TECHNO_ORIGINALS = _get_env_int("TECHNO_ORIGINALS", 1)
    TECHNO_UNHANDLED = _get_env_int("TECHNO_UNHANDLED", 1)
    TECHNO_RESTART = _get_env_int("TECHNO_RESTART", 1)
    TECHNO_IN = _get_env_int("TECHNO_IN", 1)
    TECHNO_OUT = _get_env_int("TECHNO_OUT", 1)
    TECHNO_NAMES = _get_env_int("TECHNO_NAMES", 1)
    TECHNO_ADMIN = _get_env_int("TECHNO_ADMIN", 1)

    # Spam triggers
    SPAM_TRIGGERS = _get_env_list("SPAM_TRIGGERS")
    if not SPAM_TRIGGERS:
        SPAM_TRIGGERS = ["url", "email", "phone_number", "hashtag", "mention", 
                         "text_link", "mention_name", "cashtag", "bot_command"]

    # Monitored groups
    CHANNEL_IDS = _get_env_int_list("MONITORED_GROUPS")
    CHANNEL_NAMES = _get_env_list("MONITORED_GROUP_NAMES")
    
    # Build channel dict
    CHANNEL_DICT = {}
    for i, channel_id in enumerate(CHANNEL_IDS):
        channel_name = CHANNEL_NAMES[i] if i < len(CHANNEL_NAMES) else f"Group_{channel_id}"
        CHANNEL_DICT[channel_id] = channel_name

    # Allowed forward channels
    ALLOWED_FORWARD_CHANNELS = _get_env_json("ALLOWED_FORWARD_CHANNELS", [])
    ALLOWED_FORWARD_CHANNEL_IDS = {d["id"] for d in ALLOWED_FORWARD_CHANNELS if "id" in d}

    # P2P server
    P2P_SERVER_URL = _get_env_or_none("P2P_SERVER_URL") or "http://localhost:8081"

    # Established user detection settings
    ESTABLISHED_USER_MIN_MESSAGES = _get_env_int("ESTABLISHED_USER_MIN_MESSAGES", 10)
    ESTABLISHED_USER_FIRST_MSG_DAYS = _get_env_int("ESTABLISHED_USER_FIRST_MSG_DAYS", 90)

    # High user ID threshold for new accounts
    HIGH_USER_ID_THRESHOLD = _get_env_int("HIGH_USER_ID_THRESHOLD", 8_400_000_000)

    # Content types
    ALLOWED_CONTENT_TYPES = _get_allowed_content_types()

    # Initialize bot and dispatcher
    BOT = Bot(
        token=API_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    DP = Dispatcher()
    DP["forwarded_reports_states"] = {}
    ALLOWED_UPDATES = ["message", "chat_member", "callback_query"]

    TELEGRAM_CHANNEL_BOT_ID = 136817688

    return True


def load_config():
    """Load configuration from .env file."""
    if load_from_env():
        LOGGER.info("Configuration loaded from .env file")
        return
    
    LOGGER.error("Failed to load configuration from .env file! Make sure .env exists with all required variables.")


# Load configuration when the module is imported
load_config()
