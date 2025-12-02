"""Yet Another Telegram Bot for Spammers Detection and Reporting"""

# Force process timezone to Indian/Mauritius as early as possible
import os

os.environ.setdefault("TZ", "Indian/Mauritius")
try:
    import time as _time

    _time.tzset()  # Ensure the process picks up TZ on Unix
except AttributeError:
    pass  # tzset() not available on Windows

from datetime import timedelta
from datetime import datetime
import argparse
import asyncio
import random
import sqlite3
import json
import time
import html
import tracemalloc  # for memory usage debugging
import re
import ast  # evaluate dictionaries safely

import aiocron
from zoneinfo import ZoneInfo
import ssl
import certifi

import aiohttp
from aiogram import F
from aiogram.types import Message, CallbackQuery, ChatMemberUpdated
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.filters import Command
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramNotFound,
)

# Backward compatible exception aliases for aiogram 2.x -> 3.x migration
# In aiogram 3.x, exceptions are classified by HTTP status code, not by message
BadRequest = TelegramBadRequest
MessageToDeleteNotFound = TelegramBadRequest
MessageCantBeDeleted = TelegramBadRequest
MessageCantBeForwarded = TelegramBadRequest
MessageToForwardNotFound = TelegramBadRequest
MessageIdInvalid = TelegramBadRequest
MessageNotModified = TelegramBadRequest
InvalidQueryID = TelegramBadRequest
ChatNotFound = TelegramNotFound
Unauthorized = TelegramForbiddenError
ChatAdminRequired = TelegramForbiddenError
RetryAfter = TelegramRetryAfter

# import requests
# from PIL import Image
# from io import BytesIO
# from io import BytesIO
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# Import KeyboardBuilder from utils
from utils.utils import KeyboardBuilder


# load utilities
from utils.utils import (
    initialize_logger,
    construct_message_link,
    check_message_for_sentences,
    get_latest_commit_info,
    extract_spammer_info,
    get_daily_spam_filename,
    get_inout_filename,
    extract_status_change,
    message_sent_during_night,
    check_message_for_emojis,
    check_message_for_capital_letters,
    has_custom_emoji_spam,
    format_spam_report,
    extract_chat_name_and_message_id_from_link,
    get_channel_id_by_name,
    get_channel_name_by_id,
    has_spam_entities,
    load_predetermined_sentences,
    # get_spammer_details,  # Add this line
    store_message_to_db,
    db_init,
    create_inline_keyboard,
    check_user_legit,
    report_spam_2p2p,
    remove_spam_from_2p2p,
    report_spam_from_message,
    split_list,
    extract_username,
    make_lols_kb,
    build_lols_url,
    set_forwarded_state,
    safe_send_message,
    normalize_username,
    # User baselines DB functions
    save_user_baseline,
    get_user_baseline,
    get_active_user_baselines,
    update_user_baseline_status,
    # Whois lookup
    get_user_whois,
    format_whois_response,
)

# Track usernames already posted to TECHNO_NAMES to avoid duplicates in runtime
POSTED_USERNAMES = set()  # stores normalized usernames without '@'

# Duration in hours for user monitoring after join/leave events
MONITORING_DURATION_HOURS = 24
from utils.utils_decorators import (
    is_not_bot_action,
    is_forwarded_from_unknown_channel_message,
    is_admin_user_message,
    is_in_monitored_channel,
    is_valid_message,
)


# -----------------------------------------------------------------------------
# Helper: unified profile change logging
# -----------------------------------------------------------------------------
async def log_profile_change(
    user_id: int,
    username: str | None,
    context: str,
    chat_id: int | None,
    chat_title: str | None,
    changed: list[str],
    old_values: dict,
    new_values: dict,
    photo_changed: bool,
):
    """Log a profile change event using the existing in/out style format.

    Creates a line similar to greet_chat_members event_record, prefixed with 'pc'.
    Also appends to the inout_ log file so operators have a single chronological stream.
    """
    try:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        uname = username if username else "!UNDEFINED!"
        uname_fmt = f"@{uname}" if username else uname
        chat_repr = f"{chat_title or ''}({chat_id})" if chat_id else "(unknown chat)"
        # Build compact diffs old->new for changed fields
        diff_parts = []
        mapping = {
            "first name": ("first_name", "First"),
            "last name": ("last_name", "Last"),
            "username": ("username", "User"),
            "profile photo": ("photo_count", "Photo"),
        }
        for field in changed:
            key, label = mapping.get(field, (field, field))
            o = old_values.get(key)
            n = new_values.get(key)
            if key == "username":
                o = f"@{o}" if o else "!UNDEFINED!"
                n = f"@{n}" if n else "!UNDEFINED!"
            diff_parts.append(f"{label}='{o}'→'{n}'")
        photo_marker = " P" if photo_changed else ""
        record = f"{ts}: {user_id} PC[{context}{photo_marker}] {uname_fmt} in {chat_repr} changes: {', '.join(diff_parts)}\n"
        await save_report_file("inout_", "pc" + record)
        LOGGER.info(record.rstrip())
    except OSError as _e:  # silent failure should not break main flow
        LOGGER.debug("Failed to log profile change: %s", _e)


def make_profile_dict(
    first_name: str | None,
    last_name: str | None,
    username: str | None,
    photo_count: int | None,
) -> dict:
    """Return a normalized profile snapshot dict used for logging diffs.

    Ensures keys are consistent and missing values default to simple primitives.
    """
    return {
        "first_name": first_name or "",
        "last_name": last_name or "",
        "username": username or "",
        "photo_count": photo_count or 0,
    }


def format_username_for_log(username: str | None) -> str:
    """Format username for logging with @ prefix, or return !UNDEFINED! if no username.

    Args:
        username: The username string, may be None or empty

    Returns:
        Formatted string: '@username' or '!UNDEFINED!'
    """
    if not username or username == "!UNDEFINED!":
        return "!UNDEFINED!"
    return f"@{username}"


from utils.utils_config import (
    CHANNEL_IDS,
    ADMIN_AUTOREPORTS,
    # TECHNO_LOGGING,
    TECHNO_ADMIN,
    ADMIN_ORDERS,
    TECHNO_ORIGINALS,
    TECHNO_UNHANDLED,
    ADMIN_AUTOBAN,
    ADMIN_MANBAN,
    ADMIN_SUSPICIOUS,
    TECHNO_RESTART,
    TECHNO_IN,
    TECHNO_OUT,
    ADMIN_USER_ID,
    SUPERADMIN_GROUP_ID,
    TECHNO_NAMES,
    CHANNEL_NAMES,
    SPAM_TRIGGERS,
    ALLOWED_FORWARD_CHANNELS,
    ADMIN_GROUP_ID,
    TECHNOLOG_GROUP_ID,
    ALLOWED_FORWARD_CHANNEL_IDS,
    MAX_TELEGRAM_MESSAGE_LENGTH,
    BOT_NAME,
    BOT_USERID,
    LOG_GROUP,
    LOG_GROUP_NAME,
    TECHNOLOG_GROUP,
    TECHNOLOG_GROUP_NAME,
    DP,
    BOT,
    LOGGER,
    ALLOWED_UPDATES,
    CHANNEL_DICT,
    ALLOWED_CONTENT_TYPES,
    TELEGRAM_CHANNEL_BOT_ID,
    P2P_SERVER_URL,
    ESTABLISHED_USER_MIN_MESSAGES,
    ESTABLISHED_USER_FIRST_MSG_DAYS,
    HIGH_USER_ID_THRESHOLD,
)

# Parse command line arguments
parser = argparse.ArgumentParser(
    description="Run the bot with specified logging level."
)
parser.add_argument(
    "--log-level",
    type=str,
    default="DEBUG",  # Note: for production
    choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    help="Set the logging level (default: INFO)",
)
args = parser.parse_args()

# LOGGER init
LOGGER = initialize_logger(args.log_level)

# Log the chosen logging level
LOGGER.info("Logging level set to: %s", args.log_level)

tracemalloc.start()

# List of predetermined sentences to check for
PREDETERMINED_SENTENCES = load_predetermined_sentences("spam_dict.txt", LOGGER)

bot_start_time = datetime.now().strftime("%d-%m-%Y %H:%M:%S")


# Set to keep track of active user IDs
active_user_checks_dict = dict()
banned_users_dict = dict()

# Cache for chat usernames (chat_id -> username)
# Populated when processing messages, used for constructing public links
chat_username_cache: dict[int, str | None] = {}

# Bot username (populated on startup via get_me)
BOT_USERNAME: str | None = None

# Track messages that have been sent to autoreport to prevent duplicate suspicious notifications
# Key: (chat_id, message_id) - cleared periodically or on message processing completion
autoreported_messages: set[tuple[int, int]] = set()

# Track messages that have been sent to suspicious thread to prevent duplicate reports
# Key: (chat_id, message_id) - prevents same message being reported twice
suspicious_reported_messages: set[tuple[int, int]] = set()

# Track processed media groups to prevent duplicate reports for multi-photo messages
# Key: (chat_id, media_group_id) - cleared after 60 seconds
processed_media_groups: dict[tuple[int, str], float] = {}
MEDIA_GROUP_EXPIRY_SECONDS = 60  # How long to remember processed media groups


def was_autoreported(message: Message) -> bool:
    """Check if a message was already sent to autoreport thread."""
    return (message.chat.id, message.message_id) in autoreported_messages


def clear_autoreport_tracking(message: Message):
    """Clear autoreport tracking for a message after processing is complete."""
    autoreported_messages.discard((message.chat.id, message.message_id))


def was_suspicious_reported(message: Message) -> bool:
    """Check if a message was already sent to suspicious thread."""
    return (message.chat.id, message.message_id) in suspicious_reported_messages


def mark_suspicious_reported(message: Message):
    """Mark a message as sent to suspicious thread."""
    suspicious_reported_messages.add((message.chat.id, message.message_id))


def was_media_group_processed(message: Message) -> bool:
    """Check if a message's media group was already processed.
    
    Returns True if this message is part of a media group that was already processed,
    meaning we should skip duplicate processing for this message.
    Returns False if this is a standalone message or first message in media group.
    """
    if not message.media_group_id:
        return False  # Not a media group, process normally
    
    key = (message.chat.id, message.media_group_id)
    current_time = datetime.now().timestamp()
    
    # Clean up old entries
    expired_keys = [
        k for k, v in processed_media_groups.items() 
        if current_time - v > MEDIA_GROUP_EXPIRY_SECONDS
    ]
    for k in expired_keys:
        del processed_media_groups[k]
    
    # Check if already processed
    if key in processed_media_groups:
        return True  # Already processed, skip
    
    # Mark as processed
    processed_media_groups[key] = current_time
    return False  # First message in group, process it


def move_user_to_banned(
    user_id: int,
    ban_reason: str = None,
    ban_source: str = None,
    banned_by_admin_id: int = None,
    banned_by_admin_username: str = None,
    banned_in_chat_id: int = None,
    banned_in_chat_title: str = None,
    offense_type: str = None,
    offense_details: str = None,
    time_to_first_message: int = None,
    first_message_text: str = None,
    detected_by_lols: bool = None,
    detected_by_cas: bool = None,
    detected_by_p2p: bool = None,
    detected_by_local: bool = None,
    detected_by_admin: bool = None,
):
    """Move user from active checks to banned dict and update database.
    
    Args:
        user_id: The user ID to move
        ban_reason: Human-readable reason for the ban
        ban_source: Source of detection (lols/cas/p2p/local/admin/autoreport)
        banned_by_admin_id: Admin ID who performed the ban (if manual)
        banned_by_admin_username: Admin username
        banned_in_chat_id: Chat where offense occurred
        banned_in_chat_title: Chat title
        offense_type: Type of offense:
            - fast_message: Message within 10s of join
            - spam_pattern: Matched spam dictionary
            - bot_mention: Mentioned @...bot in message
            - hidden_mentions: Used invisible chars in mentions
            - forwarded_spam: Forwarded spam content
            - channel_spam: Spam via linked channel
            - high_id_spam: Very new account + spam indicators
        offense_details: JSON with additional details
        time_to_first_message: Seconds between join and first message
        first_message_text: The offending message (truncated)
        detected_by_*: Which systems flagged the user
    """
    if user_id in active_user_checks_dict:
        banned_users_dict[user_id] = active_user_checks_dict.pop(user_id, None)
    # Update database with full ban details
    update_user_baseline_status(
        CONN, user_id,
        monitoring_active=False,
        is_banned=True,
        ban_reason=ban_reason,
        ban_source=ban_source,
        banned_by_admin_id=banned_by_admin_id,
        banned_by_admin_username=banned_by_admin_username,
        banned_in_chat_id=banned_in_chat_id,
        banned_in_chat_title=banned_in_chat_title,
        offense_type=offense_type,
        offense_details=offense_details,
        time_to_first_message=time_to_first_message,
        first_message_text=first_message_text,
        detected_by_lols=detected_by_lols,
        detected_by_cas=detected_by_cas,
        detected_by_p2p=detected_by_p2p,
        detected_by_local=detected_by_local,
        detected_by_admin=detected_by_admin,
    )

# Dictionary to store running tasks by user ID
running_watchdogs = {}

# Dictionary to store running intensive watchdog tasks (triggered when user in active_checks posts a message)
running_intensive_watchdogs = {}

# Initialize the event
shutdown_event = asyncio.Event()

# Global aiohttp session for spam checks (initialized on startup, closed on shutdown)
_http_session: aiohttp.ClientSession | None = None
_http_connector: aiohttp.TCPConnector | None = None


def get_http_session() -> aiohttp.ClientSession:
    """Get or create the global HTTP session for spam checks."""
    global _http_session, _http_connector
    if _http_session is None or _http_session.closed:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        _http_connector = aiohttp.TCPConnector(ssl=ssl_context)
        _http_session = aiohttp.ClientSession(connector=_http_connector)
    return _http_session


async def close_http_session():
    """Close the global HTTP session."""
    global _http_session, _http_connector
    if _http_session is not None and not _http_session.closed:
        await _http_session.close()
        _http_session = None
    if _http_connector is not None and not _http_connector.closed:
        _http_connector.close()
        _http_connector = None


# Setting up SQLite Database
CONN = sqlite3.connect("messages.db")
CURSOR = CONN.cursor()
db_init(CURSOR, CONN)


def update_chat_username_cache(chat_id: int, username: str | None):
    """Update the chat username cache when we learn a chat's username."""
    if username:
        chat_username_cache[chat_id] = username
    elif chat_id not in chat_username_cache:
        chat_username_cache[chat_id] = None


def get_cached_chat_username(chat_id: int) -> str | None:
    """Get cached chat username, returns None if not cached or no username."""
    return chat_username_cache.get(chat_id)


def build_message_link(chat_id: int, message_id: int, chat_username: str | None = None) -> str:
    """Build a message link using chat username if available, falling back to cache or /c/ format.
    
    Args:
        chat_id: The chat ID
        message_id: The message ID
        chat_username: Optional chat username (if already known from message object)
    
    Returns:
        Message link in t.me/username/msgid or t.me/c/id/msgid format
    """
    # Use provided username, or check cache
    username = chat_username or get_cached_chat_username(chat_id)
    
    if username:
        return f"https://t.me/{username}/{message_id}"
    else:
        # Fallback to /c/ format for private/internal links
        chat_id_str = str(chat_id)
        if chat_id_str.startswith("-100"):
            chat_id_str = chat_id_str[4:]
        return f"https://t.me/c/{chat_id_str}/{message_id}"


def build_chat_link(chat_id: int, chat_username: str | None = None, chat_title: str | None = None) -> str:
    """Build a clickable HTML chat link using username if available.
    
    Args:
        chat_id: The chat ID
        chat_username: Optional chat username
        chat_title: Optional chat title for display text
    
    Returns:
        HTML link to chat
    """
    username = chat_username or get_cached_chat_username(chat_id)
    title = html.escape(chat_title or "Chat")
    
    if username:
        return f"<a href='https://t.me/{username}'>{title}</a>"
    else:
        chat_id_str = str(chat_id)
        if chat_id_str.startswith("-100"):
            chat_id_str = chat_id_str[4:]
        return f"<a href='https://t.me/c/{chat_id_str}'>{title}</a>"


def get_spammer_details(
    spammer_id,
    spammer_first_name,
    spammer_last_name,
    message_forward_date,
    forward_sender_name="",
    forward_from_chat_title="",
    forwarded_from_id=None,
    forwarded_from_chat_id=None,
    froward_sender_chat_id=None,
):
    """Function to get chat ID and message ID by sender name and date
    or if the message is a forward of a forward then using
    forwarded_from_id and message_forward_date.
    forwarded_from_username, forwarded_from_first_name,
    forward_from_last_name are used only for forwarded forwarded messages
    and reserved for future use
    """

    spammer_id = spammer_id or None
    spammer_last_name = spammer_last_name or ""

    spammer_id_str = f"{spammer_id if spammer_id is not None else '':10}"

    LOGGER.debug(
        "\033[93m%s getting chat ID and message ID\n"
        "\t\t\tfirstName : %s : lastName : %s,\n"
        "\t\t\tmessageForwardDate: %s, forwardedFromChatTitle: %s,\n"
        "\t\t\tforwardSenderName: %s, forwardedFromID: %s,\n"
        "\t\t\tforwardedFromChatID: %s, forwardSenderChatID: %s\033[0m",
        spammer_id_str,
        spammer_first_name,
        spammer_last_name,
        message_forward_date,
        forward_from_chat_title,
        forward_sender_name,
        forwarded_from_id,
        forwarded_from_chat_id,
        froward_sender_chat_id,
    )

    # Common SQL and parameters for both cases
    base_query = """
        SELECT chat_id, message_id, chat_username, user_id, user_name, user_first_name, user_last_name, received_date
        FROM recent_messages
        WHERE {condition} AND new_chat_member IS NULL AND left_chat_member IS NULL
        ORDER BY received_date DESC
        LIMIT 1
    """
    params = {
        "message_forward_date": message_forward_date,
        "sender_first_name": spammer_first_name,
        "sender_last_name": spammer_last_name,
        "from_chat_title": forward_from_chat_title,
        "user_id": spammer_id,
        "forward_sender_name": forward_sender_name,
    }

    if (not forwarded_from_id) and (forward_sender_name != "Deleted Account"):
        # This is not a forwarded forwarded message
        condition = (
            "(user_first_name = :sender_first_name AND received_date = :message_forward_date)"
            " OR (user_id = :user_id)"
            " OR (from_chat_title = :from_chat_title)"
            " OR (user_id = :user_id AND user_first_name = :sender_first_name AND user_last_name = :sender_last_name)"
            " OR (forward_sender_name = :forward_sender_name AND forward_date = :message_forward_date)"
        )
    elif forward_sender_name == "Deleted Account":
        # Manage Deleted Account by message date only
        condition = "received_date = :message_forward_date"
        params = {
            "message_forward_date": message_forward_date,
        }
    elif spammer_id:
        # This is a forwarded forwarded message with known user_id
        condition = (
            "(user_id = :user_id)"
            " OR (user_id = :user_id AND user_first_name = :sender_first_name AND user_last_name = :sender_last_name)"
        )
        # Note: forward_date/forwarded_from_id not needed here - condition only uses user_id

    else:
        # This is a forwarded forwarded message
        condition = (
            "forwarded_from_id = :forwarded_from_id AND forward_date = :forward_date"
        )
        params.update(
            {
                "forward_date": message_forward_date,
                "forwarded_from_id": forwarded_from_id,
            }
        )

    query = base_query.format(condition=condition)
    result = CURSOR.execute(query, params).fetchone()

    # Ensure result is not None before accessing its elements
    if result is None:
        LOGGER.error(
            "\033[91mNo result found for the given query and parameters. #GSD\033[0m"
        )
        return None

    if not spammer_first_name:
        spammer_first_name, spammer_last_name = (
            result[5],
            result[6],
        )  # get names from db

    # Ensure result[3] is not None before formatting
    result_3_formatted = f"{result[3]:10}" if result[3] is not None else " " * 10

    LOGGER.info(
        "\033[92m%-10s - result for sender: %s %s, date: %s, from chat title: %s\033[0m\n\t\t\tResult: %s",
        result_3_formatted,  # padding left align 10 chars
        spammer_first_name,
        spammer_last_name,
        message_forward_date,
        forward_from_chat_title,
        result,
    )

    return result


async def submit_autoreport(message: Message, reason):
    """Function to take heuristically invoked action on the message."""

    LOGGER.info(
        # "%-10s : %s. Sending automated report to the admin group for review...",
        "%s. Sending automated report to the admin group for review...",
        # f"{message.from_user.id:10}",
        reason,
    )

    # Track this message as autoreported to prevent duplicate suspicious notifications
    autoreported_messages.add((message.chat.id, message.message_id))

    # Use the current date if message.forward_date is None
    # forward_date = message.forward_date if message.forward_date else datetime.now()
    tobot_forward_date = message.date

    # DEBUG
    # LOGGER.debug("DEBUG")
    # LOGGER.debug("Message: %s", message)
    # LOGGER.debug("message.forward_date: %s", message.forward_date)
    # LOGGER.debug("message.date: %s", message.date)
    # LOGGER.debug("forward_date: %s", tobot_forward_date)
    # LOGGER.debug("DEBUG")

    # process the message automatically
    found_message_data = get_spammer_details(
        message.from_user.id,
        message.from_user.first_name,
        message.from_user.last_name,
        tobot_forward_date,  # to see the script latency and reaction time
        message.forward_sender_name,
        message.forward_from_chat.title if message.forward_from_chat else None,
        forwarded_from_id=message.from_user.id,
        forwarded_from_chat_id=(
            message.forward_from_chat.id if message.forward_from_chat else None
        ),
        froward_sender_chat_id=message.sender_chat.id if message.sender_chat else None,
    )
    await handle_autoreports(
        message,
        message.from_user.id,
        message.from_user.first_name,
        message.from_user.last_name,
        message.forward_from_chat.title if message.forward_from_chat else None,
        message.forward_sender_name,
        found_message_data,
        reason=reason,
    )
    return True


async def on_startup():
    """Function to handle the bot startup."""
    global BOT_USERNAME
    _commit_info = get_latest_commit_info(LOGGER)

    # Get bot info and store username for command detection
    try:
        bot_info = await BOT.get_me()
        BOT_USERNAME = bot_info.username
        LOGGER.info("Bot username: @%s", BOT_USERNAME)
    except TelegramBadRequest as e:
        LOGGER.error("Failed to get bot info: %s", e)
        BOT_USERNAME = None

    # Pre-populate chat username cache for monitored channels
    LOGGER.info("Populating chat username cache for %d monitored channels...", len(CHANNEL_IDS))
    for chat_id in CHANNEL_IDS:
        try:
            chat = await BOT.get_chat(chat_id)
            update_chat_username_cache(chat_id, chat.username)
            if chat.username:
                LOGGER.debug("Cached username for %s: @%s", chat.title, chat.username)
        except TelegramBadRequest as e:
            LOGGER.warning("Could not get chat info for %s: %s", chat_id, e)
    LOGGER.info("Chat username cache populated with %d entries", len(chat_username_cache))

    bot_start_log_message = (
        f"\033[95m\nBot restarted at {bot_start_time}\n{'-' * 40}\n"
        f"Commit info: {_commit_info}\n"
        "Финальная битва между людьми и роботами...\033[0m\n"
    )
    bot_start_message = (
        f"Bot restarted at {bot_start_time}\n{'-' * 40}\n"
        f"Commit info: {_commit_info}\n"
        "Финальная битва между людьми и роботами..."
    )
    LOGGER.info(bot_start_log_message)

    # NOTE Leave chats which is not in settings file
    # await BOT.leave_chat(-1002174154456)
    # await BOT.leave_chat(-1001876523135) # @lalaland_classy

    # start message to the Technolog group
    await safe_send_message(
        BOT,
        TECHNOLOG_GROUP_ID,
        bot_start_message,
        LOGGER,
        message_thread_id=TECHNO_RESTART,
    )

    # List of user IDs to check for Deleted Accounts
    # if the user is not in the chat, the bot will not be able to get the user info
    # Deleted Accounts have first_name = ""

    # async def check_user_status(chat_id: int, user_id: int):
    #     try:
    #         member = await BOT.get_chat_member(chat_id, user_id)
    #         LOGGER.debug("Checking user %s: %s", user_id, member.user)
    #     except Exception as e:
    #         LOGGER.error("Error checking user %s: %s", user_id, e)
    #         return False

    # for user_id in user_ids:
    #     await check_user_status(chat_id, user_id)

    # DELETE MESSAGE once the bot is started
    # https://t.me/chatname/threadID/message
    # try:
    #     await BOT.delete_message(-1001711422922, 81235)
    # except MessageToDeleteNotFound as e:
    #     LOGGER.error("Error deleting message: %s", e)
    # except Exception as e:
    #     LOGGER.error("Error deleting message: %s", e)
    # https://t.me/123/127041
    # https://t.me/123/1/81190
    # await BOT.delete_message(-1002331876, 81190)
    # await lols_autoban(5697700097, "on_startup event", "banned during on_startup event")

    # Call the function to load and start checks
    asyncio.create_task(load_and_start_checks())


async def ban_rogue_chat_everywhere(
    rogue_chat_id: int, chan_list: list
) -> tuple[bool, str, str, list]:
    """ban chat sender chat for Rogue channels
    
    Returns:
        tuple: (success, channel_name, channel_username, failed_chats)
        - success: True if banned in all chats, False if any failures
        - channel_name: Name of the rogue channel
        - channel_username: Username of the rogue channel
        - failed_chats: List of (chat_id, error_message) tuples for failed bans
    """
    failed_chats = []  # List of (chat_id, error) tuples
    success_count = 0

    # Try to get chat information, handle case where bot is not a member
    try:
        chat = await BOT.get_chat(rogue_chat_id)
        rogue_chat_name = chat.title if chat.title else "!ROGUECHAT!"
        rogue_chat_username = chat.username if chat.username else "!@ROGUECHAT!"
    except (Unauthorized, BadRequest) as e:
        # Bot is not a member of the channel or channel doesn't exist
        LOGGER.warning(
            "Cannot get chat info for rogue channel %s: %s. Using default names.",
            rogue_chat_id,
            str(e),
        )
        rogue_chat_name = "!ROGUECHAT!"
        rogue_chat_username = "!ROGUECHAT!"

    for chat_id in chan_list:
        try:
            await BOT.ban_chat_sender_chat(chat_id, rogue_chat_id)
            success_count += 1
            await asyncio.sleep(1)  # pause 1 sec
        except TelegramBadRequest as e:  # if user were Deleted Account while banning
            LOGGER.error(
                "%s:%s - error banning in chat (%s): %s. Deleted CHANNEL?",
                rogue_chat_id,
                format_username_for_log(rogue_chat_username),
                chat_id,
                e,
            )
            failed_chats.append((chat_id, str(e)))
            continue

    # report rogue chat to the p2p server
    await report_spam_2p2p(rogue_chat_id, LOGGER)
    await safe_send_message(
        BOT,
        TECHNOLOG_GROUP_ID,
        f"Channel {rogue_chat_name} @{rogue_chat_username}(<code>{rogue_chat_id}</code>) reported to P2P spamcheck server.",
        LOGGER,
        parse_mode="HTML",
        disable_web_page_preview=True,
        message_thread_id=TECHNO_ADMIN,
    )

    if failed_chats:
        LOGGER.error(
            "Failed to ban rogue channel %s @%s(%s) in %d chats: %s",
            rogue_chat_name,
            rogue_chat_username,
            rogue_chat_id,
            len(failed_chats),
            failed_chats,
        )
        return False, rogue_chat_name, rogue_chat_username, failed_chats
    else:
        LOGGER.info(
            "%s @%s(%s)  CHANNEL successfully banned in all %d chats",
            rogue_chat_name,
            rogue_chat_username,
            rogue_chat_id,
            success_count,
        )
        banned_users_dict[rogue_chat_id] = rogue_chat_username
        return True, rogue_chat_name, rogue_chat_username, []


async def unban_rogue_chat_everywhere(rogue_chat_id: int, chan_list: list) -> bool:
    """Unban chat sender chat for Rogue channels"""
    unban_rogue_chat_everywhere_error = None

    # Try to get chat information, handle case where bot is not a member
    try:
        chat = await BOT.get_chat(rogue_chat_id)
        rogue_chat_name = chat.title if chat.title else "!ROGUECHAT!"
        rogue_chat_username = chat.username if chat.username else "!@ROGUECHAT!"
    except (Unauthorized, BadRequest) as e:
        # Bot is not a member of the channel or channel doesn't exist
        LOGGER.warning(
            "Cannot get chat info for rogue channel %s during unban: %s. Using default names.",
            rogue_chat_id,
            str(e),
        )
        rogue_chat_name = "!ROGUECHAT!"
        rogue_chat_username = "!@ROGUECHAT!"

    for chat_id in chan_list:
        try:
            await BOT.unban_chat_sender_chat(chat_id, rogue_chat_id)
            # LOGGER.debug("%s  CHANNEL successfully unbanned in %s", rogue_chat_id, chat_id)
            await asyncio.sleep(1)  # pause 1 sec
        except TelegramBadRequest as e:  # if user were Deleted Account while unbanning
            # chat_name = get_channel_id_by_name(channel_dict, chat_id)
            LOGGER.error(
                "%s %s @%s - error unbanning in chat (%s): %s. Deleted CHANNEL?",
                rogue_chat_id,
                rogue_chat_name,
                rogue_chat_username,
                chat_id,
                e,
            )
            unban_rogue_chat_everywhere_error = str(e) + f" in {chat_id}"
            continue

    # Note:: Remove rogue chat from the p2p server report list?
    # await unreport_spam(rogue_chat_id, LOGGER)

    if unban_rogue_chat_everywhere_error:
        return unban_rogue_chat_everywhere_error
    else:
        LOGGER.info(
            "%s @%s(%s)  CHANNEL successfully unbanned where it was possible",
            rogue_chat_name,
            rogue_chat_username,
            rogue_chat_id,
        )
        if rogue_chat_id in banned_users_dict:
            del banned_users_dict[rogue_chat_id]
        return True, rogue_chat_name, rogue_chat_username


async def get_user_other_chats(
    user_id: int, exclude_chat_id: int, channel_ids: list, channel_dict: dict
) -> list:
    """
    Check which other monitored chats a user is still a member of.
    
    Args:
        user_id: The user ID to check
        exclude_chat_id: The chat ID to exclude (the chat user just left)
        channel_ids: List of all monitored channel IDs
        channel_dict: Dictionary mapping channel IDs to names
    
    Returns:
        List of tuples (chat_id, chat_name, chat_username) where user is still a member
    """
    other_chats = []
    for chat_id in channel_ids:
        if chat_id == exclude_chat_id:
            continue
        try:
            member = await BOT.get_chat_member(chat_id, user_id)
            # Check if user is actually a member (not left/kicked/restricted)
            if member.status in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.CREATOR,
            ):
                chat_name = channel_dict.get(chat_id, str(chat_id))
                chat_username = get_cached_chat_username(chat_id)
                other_chats.append((chat_id, chat_name, chat_username))
        except TelegramBadRequest as e:
            # User not in chat or bot can't access - skip silently
            LOGGER.debug(
                "Cannot check user %s in chat %s: %s", user_id, chat_id, e
            )
            continue
    return other_chats


def analyze_mentions_in_message(message) -> dict:
    """
    Analyze mentions in a message to detect:
    - All @username and text_mention entities
    - Hidden/invisible characters around mentions (used by spammers to obfuscate)
    - t.me/m/ profile deeplinks (spam recruitment links) - both in text and in text_link entities
    - Fake mentions: text_link entities with t.me/m/ URLs hidden under @username-like text
    - Plain @username patterns in text
    - Total count of mentions
    
    Args:
        message: Telegram message object
        
    Returns:
        dict with keys:
            - mentions: list of tuples (type, value, display_name) for buttons
            - total_count: total number of mention entities found
            - hidden_mentions: list of mentions with suspicious invisible chars
            - has_more: True if more than max_buttons mentions exist
            - tme_deeplinks: list of full t.me/m/ URLs found
            - fake_mentions: list of dicts with visible_text and hidden_url for deceptive links
    """
    # Invisible/zero-width characters commonly used by spammers
    INVISIBLE_CHARS = {
        '\u200b',  # Zero-width space
        '\u200c',  # Zero-width non-joiner
        '\u200d',  # Zero-width joiner
        '\u200e',  # Left-to-right mark
        '\u200f',  # Right-to-left mark
        '\u2060',  # Word joiner
        '\u2061',  # Function application
        '\u2062',  # Invisible times
        '\u2063',  # Invisible separator
        '\u2064',  # Invisible plus
        '\ufeff',  # Zero-width no-break space (BOM)
        '\u034f',  # Combining grapheme joiner
        '\u00ad',  # Soft hyphen
        '\u180e',  # Mongolian vowel separator
        '\u061c',  # Arabic letter mark
    }
    
    result = {
        "mentions": [],
        "total_count": 0,
        "hidden_mentions": [],
        "has_more": False,
        "tme_deeplinks": [],
        "fake_mentions": [],  # List of {visible_text, hidden_url} for deceptive links
    }
    
    # Get entities and text (support both text and caption)
    entities_to_check = []
    text_to_check = None
    if message.entities and message.text:
        entities_to_check = message.entities
        text_to_check = message.text
    elif message.caption_entities and message.caption:
        entities_to_check = message.caption_entities
        text_to_check = message.caption
    
    # Regex for t.me/m/ profile deeplinks
    tme_m_pattern = re.compile(r'(?:https?://)?(?:t\.me|telegram\.me)/m/([A-Za-z0-9_-]+)')
    
    # Even if no entities, check for text patterns (t.me/m/ links, @usernames)
    if text_to_check:
        # Detect t.me/m/ profile deeplinks in plain text (spam recruitment links)
        tme_m_matches = tme_m_pattern.findall(text_to_check)
        # Store full URLs, not just codes
        for code in tme_m_matches:
            result["tme_deeplinks"].append(f"https://t.me/m/{code}")
        
        # Detect plain @username patterns that may not be entity-detected
        # (some messages have @username as plain text without entity)
        username_pattern = re.compile(r'@([A-Za-z][A-Za-z0-9_]{4,31})')
        plain_usernames = username_pattern.findall(text_to_check)
        # Store plain usernames to compare with entity-based ones later
        plain_username_set = set(u.lower() for u in plain_usernames)
    else:
        plain_username_set = set()
    
    if not entities_to_check:
        # No entities but may have detected patterns above
        # Add plain @usernames as mentions if found
        max_buttons = 3
        seen_usernames = set()
        for username in plain_usernames if text_to_check else []:
            if username.lower() not in seen_usernames and len(result["mentions"]) < max_buttons:
                result["mentions"].append(("username", username, f"@{username}"))
                seen_usernames.add(username.lower())
                result["total_count"] += 1
        result["has_more"] = len(plain_usernames if text_to_check else []) > max_buttons
        return result
    
    max_buttons = 3
    seen_usernames = set()  # Track usernames we've already added
    
    for entity in entities_to_check:
        entity_type = entity.get("type") if isinstance(entity, dict) else getattr(entity, "type", None)
        
        if entity_type == "mention":
            result["total_count"] += 1
            offset = entity.get("offset") if isinstance(entity, dict) else getattr(entity, "offset", 0)
            length = entity.get("length") if isinstance(entity, dict) else getattr(entity, "length", 0)
            mention = text_to_check[offset:offset + length]
            
            # Check for invisible characters around the mention
            context_start = max(0, offset - 3)
            context_end = min(len(text_to_check), offset + length + 3)
            context = text_to_check[context_start:context_end]
            has_invisible = any(char in context for char in INVISIBLE_CHARS)
            
            if mention.startswith("@"):
                username_clean = mention.lstrip("@")
                seen_usernames.add(username_clean.lower())
                if len(result["mentions"]) < max_buttons:
                    result["mentions"].append(("username", username_clean, mention))
                if has_invisible:
                    result["hidden_mentions"].append(mention)
                    
        elif entity_type == "text_mention":
            result["total_count"] += 1
            user = entity.get("user") if isinstance(entity, dict) else getattr(entity, "user", None)
            if user:
                user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
                first_name = user.get("first_name", "") if isinstance(user, dict) else getattr(user, "first_name", "")
                if user_id:
                    display = first_name[:15] + "..." if len(first_name) > 15 else first_name
                    if len(result["mentions"]) < max_buttons:
                        result["mentions"].append(("user_id", str(user_id), display))
                    
                    # Check for invisible characters around the text_mention
                    offset = entity.get("offset") if isinstance(entity, dict) else getattr(entity, "offset", 0)
                    length = entity.get("length") if isinstance(entity, dict) else getattr(entity, "length", 0)
                    context_start = max(0, offset - 3)
                    context_end = min(len(text_to_check), offset + length + 3)
                    context = text_to_check[context_start:context_end]
                    has_invisible = any(char in context for char in INVISIBLE_CHARS)
                    if has_invisible:
                        result["hidden_mentions"].append(f"ID:{user_id}")
        
        elif entity_type == "text_link":
            # Check if text_link contains t.me/m/ deeplink (hidden spam link)
            url = entity.get("url", "") if isinstance(entity, dict) else getattr(entity, "url", "")
            tme_m_match = tme_m_pattern.search(url)
            if tme_m_match:
                # This is a deceptive link - visible text hides a t.me/m/ deeplink
                offset = entity.get("offset") if isinstance(entity, dict) else getattr(entity, "offset", 0)
                length = entity.get("length") if isinstance(entity, dict) else getattr(entity, "length", 0)
                visible_text = text_to_check[offset:offset + length]
                
                # Normalize URL to include https://
                full_url = url if url.startswith("http") else f"https://{url}"
                
                result["fake_mentions"].append({
                    "visible_text": visible_text,
                    "hidden_url": full_url,
                })
                
                # Also add to deeplinks list if not already there
                if full_url not in result["tme_deeplinks"]:
                    result["tme_deeplinks"].append(full_url)
    
    # Add any plain text @usernames that weren't detected as entities (e.g., broken by invisible chars)
    for username in plain_username_set:
        if username not in seen_usernames:
            result["total_count"] += 1
            if len(result["mentions"]) < max_buttons:
                result["mentions"].append(("username", username, f"@{username}"))
            seen_usernames.add(username)
    
    result["has_more"] = result["total_count"] > max_buttons
    return result


async def load_banned_users():
    """Coroutine to load banned users from file"""
    banned_users_filename = "banned_users.txt"

    if not os.path.exists(banned_users_filename):
        LOGGER.error("File not found: %s", banned_users_filename)
        return

    with open(banned_users_filename, "r", encoding="utf-8") as file:
        for line in file:
            user_id, user_name_repr = (
                int(line.strip().split(":", 1)[0]),
                line.strip().split(":", 1)[1],
            )
            user_name = ast.literal_eval(user_name_repr)
            banned_users_dict[user_id] = user_name
        LOGGER.info(
            "\033[91mBanned users dict (%s) loaded from file: %s\033[0m",
            len(banned_users_dict),
            banned_users_dict,
        )


async def load_active_user_checks():
    """Coroutine to load checks non-blockingly from database"""
    # Load from database
    baselines = get_active_user_baselines(CONN)
    
    if not baselines:
        LOGGER.info("No active user baselines found in database")
        # Fallback: try loading from legacy file if exists
        active_checks_filename = "active_user_checks.txt"
        if os.path.exists(active_checks_filename):
            LOGGER.info("Found legacy file %s, migrating to database...", active_checks_filename)
            await _migrate_legacy_active_checks(active_checks_filename)
            # Re-load from database after migration
            baselines = get_active_user_baselines(CONN)
    
    for baseline in baselines:
        user_id = baseline["user_id"]
        username = baseline.get("username") or "!UNDEFINED!"
        
        # Reconstruct the dict format for active_user_checks_dict
        active_user_checks_dict[user_id] = {
            "username": baseline.get("username"),
            "baseline": {
                "first_name": baseline.get("first_name") or "",
                "last_name": baseline.get("last_name") or "",
                "username": baseline.get("username") or "",
                "photo_count": baseline.get("photo_count") or 0,
                "joined_at": baseline.get("joined_at"),
                "chat": {
                    "id": baseline.get("join_chat_id"),
                    "username": baseline.get("join_chat_username"),
                    "title": baseline.get("join_chat_title") or "",
                },
            },
        }
        
        event_message = (
            f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "
            + str(user_id)
            + " ❌ \t\t\tbanned everywhere during initial checks on_startup"
        )
        
        # Extract start_time for resuming after restart
        start_time = None
        joined_at_str = baseline.get("joined_at")
        if joined_at_str:
            try:
                # Handle both formats: with and without timezone
                start_time = datetime.fromisoformat(joined_at_str.replace(" ", "T"))
            except ValueError:
                LOGGER.warning(
                    "%s: Could not parse joined_at: %s", user_id, joined_at_str
                )
        
        user_name_display = username if username and username != "None" else "!UNDEFINED!"
        
        # Start the check NON-BLOCKING
        asyncio.create_task(
            perform_checks(
                user_id=user_id,
                user_name=user_name_display,
                event_record=event_message,
                inout_logmessage=f"(<code>{user_id}</code>) banned using data loaded on_startup event",
                start_time=start_time,
            )
        )
        
        # Insert a 1-second interval between task creations
        await asyncio.sleep(1)
    
    LOGGER.info(
        "\033[93mActive users checks dict (%s) loaded from database\033[0m",
        len(active_user_checks_dict),
    )


async def _migrate_legacy_active_checks(filename: str):
    """Migrate legacy active_user_checks.txt to database"""
    migrated = 0
    with open(filename, "r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            user_id = int(line.strip().split(":")[0])
            user_name = line.strip().split(":", 1)[1]
            try:
                user_name = (
                    ast.literal_eval(user_name)
                    if user_name.startswith("{") and user_name.endswith("}")
                    else user_name
                )
            except (ValueError, SyntaxError):
                pass
            
            if isinstance(user_name, dict):
                baseline = user_name.get("baseline", {})
                chat = baseline.get("chat", {})
                # Normalize username - treat !UNDEFINED!/None/empty as None
                _uname = normalize_username(user_name.get("username"))
                save_user_baseline(
                    conn=CONN,
                    user_id=user_id,
                    username=_uname or None,
                    first_name=baseline.get("first_name"),
                    last_name=baseline.get("last_name"),
                    photo_count=baseline.get("photo_count", 0),
                    join_chat_id=chat.get("id"),
                    join_chat_username=chat.get("username"),
                    join_chat_title=chat.get("title"),
                )
            else:
                # Simple username string - minimal baseline
                # Normalize username - treat !UNDEFINED!/None/empty as None
                _uname = normalize_username(user_name)
                save_user_baseline(
                    conn=CONN,
                    user_id=user_id,
                    username=_uname or None,
                )
            migrated += 1
    
    LOGGER.info("Migrated %d users from legacy file to database", migrated)
    # Rename legacy file to .bak
    os.rename(filename, filename + ".bak")
    LOGGER.info("Renamed %s to %s.bak", filename, filename)


async def load_and_start_checks():
    """Load all unfinished checks from file and start them with 1 sec interval"""

    # Run the load_banned_users function as a background task
    asyncio.create_task(load_banned_users())

    # Run the load_active_user_checks function as a background task
    asyncio.create_task(load_active_user_checks())

    LOGGER.debug("NON BLOCKING LOAD STARTUP CHECKS DONE!")


async def sequential_shutdown_tasks(_id, _uname):
    """Define the new coroutine that runs two async functions sequentially"""
    # First async function
    lols_cas_result = await spam_check(_id) is True
    # Second async function
    await check_and_autoban(
        f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "
        + str(_id)
        + " ❌ \t\t\tbanned everywhere during final checks on_shutdown inout",
        _id,
        "(<code>" + str(_id) + "</code>) banned during final checks on_shutdown event",
        _uname,
        lols_cas_result,
    )


async def on_shutdown():
    """Function to handle the bot shutdown."""
    LOGGER.info(
        "\033[95mBot is shutting down... Performing final spammer check...\033[0m"
    )

    # Create a list to hold all tasks
    tasks = []

    # Iterate over active user checks and create a task for each check
    for _id, _uname in active_user_checks_dict.items():
        # Extract username from dict or use string value
        _username_str = (
            _uname.get("username") if isinstance(_uname, dict) else _uname
        )
        LOGGER.info(
            "%s:%s shutdown check for spam...",
            _id,
            format_username_for_log(_username_str),
        )

        # Create the task for the sequential coroutine without awaiting it immediately
        task = asyncio.create_task(
            sequential_shutdown_tasks(_id, _uname), name=str(_id) + "shutdown"
        )
        tasks.append(task)

    # try:
    # Run all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Note: add messages deletion if spammer detected and have messages posted

    # Process results and log any exceptions
    for task, result in zip(tasks, results):
        if isinstance(result, Exception):
            LOGGER.error("Task %s failed with exception: %s", task.get_name(), result)
        else:
            LOGGER.info("Task %s completed successfully.", task.get_name())
    # except Exception as e:
    #     LOGGER.error("Unexpected error during shutdown tasks: %s", e)

    # Database already has the current state - no need to save on shutdown
    # (baselines are saved on join, updated on ban/legit actions)
    LOGGER.info(
        "Shutdown: %d active users in monitoring (persisted in database)",
        len(active_user_checks_dict),
    )

    # save all banned users to temp file to preserve list after bot restart
    banned_users_filename = "banned_users.txt"

    # debug
    if banned_users_dict:
        LOGGER.debug(
            "Saving banned users to file...\n\033[93m%s\033[0m", banned_users_dict
        )
    # end debug

    if os.path.exists(banned_users_filename) and banned_users_dict:
        with open(banned_users_filename, "a", encoding="utf-8") as file:
            for _id, _uname in banned_users_dict.items():
                file.write(f"{_id}:{repr(_uname)}\n")
    elif banned_users_dict:
        with open(banned_users_filename, "w", encoding="utf-8") as file:
            for _id, _uname in banned_users_dict.items():
                file.write(f"{_id}:{repr(_uname)}\n")

    # Signal that shutdown tasks are completed
    # shutdown_event.set()
    # Example of another coroutine that waits for the shutdown event
    # async def some_other_coroutine():
    #     await shutdown_event.wait()  # Wait for the shutdown tasks to complete
    #     # Continue with the rest of the coroutine

    # send message with short stats about previous session
    # bot start time
    # bot end time
    # Runtime of the previous session
    # number of spammers detected
    # number of spammers banned
    # number of spammers not banned
    # number of messages from admins
    # number of the other messages
    # number of the messages with spam detected
    # number of the messages with spam not detected and deleted by admins
    # number of active user checks forwarded to the next session

    try:
        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP,
            (
                "Runtime session shutdown stats:\n"
                f"Bot started at: {bot_start_time}\n"
                f"Current active user checks: {len(active_user_checks_dict)}\n"
                f"Spammers detected: {len(banned_users_dict)}\n"
            ),
            LOGGER,
            message_thread_id=TECHNO_RESTART,
        )
    except TelegramBadRequest as e:
        LOGGER.warning("Could not send shutdown stats message: %s", e)
        
    LOGGER.info(
        "\033[93m\nRuntime session shutdown stats:\n"
        "Bot started at: %s\n"
        "Current active user checks: %d\n"
        "Spammers detected: %d\033[0m",
        bot_start_time,
        len(active_user_checks_dict),
        len(banned_users_dict),
    )
    
    # Close the global HTTP session used for spam checks
    await close_http_session()
    
    # Note: Don't call BOT.close() here - aiogram 3.x dispatcher handles it automatically
    # Calling it manually causes "Flood control exceeded on method 'Close'" errors

    # for _id in active_user_checks_dict:
    #     LOGGER.info("%s shutdown check for spam...", _id)
    #     lols_cas_final_check = await lols_cas_check(_id) is True
    #     await check_and_autoban(
    #         str(_id) + "on_shutdown inout",
    #         _id,
    #         "<code>(" + str(_id) + ")</code> banned on_shutdown event",
    #         lols_cas_final_check,
    #     )


async def is_admin(reporter_user_id: int, admin_group_id_check: int) -> bool:
    """Function to check if the reporter is an admin in the Admin group."""
    chat_admins = await BOT.get_chat_administrators(admin_group_id_check)
    for admin in chat_admins:
        if admin.user.id == reporter_user_id:
            return True
    return False


async def handle_autoreports(
    message: Message,
    spammer_id: int,
    spammer_first_name: str,
    spammer_last_name: str,
    forward_from_chat_title: str,
    forward_sender_name: str,
    found_message_data: dict,
    reason: str = "Automated report",
):
    """Function to handle forwarded messages with provided user details."""

    # store spam text and caption to the daily_spam file
    reported_spam = "ADM" + format_spam_report(message)[3:]
    await save_report_file("daily_spam_", reported_spam)

    # LOGGER.debug(f"Received forwarded message for the investigation: {message}")
    # Send a thank you note to the user we dont need it for the automated reports anymore
    # await message.answer("Thank you for the report. We will investigate it.")
    # Forward the message to the admin group
    try:  # if it was already removed earlier
        technnolog_spam_message_copy = await BOT.forward_message(
            TECHNOLOG_GROUP_ID, message.chat.id, message.message_id
        )
    except TelegramBadRequest:
        LOGGER.error(
            "%s:@%s Message to forward not found: %s",
            spammer_id,
            "!UNDEFINED!",
            message.message_id,
        )
        return

    message_as_json = json.dumps(message.model_dump(mode="json"), indent=4, ensure_ascii=False)
    # Truncate and add an indicator that the message has been truncated
    if len(message_as_json) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
        message_as_json = message_as_json[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
    await safe_send_message(BOT, TECHNOLOG_GROUP_ID, message_as_json, LOGGER)
    await safe_send_message(
        BOT, TECHNOLOG_GROUP_ID, "Please investigate this message.", LOGGER
    )

    if not found_message_data:
        if forward_sender_name == "Deleted Account":
            found_message_data = get_spammer_details(
                spammer_id,
                spammer_first_name,
                spammer_last_name,
                message.forward_date,
                forward_sender_name,
                forward_from_chat_title,
                forwarded_from_chat_id=(
                    message.forward_from_chat.id if message.forward_from_chat else None
                ),
                froward_sender_chat_id=(
                    message.sender_chat.id if message.sender_chat else None
                ),
            )
            LOGGER.debug(
                "The requested data associated with the Deleted Account has been retrieved. Please verify the accuracy of this information, as it cannot be guaranteed due to the account's deletion."
            )
            await message.answer(
                "The requested data associated with the Deleted Account has been retrieved. Please verify the accuracy of this information, as it cannot be guaranteed due to the account's deletion."
            )
        else:
            e = "Renamed Account or wrong chat?"
            LOGGER.debug(
                "Could not retrieve the author's user ID. Please ensure you're reporting recent messages. %s",
                e,
            )
            await message.answer(
                f"Could not retrieve the author's user ID. Please ensure you're reporting recent messages. {e}"
            )

    if not found_message_data:  # Last resort. Give up.
        LOGGER.warning(
            "%s:%s spammer data not found in DB. I giveup :(",
            message.from_user.id,
            (
                message.from_user.username
                if message.from_user.username
                else (
                    message.forward_from_chat.username
                    if message.forward_from_chat.username
                    else "@!UNDEFINED!"
                )
            ),
        )
        return

    # LOGGER.debug(
    #     "%-10s - message data: %s", f"{found_message_data[3]:10}", found_message_data
    # )
    # LOGGER.debug("message object: %s", message)

    # Save both the original message_id and the forwarded message's date
    received_date = message.date if message.date else None
    # remove -100 from the chat ID if this is a public group
    if message.chat.id < 0:
        report_id = int(str(message.chat.id)[4:] + str(message.message_id))
    else:
        report_id = int(str(message.chat.id) + str(message.message_id))
    # Save the message to the database
    CURSOR.execute(
        """
        INSERT OR REPLACE INTO recent_messages 
        (chat_id, message_id, user_id, user_name, user_first_name, user_last_name, forward_date, received_date, forwarded_message_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.chat.id,
            report_id,
            message.from_user.id,
            message.from_user.username,
            message.from_user.first_name,
            message.from_user.last_name,
            message.forward_date.strftime("%Y-%m-%d %H:%M:%S") if message.forward_date else None,
            received_date,
            str(found_message_data),
        ),
    )

    CONN.commit()

    # Construct message link using chat username if available
    if message.chat.username:
        message_link = f"https://t.me/{message.chat.username}/{message.message_id}"
    else:
        chat_id_str = str(message.chat.id)[4:] if message.chat.id < 0 else str(message.chat.id)
        message_link = f"https://t.me/c/{chat_id_str}/{message.message_id}"

    # Get the username, first name, and last name of the user who forwarded the message and handle the cases where they're not available
    if message.forward_from:
        first_name = message.forward_from.first_name or ""
        last_name = message.forward_from.last_name or ""
    else:
        first_name = found_message_data[5]
        last_name = found_message_data[6]

    # Handle both formats: with and without timezone
    message_timestamp = datetime.fromisoformat(found_message_data[7].replace(" ", "T"))

    # Get the username
    username = found_message_data[4]
    if not username:
        username = "!UNDEFINED!"

    # Initialize user_id and user_link with default values
    user_id = found_message_data[3]

    technolog_chat_id = int(
        str(technnolog_spam_message_copy.chat.id)[4:]
    )  # Remove -100 from the chat ID
    technnolog_spamMessage_copy_link = (
        f"https://t.me/c/{technolog_chat_id}/{technnolog_spam_message_copy.message_id}"
    )

    # fix if message not forwarded and autoreported
    # if message.forward_date:
    #     message_report_date = message.forward_date
    # else:
    message_report_date = datetime.now()

    # Escape the name to prevent HTML injection
    escaped_name = html.escape(
        f"{message.forward_sender_name or f'{first_name} {last_name}'}"
    )

    # Log the information with the link
    log_info = (
        f"💡 Report timestamp: {message_report_date}\n"
        f"💡 Spam message timestamp: {message.date}\n"
        f"💡 Reaction time: {message_report_date - message_timestamp}\n"
        f"💔 Reported by automated spam detection system\n"
        f"💔 {reason}\n"
        f"💀 Forwarded from <a href='tg://resolve?domain={username}'>@{username}</a> : "
        f"{escaped_name}\n"
        f"💀 SPAMMER ID profile links:\n"
        f"   ├☠️ <a href='tg://user?id={user_id}'>Spammer ID based profile link</a>\n"
        f"   ├☠️ <a href='tg://openmessage?user_id={user_id}'>Android</a>\n"
        f"   └☠️ <a href='https://t.me/@id{user_id}'>IOS (Apple)</a>\n"
        f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
        f"ℹ️ <a href='{technnolog_spamMessage_copy_link}'>Technolog copy</a>\n"
        f"❌ <b>Use <code>/ban {report_id}</code></b> to take action.\n"
    )

    admin_ban_banner = (
        f"💡 Reaction time: {message_report_date - message_timestamp}\n"
        f"💔 {reason}\n"
        f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
        f"ℹ️ <a href='{technnolog_spamMessage_copy_link}'>Technolog copy</a>\n"
        f"❌ <b>Use <code>/ban {report_id}</code></b> to take action.\n"
        f"\n🔗 <b>Profile links:</b>\n"
        f"   ├ <a href='tg://user?id={spammer_id}'>ID based profile link</a>\n"
        f"   └ <a href='tg://openmessage?user_id={spammer_id}'>Android</a>, "
        f"<a href='https://t.me/@id{spammer_id}'>iOS</a>\n"
    )

    # Analyze mentions in the message
    mention_analysis = analyze_mentions_in_message(message)
    
    # Add mention info to banner if there are mentions
    if mention_analysis["total_count"] > 0:
        mention_info_parts = []
        if mention_analysis["has_more"]:
            mention_info_parts.append(f"⚠️ <b>{mention_analysis['total_count']} mentions found</b> (showing first 3 buttons)")
        if mention_analysis["hidden_mentions"]:
            hidden_list = ", ".join(mention_analysis["hidden_mentions"][:5])
            mention_info_parts.append(f"🕵️ <b>Hidden/obfuscated mentions detected:</b> {hidden_list}")
        if mention_info_parts:
            admin_ban_banner += "\n" + "\n".join(mention_info_parts)

    # construct lols check link button
    inline_kb = make_lols_kb(user_id)
    # Send the banner to the technolog group
    await safe_send_message(
        BOT,
        TECHNOLOG_GROUP_ID,
        log_info,
        LOGGER,
        parse_mode="HTML",
        reply_markup=inline_kb.as_markup(),
    )

    # Keyboard ban/cancel/confirm buttons
    keyboard = KeyboardBuilder()
    # Add LOLS check button
    lols_link = f"https://t.me/oLolsBot?start={user_id}"
    keyboard.add(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))
    # Add legitimization button to stop further checks
    # Use actual message_id for linking (not report_id which is for DB storage)
    keyboard.add(
        InlineKeyboardButton(
            text="✅ Mark as Legit",
            callback_data=f"stopchecks_{spammer_id}_{message.chat.id}_{message.message_id}",
        )
    )
    # Consolidated actions button (expands to Ban / Global Ban / Delete on click)
    actions_btn = InlineKeyboardButton(
        text="⚙️ Actions (Ban / Delete) ⚙️",
        callback_data=f"suspiciousactions_{message.chat.id}_{message.message_id}_{spammer_id}",
    )
    keyboard.add(actions_btn)

    # Add LOLS check buttons for mentioned users in the spam message (using pre-analyzed data)
    for mention_type, mention_value, display_name in mention_analysis["mentions"]:
        if mention_type == "username":
            mention_lols_link = f"https://t.me/oLolsBot?start=u-{mention_value}"
            keyboard.add(
                InlineKeyboardButton(text=f"🔍 Check mentioned @{mention_value}", url=mention_lols_link)
            )
        elif mention_type == "user_id":
            mention_lols_link = f"https://t.me/oLolsBot?start={mention_value}"
            keyboard.add(
                InlineKeyboardButton(text=f"🔍 Check mentioned ID:{mention_value} ({display_name})", url=mention_lols_link)
            )

    try:
        # Forward original message to the admin group
        await BOT.forward_message(
            ADMIN_GROUP_ID,
            found_message_data[0],  # from_chat_id
            found_message_data[1],  # message_id
            message_thread_id=ADMIN_AUTOREPORTS,
            disable_notification=True,
        )
    except TelegramBadRequest:
        if message:
            await message.forward(ADMIN_GROUP_ID, ADMIN_AUTOREPORTS)
        else:
            LOGGER.warning("%s autoreported message already DELETED?", spammer_id)
    # Show ban banner with buttons in the admin group to confirm or cancel the ban
    admin_group_banner_autoreport_message = await safe_send_message(
        BOT,
        ADMIN_GROUP_ID,
        admin_ban_banner,
        LOGGER,
        reply_markup=keyboard.as_markup(),
        parse_mode="HTML",
        message_thread_id=ADMIN_AUTOREPORTS,
        disable_web_page_preview=True,
    )

    # Store the admin action banner message data
    # AUTOREPORT ALWAYS IN ADMIN_GROUP_ID so there is no ADMIN action banner message

    set_forwarded_state(
        DP,
        report_id,
        {
            "original_forwarded_message": message,
            "admin_group_banner_message": admin_group_banner_autoreport_message,
            "action_banner_message": None,  # AUTOREPORT have no ADMIN ACTION
            "report_chat_id": message.chat.id,
        },
    )

    return


async def spam_check(user_id):
    """Function to check if a user is in the lols/cas/p2p/db spam list.
    var: user_id: int: The ID of the user to check."""
    # Check if the user is in the lols bot database
    # https://api.lols.bot/account?id=
    # https://api.cas.chat/check?user_id=
    # P2P_SERVER_URL/check?user_id=
    # Note: implement prime_radiant local DB check
    session = get_http_session()
    lols = False
    cas = 0
    is_spammer = False

    async def check_local():
        try:
            async with session.get(
                f"{P2P_SERVER_URL}/check?user_id={user_id}", timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("is_spammer", False)
        except aiohttp.ClientConnectorError as e:
            LOGGER.warning(
                "Local endpoint check error (ClientConnectorError): %s", e
            )
            return False
        except asyncio.TimeoutError as e:
            LOGGER.warning("Local endpoint check error (TimeoutError): %s", e)
            return False

    async def check_lols():
        try:
            async with session.get(
                f"https://api.lols.bot/account?id={user_id}", timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("banned", False)
        except aiohttp.ClientConnectorError as e:
            LOGGER.warning(
                "LOLS endpoint check error (ClientConnectorError): %s", e
            )
            return False
        except asyncio.TimeoutError as e:
            LOGGER.warning("LOLS endpoint check error (TimeoutError): %s", e)
            return False

    async def check_cas():
        try:
            async with session.get(
                f"https://api.cas.chat/check?user_id={user_id}", timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ok", False):
                        return data["result"].get("offenses", 0)
        except aiohttp.ClientConnectorError as e:
            LOGGER.warning("CAS endpoint check error (ClientConnectorError): %s", e)
            return 0
        except asyncio.TimeoutError as e:
            LOGGER.warning("CAS endpoint check error (TimeoutError): %s", e)
            return 0

    try:
        results = await asyncio.gather(
            check_local(), check_lols(), check_cas(), return_exceptions=True
        )

        is_spammer = results[0]
        lols = results[1]
        cas = results[2] if results[2] is not None else 0

        if lols or is_spammer or cas > 0:
            return True
        else:
            return False
    except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
        LOGGER.error("Unexpected error: %s", e)
        return None


async def save_report_file(file_type, data):
    """Function to create or load the daily spam file.

    file_type: str: The type of file to create or load (e.g., daily_spam_)

    data: str: The data to write to the file.
    """

    # Get today's date
    today = datetime.now().strftime("%d-%m-%Y")
    # Construct the filename
    filename = f"{file_type}{today}.txt"

    # Check if any file with the pattern daily_spam_* exists
    existing_files = [f for f in os.listdir() if f.startswith(file_type)]

    if filename in existing_files:
        with open(filename, "a", encoding="utf-8") as file:
            file.write(data)
        return  # File found no need to iterate further. exiting
    else:  # Create a new file with the current date if there are no existing files with the pattern inout_TODAY*
        with open(filename, "w", encoding="utf-8") as file:
            file.write(data)


async def ban_user_from_all_chats(
    user_id: int, user_name: str, channel_ids: list, channel_dict: dict
):
    """
    Ban a user from all specified chats and log the results.

    Args:
        user_id (int): The ID of the user to ban.
        user_name (str): The name of the user to ban.
        channel_ids (list): A list of channel IDs to ban the user from.
        channel_dict (dict): A dictionary mapping channel IDs to channel names.

    Returns:
        tuple: (success_count, fail_count, total_count)
    """
    success_count = 0
    fail_count = 0

    for chat_id in channel_ids:
        try:
            await BOT.ban_chat_member(chat_id, user_id, revoke_messages=True)
            success_count += 1
            # LOGGER.debug("Successfully banned USER %s in chat %s", user_id, chat_id)
        except TelegramBadRequest as e:  # if user were Deleted Account while banning
            fail_count += 1
            chat_name = get_channel_name_by_id(channel_dict, chat_id)
            LOGGER.error(
                "%s:%s - error banning in chat %s (%s): %s. Deleted ACCOUNT or no BOT in CHAT? (Successfully banned: %d)",
                user_id,
                format_username_for_log(user_name),
                chat_name,
                chat_id,
                e,
                success_count,
            )
            await asyncio.sleep(1)
            # Note: Consider removing user_id check coroutine from monitoring list on ChatMigrated
            continue
        except TelegramForbiddenError as e:  # Catch permission errors
            fail_count += 1
            chat_name = get_channel_name_by_id(channel_dict, chat_id)
            LOGGER.error(
                "%s:%s - unexpected error banning in chat %s (%s): %s",
                user_id,
                format_username_for_log(user_name),
                chat_name,
                chat_id,
                e,
            )
            await asyncio.sleep(1)
            continue

    total_count = len(channel_ids)
    # RED color for the log
    LOGGER.info(
        "\033[91m%s:%s identified as a SPAMMER, banned from %d/%d chats.\033[0m",
        user_id,
        format_username_for_log(user_name),
        success_count,
        total_count,
    )

    return success_count, fail_count, total_count


async def autoban(_id, user_name="!UNDEFINED!"):
    """Function to ban a user from all chats using lols's data.
    id: int: The ID of the user to ban."""

    # Cancel intensive watchdog if running (user is being banned)
    if _id in running_intensive_watchdogs:
        intensive_task = running_intensive_watchdogs.pop(_id, None)
        if intensive_task:
            intensive_task.cancel()
            LOGGER.info(
                "%s:@%s Intensive watchdog cancelled during autoban",
                _id,
                user_name,
            )

    # Delete ALL stored messages for this user BEFORE removing from active_user_checks_dict
    if _id in active_user_checks_dict:
        deleted_count, _ = await delete_all_user_messages(_id, user_name)
        if deleted_count > 0:
            LOGGER.info(
                "%s:@%s Deleted %d spam messages during autoban",
                _id,
                user_name,
                deleted_count,
            )

    if _id in active_user_checks_dict:
        banned_users_dict[_id] = active_user_checks_dict.pop(
            _id, None
        )  # add and remove the user to the banned_users_dict

        # remove user from all known chats first
        _, _, _ = await ban_user_from_all_chats(
            _id, user_name, CHANNEL_IDS, CHANNEL_DICT
        )

        last_3_users = list(banned_users_dict.items())[-3:]  # Last 3 elements
        last_3_users_str = ", ".join([f"{uid}: {uname}" for uid, uname in last_3_users])
        LOGGER.info(
            "\033[91m%s:@%s removed from active_user_checks_dict during lols_autoban:\n\t\t\t%s... %d totally\033[0m",
            _id,
            user_name,
            last_3_users_str,  # Last 3 elements
            len(active_user_checks_dict),  # Number of elements left
        )
    else:
        banned_users_dict[_id] = user_name

        # remove user from all known chats first
        _, _, _ = await ban_user_from_all_chats(
            _id, user_name, CHANNEL_IDS, CHANNEL_DICT
        )

        last_3_users = list(banned_users_dict.items())[-3:]  # Last 3 elements
        last_3_users_str = ", ".join([f"{uid}: {uname}" for uid, uname in last_3_users])
        LOGGER.info(
            "\033[91m%s:%s added to banned_users_dict during lols_autoban: %s... %d totally\033[0m",
            _id,
            format_username_for_log(user_name),
            last_3_users_str,  # Last 3 elements
            len(banned_users_dict),  # Number of elements left
        )

    # Normalize username for logging / notification using consistent normalize_username function
    norm_username = normalize_username(user_name)
    if not norm_username:
        LOGGER.debug(
            "%s:%s username undefined; skipping TECHNO_NAMES notification", _id, format_username_for_log(user_name)
        )
        return
    # Check if already posted to avoid duplicates
    if norm_username in POSTED_USERNAMES:
        LOGGER.debug("%s @%s already posted to TECHNO_NAMES, skipping (1156)", _id, norm_username)
        return
    POSTED_USERNAMES.add(norm_username)
    await safe_send_message(
        BOT,
        TECHNOLOG_GROUP_ID,
        f"<code>{_id}</code> @{norm_username} (1156)",
        LOGGER,
        parse_mode="HTML",
        message_thread_id=TECHNO_NAMES,
    )


async def delete_all_user_messages(user_id: int, user_name: str = "!UNDEFINED!"):
    """Delete ALL stored messages for a user from active_user_checks_dict.
    
    Messages are stored with keys like 'chat_id_message_id' in the user's dict entry.
    This function finds all such message keys and deletes each message.
    
    Rate limiting: Telegram allows ~30 API calls/second for bulk operations.
    We add a small delay (0.05s = 50ms) between deletions to stay well under the limit
    (max ~20 deletions/second). For typical spam cases (1-10 messages), this adds
    only 50-500ms total delay which is acceptable.
    
    Returns:
        tuple: (deleted_count, failed_count)
    """
    deleted_count = 0
    failed_count = 0
    
    if user_id not in active_user_checks_dict:
        return deleted_count, failed_count
    
    user_data = active_user_checks_dict.get(user_id, {})
    if not isinstance(user_data, dict):
        return deleted_count, failed_count
    
    # Find all message keys (format: chat_id_message_id)
    message_keys = [
        k for k, v in user_data.items()
        if isinstance(k, str)
        and "_" in k
        and k not in ("username", "baseline", "notified_profile_change")
    ]
    
    if not message_keys:
        return deleted_count, failed_count
    
    LOGGER.info(
        "%s:@%s Found %d messages to delete: %s",
        user_id,
        user_name,
        len(message_keys),
        message_keys,
    )
    
    for i, msg_key in enumerate(message_keys):
        # Rate limiting: add small delay between deletions to avoid hitting Telegram limits
        # Skip delay for the first message
        if i > 0:
            await asyncio.sleep(0.05)  # 50ms delay = max 20 requests/second (well under 30/s limit)
        
        try:
            parts = msg_key.split("_")
            if len(parts) >= 2:
                chat_id_str = parts[0]
                message_id_str = parts[1]
                
                # Convert chat_id - add -100 prefix if needed
                chat_id = int(chat_id_str)
                if chat_id > 0:
                    chat_id = int(f"-100{chat_id}")
                elif not str(chat_id).startswith("-100"):
                    chat_id = int(f"-100{str(chat_id).replace('-', '', 1)}")
                
                message_id = int(message_id_str)
                
                try:
                    await BOT.delete_message(chat_id, message_id)
                    deleted_count += 1
                    LOGGER.debug(
                        "%s:@%s Deleted message %s in chat %s",
                        user_id,
                        user_name,
                        message_id,
                        chat_id,
                    )
                except TelegramBadRequest as e:
                    # Covers MessageToDeleteNotFound, MessageCantBeDeleted, etc.
                    if "message to delete not found" in str(e).lower():
                        LOGGER.debug(
                            "%s:@%s Message %s not found (already deleted?)",
                            user_id,
                            user_name,
                            message_id,
                        )
                    else:
                        LOGGER.warning(
                            "%s:@%s Cannot delete message %s: %s",
                            user_id,
                            user_name,
                            message_id,
                            e,
                        )
                    failed_count += 1
                except TelegramNotFound:
                    LOGGER.warning(
                        "%s:@%s Chat %s not found for message deletion",
                        user_id,
                        user_name,
                        chat_id,
                    )
                    failed_count += 1
                except RetryAfter as e:
                    # Telegram rate limit hit - wait and retry
                    LOGGER.warning(
                        "%s:@%s Rate limit hit, waiting %s seconds...",
                        user_id,
                        user_name,
                        e.retry_after,
                    )
                    await asyncio.sleep(e.retry_after)
                    try:
                        await BOT.delete_message(chat_id, message_id)
                        deleted_count += 1
                    except (TelegramBadRequest, TelegramForbiddenError):
                        failed_count += 1
        except (ValueError, IndexError) as e:
            LOGGER.warning(
                "%s:@%s Invalid message key format '%s': %s",
                user_id,
                user_name,
                msg_key,
                e,
            )
            failed_count += 1
    
    if deleted_count > 0 or failed_count > 0:
        LOGGER.info(
            "\033[91m%s:@%s Deleted %d/%d messages (failed: %d)\033[0m",
            user_id,
            user_name,
            deleted_count,
            deleted_count + failed_count,
            failed_count,
        )
    
    return deleted_count, failed_count


async def check_and_autoban(
    event_record: str,
    user_id: int,
    inout_logmessage: str,
    user_name: str,
    lols_spam=False,
    message_to_delete=None,
):
    """Function to check for spam and take action if necessary.

    :param event_record: str: The event record to log to inout file.

    :param user_id: int: The ID of the user to check for spam.

    :param inout_logmessage: str: The log message for the user's activity.

    :param user_name: str: The name of the user to check for spam.

    :param lols_spam: bool: The result of the lols_check function. OR TIMEOUT

    :param message_to_delete: tuple: chat_id, message_id: The message to delete.
    """

    inline_kb = make_lols_kb(user_id)

    if lols_spam is True:  # not Timeout exaclty
        if user_id not in banned_users_dict:
            await autoban(user_id, user_name)
            # banned_users_dict[user_id] = user_name
            action = "added to"
        else:
            action = "is already added to"
        # if len(banned_users_dict) > 3:  # prevent spamming the log
        #     last_3_users = list(banned_users_dict.items())[-3:]  # Last 3 elements
        #     last_3_users_str = ", ".join(
        #         [f"{uid}: {uname}" for uid, uname in last_3_users]
        #     )
        #     LOGGER.info(
        #         "\033[93m%s:@%s %s runtime banned users list: %s... %d totally\033[0m",
        #         user_id,
        #         user_name if user_name else "!UNDEFINED!",
        #         action,
        #         last_3_users_str,  # Last 3 elements as string
        #         len(banned_users_dict),  # Total number of elements
        #     )
        # else:  # less than 3 banned users
        #     all_users_str = ", ".join(
        #         [f"{uid}: {uname}" for uid, uname in banned_users_dict.items()]
        #     )
        #     LOGGER.info(
        #         "\033[93m%s:@%s %s runtime banned users list: %s\033[0m",
        #         user_id,
        #         user_name if user_name else "!UNDEFINED!",
        #         action,
        #         all_users_str,  # All elements as string
        #     )
        if action == "is already added to":
            return True

        # Delete ALL stored messages for this user (not just one)
        _del_count, _fail_count = await delete_all_user_messages(user_id, user_name)
        LOGGER.debug(
            "%s:%s check_and_autoban deleted %d messages (failed: %d)",
            user_id,
            format_username_for_log(user_name),
            _del_count,
            _fail_count,
        )
        
        # Also try to delete the specific message passed as parameter (fallback/legacy)
        if message_to_delete:
            LOGGER.debug("%s message to delete list (#CNAB)", message_to_delete)
            origin_chat_id = (
                int(f"-100{message_to_delete[0]}")
                if message_to_delete[0] > 0
                else message_to_delete[0]
            )
            try:
                await BOT.delete_message(origin_chat_id, message_to_delete[1])
            except TelegramNotFound:
                LOGGER.error(
                    "%s:@%s Chat not found: %s",
                    user_id,
                    user_name,
                    message_to_delete[0],
                )
            except TelegramBadRequest:
                LOGGER.debug(
                    "%s:@%s Message to delete not found (maybe already deleted): %s",
                    user_id,
                    user_name,
                    message_to_delete[1],
                )
            except TelegramForbiddenError:
                pass  # Already handled by delete_all_user_messages

        if "kicked" in inout_logmessage or "restricted" in inout_logmessage:
            await safe_send_message(
                BOT,
                ADMIN_GROUP_ID,
                inout_logmessage.replace("kicked", "<b>KICKED BY ADMIN</b>", 1).replace(
                    "restricted", "<b>RESTRICTED BY ADMIN</b>", 1
                ),
                LOGGER,
                message_thread_id=ADMIN_MANBAN,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=inline_kb.as_markup(),
            )
            event_record = (
                event_record.replace("member", "kicked", 1).split(" by ")[0]
                + " by Хранитель Порядков\n"
            )
            await save_report_file("inout_", "cbk" + event_record)
        elif "manual check requested" in inout_logmessage:
            # Manual /check id command - notify admins
            await safe_send_message(
                BOT,
                ADMIN_GROUP_ID,
                inout_logmessage.replace(
                    "manual check requested,",
                    "<b>manually kicked</b> from all chats with /check id command while",
                    1,
                )
                + " please check for the other spammer messages!",
                LOGGER,
                message_thread_id=ADMIN_MANBAN,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=inline_kb.as_markup(),
            )
            _norm_username_990 = normalize_username(user_name)
            if _norm_username_990 and _norm_username_990 not in POSTED_USERNAMES:
                POSTED_USERNAMES.add(_norm_username_990)
                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code> @{_norm_username_990} (990)",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )
            elif not _norm_username_990:
                LOGGER.debug(
                    "%s:%s username undefined; skipping 990 notification line", user_id, format_username_for_log(user_name)
                )
            event_record = (
                event_record.replace("member", "kicked", 1).split(" by ")[0]
                + " by Хранитель Порядков\n"
            )
            await save_report_file("inout_", "cbm" + event_record)
        else:  # Done by bot but not yet detected by lols_cas
            # fetch user join date and time from database if 🟢 is present
            if "🟢" in inout_logmessage:
                # Insert current timestamp after clock emoji and before timestamp, no DB query needed
                current_ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                clock_idx = inout_logmessage.find("🕔")
                if clock_idx != -1:
                    after_clock = inout_logmessage[clock_idx + 1 :]
                    ts_match = re.search(
                        r"\d{2}-\d{2}-\d{4} \d{2}:\d{2}:\d{2}", after_clock
                    )
                    if ts_match:
                        ts_start = clock_idx + 1 + ts_match.start()
                        join_ts = inout_logmessage[
                            ts_start : ts_start + 19
                        ]  # DD-MM-YYYY HH:MM:SS
                        # Replace so order is JOIN_TIMESTAMP --> TODAY_TIMESTAMP
                        inout_logmessage = (
                            inout_logmessage[:ts_start]
                            + f" {join_ts} --> {current_ts} "
                            + inout_logmessage[ts_start + 19 :]
                        )
            # modify inout_logmessage (replace logic)
            inout_logmessage = inout_logmessage.replace(
                "member", "<i>member</i> --> <b>KICKED</b>", 1
            ).replace("left", "<i>left</i> --> <b>KICKED</b>", 1)
            # send message to the admin group
            await safe_send_message(
                BOT,
                ADMIN_GROUP_ID,
                inout_logmessage,
                LOGGER,
                message_thread_id=ADMIN_AUTOBAN,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=inline_kb.as_markup(),
            )
            _norm_username = normalize_username(user_name)
            if _norm_username and _norm_username not in POSTED_USERNAMES:
                POSTED_USERNAMES.add(_norm_username)
                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code> @{_norm_username} (1526)",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )
            elif not _norm_username:
                LOGGER.debug(
                    "%s:%s username undefined; skipping 1526 notification line", user_id, format_username_for_log(user_name)
                )
            event_record = (
                event_record.replace("--> member", "--> kicked", 1)
                .replace("--> left", "--> kicked", 1)
                .replace("  member  ", "  kicked  ", 1)
                .replace("  left  ", "  member", 1)
                .split(" by ")[0]
                + " by Хранитель Порядков\n"
            )
            await save_report_file("inout_", "cbb" + event_record)
        return True

    elif ("kicked" in inout_logmessage or "restricted" in inout_logmessage) and (
        str(BOT_USERID) not in event_record
    ):  # Note: User is not in the lols database and was kicked/restricted by admin

        # perform_checks(user_id, user_name)
        # Note: Add perform-checks coroutine!!!
        # Note: check again if it is marked as SPAMMER already

        # LOGGER.debug("inout_logmessage: %s", inout_logmessage)
        # LOGGER.debug("event_record: %s", event_record)
        # user is not spammer but kicked or restricted by admin
        # Note: log admin name getting it from inout_logmessage
        admin_name = (
            inout_logmessage.split("by ", 1)[-1]
            .split("\n", 1)[0]
            .replace("<code>", "")
            .replace("</code>", "")
            if "by " in inout_logmessage
            else "!UNDEFINED!"
        )
        LOGGER.info(
            "\033[95m%s:@%s kicked/restricted by %s, but is not now in the lols database.\033[0m",
            user_id,
            user_name,
            admin_name,
        )
        await safe_send_message(
            BOT,
            ADMIN_GROUP_ID,
            "User is not now in the SPAM database\nbut kicked/restricted by Admin or other BOT.\n"
            + inout_logmessage,
            LOGGER,
            message_thread_id=ADMIN_MANBAN,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb.as_markup(),
        )
        if user_name and user_name != "!UNDEFINED!":
            _norm_username_1054 = normalize_username(user_name)
            if _norm_username_1054 and _norm_username_1054 not in POSTED_USERNAMES:
                POSTED_USERNAMES.add(_norm_username_1054)
                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code> @{_norm_username_1054} (1054)",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )
            elif not _norm_username_1054:
                LOGGER.debug(
                    "%s:%s username undefined; skipping 1054 notification line", user_id, format_username_for_log(user_name)
                )
        return True

    return False


async def check_n_ban(message: Message, reason: str):
    """ "Helper function to check for spam and take action if necessary if heuristics check finds it suspicious.

    message: Message: The message to check for spam.

    reason: str: The reason for the check.
    """
    lolscheck = await spam_check(message.from_user.id)
    # Temporarily check if channel already banned
    channel_spam_check = (
        message.forward_from_chat.id in banned_users_dict
        if message.forward_from_chat
        else False
    )
    if lolscheck is True or channel_spam_check:
        # send message to the admin group AUTOREPORT thread
        LOGGER.info(
            "%s in %s (%s):@%s message %s",
            reason,
            message.chat.title,
            message.chat.id,
            message.chat.username if message.chat.username else "!NONAME!",
            message.message_id,
        )
        time_passed = reason.split("...")[0].split()[-1]
        # delete id from the active_user_checks_dict
        if message.from_user.id in active_user_checks_dict:
            banned_users_dict[message.from_user.id] = active_user_checks_dict.pop(
                message.from_user.id, None
            )

            if len(active_user_checks_dict) > 3:
                active_user_checks_dict_last3_list = list(
                    active_user_checks_dict.items()
                )[-3:]
                active_user_checks_dict_last3_str = ", ".join(
                    [
                        f"{uid}: {uname}"
                        for uid, uname in active_user_checks_dict_last3_list
                    ]
                )
                LOGGER.info(
                    "\033[91m%s:@%s removed from the active_user_checks_dict in check_n_ban:\n\t\t\t%s... %d totally\033[0m",
                    message.from_user.id,
                    (
                        message.from_user.username
                        if message.from_user.username
                        else "!UNDEFINED!"
                    ),
                    active_user_checks_dict_last3_str,  # Last 3 elements
                    len(active_user_checks_dict),  # Number of elements left
                )
            else:
                banned_users_dict[message.from_user.id] = message.from_user.username
                LOGGER.info(
                    "\033[91m%s:@%s removed from the active_user_checks_dict in check_n_ban:\n\t\t\t%s\033[0m",
                    message.from_user.id,
                    (
                        message.from_user.username
                        if message.from_user.username
                        else "!UNDEFINED!"
                    ),
                    active_user_checks_dict,
                )
            # stop the perform_checks coroutine if it is running for author_id
            for task in asyncio.all_tasks():
                if task.get_name() == str(message.from_user.id):
                    task.cancel()
        # forward the telefragged message to the admin group
        try:
            if message is not None:
                await message.forward(
                    chat_id=ADMIN_GROUP_ID,
                    message_thread_id=ADMIN_AUTOBAN,
                    disable_notification=True,
                )
                LOGGER.debug("%s message.forward #CNB", message.from_user.id)
            else:
                await BOT.forward_message(
                    ADMIN_GROUP_ID,
                    message.chat.id,
                    message.message_id,
                    message_thread_id=ADMIN_AUTOBAN,
                )
                LOGGER.debug("%s BOT.forward_message #CNB", message.from_user.id)
        except TelegramBadRequest as e:
            LOGGER.error(
                "\033[93m%s - message %s to forward using check_n_ban(1044) not found in %s (%s)\033[0m Already deleted? %s",
                message.from_user.id,
                message.message_id,
                message.chat.title,
                message.chat.id,
                e,
            )
        # send the telefrag log message to the admin group
        # Create keyboard with both LOLS check and Actions button
        inline_kb = KeyboardBuilder()
        inline_kb.add(
            InlineKeyboardButton(
                text="ℹ️ Check Spam Data ℹ️",
                url=f"https://t.me/oLolsBot?start={message.from_user.id}",
            )
        )
        # Add Actions button for manual review/unban
        # Use actual message_id for linking back to the message
        inline_kb.add(
            InlineKeyboardButton(
                text="⚙️ Actions (Unban / Review) ⚙️",
                callback_data=f"suspiciousactions_{message.chat.id}_{message.message_id}_{message.from_user.id}",
            )
        )

        # Analyze mentions in the spam message using helper function
        mention_analysis = analyze_mentions_in_message(message)
        
        # Add LOLS check buttons for mentioned users (up to 3)
        for mention_type, mention_value, display_name in mention_analysis["mentions"]:
            if mention_type == "username":
                mention_lols_link = f"https://t.me/oLolsBot?start=u-{mention_value}"
                inline_kb.add(
                    InlineKeyboardButton(text=f"🔍 Check @{mention_value}", url=mention_lols_link)
                )
            elif mention_type == "user_id":
                mention_lols_link = f"https://t.me/oLolsBot?start={mention_value}"
                inline_kb.add(
                    InlineKeyboardButton(text=f"🔍 Check ID:{mention_value} ({display_name})", url=mention_lols_link)
                )

        chat_link = (
            f"https://t.me/{message.chat.username}"
            if message.chat.username
            else f"https://t.me/c/{str(message.chat.id)[4:] if str(message.chat.id).startswith('-100') else message.chat.id}"
        )
        chat_link_name = (
            f"@{message.chat.username}:({message.chat.title})"
            if message.chat.username
            else message.chat.title
        )
        
        # Build autoban banner with mention info if present
        autoban_banner_text = f"Alert! 🚨 User @{message.from_user.username if message.from_user.username else '!UNDEFINED!'}:(<code>{message.from_user.id}</code>) has been caught red-handed spamming in <a href='{chat_link}'>{chat_link_name}</a>! Telefragged in {time_passed}..."
        
        # Add mention info if there are mentions
        if mention_analysis["total_count"] > 0:
            mention_info_parts = []
            if mention_analysis["has_more"]:
                mention_info_parts.append(f"\n⚠️ <b>{mention_analysis['total_count']} mentions found</b> (showing first 3 buttons)")
            if mention_analysis["hidden_mentions"]:
                hidden_list = ", ".join(mention_analysis["hidden_mentions"][:5])
                mention_info_parts.append(f"\n🕵️ <b>Hidden/obfuscated mentions detected:</b> {hidden_list}")
            if mention_info_parts:
                autoban_banner_text += "".join(mention_info_parts)
        
        # Add fake mentions info (text_link with t.me/m/ hidden under @username-like text)
        if mention_analysis.get("fake_mentions"):
            fake_list = []
            for fake in mention_analysis["fake_mentions"][:3]:
                fake_list.append(f"'{fake['visible_text']}' → <code>{fake['hidden_url']}</code>")
            autoban_banner_text += "\n🎭 <b>FAKE MENTIONS (deceptive links):</b>\n" + "\n".join(fake_list)
        
        # Add t.me/m/ deeplink info if present (spam recruitment links)
        if mention_analysis.get("tme_deeplinks"):
            deeplinks_list = mention_analysis["tme_deeplinks"][:3]
            deeplinks_str = "\n".join([f"<code>{link}</code>" for link in deeplinks_list])
            autoban_banner_text += f"\n🔗 <b>Profile deeplinks:</b>\n{deeplinks_str}"
        
        admin_autoban_banner = await safe_send_message(
            BOT,
            ADMIN_GROUP_ID,
            autoban_banner_text,
            LOGGER,
            message_thread_id=ADMIN_AUTOBAN,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb.as_markup(),
        )

        # Store the autoban state for Actions button to work
        # Generate report_id from chat_id and message_id
        if str(message.chat.id).startswith("-100"):
            report_id = int(str(message.chat.id)[4:] + str(message.message_id))
        else:
            report_id = int(str(message.chat.id) + str(message.message_id))
        set_forwarded_state(
            DP,
            report_id,
            {
                "original_forwarded_message": message,
                "admin_group_banner_message": admin_autoban_banner,
                "action_banner_message": None,
                "report_chat_id": message.chat.id,
            },
        )

        # log username to the username thread
        _uname_1191 = normalize_username(message.from_user.username)
        if _uname_1191 and _uname_1191 not in POSTED_USERNAMES:
            POSTED_USERNAMES.add(_uname_1191)
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                f"<code>{message.from_user.id}</code> @{_uname_1191} (1191)",
                LOGGER,
                parse_mode="HTML",
                message_thread_id=TECHNO_NAMES,
            )
        # remove spammer from all groups
        await autoban(message.from_user.id, message.from_user.username)
        event_record = (
            f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "  # Date and time with milliseconds
            f"{message.from_user.id:<10} "
            f"❌  {' '.join('@' + getattr(message.from_user, attr) if attr == 'username' else str(getattr(message.from_user, attr, '')) for attr in ('username', 'first_name', 'last_name') if getattr(message.from_user, attr, '')):<32}"
            f" member          --> kicked          in "
            f"{'@' + message.chat.username + ': ' if message.chat.username else '':<24}{message.chat.title:<30} by Хранитель Порядков\n"
        )
        reported_spam = (
            "AUT" + format_spam_report(message)[3:]
        )  # replace leading ### with AUT to indicate autoban
        # save to report file spam message
        await save_report_file("daily_spam_", reported_spam)
        await save_report_file("inout_", "cnb" + event_record)

        # add the user to the banned users list
        if message.from_user.id not in banned_users_dict:
            banned_users_dict[message.from_user.id] = (
                message.from_user.username or "!UNDEFINED!"
            )
            if len(banned_users_dict) > 3:
                last_3_users = list(banned_users_dict.items())[-3:]  # Last 3 elements
                last_3_users_str = ", ".join(
                    [f"{uid}: {uname}" for uid, uname in last_3_users]
                )
                LOGGER.info(
                    "\033[93m%s:@%s added to banned users list in check_n_ban: %s... %d totally\033[0m",
                    message.from_user.id,
                    (
                        message.from_user.username
                        if message.from_user.username
                        else "!UNDEFINED!"
                    ),
                    last_3_users_str,  # First 2 elements
                    len(banned_users_dict),  # Number of elements left
                )
            else:
                LOGGER.info(
                    "\033[93m%s:@%s added to banned users list in check_n_ban: %s\033[0m",
                    message.from_user.id,
                    (
                        message.from_user.username
                        if message.from_user.username
                        else "!UNDEFINED!"
                    ),
                    banned_users_dict,
                )

        # Note: Message may already be deleted by another bot or process
        # Note: shift to delete_messages in aiogram 3.0
        try:
            await BOT.delete_message(message.chat.id, message.message_id)
        except TelegramBadRequest:
            LOGGER.error(
                "\033[93m%s:@%s - message %s to delete using check_n_ban(1132) not found in %s (%s)\033[0m Already deleted?",
                message.from_user.id,
                (
                    message.from_user.username
                    if message.from_user.username
                    else "!UNDEFINED!"
                ),
                message.message_id,
                message.chat.title,
                message.chat.id,
            )

        return True
    else:
        return False


async def perform_checks(
    message_to_delete=None,
    event_record="",
    user_id=None,
    inout_logmessage="",
    user_name="!UNDEFINED!",
    start_time=None,  # Optional: when monitoring started (for resuming after restart)
):
    """Corutine to perform checks for spam and take action if necessary.
    param message_to_delete: tuple: chat_id, message_id: The message to delete.
    param event_record: str: The event record to log to inout file.
    param user_id: int: The ID of the user to check for spam.
    param inout_logmessage: str: The log message for the user's activity.
    param start_time: datetime: When monitoring started (to resume after bot restart).
    """

    # immediate check
    # lols_spam = await lols_check(user_id)
    # if await check_and_autoban(user_id, inout_logmessage,lols_spam=lols_spam):
    #     return

    # Define a dictionary to map lols_spam values to ANSI color codes
    color_map = {
        False: "\033[92m",  # Green for False
        True: "\033[91m",  # Red for True
        None: "\033[93m",  # Yellow for None or other values
    }

    try:

        # List of sleep times in seconds (cumulative from start)
        sleep_times = [
            65,  # 1 min
            185,  # 3 min
            305,  # 5 min
            605,  # 10 min
            1205,  # 20 min
            1805,  # 30 min
            3605,  # 1 hr
            7205,  # 2 hr
            10805,  # 3 hr
            21605,  # 6 hr
            43205,  # 12 hr
            MONITORING_DURATION_HOURS * 3600 + 5,  # final check
        ]

        # Calculate elapsed time if resuming after restart
        elapsed_seconds = 0
        skipped_intervals = []
        if start_time:
            elapsed_seconds = (datetime.now() - start_time).total_seconds()
            if elapsed_seconds >= sleep_times[-1]:
                # Monitoring period already completed
                LOGGER.info(
                    "%s:%s monitoring period already completed (%.1f hrs elapsed), removing from checks",
                    user_id,
                    format_username_for_log(user_name),
                    elapsed_seconds / 3600,
                )
                if user_id in active_user_checks_dict:
                    del active_user_checks_dict[user_id]
                # Mark monitoring as ended in database
                update_user_baseline_status(CONN, user_id, monitoring_active=False)
                return
            # Collect skipped intervals for single log line
            for st in sleep_times:
                if st <= elapsed_seconds:
                    skipped_intervals.append(f"{st // 60}min")
            if skipped_intervals:
                LOGGER.info(
                    "%s:%s resuming from %.1f min, skipped: %s",
                    user_id,
                    format_username_for_log(user_name),
                    elapsed_seconds / 60,
                    ", ".join(skipped_intervals),
                )
            else:
                LOGGER.info(
                    "%s:%s resuming monitoring from %.1f min elapsed",
                    user_id,
                    format_username_for_log(user_name),
                    elapsed_seconds / 60,
                )

        for sleep_time in sleep_times:
            # Skip intervals that have already passed (when resuming)
            if elapsed_seconds > 0 and sleep_time <= elapsed_seconds:
                continue

            # Calculate adjusted sleep time (subtract already elapsed time for first remaining interval)
            adjusted_sleep = sleep_time - elapsed_seconds if elapsed_seconds > 0 else sleep_time
            elapsed_seconds = 0  # Reset after first adjusted sleep

            if user_id not in active_user_checks_dict:  # if user banned somewhere else
                return

            await asyncio.sleep(adjusted_sleep)
            lols_spam = await spam_check(user_id)

            # Get the color code based on the value of lols_spam
            color_code = color_map.get(
                lols_spam, "\033[93m"
            )  # Default to yellow if lols_spam is not in the map

            # Log the message with the appropriate color
            LOGGER.debug(
                "%s%s:%s %02dmin check lols_cas_spam: %s\033[0m IDs to check left: %s",
                color_code,
                user_id,
                format_username_for_log(user_name),
                sleep_time // 60,
                lols_spam,
                len(active_user_checks_dict),
            )

            # getting message to delete link if it is in the checks dict
            # Note: Currently returns first message link - consider handling multiple links
            if user_id in active_user_checks_dict:
                if isinstance(active_user_checks_dict[user_id], dict):
                    # Detect post-join profile changes (name/username/photo)
                    _entry = active_user_checks_dict[user_id]
                    baseline = (
                        _entry.get("baseline") if isinstance(_entry, dict) else None
                    )
                    already_notified = (
                        _entry.get("notified_profile_change")
                        if isinstance(_entry, dict)
                        else False
                    )
                    if baseline and not already_notified:
                        _chat_info = (
                            baseline.get("chat", {})
                            if isinstance(baseline, dict)
                            else {}
                        )
                        _chat_id = _chat_info.get("id")

                        # Start from baseline and override with live data if available
                        cur_first = baseline.get("first_name", "")
                        cur_last = baseline.get("last_name", "")
                        cur_username = baseline.get("username", "")
                        cur_photo_count = baseline.get("photo_count", 0)

                        # Only fetch live data if we have a valid chat_id
                        if _chat_id:
                            try:
                                _member = await BOT.get_chat_member(_chat_id, user_id)
                                _user = getattr(_member, "user", None) or _member
                                cur_first = getattr(_user, "first_name", "") or ""
                                cur_last = getattr(_user, "last_name", "") or ""
                                cur_username = getattr(_user, "username", "") or ""
                            except TelegramBadRequest as _e:
                                LOGGER.debug(
                                    "%s:@%s unable to fetch chat member for profile-change check: %s",
                                    user_id,
                                    user_name,
                                    _e,
                                )

                        try:
                            _photos = await BOT.get_user_profile_photos(
                                user_id, limit=1
                            )
                            cur_photo_count = (
                                getattr(_photos, "total_count", 0)
                                if _photos
                                else cur_photo_count
                            )
                        except TelegramBadRequest as _e:
                            LOGGER.debug(
                                "%s:@%s unable to fetch photo count during checks: %s",
                                user_id,
                                user_name,
                                _e,
                            )

                        changed = []
                        if cur_first != baseline.get("first_name", ""):
                            changed.append("first name")
                        if cur_last != baseline.get("last_name", ""):
                            changed.append("last name")
                        # Normalize usernames before comparison to handle !UNDEFINED!/None/empty equivalence
                        if normalize_username(cur_username) != normalize_username(baseline.get("username", "")):
                            changed.append("username")
                        if baseline.get("photo_count", 0) == 0 and cur_photo_count > 0:
                            changed.append("profile photo")

                        if changed:
                            chat_username = _chat_info.get("username")
                            chat_title = _chat_info.get("title") or ""
                            universal_chatlink = build_chat_link(_chat_id, chat_username, chat_title) if _chat_id else "(unknown chat)"
                            _ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                            kb = make_lols_kb(user_id)
                            _chat_id_for_gban = baseline.get("chat", {}).get("id")
                            # Consolidated actions menu (expands to Ban / Global Ban / Delete)
                            # Use 0 for message_id - this is a profile change event, not a message
                            kb.add(
                                InlineKeyboardButton(
                                    text="⚙️ Actions (Ban / Delete) ⚙️",
                                    callback_data=f"suspiciousactions_{_chat_id_for_gban}_0_{user_id}",
                                )
                            )

                            def _fmt(old, new, label, username=False):
                                if username:
                                    old_disp = f"@{old}" if old else "!UNDEFINED!"
                                    new_disp = f"@{new}" if new else "!UNDEFINED!"
                                else:
                                    old_disp = html.escape(old) if old else ""
                                    new_disp = html.escape(new) if new else ""
                                if old != new:
                                    return f"{label}: {old_disp or '∅'} ➜ <b>{new_disp or '∅'}</b>"
                                return f"{label}: {new_disp or '∅'}"

                            field_lines = [
                                _fmt(
                                    baseline.get("first_name", ""),
                                    cur_first,
                                    "First name",
                                ),
                                _fmt(
                                    baseline.get("last_name", ""), cur_last, "Last name"
                                ),
                                _fmt(
                                    baseline.get("username", ""),
                                    cur_username,
                                    "Username",
                                    username=True,
                                ),
                                f"User ID: <code>{user_id}</code>",
                            ]
                            if (
                                baseline.get("photo_count", 0) == 0
                                and cur_photo_count > 0
                            ):
                                field_lines.append("Profile photo: none ➜ <b>set</b>")

                            profile_links = (
                                f"🔗 <b>Profile links:</b>\n"
                                f"   ├ <a href='tg://user?id={user_id}'>id based profile link</a>\n"
                                f"   └ <a href='tg://openmessage?user_id={user_id}'>Android</a>, <a href='https://t.me/@id{user_id}'>IOS (Apple)</a>"
                            )
                            # Compute elapsed time since join if we have a joined_at
                            joined_at_raw = baseline.get("joined_at")
                            elapsed_line = ""
                            if joined_at_raw:
                                try:
                                    # Handle both formats: with and without timezone
                                    joined_dt = datetime.fromisoformat(
                                        joined_at_raw.replace(" ", "T")
                                    )
                                    delta = datetime.now() - joined_dt
                                    # human friendly formatting
                                    days = delta.days
                                    hours, rem = divmod(delta.seconds, 3600)
                                    minutes, seconds = divmod(rem, 60)
                                    parts = []
                                    if days:
                                        parts.append(f"{days}d")
                                    if hours:
                                        parts.append(f"{hours}h")
                                    if minutes and not days:
                                        parts.append(f"{minutes}m")
                                    if seconds and not days and not hours:
                                        parts.append(f"{seconds}s")
                                    human_elapsed = " ".join(parts) or f"{seconds}s"
                                    elapsed_line = f"\nJoined at: {joined_at_raw} (elapsed: {human_elapsed})"
                                except ValueError:
                                    elapsed_line = f"\nJoined at: {joined_at_raw}"

                            message_text = (
                                f"Suspicious profile change detected after joining {universal_chatlink}.\n"
                                + "\n".join(field_lines)
                                + f"\nChanges: <b>{', '.join(changed)}</b> at {_ts}."
                                + elapsed_line
                                + "\n"
                                + profile_links
                            )

                            await safe_send_message(
                                BOT,
                                ADMIN_GROUP_ID,
                                message_text,
                                LOGGER,
                                message_thread_id=ADMIN_SUSPICIOUS,
                                parse_mode="HTML",
                                disable_web_page_preview=True,
                                reply_markup=kb.as_markup(),
                            )
                            # Log periodic profile change
                            await log_profile_change(
                                user_id=user_id,
                                username=cur_username,
                                context="periodic",
                                chat_id=_chat_id,
                                chat_title=chat_title,
                                changed=changed,
                                old_values=make_profile_dict(
                                    baseline.get("first_name", ""),
                                    baseline.get("last_name", ""),
                                    baseline.get("username", ""),
                                    baseline.get("photo_count", 0),
                                ),
                                new_values=make_profile_dict(
                                    cur_first,
                                    cur_last,
                                    cur_username,
                                    cur_photo_count,
                                ),
                                photo_changed=("profile photo" in changed),
                            )
                            active_user_checks_dict[user_id][
                                "notified_profile_change"
                            ] = True

                    suspicious_messages = {
                        k: v
                        for k, v in active_user_checks_dict[user_id].items()
                        if isinstance(k, str)
                        and "_" in k
                        and k not in ("username", "baseline", "notified_profile_change")
                    }
                    if suspicious_messages:
                        chat_id, message_id = next(iter(suspicious_messages)).split("_")
                        message_to_delete = [
                            int(str(chat_id).replace("-100", "", 1)),
                            int(message_id),
                        ]
            else:
                LOGGER.warning(
                    "%s:@%s User ID not found in active_user_checks_dict. Skipping...",
                    user_id,
                    user_name,
                )
                await cancel_named_watchdog(user_id, user_name)
                # stop cycle
                break

            if await check_and_autoban(
                event_record,
                user_id,
                inout_logmessage,
                user_name,
                lols_spam=lols_spam,
                message_to_delete=message_to_delete,
            ):
                return

    except asyncio.exceptions.CancelledError as e:
        LOGGER.error(
            "\033[93m%s:@%s %dhr spam checking cancelled. %s\033[0m",
            user_id,
            user_name,
            MONITORING_DURATION_HOURS,
            e,
        )
        if user_id in active_user_checks_dict:
            banned_users_dict[user_id] = active_user_checks_dict.pop(user_id, None)
            LOGGER.info(
                "\033[93m%s:@%s removed from active_user_checks_dict during perform_checks:\033[0m\n\t\t\t%s",
                user_id,
                user_name,
                active_user_checks_dict,
            )

    except aiohttp.ServerDisconnectedError as e:
        LOGGER.warning(
            "\033[93m%s Aiohttp Server DISCONNECTED error while checking for spam. \033[0m%s",
            user_id,
            e,
        )

    finally:
        # Remove the user ID from the active set when done
        # Finally Block:
        # The `finally` block ensures that the `user_id`
        # is removed from the `active_user_checks` dict
        # after all checks are completed or
        # if the function exits early due to a `return` statement:
        if (
            user_id in active_user_checks_dict
        ):  # avoid case when manually banned by admin same time
            # remove user from active checks dict as LEGIT / cleanup baseline
            try:
                del active_user_checks_dict[user_id]
            except KeyError:
                active_user_checks_dict.pop(user_id, None)
            # Mark monitoring as ended (completed without ban = legit)
            update_user_baseline_status(CONN, user_id, monitoring_active=False, is_legit=True)
            if len(active_user_checks_dict) > 3:
                active_user_checks_dict_last3_list = list(
                    active_user_checks_dict.items()
                )[-3:]
                active_user_checks_dict_last3_str = ", ".join(
                    [
                        f"{uid}: {uname}"
                        for uid, uname in active_user_checks_dict_last3_list
                    ]
                )
                LOGGER.info(
                    "\033[92m%s:@%s removed from active_user_checks_dict in finally block:\n\t\t\t%s... %d totally\033[0m",
                    user_id,
                    user_name,
                    active_user_checks_dict_last3_str,  # Last 3 elements
                    len(active_user_checks_dict),  # Number of elements left
                )
            else:
                LOGGER.info(
                    "\033[92m%s:@%s removed from active_user_checks_dict in finally block:\n\t\t\t%s\033[0m",
                    user_id,
                    user_name,
                    active_user_checks_dict,
                )


async def cancel_named_watchdog(user_id: int, user_name: str = "!UNDEFINED!"):
    """Cancels a running watchdog task for a given user ID (also cancels intensive watchdog if running)."""
    # Also cancel intensive watchdog if running
    if user_id in running_intensive_watchdogs:
        intensive_task = running_intensive_watchdogs.pop(user_id, None)
        if intensive_task:
            intensive_task.cancel()
            try:
                await intensive_task
            except asyncio.CancelledError:
                LOGGER.info(
                    "%s:@%s Intensive watchdog also cancelled.",
                    user_id,
                    user_name,
                )
            except RuntimeError:
                pass
    
    if user_id in running_watchdogs:
        # Try to remove from active_checks dict and add to banned_users_dict
        try:
            banned_users_dict[user_id] = active_user_checks_dict.pop(user_id, None)
        except KeyError:
            LOGGER.warning(
                "%s not found in active_user_checks_dict during cancel_named_watchdog.",
                user_id,
            )
        if user_id in active_user_checks_dict:
            del active_user_checks_dict[user_id]
            LOGGER.info(
                "\033[92m%s:@%s removed from active_user_checks_dict during cancel_named_watchdog:\033[0m\n\t\t\t%s",
                user_id,
                user_name,
                active_user_checks_dict,
            )
        # Cancel the task and remove it from the dictionary
        task = running_watchdogs.pop(user_id)
        task.cancel()
        try:
            await task
            LOGGER.info(
                "%s:@%s Watchdog disabled.(Cancelled)",
                user_id,
                user_name,
            )
        except asyncio.CancelledError:
            LOGGER.info(
                "%s:@%s Watchdog cancellation confirmed.",
                user_id,
                user_name,
            )
        except RuntimeError as e:
            LOGGER.error(
                "%s:@%s Error during watchdog cancellation: %s",
                user_id,
                user_name,
                e,
            )
    else:
        LOGGER.info(
            "%s:@%s No running watchdog found to cancel.",
            user_id,
            user_name,
        )


async def perform_intensive_checks(
    user_id: int,
    user_name: str = "!UNDEFINED!",
    message_chat_id: int = None,
    message_id: int = None,
    _message_link: str = None,
):
    """Perform intensive spam checks when a user from active_checks posts a message.
    
    This function checks external APIs (CAS/LOLS/P2P) very frequently in the first 5 minutes
    to catch spammers as soon as they get reported by other groups/bots.
    
    Schedule:
    - First 60 seconds: check every 10 seconds (6 checks)
    - Next 4 minutes: check every 30 seconds (8 checks)
    - Total: 14 checks in 5 minutes
    
    If spam is detected, the user is auto-banned. If admin legitimizes the user,
    the intensive watchdog is cancelled via cancel_intensive_watchdog().
    
    Args:
        user_id: The user ID to check
        user_name: Username for logging
        message_chat_id: Chat ID where the suspicious message was sent
        message_id: Message ID of the suspicious message
        message_link: Link to the suspicious message
    """
    color_map = {
        False: "\033[92m",  # Green for False (not spam)
        True: "\033[91m",   # Red for True (spam)
        None: "\033[93m",   # Yellow for None/unknown
    }
    
    message_to_delete = None
    if message_chat_id and message_id:
        message_to_delete = [message_chat_id, message_id]
    
    LOGGER.info(
        "\033[95m%s:@%s INTENSIVE watchdog started (message posted while in active_checks)\033[0m",
        user_id,
        user_name,
    )
    
    try:
        # Phase 1: First 60 seconds - check every 10 seconds (6 checks)
        for i in range(6):
            if user_id not in active_user_checks_dict:
                LOGGER.info(
                    "%s:@%s INTENSIVE check stopped - user no longer in active_checks",
                    user_id,
                    user_name,
                )
                return
            
            await asyncio.sleep(10)
            lols_spam = await spam_check(user_id)
            
            color_code = color_map.get(lols_spam, "\033[93m")
            LOGGER.debug(
                "%s%s:%s INTENSIVE check %d/14 (phase1 @10s): spam=%s\033[0m",
                color_code,
                user_id,
                format_username_for_log(user_name),
                i + 1,
                lols_spam,
            )
            
            if lols_spam is True:
                LOGGER.warning(
                    "\033[91m%s:@%s INTENSIVE check DETECTED SPAM! Auto-banning...\033[0m",
                    user_id,
                    user_name,
                )
                # Build event record and inout log message
                event_record = f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: {user_id:<10} INTENSIVE spam detected"
                inout_logmessage = f"{user_id}:@{user_name} detected as spam during INTENSIVE checks after posting message"
                
                if await check_and_autoban(
                    event_record,
                    user_id,
                    inout_logmessage,
                    user_name,
                    lols_spam=lols_spam,
                    message_to_delete=message_to_delete,
                ):
                    return
        
        # Phase 2: Next 4 minutes - check every 30 seconds (8 checks)
        for i in range(8):
            if user_id not in active_user_checks_dict:
                LOGGER.info(
                    "%s:@%s INTENSIVE check stopped - user no longer in active_checks",
                    user_id,
                    user_name,
                )
                return
            
            await asyncio.sleep(30)
            lols_spam = await spam_check(user_id)
            
            color_code = color_map.get(lols_spam, "\033[93m")
            LOGGER.debug(
                "%s%s:%s INTENSIVE check %d/14 (phase2 @30s): spam=%s\033[0m",
                color_code,
                user_id,
                format_username_for_log(user_name),
                i + 7,  # 7-14
                lols_spam,
            )
            
            if lols_spam is True:
                LOGGER.warning(
                    "\033[91m%s:@%s INTENSIVE check DETECTED SPAM! Auto-banning...\033[0m",
                    user_id,
                    user_name,
                )
                event_record = f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: {user_id:<10} INTENSIVE spam detected"
                inout_logmessage = f"{user_id}:@{user_name} detected as spam during INTENSIVE checks after posting message"
                
                if await check_and_autoban(
                    event_record,
                    user_id,
                    inout_logmessage,
                    user_name,
                    lols_spam=lols_spam,
                    message_to_delete=message_to_delete,
                ):
                    return
        
        LOGGER.info(
            "\033[92m%s:@%s INTENSIVE checks completed (5 min) - no spam detected, regular watchdog continues\033[0m",
            user_id,
            user_name,
        )
    
    except asyncio.CancelledError:
        LOGGER.info(
            "\033[93m%s:@%s INTENSIVE watchdog cancelled (user legitimized or banned elsewhere)\033[0m",
            user_id,
            user_name,
        )
    except RuntimeError as e:
        LOGGER.error(
            "%s:@%s Error during INTENSIVE checks: %s",
            user_id,
            user_name,
            e,
        )


async def cancel_intensive_watchdog(user_id: int, user_name: str = "!UNDEFINED!"):
    """Cancel an intensive watchdog for a user (called when admin legitimizes user or user is banned)."""
    if user_id in running_intensive_watchdogs:
        task = running_intensive_watchdogs.pop(user_id)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            LOGGER.info(
                "%s:@%s Intensive watchdog cancelled.",
                user_id,
                user_name,
            )
        except RuntimeError as e:
            LOGGER.warning(
                "%s:@%s Error cancelling intensive watchdog: %s",
                user_id,
                user_name,
                e,
            )


async def start_intensive_watchdog(
    user_id: int,
    user_name: str = "!UNDEFINED!",
    message_chat_id: int = None,
    message_id: int = None,
    _message_link: str = None,
):
    """Start an intensive watchdog for a user who posted a message while in active_checks.
    
    If an intensive watchdog is already running for this user, it will NOT restart it
    to avoid excessive API calls for users who post multiple messages.
    """
    if user_id in running_intensive_watchdogs:
        existing_task = running_intensive_watchdogs[user_id]
        if not existing_task.done():
            LOGGER.debug(
                "%s:@%s Intensive watchdog already running, skipping restart",
                user_id,
                user_name,
            )
            return
    
    # Create and start the intensive watchdog task
    task = asyncio.create_task(
        perform_intensive_checks(
            user_id=user_id,
            user_name=user_name,
            message_chat_id=message_chat_id,
            message_id=message_id,
        ),
        name=f"intensive_{user_id}",
    )
    running_intensive_watchdogs[user_id] = task
    
    # Cleanup callback when task completes
    def _cleanup(t: asyncio.Task, _uid=user_id):
        if running_intensive_watchdogs.get(_uid) is t:
            running_intensive_watchdogs.pop(_uid, None)
    
    task.add_done_callback(_cleanup)


async def create_named_watchdog(coro, user_id, user_name="!UNDEFINED!"):
    """Check if a task for the same user_id is already running

    :param coro: The coroutine to run

    :param user_id: The user ID to use as the key in the running_watchdogs dictionary

    """
    existing_task = running_watchdogs.get(user_id)
    if existing_task:
        LOGGER.info(
            "\033[93m%s:@%s Watchdog is already set. Cancelling and restarting existing task.\033[0m",
            user_id,
            user_name,
        )

    # Always create and register the new task immediately (non-blocking restart)
    task = asyncio.create_task(coro, name=str(user_id))
    running_watchdogs[user_id] = task
    LOGGER.info(
        "\033[91m%s:@%s Watchdog assigned.\033[0m",
        user_id,
        user_name,
    )  # Include user_name

    # Remove the task from the dictionary when it completes (only if it's still the current one)
    def _task_done(t: asyncio.Task, _uid=user_id):
        try:
            if running_watchdogs.get(_uid) is t:
                running_watchdogs.pop(_uid, None)
        finally:
            if t.cancelled():
                LOGGER.info("%s Task was cancelled.", _uid)
            else:
                exc = t.exception()
                if exc:
                    LOGGER.error("%s Task raised an exception: %s", _uid, exc)

    task.add_done_callback(_task_done)

    # If there was an existing task, cancel it and await in background
    if existing_task:
        try:
            existing_task.cancel()
        except RuntimeError:
            pass

        async def _await_cancel(_t: asyncio.Task, _uid=user_id, _uname=user_name):
            try:
                await _t
                _formatted_uname = (
                    f"@{_uname}"
                    if _uname and _uname != "!UNDEFINED!"
                    else "!UNDEFINED!"
                )
                LOGGER.info(
                    "%s:%s Previous watchdog cancelled.", _uid, _formatted_uname
                )
            except asyncio.CancelledError:
                _formatted_uname = (
                    f"@{_uname}"
                    if _uname and _uname != "!UNDEFINED!"
                    else "!UNDEFINED!"
                )
                LOGGER.info(
                    "%s:%s Previous watchdog cancellation confirmed.",
                    _uid,
                    _formatted_uname,
                )
            except RuntimeError as e:
                _formatted_uname = (
                    f"@{_uname}"
                    if _uname and _uname != "!UNDEFINED!"
                    else "!UNDEFINED!"
                )
                LOGGER.error(
                    "%s:%s Error while cancelling previous watchdog: %s",
                    _uid,
                    _formatted_uname,
                    e,
                )

        asyncio.create_task(_await_cancel(existing_task), name=f"cancel:{user_id}")

    return task  # Return the task so the caller can manage it


async def log_lists(group=TECHNOLOG_GROUP_ID, msg_thread_id=TECHNO_ADMIN):
    """
    Log the banned users and active user checks lists.

    Args:
        group (int): The group ID to send the log message to. Defaults to TECHNOLOG_GROUP_ID.
        msg_thread_id (int): The message thread ID to send the log message to. Defaults to TECHNO_ADMIN.
    """

    LOGGER.info(
        "\033[93m%s banned users dict: %s\033[0m",
        len(banned_users_dict),
        banned_users_dict,
    )
    LOGGER.info(
        "\033[93m%s Active user checks dict: %s\033[0m",
        len(active_user_checks_dict),
        active_user_checks_dict,
    )
    # Note: move inout and daily_spam logs to the dedicated folders
    # save banned users list to the file
    # Get yesterday's date
    today = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")
    # Construct the filename with the current date
    filename = f"inout/banned_users_{today}.txt"

    # Ensure the inout directory exists
    os.makedirs("inout", exist_ok=True)
    os.makedirs("daily_spam", exist_ok=True)

    # read current banned users list from the file
    banned_users_filename = "banned_users.txt"

    if os.path.exists(banned_users_filename):
        with open(banned_users_filename, "r", encoding="utf-8") as file:
            # append users to the set
            for line in file:
                parts = line.strip().split(":", 1)
                if len(parts) == 2:
                    user_id, user_name = parts
                    try:
                        user_name = ast.literal_eval(user_name.strip())
                    except (ValueError, SyntaxError):
                        pass  # keep user_name as string if it's not a valid dict
                    banned_users_dict[int(user_id)] = user_name
                else:
                    LOGGER.warning("\033[93mSkipping invalid line: %s\033[0m", line)
        os.remove(banned_users_filename)  # remove the file after reading

    # save banned users list to the file with the current date to the inout folder
    with open(filename, "w", encoding="utf-8") as file:
        for _id, _username in banned_users_dict.items():
            file.write(f"{_id}:{_username}\n")

    # move yesterday's daily_spam file to the daily_spam folder
    daily_spam_filename = get_daily_spam_filename()
    inout_filename = get_inout_filename()

    # Move yesterday's daily_spam file to the daily_spam folder
    for file in os.listdir():
        if file.startswith("daily_spam_") and file != daily_spam_filename:
            os.rename(file, f"daily_spam/{file}")

    # Move yesterday's inout file to the inout folder
    for file in os.listdir():
        if file.startswith("inout_") and file != inout_filename:
            os.rename(file, f"inout/{file}")

    try:
        # Create a list for active user checks with user_id as key and username as value
        active_user_checks_list = []
        for user, uname in active_user_checks_dict.items():
            # extract_username handles @ symbol correctly (adds @ for valid usernames, no @ for !UNDEFINED!)
            _disp = extract_username(uname)
            active_user_checks_list.append(f"<code>{user}</code>  {_disp}")
            # If uname is a dict, extract URLs from it
            if isinstance(uname, dict):
                for k, v in uname.items():
                    if k != "username" and isinstance(v, str) and v.startswith("http"):
                        active_user_checks_list.append(v)
        # Create a list for banned users with user_id as key and user_name as value
        banned_users_list = [
            f"<code>{user_id}</code>  {extract_username(user_name)}"
            for user_id, user_name in banned_users_dict.items()
        ]

        # Split lists into chunks
        max_message_length = (
            MAX_TELEGRAM_MESSAGE_LENGTH - 100
        )  # Reserve some space for other text
        active_user_chunks = list(
            split_list(active_user_checks_list, max_message_length)
        )
        banned_user_chunks = list(split_list(banned_users_list, max_message_length))

        # Send active user checks dict
        if active_user_chunks:
            for i, chunk in enumerate(active_user_chunks):
                header = (
                    f"Active user checks dict ({len(active_user_checks_dict)}):\n"
                    if i == 0
                    else "Active user checks dict (continued):\n"
                )
                try:
                    await safe_send_message(
                        BOT,
                        group,
                        header + chr(10).join(chunk),
                        LOGGER,
                        message_thread_id=msg_thread_id,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                except TelegramBadRequest as e:
                    LOGGER.error("Error sending active user checks chunk: %s", e)
        else:
            await safe_send_message(
                BOT,
                group,
                "No active user checks at the moment.",
                LOGGER,
                message_thread_id=msg_thread_id,
                parse_mode="HTML",
            )

        # Send banned users dict
        if banned_user_chunks:
            for i, chunk in enumerate(banned_user_chunks):
                header = (
                    f"Banned users dict ({len(banned_users_dict)}):\n"
                    if i == 0
                    else "Banned users dict (continued):\n"
                )
                try:
                    await safe_send_message(
                        BOT,
                        group,
                        header + chr(10).join(chunk),
                        LOGGER,
                        message_thread_id=msg_thread_id,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                except TelegramBadRequest as e:
                    LOGGER.error("Error sending banned users chunk: %s", e)
        else:
            await safe_send_message(
                BOT,
                group,
                "No banned users at the moment.",
                LOGGER,
                message_thread_id=msg_thread_id,
                parse_mode="HTML",
            )
    except TelegramBadRequest as e:
        LOGGER.error("Error sending active_user_checks_dict: %s", e)


# async def get_photo_details(user_id: int):
#     """Function to get the photo details of the user profile with the given ID.

#     :param user_id: int: The ID of the user profile to get the photo details for

#     """
#     # Get the photo details of the user profile with the given ID
#     # https://core.telegram.org/bots/api#getuserprofilephotos
#     # https://core.telegram.org/bots/api#userprofilephotos
#     # https://core.telegram.org/bots/api#photofile
#     photo_data = await BOT.get_user_profile_photos(user_id)
#     # get photo upload date of the user profile with ID user_id
#     if not photo_data:
#         LOGGER.debug("\033[96m%s have no photo data\033[0m", user_id)
#     for photo in photo_data.photos:
#         for size in photo:
#             photo = await BOT.get_file(size.file_id)
#             # get file details of photo file
#             # https://core.telegram.org/bots/api#file
#             # https://core.telegram.org/bots/api#photofile
#             # LOGGER.debug("%s Photo file details: %s", user_id, photo)
#             # get file Use https://api.telegram.org/file/bot<token>/<file_path> to get the file.
#             url = f"https://api.telegram.org/file/bot{API_TOKEN}/{photo.file_path}"
#             response = requests.get(url)
#             if response.status_code == 200:
#                 image = Image.open(BytesIO(response.content))
#                 metadata = image.info

#                 LOGGER.debug("%s photo metadata: %s", user_id, metadata)

#                 return response.content
#             else:
#                 response.raise_for_status()


if __name__ == "__main__":

    # Start tracing Python memory allocations
    # tracemalloc.start()

    # Dictionary to store the mapping of unhandled messages to admin's replies
    # global unhandled_messages
    unhandled_messages = (
        {}
    )  # Note:: Store in DB to preserve between sessions

    # Load configuration values from the XML file
    # load_config()

    LOGGER.info("Using bot: %s", BOT_NAME)
    LOGGER.info("Using bot id: %s", BOT_USERID)
    LOGGER.info("Using log group: %s, id: %s", LOG_GROUP_NAME, LOG_GROUP)
    LOGGER.info(
        "Using techno log group: %s, id: %s", TECHNOLOG_GROUP_NAME, TECHNOLOG_GROUP
    )
    channel_info = [f"{name}({id_})" for name, id_ in zip(CHANNEL_NAMES, CHANNEL_IDS)]
    LOGGER.info("Monitoring chats: %s", ", ".join(channel_info))
    LOGGER.info("\n")
    LOGGER.info(
        "Excluding autoreport when forwarded from chats: @%s",
        " @".join([d["name"] for d in ALLOWED_FORWARD_CHANNELS]),
    )
    LOGGER.info("\n")

    @DP.chat_member(is_not_bot_action)  # exclude bot's own actions
    async def greet_chat_members(update: ChatMemberUpdated):
        """Checks for change in the chat members statuses and check if they are spammers."""
        # Update chat username cache
        update_chat_username_cache(update.chat.id, update.chat.username)

        # Who did the action
        by_user = None
        # get photo upload date of the user profile with ID update.from_user.id
        # Note:: get the photo upload date of the user profile
        # photo_date = await BOT.get_user_profile_photos(update.from_user.id)
        # await get_photo_details(update.from_user.id)  # Disabled for now

        if (
            update.old_chat_member.user.id in banned_users_dict
        ):  # prevent double actions if user already banned by other process
            LOGGER.info(
                "%s:@%s already banned - skipping actions.",
                update.old_chat_member.user.id,
                update.from_user.username or "!UNDEFINED!",
            )
            return

        if update.from_user.id != update.old_chat_member.user.id:
            # Someone else changed user status
            by_username = update.from_user.username  # optional, may be None
            # by_userid = update.from_user.id
            by_userfirstname = update.from_user.first_name
            by_userlastname = update.from_user.last_name or ""  # optional
            by_username_display = f"@{by_username}" if by_username else ""
            by_user = f"by {by_userfirstname} {by_userlastname} {by_username_display} (<code>{update.from_user.id}</code>)\n"

        inout_status = update.new_chat_member.status

        inout_chattitle = update.chat.title

        # Whoose this action is about
        inout_userid = update.old_chat_member.user.id
        inout_userfirstname = update.old_chat_member.user.first_name
        inout_userlastname = update.old_chat_member.user.last_name or ""  # optional
        inout_username = (
            update.old_chat_member.user.username or "!UNDEFINED!"
        )  # optional

        lols_spam = await spam_check(update.old_chat_member.user.id)

        event_record = (
            f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "  # Date and time with milliseconds
            f"{inout_userid:<10} "
            f"{'❌  ' if lols_spam is True else '🟢 ' if lols_spam is False else '❓ '}"
            f"{' '.join('@' + getattr(update.old_chat_member.user, attr) if attr == 'username' else str(getattr(update.old_chat_member.user, attr, '')) for attr in ('username', 'first_name', 'last_name') if getattr(update.old_chat_member.user, attr, '')):<32}"
            f" {update.old_chat_member.status:<15} --> {inout_status:<15} in "
            f"{'@' + update.chat.username + ': ' if update.chat.username else '':<24}{update.chat.title:<30} by "
            f"{update.from_user.id:<10} "
            f"{' '.join('@' + getattr(update.from_user, attr) if attr == 'username' else str(getattr(update.from_user, attr, '')) for attr in ('username', 'first_name', 'last_name') if getattr(update.from_user, attr, ''))}\n"
        )

        # Save the event to the inout file
        await save_report_file("inout_", "gcm" + event_record)

        # Escape special characters in the log message
        escaped_inout_userfirstname = html.escape(inout_userfirstname)
        escaped_inout_userlastname = html.escape(inout_userlastname)
        # construct chatlink for any type of chat
        universal_chatlink = build_chat_link(update.chat.id, update.chat.username, update.chat.title)
        # Get current date and time DD-MM-YY HH:MM
        greet_timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        # Construct the log message
        inout_username_display = f"@{inout_username}" if inout_username and inout_username != "!UNDEFINED!" else ""
        inout_logmessage = (
            f"{escaped_inout_userfirstname} {escaped_inout_userlastname} "
            f"{inout_username_display} (<code>{inout_userid}</code>)\n"
            f"{'❌ -->' if lols_spam is True else '🟢 -->' if lols_spam is False else '❓ '}"
            f" {inout_status}\n"
            f"{by_user if by_user else ''}"
            f"💬 {universal_chatlink}\n"
            f"🕔 {greet_timestamp}\n"
            f"🔗 <b>profile links:</b>\n"
            f"   ├ <b><a href='tg://user?id={inout_userid}'>id based profile link</a></b>\n"
            f"   └ <a href='tg://openmessage?user_id={inout_userid}'>Android</a>, <a href='https://t.me/@id{inout_userid}'>IOS (Apple)</a>\n"
        )

        inline_kb = make_lols_kb(inout_userid)

        inout_thread = None  # initialize
        # Determine thread: OUT for spammers or users leaving, IN for clean users joining
        is_leaving = inout_status in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.KICKED,
            ChatMemberStatus.RESTRICTED,
        )
        if lols_spam is True or is_leaving:
            inout_thread = TECHNO_OUT
        else:
            inout_thread = TECHNO_IN
            # Add buttons for non-spammers joining
            # Use 0 for message_id to indicate this is a join event (no message to link to)
            inline_kb.add(
                InlineKeyboardButton(
                    text="✅ Mark as Legit",
                    callback_data=f"stopchecks_{inout_userid}_{update.chat.id}_0",
                )
            )
            inline_kb.add(
                InlineKeyboardButton(
                    text="🚫 Ban User", callback_data=f"banuser_{inout_userid}"
                )
            )

        # Check if leaving user is still in other monitored chats
        other_chats_info = ""
        if is_leaving:
            # Always add ban button for leaving users (admin can decide if suspicious)
            if lols_spam is not True:  # Don't duplicate if already detected as spammer
                inline_kb.add(
                    InlineKeyboardButton(
                        text="🚫 Ban User", callback_data=f"banuser_{inout_userid}"
                    )
                )
            
            other_chats = await get_user_other_chats(
                inout_userid, update.chat.id, CHANNEL_IDS, CHANNEL_DICT
            )
            if other_chats:
                # Build clickable chat links with @username format
                other_chats_links = []
                for chat_id, chat_name, chat_username in other_chats:
                    if chat_username:
                        # @username (ChatName) with clickable link
                        other_chats_links.append(
                            f"<a href='https://t.me/{chat_username}'>@{chat_username}</a> ({html.escape(chat_name)})"
                        )
                    else:
                        # Fallback to private link if no username
                        chat_id_str = str(chat_id)[4:] if str(chat_id).startswith("-100") else str(chat_id)
                        other_chats_links.append(
                            f"<a href='https://t.me/c/{chat_id_str}'>{html.escape(chat_name)}</a>"
                        )
                other_chats_list = "\n   • ".join(other_chats_links)
                other_chats_info = (
                    f"\n⚠️ <b>Still in {len(other_chats)} other chat(s):</b>\n   • {other_chats_list}"
                )

        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP,
            inout_logmessage + other_chats_info,
            LOGGER,
            message_thread_id=inout_thread,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb.as_markup(),
        )

        # different colors for inout status
        status_colors = {
            ChatMemberStatus.KICKED: "\033[91m",  # Red
            ChatMemberStatus.RESTRICTED: "\033[93m",  # Yellow
        }
        color = status_colors.get(inout_status, "")  # Default to no color
        reset_color = "\033[0m" if color else ""  # Reset color if a color was used
        LOGGER.info(
            "%s%s:%s --> %s in %s%s",
            color,
            inout_userid,
            format_username_for_log(inout_username),
            inout_status,
            inout_chattitle,
            reset_color,
        )

        # if already identified as a spammer and not TIMEOUT
        if lols_spam is True:
            await check_and_autoban(
                event_record,
                inout_userid,
                inout_logmessage,
                inout_username,
                lols_spam=lols_spam,
            )
            return  # stop further checks

        # Extract the user status change
        result = extract_status_change(update)
        if result is None:
            return
        was_member, is_member = result

        # Check for very high user ID on JOIN events (very new accounts are suspicious)
        if is_member and not was_member and inout_userid > HIGH_USER_ID_THRESHOLD:
            # User is joining and has very high ID - send alert to suspicious thread
            # Use 0 for message_id to indicate this is a join event (no message to link to)
            _chat_link_html = build_chat_link(update.chat.id, update.chat.username, update.chat.title)
            _high_id_message = (
                f"🆕 <b>Very New Account Joined</b>\n"
                f"User ID: <code>{inout_userid}</code> (> 8.2B)\n"
                f"Name: {html.escape(inout_userfirstname)} {html.escape(inout_userlastname)}\n"
                f"Username: @{inout_username}\n"
                f"Chat: {_chat_link_html}\n\n"
                f"🔗 <b>Profile links:</b>\n"
                f"   ├ <a href='tg://user?id={inout_userid}'>ID based profile link</a>\n"
                f"   └ <a href='tg://openmessage?user_id={inout_userid}'>Android</a>, "
                f"<a href='https://t.me/@id{inout_userid}'>iOS</a>"
            )
            _high_id_kb = make_lols_kb(inout_userid)
            _high_id_kb.add(
                InlineKeyboardButton(
                    text="⚙️ Actions (Ban / Delete) ⚙️",
                    callback_data=f"suspiciousactions_{update.chat.id}_0_{inout_userid}",
                )
            )
            _high_id_kb.add(
                InlineKeyboardButton(
                    text="✅ Mark as Legit",
                    callback_data=f"stopchecks_{inout_userid}_{update.chat.id}_0",
                )
            )
            await safe_send_message(
                BOT,
                ADMIN_GROUP_ID,
                _high_id_message,
                LOGGER,
                message_thread_id=ADMIN_SUSPICIOUS,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=_high_id_kb.as_markup(),
            )
            LOGGER.warning(
                "\033[93m%s:@%s has very high user ID (>8.2B) - flagged as suspicious on join\033[0m",
                inout_userid,
                inout_username,
            )

        # Check lols after user join/leave event and ban if spam
        if (
            inout_status == ChatMemberStatus.KICKED
            or inout_status == ChatMemberStatus.RESTRICTED
        ):  # not Timeout (lols_spam) exactly or if kicked/restricted by someone else
            # Call check_and_autoban with concurrency control using named tasks
            _task_GCM = await create_named_watchdog(
                check_and_autoban(
                    event_record,
                    inout_userid,
                    inout_logmessage,
                    user_name=update.old_chat_member.user.username,
                    lols_spam=lols_spam,
                ),
                user_id=inout_userid,
                user_name=inout_username,
            )

        elif inout_status in (
            ChatMemberStatus.MEMBER,
            # ChatMemberStatus.KICKED,
            # ChatMemberStatus.RESTRICTED,
            ChatMemberStatus.LEFT,
        ):  # only if user joined or kicked or restricted or left

            # Check if admin manually re-added a previously banned/monitored user
            if (
                inout_status == ChatMemberStatus.MEMBER
                and is_member
                and not was_member
                and update.from_user.id != inout_userid  # Someone else added the user
                and (inout_userid in banned_users_dict or inout_userid in active_user_checks_dict)
            ):
                # Check if the person who added the user is an admin in that chat
                try:
                    is_admin_in_chat = await is_admin(update.from_user.id, update.chat.id)
                    if is_admin_in_chat:
                        admin_username = update.from_user.username
                        admin_id = update.from_user.id
                        
                        LOGGER.info(
                            "\033[95m%s:@%s manually re-added by admin %s:%s - cancelling checks and marking as legit\033[0m",
                            inout_userid,
                            inout_username,
                            admin_id,
                            f"@{admin_username}" if admin_username else "!UNDEFINED!",
                        )
                        
                        # Cancel watchdog
                        await cancel_named_watchdog(inout_userid, inout_username)
                        
                        # Remove from dicts
                        if inout_userid in active_user_checks_dict:
                            del active_user_checks_dict[inout_userid]
                        if inout_userid in banned_users_dict:
                            del banned_users_dict[inout_userid]
                        
                        # Mark as legit in database
                        try:
                            CURSOR.execute(
                                """
                                INSERT OR REPLACE INTO recent_messages
                                (chat_id, message_id, user_id, user_name, user_first_name, user_last_name, received_date, new_chat_member, left_chat_member)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    update.chat.id,
                                    int(f"{int(getattr(update, 'date', datetime.now()).timestamp())}"),
                                    inout_userid,
                                    inout_username if inout_username != "!UNDEFINED!" else None,
                                    inout_userfirstname,
                                    inout_userlastname if inout_userlastname else None,
                                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    1,
                                    1,
                                ),
                            )
                            CONN.commit()
                            LOGGER.info(
                                "\033[92m%s:@%s marked as legitimate in database by admin %s:@%s re-add action\033[0m",
                                inout_userid,
                                inout_username,
                                admin_id,
                                admin_username,
                            )
                        except sqlite3.Error as db_err:
                            LOGGER.error(
                                "Database error while marking user %d as legit on admin re-add: %s", inout_userid, db_err
                            )
                        
                        # Remove from P2P network spam list
                        try:
                            p2p_removed = await remove_spam_from_2p2p(inout_userid, LOGGER)
                            if p2p_removed:
                                LOGGER.info(
                                    "\033[92m%s:@%s removed from P2P spam list by admin re-add\033[0m",
                                    inout_userid,
                                    inout_username,
                                )
                            else:
                                LOGGER.warning(
                                    "\033[93m%s:@%s could not be removed from P2P spam list\033[0m",
                                    inout_userid,
                                    inout_username,
                                )
                        except (aiohttp.ClientError, asyncio.TimeoutError) as p2p_e:
                            LOGGER.error(
                                "Failed to remove user %s from P2P on admin re-add: %s", inout_userid, p2p_e
                            )
                        
                        # Notify tech group
                        await safe_send_message(
                            BOT,
                            TECHNOLOG_GROUP_ID,
                            f"User {inout_userid} (@{inout_username}) manually re-added to {inout_chattitle} by admin {admin_id}:@{admin_username}. Marked as legitimate.",
                            LOGGER,
                            message_thread_id=TECHNO_ADMIN,
                        )
                        
                        return  # Skip further processing
                except TelegramBadRequest as admin_check_err:
                    LOGGER.error(
                        "Error checking admin status for user re-add: %s", admin_check_err
                    )

            # Get the current timestamp

            # Log the message with the timestamp
            LOGGER.debug(
                "\033[96m%s:@%s Scheduling perform_checks coroutine\033[0m",
                inout_userid,
                inout_username,
            )
            # Check if the user ID is already being processed
            if inout_userid not in active_user_checks_dict:
                # Only capture baseline on join (is_member True) to compare later on leave
                if "is_member" in locals() and is_member:
                    try:
                        photos = await BOT.get_user_profile_photos(
                            inout_userid, limit=1
                        )
                        _photo_count = (
                            getattr(photos, "total_count", 0) if photos else 0
                        )
                    except TelegramBadRequest as _e:
                        _photo_count = 0
                        LOGGER.debug(
                            "%s:@%s unable to fetch initial photo count: %s",
                            inout_userid,
                            inout_username,
                            _e,
                        )

                    # Save baseline to database
                    save_user_baseline(
                        conn=CONN,
                        user_id=inout_userid,
                        username=update.old_chat_member.user.username,
                        first_name=update.old_chat_member.user.first_name or "",
                        last_name=update.old_chat_member.user.last_name or "",
                        photo_count=_photo_count,
                        join_chat_id=update.chat.id,
                        join_chat_username=getattr(update.chat, "username", None),
                        join_chat_title=getattr(update.chat, "title", "") or "",
                    )

                    active_user_checks_dict[inout_userid] = {
                        "username": update.old_chat_member.user.username,
                        "baseline": {
                            "first_name": update.old_chat_member.user.first_name or "",
                            "last_name": update.old_chat_member.user.last_name or "",
                            "username": update.old_chat_member.user.username or "",
                            "photo_count": _photo_count,
                            # Store join timestamp (server local time) to compute elapsed durations later
                            "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "chat": {
                                "id": update.chat.id,
                                "username": getattr(update.chat, "username", None),
                                "title": getattr(update.chat, "title", "") or "",
                            },
                        },
                    }
                # create task with user_id as name
                asyncio.create_task(
                    perform_checks(
                        event_record=event_record,
                        user_id=update.old_chat_member.user.id,
                        inout_logmessage=inout_logmessage,
                        user_name=(
                            update.old_chat_member.user.username
                            if update.old_chat_member.user.username
                            else "!UNDEFINED!"
                        ),
                    ),
                    name=str(inout_userid),
                )
            else:
                LOGGER.debug(
                    "\033[93m%s:@%s skipping perform_checks as it is already being processed\033[0m",
                    inout_userid,
                    inout_username,
                )

        # record the event in the database if not lols_spam
        if not lols_spam:
            CURSOR.execute(
                """
                INSERT OR REPLACE INTO recent_messages
                (chat_id, chat_username, message_id, user_id, user_name, user_first_name, user_last_name, forward_date, forward_sender_name, received_date, from_chat_title, forwarded_from_id, forwarded_from_username, forwarded_from_first_name, forwarded_from_last_name, new_chat_member, left_chat_member)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    getattr(update.chat, "id", None),
                    getattr(update.chat, "username", ""),
                    # Note: Using timestamp as message_id since ChatMemberUpdated has no message_id
                    int(f"{int(getattr(update, 'date', datetime.now()).timestamp())}"),
                    getattr(update.old_chat_member.user, "id", None),
                    getattr(update.old_chat_member.user, "username", ""),
                    getattr(update.old_chat_member.user, "first_name", ""),
                    getattr(update.old_chat_member.user, "last_name", ""),
                    # Convert datetime to string to avoid Python 3.12+ deprecation warning
                    update.date.strftime("%Y-%m-%d %H:%M:%S") if update.date else None,
                    getattr(update.from_user, "id", ""),
                    update.date.strftime("%Y-%m-%d %H:%M:%S") if update.date else None,
                    getattr(update.chat, "title", None),
                    getattr(update.from_user, "id", None),
                    getattr(update.from_user, "username", ""),
                    getattr(update.from_user, "first_name", ""),
                    getattr(update.from_user, "last_name", ""),
                    is_member,
                    was_member,
                ),
            )
            CONN.commit()

        # checking if user joins and leave chat in 1 minute or less
        if inout_status == ChatMemberStatus.LEFT:
            try:  # check if left less than 1 min after join
                # First, compare against baseline captured at join, if available
                _entry = active_user_checks_dict.get(inout_userid)
                _baseline = _entry.get("baseline") if isinstance(_entry, dict) else None
                _already_notified = (
                    _entry.get("notified_profile_change")
                    if isinstance(_entry, dict)
                    else False
                )
                if _baseline and not _already_notified:
                    # For leave events, Telegram provides the current user data in update.old_chat_member.user
                    _u = update.old_chat_member.user
                    cur_first = getattr(_u, "first_name", "") or ""
                    cur_last = getattr(_u, "last_name", "") or ""
                    cur_username = getattr(_u, "username", "") or ""
                    try:
                        _p = await BOT.get_user_profile_photos(inout_userid, limit=1)
                        cur_photo_count = (
                            getattr(_p, "total_count", 0)
                            if _p
                            else _baseline.get("photo_count", 0)
                        )
                    except TelegramBadRequest as _e:
                        cur_photo_count = _baseline.get("photo_count", 0)
                        LOGGER.debug(
                            "%s:@%s unable to fetch photo count on leave: %s",
                            inout_userid,
                            inout_username,
                            _e,
                        )

                    _changed = []
                    if cur_first != _baseline.get("first_name", ""):
                        _changed.append("first name")
                    if cur_last != _baseline.get("last_name", ""):
                        _changed.append("last name")
                    # Normalize usernames before comparison to handle !UNDEFINED!/None/empty equivalence
                    if normalize_username(cur_username) != normalize_username(_baseline.get("username", "")):
                        _changed.append("username")
                    if _baseline.get("photo_count", 0) == 0 and cur_photo_count > 0:
                        _changed.append("profile photo")

                    if _changed:
                        _chat_info = _baseline.get("chat", {})
                        _cid = _chat_info.get("id", update.chat.id)
                        _cuser = _chat_info.get("username") or getattr(
                            update.chat, "username", None
                        )
                        _ctitle = (
                            _chat_info.get("title")
                            or getattr(update.chat, "title", "")
                            or ""
                        )
                        _link = build_chat_link(_cid, _cuser, _ctitle)
                        _ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                        _kb = make_lols_kb(inout_userid)
                        # Use 0 for message_id - this is a leave event, not a message
                        _kb.add(
                            InlineKeyboardButton(
                                text="⚙️ Actions (Ban / Delete) ⚙️",
                                callback_data=f"suspiciousactions_{update.chat.id}_0_{inout_userid}",
                            )
                        )
                        # Elapsed time since join if available
                        joined_at_raw = _baseline.get("joined_at")
                        elapsed_line = ""
                        if joined_at_raw:
                            try:
                                # Strip timezone if present
                                _ja_str = str(joined_at_raw)
                                if "+" in _ja_str:
                                    _ja_str = _ja_str.split("+")[0].strip()
                                _jdt = datetime.strptime(
                                    _ja_str, "%Y-%m-%d %H:%M:%S"
                                )
                                _delta = datetime.now() - _jdt
                                _days = _delta.days
                                _hours, _rem = divmod(_delta.seconds, 3600)
                                _minutes, _seconds = divmod(_rem, 60)
                                _parts = []
                                if _days:
                                    _parts.append(f"{_days}d")
                                if _hours:
                                    _parts.append(f"{_hours}h")
                                if _minutes and not _days:
                                    _parts.append(f"{_minutes}m")
                                if _seconds and not _days and not _hours:
                                    _parts.append(f"{_seconds}s")
                                _human_elapsed = " ".join(_parts) or f"{_seconds}s"
                                elapsed_line = f"\nJoined at: {joined_at_raw} (elapsed: {_human_elapsed})"
                            except ValueError:
                                elapsed_line = f"\nJoined at: {joined_at_raw}"

                        _leave_msg = (
                            f"Suspicious activity detected between join and leave in {_link}.\n"
                            f"User @{cur_username or '!UNDEFINED!'} (<code>{inout_userid}</code>) changed: <b>{', '.join(_changed)}</b> before leaving at {_ts}."
                            + elapsed_line
                        )
                        await safe_send_message(
                            BOT,
                            ADMIN_GROUP_ID,
                            _leave_msg,
                            LOGGER,
                            message_thread_id=ADMIN_SUSPICIOUS,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                            reply_markup=_kb.as_markup(),
                        )
                        # Log profile change on leave
                        await log_profile_change(
                            user_id=inout_userid,
                            username=cur_username,
                            context="leave",
                            chat_id=_cid,
                            chat_title=_ctitle,
                            changed=_changed,
                            old_values=make_profile_dict(
                                _baseline.get("first_name", ""),
                                _baseline.get("last_name", ""),
                                _baseline.get("username", ""),
                                _baseline.get("photo_count", 0),
                            ),
                            new_values=make_profile_dict(
                                cur_first,
                                cur_last,
                                cur_username,
                                cur_photo_count,
                            ),
                            photo_changed=("profile photo" in _changed),
                        )
                        active_user_checks_dict[inout_userid][
                            "notified_profile_change"
                        ] = True

                last2_join_left_event = CURSOR.execute(
                    """
                    SELECT received_date, new_chat_member, left_chat_member
                    FROM recent_messages
                    WHERE user_id = ?
                    ORDER BY received_date DESC
                    LIMIT 2
                    """,
                    (inout_userid,),
                ).fetchall()
                # Handle both formats: with and without timezone
                time_diff = (
                    datetime.fromisoformat(last2_join_left_event[0][0].replace(" ", "T"))
                    - datetime.fromisoformat(
                        last2_join_left_event[1][0].replace(" ", "T")
                    )
                ).total_seconds()

                if (
                    time_diff <= 30
                    and last2_join_left_event[0][2] == 1
                    and last2_join_left_event[1][1] == 1
                ):
                    LOGGER.debug(
                        "%s:@%s joined and left %s in 30 seconds or less",
                        inout_userid,
                        inout_username,
                        inout_chattitle,
                    )
                    # ban user from all chats
                    _success_count, _fail_count, _total_count = (
                        await ban_user_from_all_chats(
                            inout_userid, inout_username, CHANNEL_IDS, CHANNEL_DICT
                        )
                    )
                    lols_url = build_lols_url(inout_userid)
                    inline_kb = KeyboardBuilder().add(
                        InlineKeyboardButton(text="Check user profile", url=lols_url)
                    )
                    joinleft_timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                    await safe_send_message(
                        BOT,
                        ADMIN_GROUP_ID,
                        f"{escaped_inout_userfirstname} {escaped_inout_userlastname} @{inout_username} (<code>{inout_userid}</code>) joined and left {universal_chatlink} in 30 seconds or less. Telefragged at {joinleft_timestamp}...",
                        LOGGER,
                        message_thread_id=ADMIN_AUTOBAN,
                        parse_mode="HTML",
                        reply_markup=inline_kb.as_markup(),
                        disable_web_page_preview=True,
                    )
                    _uname_1790 = normalize_username(
                        getattr(update.old_chat_member.user, "username", None)
                    )
                    if _uname_1790 and _uname_1790 not in POSTED_USERNAMES:
                        POSTED_USERNAMES.add(_uname_1790)
                        await safe_send_message(
                            BOT,
                            TECHNOLOG_GROUP_ID,
                            f"<code>{inout_userid}</code> @{_uname_1790} (1790)",
                            LOGGER,
                            parse_mode="HTML",
                            message_thread_id=TECHNO_NAMES,
                        )
            except IndexError:
                LOGGER.debug(
                    "%s:@%s left and has no previous join/leave events or was already in lols/cas spam",
                    inout_userid,
                    inout_username,
                )

            # Always cleanup the baseline/watch entry when the user leaves
            if inout_userid in active_user_checks_dict:
                try:
                    del active_user_checks_dict[inout_userid]
                    LOGGER.debug(
                        "%s:@%s removed baseline/watch entry on leave",
                        inout_userid,
                        inout_username,
                    )
                except KeyError as _e:
                    LOGGER.debug(
                        "%s:@%s failed to remove baseline/watch entry on leave: %s",
                        inout_userid,
                        inout_username,
                        _e,
                    )

    @DP.message(is_forwarded_from_unknown_channel_message)
    async def handle_forwarded_reports(message: Message):
        """Function to handle forwarded messages."""

        reported_spam = format_spam_report(message)
        # store spam text and caption to the daily_spam file
        await save_report_file("daily_spam_", reported_spam)

        # Check if this is superadmin in private chat or superadmin group - they may be forwarding for /copy or /forward
        # We'll only respond after we verify we can process the report
        is_superadmin_msg = superadmin_filter(message)

        # LOGGER.debug("############################################################")
        # LOGGER.debug("                                                            ")
        # LOGGER.debug("------------------------------------------------------------")
        # LOGGER.debug("Received forwarded message for the investigation: %s", message)
        # Send a thank you note to the user (but not to superadmin - wait until we verify)
        if not is_superadmin_msg:
            await message.answer("Thank you for the report. We will investigate it.")
        # Forward the message to the admin group
        technnolog_spam_message_copy = await BOT.forward_message(
            TECHNOLOG_GROUP_ID, message.chat.id, message.message_id
        )
        message_as_json = json.dumps(message.model_dump(mode="json"), indent=4, ensure_ascii=False)
        # Truncate and add an indicator that the message has been truncated
        if len(message_as_json) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
            message_as_json = message_as_json[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
        await safe_send_message(BOT, TECHNOLOG_GROUP_ID, message_as_json, LOGGER)
        await safe_send_message(
            BOT, TECHNOLOG_GROUP_ID, "Please investigate this message.", LOGGER
        )

        # Get the username, first name, and last name of the user who forwarded the message and handle the cases where they're not available
        spammer_id, spammer_first_name, spammer_last_name = extract_spammer_info(
            message
        )
        forward_from_chat_title = (
            message.forward_from_chat.title if message.forward_from_chat else None
        )

        # forward_from_username = (
        #     getattr(message.forward_from, "username", None)
        #     if message.forward_from
        #     else None
        # )

        found_message_data = None
        forward_sender_name = (
            spammer_first_name + " " + spammer_last_name
            if spammer_last_name
            else spammer_first_name
        )

        # message forwarded from a user or forwarded forward from a user
        if spammer_id:
            found_message_data = get_spammer_details(
                spammer_id,
                spammer_first_name,
                spammer_last_name,
                message.forward_date,
                forward_sender_name,
                forward_from_chat_title,
                forwarded_from_id=spammer_id,
                forwarded_from_chat_id=(
                    message.forward_from_chat.id if message.forward_from_chat else None
                ),
                froward_sender_chat_id=(
                    message.sender_chat.id if message.sender_chat else None
                ),
            )

        # For users with open profiles, or if previous fetch didn't work.
        if not found_message_data:
            found_message_data = get_spammer_details(
                spammer_id,
                spammer_first_name,
                spammer_last_name,
                message.forward_date,
                forward_sender_name,
                forward_from_chat_title,
                forwarded_from_id=None,
                forwarded_from_chat_id=(
                    message.forward_from_chat.id if message.forward_from_chat else None
                ),
                froward_sender_chat_id=(
                    message.sender_chat.id if message.sender_chat else None
                ),
            )

        # Try getting details for forwarded messages from channels.
        if not found_message_data:
            found_message_data = get_spammer_details(
                spammer_id,
                spammer_first_name,
                spammer_last_name,
                message.forward_date,
                forward_sender_name,
                forward_from_chat_title,
                forwarded_from_chat_id=(
                    message.forward_from_chat.id if message.forward_from_chat else None
                ),
                froward_sender_chat_id=(
                    message.sender_chat.id if message.sender_chat else None
                ),
            )

        if not found_message_data:
            if forward_sender_name == "Deleted Account":
                found_message_data = get_spammer_details(
                    spammer_id,
                    spammer_first_name,
                    spammer_last_name,
                    message.forward_date,
                    forward_sender_name,
                    forward_from_chat_title,
                    forwarded_from_chat_id=(
                        message.forward_from_chat.id
                        if message.forward_from_chat
                        else None
                    ),
                    froward_sender_chat_id=(
                        message.sender_chat.id if message.sender_chat else None
                    ),
                )
                LOGGER.debug(
                    "The requested data associated with the Deleted Account has been retrieved. Please verify the accuracy of this information, as it cannot be guaranteed due to the account's deletion."
                )
                await message.answer(
                    "The requested data associated with the Deleted Account has been retrieved. Please verify the accuracy of this information, as it cannot be guaranteed due to the account's deletion."
                )
            else:
                # Message forwarded from chat without bot, or sender data hidden
                # Different behavior based on who forwarded the message:
                
                # 1. Superadmin in private chat or superadmin group - stay silent (they may use /copy or /forward)
                if is_superadmin_msg:
                    LOGGER.debug(
                        "Superadmin forwarded message from unknown source - staying silent for potential /copy or /forward use"
                    )
                    return
                
                # 2. Admins from admin group - inform them bot can't help
                if await is_admin(message.from_user.id, ADMIN_GROUP_ID):
                    await message.answer(
                        "⚠️ This message is forwarded from a chat where the bot is not present, "
                        "or sender data was hidden.\n\n"
                        "The bot cannot retrieve the original message details.\n"
                        "Please ensure the message is from a monitored chat and "
                        "sender information is preserved when forwarding."
                    )
                    LOGGER.debug(
                        "Admin %s forwarded message from unknown source - informed them",
                        message.from_user.id,
                    )
                    return
                
                # 3. Regular users - stay silent, but log and optionally notify admin group
                LOGGER.info(
                    "User %s:@%s forwarded message from unknown source - staying silent",
                    message.from_user.id,
                    message.from_user.username or "!UNDEFINED!",
                )
                # Optionally forward to admin group for review (without response to user)
                try:
                    await BOT.forward_message(
                        TECHNOLOG_GROUP_ID,
                        message.chat.id,
                        message.message_id,
                        message_thread_id=TECHNO_UNHANDLED,
                    )
                    await safe_send_message(
                        BOT,
                        TECHNOLOG_GROUP_ID,
                        f"⚠️ User {message.from_user.id}:@{message.from_user.username or '!UNDEFINED!'} "
                        f"forwarded message from unknown source (bot not present or sender hidden). "
                        f"No response sent to user.",
                        LOGGER,
                        message_thread_id=TECHNO_UNHANDLED,
                    )
                except TelegramBadRequest as log_err:
                    LOGGER.warning("Failed to log unknown forward to technolog: %s", log_err)
                return

        if not found_message_data:  # Last resort. Give up.
            LOGGER.info("           Could not retrieve the author's user ID.")
            return
            # pass

        LOGGER.debug("%s - message data: %s", found_message_data[3], found_message_data)

        # Save both the original message_id and the forwarded message's date
        received_date = message.date if message.date else None
        # Create a unique report ID based on the chat ID and message ID and remove -100 if public chat
        if message.chat.id < 0:
            report_id = int(str(message.chat.id)[4:] + str(message.message_id))
        else:
            report_id = int(str(message.chat.id) + str(message.message_id))

        if report_id:
            # send report ID to the reporter
            # For superadmin in private chat or group, also send "Thank you" since we successfully found the data
            if is_superadmin_msg:
                await message.answer(f"Thank you for the report. Report ID: {report_id}")
            else:
                await message.answer(f"Report ID: {report_id}")
        CURSOR.execute(
            """
            INSERT OR REPLACE INTO recent_messages 
            (chat_id, message_id, user_id, user_name, user_first_name, user_last_name, forward_date, received_date, forwarded_message_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.chat.id,
                report_id,
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
                message.from_user.last_name,
                message.forward_date.strftime("%Y-%m-%d %H:%M:%S") if message.forward_date else None,
                received_date,
                str(found_message_data),
            ),
        )

        CONN.commit()

        # Found message data:
        #        0           1           2            3            4        5           6            7
        #     chat ID       msg #   chat username  user ID     username  first name  last name     date
        # (-1001461337235, 126399, 'mavrikiy',     7283940136, None,     'павел',    'запорожец', '2024-10-06 15:14:57')
        # _______________________________________________________________________________________________________________
        # BUG if there is a date instead of channel username - it shows wrong message link!!!
        # found_message_data[2] is not always a channel username since we put date to the DATABASE
        # NOTE add checks if its inout event or previous report (better delete reports?)

        message_link = construct_message_link(found_message_data)

        # Get the username, first name, and last name of the user who forwarded the message and handle the cases where they're not available
        if message.forward_from:
            first_name = message.forward_from.first_name or ""
            last_name = message.forward_from.last_name or ""
        else:
            first_name = found_message_data[5]
            last_name = found_message_data[6]

        # Handle both formats: with and without timezone
        _ts_str = found_message_data[7]
        if _ts_str and "+" in str(_ts_str):
            _ts_str = str(_ts_str).split("+")[0].strip()
        massage_timestamp = datetime.strptime(
            _ts_str, "%Y-%m-%d %H:%M:%S"
        )  # convert to datetime object

        # Get the username
        username = found_message_data[4]
        if not username:
            username = "!UNDEFINED!"

        # Initialize user_id and user_link with default values
        user_id = found_message_data[3]
        # user_id=5338846489

        # print('##########----------DEBUG----------##########')
        technolog_chat_id = int(
            str(technnolog_spam_message_copy.chat.id)[4:]
        )  # Remove -100 from the chat ID
        technnolog_spam_message_copy_link = f"https://t.me/c/{technolog_chat_id}/{technnolog_spam_message_copy.message_id}"
        # LOGGER.info('Spam Message Technolog Copy: ', technnolog_spamMessage_copy)

        # print('##########----------DEBUG----------##########')

        message_report_date = datetime.now()
        # avoid html tags in the name
        escaped_name = html.escape(
            f"{message.forward_sender_name or f'{first_name} {last_name}'}"
        )

        # Log the information with the link
        technolog_info = (
            f"💡 Report timestamp: {message_report_date}\n"
            f"💡 Spam message timestamp: {message.date}\n"
            f"💡 Reaction time: {message_report_date - massage_timestamp}\n"
            f"💔 Reported by admin <a href='tg://user?id={message.from_user.id}'></a>"
            f"@{message.from_user.username or '!UNDEFINED!'}\n"
            f"💀 Forwarded from <a href='tg://resolve?domain={username}'>@{username}</a> : "
            f"{escaped_name}\n"
            f"💀 SPAMMER ID profile links:\n"
            f"   ├☠️ <a href='tg://user?id={user_id}'>Spammer ID based profile link</a>\n"
            f"   ├☠️ <a href='tg://openmessage?user_id={user_id}'>Android</a>\n"
            f"   └☠️ <a href='https://t.me/@id{user_id}'>IOS (Apple)</a>\n"
            f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
            f"ℹ️ <a href='{technnolog_spam_message_copy_link}'>Technolog copy</a>\n"
            f"❌ <b>Use <code>/ban {report_id}</code></b> to take action.\n"
        )
        # LOGGER.debug("Report banner content:")
        # LOGGER.debug(log_info)

        admin_ban_banner = (
            f"💡 Reaction time: {message_report_date - massage_timestamp}\n"
            f"💔 Reported by admin <a href='tg://user?id={message.from_user.id}'></a>"
            f"@{message.from_user.username or '!UNDEFINED!'}\n"
            f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
            f"ℹ️ <a href='{technnolog_spam_message_copy_link}'>Technolog copy</a>\n"
            f"❌ <b>Use <code>/ban {report_id}</code></b> to take action.\n"
            f"\n🔗 <b>Profile links:</b>\n"
            f"   ├ <a href='tg://user?id={user_id}'>ID based profile link</a>\n"
            f"   └ <a href='tg://openmessage?user_id={user_id}'>Android</a>, "
            f"<a href='https://t.me/@id{user_id}'>iOS</a>\n"
        )

        # construct lols check link button
        inline_kb = make_lols_kb(user_id)
        # Send the banner to the technolog group
        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP_ID,
            technolog_info,
            LOGGER,
            parse_mode="HTML",
            reply_markup=inline_kb.as_markup(),
        )

        # Keyboard ban/cancel/confirm buttons
        keyboard = KeyboardBuilder()
        # Consolidated actions button (expands to Ban / Global Ban / Delete on click)
        # Use original message_id from found_message_data for proper linking
        original_chat_id = found_message_data[0]
        original_message_id = found_message_data[1]
        actions_btn = InlineKeyboardButton(
            text="⚙️ Actions (Ban / Delete) ⚙️",
            callback_data=f"suspiciousactions_{original_chat_id}_{original_message_id}_{user_id}",
        )
        keyboard.add(actions_btn)

        # Show ban banner with buttons in the admin group to confirm or cancel the ban
        # And store published banner message data to provide link to the reportee
        # admin_group_banner_message: Message = None # Type hinting
        try:  # If Topic_closed error
            if await is_admin(message.from_user.id, ADMIN_GROUP_ID):

                # Forward reported message to the ADMIN group REPORT thread
                await BOT.forward_message(
                    ADMIN_GROUP_ID,
                    message.chat.id,
                    message.message_id,
                    disable_notification=True,
                )
                # Send report banner to the admin group
                admin_group_banner_message = await safe_send_message(
                    BOT,
                    ADMIN_GROUP_ID,
                    admin_ban_banner,
                    LOGGER,
                    reply_markup=keyboard.as_markup(),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                # Send report action banner to the reporter
                admin_action_banner_message = await message.answer(
                    admin_ban_banner,
                    parse_mode="HTML",
                    disable_notification=True,
                    protect_content=True,
                    allow_sending_without_reply=True,
                    disable_web_page_preview=False,
                    reply_markup=keyboard.as_markup(),
                )

                # Store the admin action banner message data
                set_forwarded_state(
                    DP,
                    report_id,
                    {
                        "original_forwarded_message": message,
                        "admin_group_banner_message": admin_group_banner_message,
                        "action_banner_message": admin_action_banner_message,
                        "report_chat_id": message.chat.id,
                    },
                )

                # Construct link to the published banner and send it to the reporter
                private_chat_id = int(
                    str(admin_group_banner_message.chat.id)[4:]
                )  # Remove -100 from the chat ID
                banner_link = f"https://t.me/c/{private_chat_id}/{admin_group_banner_message.message_id}"
                # Send the banner link to the reporter-admin
                await message.answer(f"Admin group banner link: {banner_link}")

                # Return admin personal report banner message object
                return admin_action_banner_message

            else:  # send report to AUTOREPORT thread of the admin group if reported by non-admin user
                await BOT.forward_message(
                    ADMIN_GROUP_ID,
                    message.chat.id,
                    message.message_id,
                    message_thread_id=ADMIN_AUTOREPORTS,
                )
                admin_group_banner_message = await safe_send_message(
                    BOT,
                    ADMIN_GROUP_ID,
                    admin_ban_banner,
                    LOGGER,
                    reply_markup=keyboard.as_markup(),
                    parse_mode="HTML",
                    message_thread_id=ADMIN_AUTOREPORTS,
                    disable_web_page_preview=True,
                )
                # Store the admin action banner message data
                # Note: Lock is implemented via set_forwarded_state synchronous call
                # # import asyncio

                # # Initialize the lock
                # dp_lock = asyncio.Lock()

                # async def store_state(report_id, message, admin_group_banner_message, admin_action_banner_message):
                #     async with dp_lock:
                #         # Retrieve the existing forwarded_reports_states dictionary from DP
                #         forwarded_report_state = DP.get("forwarded_reports_states", {})

                #         # Add the new state to the forwarded_reports_states dictionary
                #         forwarded_report_state[report_id] = {
                #             "original_forwarded_message": message,
                #             "admin_group_banner_message": admin_group_banner_message,
                #             "action_banner_message": admin_action_banner_message,
                #             "report_chat_id": message.chat.id,
                #         }

                #         # Update the DP dictionary with the modified forwarded_reports_states dictionary
                #         DP["forwarded_reports_states"] = forwarded_report_state

                # async def handle_admin_action(report_id, message, admin_group_banner_message, admin_action_banner_message):
                #     # Your existing code to handle the admin action
                #     await BOT.send_message(
                #         ADMIN_GROUP_ID,
                #         admin_ban_banner,
                #         reply_markup=keyboard.as_markup(),
                #         parse_mode="HTML",
                #         message_thread_id=ADMIN_AUTOREPORTS,
                #         disable_web_page_preview=True,
                #     )

                #     # Store the state
                #     await store_state(report_id, message, admin_group_banner_message, admin_action_banner_message)

                #     return admin_group_banner_message
                # State is stored synchronously via set_forwarded_state
                set_forwarded_state(
                    DP,
                    report_id,
                    {
                        "original_forwarded_message": message,
                        "admin_group_banner_message": admin_group_banner_message,
                        "action_banner_message": admin_action_banner_message,  # BUG if report sent by non-admin user - there is no admin action banner message
                        "report_chat_id": message.chat.id,
                    },
                )

                return admin_group_banner_message

        except TelegramBadRequest as e:
            LOGGER.error("Error while sending the banner to the admin group: %s", e)
            await message.answer(
                "Error while sending the banner to the admin group. Please check the logs."
            )

    @DP.callback_query(
        lambda c: c.data.startswith("confirmban_")
    )  # MODIFIED: Renamed callback prefix
    async def ask_confirmation(callback_query: CallbackQuery):
        """Function to ask for confirmation before banning the user."""
        # MODIFIED: Parse user_id and report_id
        parts = callback_query.data.split("_")
        spammer_user_id_str = parts[1]
        report_id_to_ban_str = parts[2]

        # DEBUG:
        # logger.debug(f"Report {callback_query} confirmed for banning.")

        keyboard = KeyboardBuilder()
        # MODIFIED: Pass spammer_user_id_str and report_id_to_ban_str, and rename callback prefixes
        confirm_btn = InlineKeyboardButton(
            text="🟢 Confirm",
            callback_data=f"doban_{spammer_user_id_str}_{report_id_to_ban_str}",
        )
        cancel_btn = InlineKeyboardButton(
            text="🔴 Cancel",
            callback_data=f"resetban_{spammer_user_id_str}_{report_id_to_ban_str}",
        )

        keyboard.add(confirm_btn, cancel_btn)

        report_id_to_ban = int(report_id_to_ban_str)
        # Try to get report states (might not exist for ad-hoc ban buttons e.g. profile change alerts)
        forwarded_reports_states: dict | None = DP.get("forwarded_reports_states")
        admin_group_banner_message = None
        action_banner_message = None
        if forwarded_reports_states:
            forwarded_report_state = forwarded_reports_states.get(report_id_to_ban)
            if forwarded_report_state:
                admin_group_banner_message = forwarded_report_state.get(
                    "admin_group_banner_message"
                )
                action_banner_message = forwarded_report_state.get(
                    "action_banner_message"
                )
                # prune stored buttons so we don't try to edit twice later
                if "action_banner_message" in forwarded_report_state:
                    del forwarded_report_state["action_banner_message"]
                if "admin_group_banner_message" in forwarded_report_state:
                    del forwarded_report_state["admin_group_banner_message"]
                forwarded_reports_states[report_id_to_ban] = forwarded_report_state
                DP["forwarded_reports_states"] = forwarded_reports_states
            else:
                LOGGER.debug(
                    "Ad-hoc ban confirmation (no stored report state) for user %s report_id %s",
                    spammer_user_id_str,
                    report_id_to_ban_str,
                )
        else:
            LOGGER.debug(
                "Ad-hoc ban confirmation (no forwarded_reports_states dict) for user %s report_id %s",
                spammer_user_id_str,
                report_id_to_ban_str,
            )

        # Edit messages to remove buttons or messages
        # check where the callback_query was pressed
        # remove buttons and add Confirm/Cancel buttons in the same chat
        try:
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=keyboard.as_markup(),
            )

            if admin_group_banner_message:
                try:
                    if (
                        callback_query.message.chat.id == ADMIN_GROUP_ID
                        and action_banner_message  # Action done in Admin group and reported by admin
                    ):
                        await BOT.edit_message_reply_markup(
                            chat_id=action_banner_message.chat.id,
                            message_id=action_banner_message.message_id,
                        )
                    elif (
                        callback_query.message.chat.id == ADMIN_GROUP_ID
                        and action_banner_message is None
                    ):
                        # AUTOREPORT or no personal banner: nothing else to edit
                        pass
                    else:  # report was actioned in the personal chat
                        await BOT.edit_message_reply_markup(
                            chat_id=ADMIN_GROUP_ID,
                            message_id=admin_group_banner_message.message_id,
                        )
                except TelegramBadRequest as _e:
                    LOGGER.debug(
                        "Editing related banners during confirmation failed: %s", _e
                    )

        except KeyError as e:
            LOGGER.error(
                "\033[93m%s Error while removing the buttons: %s. Message reported by non-admin user?\033[0m",
                callback_query.from_user.id,
                e,
            )

        except AttributeError as e:
            LOGGER.error(
                "\033[93m%s Error accessing message_id: %s. Possible NoneType object.\033[0m",
                callback_query.from_user.id,
                e,
            )

    @DP.callback_query(
        lambda c: c.data.startswith("doban_")
    )  # MODIFIED: Renamed callback prefix
    async def handle_ban(callback_query: CallbackQuery):
        """Function to ban the user and delete all known to bot messages."""

        # remove buttons from the admin group first
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
        )
        # get the message ID to ban and who pressed the button
        button_pressed_by = callback_query.from_user.username
        try:
            # MODIFIED: Parse user_id (author_id_from_callback_str) and report_id_to_ban_str
            parts = callback_query.data.split("_")
            author_id_from_callback_str = parts[1]  # This is the spammer's user_id
            report_id_to_ban_str = parts[
                2
            ]  # This is the original report_id (chat_id+message_id combo)

            report_id_to_ban = int(report_id_to_ban_str)
            # author_id_from_callback = int(author_id_from_callback_str) # Can be used for checks

            LOGGER.info(
                "\033[95m%s:@%s requested to ban REPORT %s (Spammer ID from callback: %s)\033[0m",
                callback_query.from_user.id,
                button_pressed_by,
                report_id_to_ban,
                author_id_from_callback_str,
            )
            # get report states
            forwarded_reports_states: dict | None = DP.get("forwarded_reports_states")
            forwarded_report_state = (
                forwarded_reports_states.get(report_id_to_ban)
                if forwarded_reports_states
                else None
            )

            if not forwarded_report_state:
                # Ad-hoc ban (e.g., profile change alert) – perform minimal ban logic
                author_id = int(author_id_from_callback_str)
                _success_count, _fail_count, _total_count = await ban_user_from_all_chats(
                    author_id, None, CHANNEL_IDS, CHANNEL_DICT
                )
                banned_users_dict[author_id] = "!UNDEFINED!"
                # cancel watchdog if running
                for task in asyncio.all_tasks():
                    if task.get_name() == str(author_id):
                        task.cancel()
                lols_check_kb = make_lols_kb(author_id)
                await safe_send_message(
                    BOT,
                    ADMIN_GROUP_ID,
                    f"Ad-hoc ban executed by {f'@{button_pressed_by}' if button_pressed_by else '!UNDEFINED!'}: User (<code>{author_id}</code>) banned across monitored chats.",
                    LOGGER,
                    parse_mode="HTML",
                    reply_markup=lols_check_kb.as_markup(),
                    message_thread_id=callback_query.message.message_thread_id,
                    reply_to_message_id=callback_query.message.message_id,
                )
                return

            original_spam_message: Message = forwarded_report_state.get(
                "original_forwarded_message"
            )
            CURSOR.execute(
                "SELECT chat_id, message_id, forwarded_message_data, received_date FROM recent_messages WHERE message_id = ?",
                (report_id_to_ban,),
            )
            result = CURSOR.fetchone()

            if not result:
                await callback_query.message.reply(
                    "Error: Report not found in database."
                )
                return

            (
                original_chat_id,
                report_id,
                forwarded_message_data,
                original_message_timestamp,
            ) = result
            #  result for sender:
            #
            # ФАЛЬШ СУПЕР , date: 2025-01-04 22:13:02, from chat title: ФАЛЬШ СУПЕР
            #            [0]            [1]      [2]                 [3]         [4]        [5]    [6]    [7]
            #            ChatID        MsgID    ChatUsername        UserID     UserName    User1  User2   MessageForwardDate
            # Result: (-1001753683146, 3255, 'exampleChatUsername', 66666666, 'userUser', 'нелл', None, '2025-01-05 02:35:53')

            # Note: author_id is safely extracted from forwarded_message_data[3]
            # author_id = eval(forwarded_message_data)[3]
            # LOGGER.debug("Author ID retrieved for original message: %s", author_id)

            # Check if forwarded_message_data is not empty and is a list
            # if not forwarded_message_data:
            #     await callback_query.message.reply("Error: Forwarded message data is empty.")
            #     return

            # # Extract author_id from the list
            # try:
            #     author_id = forwarded_message_data[3]
            # except IndexError as e:
            #     LOGGER.error("Index error: %s", e)
            #     await callback_query.message.reply("Error: Invalid data format in forwarded message.")
            #     return
            # MODIFIED: Use ast.literal_eval for safety
            try:
                author_id = ast.literal_eval(forwarded_message_data)[3]
                LOGGER.debug("%s author ID retrieved for original message", author_id)
            except (ValueError, SyntaxError, IndexError) as e:
                LOGGER.error("Failed to parse forwarded_message_data: %s", e)
                await callback_query.message.reply(
                    "Error: Invalid message data format."
                )
                return

            LOGGER.debug(
                "\033[93m%s Message timestamp: %-10s, Original chat ID: %s, Original report ID: %s,\n\t\t\tForwarded message data: %s,\n\t\t\tOriginal message timestamp: %s\033[0m",
                author_id,
                (
                    f"{result[3]:10}" if result[3] is not None else f"{' ' * 10}"
                ),  # padding left align 10 chars
                original_chat_id,
                report_id,
                forwarded_message_data,
                original_message_timestamp,
            )
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                f"Author ID (<code>{author_id}</code>) retrieved for original message.",
                LOGGER,
                parse_mode="HTML",
            )
            if not author_id:
                # show error message
                await callback_query.message.reply(
                    "Could not retrieve the author's user ID from the report."
                )
                return
            # remove userid from the active_user_checks_dict
            if author_id in active_user_checks_dict:
                banned_users_dict[author_id] = active_user_checks_dict.pop(
                    author_id, None
                )
                if len(active_user_checks_dict) > 3:
                    active_user_checks_dict_last3_list = list(
                        active_user_checks_dict.items()
                    )[-3:]
                    active_user_checks_dict_last3_str = ", ".join(
                        [
                            f"{uid}: {uname}"
                            for uid, uname in active_user_checks_dict_last3_list
                        ]
                    )
                    LOGGER.info(
                        "\033[91m%s:@%s removed from active_user_checks_dict during handle_ban by admin (%s):\n\t\t\t\033[0m %s... %d totally",
                        author_id,
                        (
                            forwarded_message_data[4]
                            if forwarded_message_data[4] not in [0, "0", None]
                            else "!UNDEFINED!"
                        ),
                        button_pressed_by,
                        active_user_checks_dict_last3_str,  # Last 3 elements
                        len(active_user_checks_dict),  # Number of elements left
                    )
                else:
                    LOGGER.info(
                        "\033[91m%s:@%s removed from active_user_checks_dict during handle_ban by admin (%s):\n\t\t\t\033[0m %s",
                        author_id,
                        (
                            forwarded_message_data[4]
                            if forwarded_message_data[4] not in [0, "0", None]
                            else "!UNDEFINED!"
                        ),
                        button_pressed_by,
                        active_user_checks_dict,
                    )
                # stop the perform_checks coroutine if it is running for author_id
                for task in asyncio.all_tasks():
                    if task.get_name() == str(author_id):
                        task.cancel()

            # save event to the ban file
            _admin_for_record = f"@{button_pressed_by}" if button_pressed_by else "!UNDEFINED!"
            event_record = (
                f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "  # Date and time with milliseconds
                f"{author_id:<10} "
                f"❌  {' '.join('@' + forwarded_message_data[4] if forwarded_message_data[4] is not None else forwarded_message_data[5]+' '+forwarded_message_data[6]):<32}"
                f" member          --> kicked          in "
                f"{'@' + forwarded_message_data[2] + ': ' if forwarded_message_data[2] else '':<24}{forwarded_message_data[0]:<30} by {_admin_for_record}\n"
            )
            LOGGER.debug(
                "%s:@%s (#HBN) forwared_message_data: %s",
                author_id,
                (
                    forwarded_message_data[4]
                    if forwarded_message_data[4] not in [0, "0", None]
                    else "!UNDEFINED!"
                ),
                forwarded_message_data,
            )
            await save_report_file("inout_", "hbn" + event_record)

            # add to the banned users set
            banned_users_dict[int(author_id)] = (
                forwarded_message_data[4]
                if forwarded_message_data[4] not in [0, "0", None]
                else "!UNDEFINED!"
            )

            # Select all messages from the user in chats with usernames
            # Note: Private chats are excluded (chat_username IS NOT NULL) since they don't have public usernames
            query = """
                SELECT chat_id, message_id, user_name
                FROM recent_messages 
                WHERE user_id = :author_id
                AND new_chat_member IS NULL
                AND left_chat_member IS NULL
                AND chat_username IS NOT NULL
                """
            params = {"author_id": author_id}
            result = CURSOR.execute(query, params).fetchall()
            # delete them one by one
            spam_messages_count = len(result)
            _raw_name = forwarded_message_data[4]
            user_name = _raw_name if _raw_name and str(_raw_name) not in ["None", "0"] else None
            bot_info_message = (
                f"Attempting to delete all messages <b>({spam_messages_count})</b> from {f'@{user_name}' if user_name else '!UNDEFINED!'} (<code>{author_id}</code>)\n"
                f"action taken by @{button_pressed_by if button_pressed_by else '!UNDEFINED!'}):"
            )
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                bot_info_message,
                LOGGER,
                parse_mode="HTML",
                disable_web_page_preview=True,
                disable_notification=True,
                message_thread_id=TECHNO_ORIGINALS,
            )
            # Attempting to delete all messages one by one
            for channel_id, message_id, user_name in result:
                try:
                    # Use cached username if available for public links
                    cached_username = get_cached_chat_username(channel_id)
                    message_link = build_message_link(channel_id, message_id, cached_username)
                    chat_link_html = build_chat_link(channel_id, cached_username, CHANNEL_DICT.get(channel_id, "Chat"))
                    bot_chatlink_message = (
                        f"Attempting to delete message <code>{message_id}</code>\n"
                        f"in chat {chat_link_html} (<code>{channel_id}</code>)\n"
                        f"<a href='{message_link}'>{message_link}</a>"
                    )
                    await safe_send_message(
                        BOT,
                        TECHNOLOG_GROUP_ID,
                        bot_chatlink_message,
                        LOGGER,
                        disable_web_page_preview=True,
                        disable_notification=True,
                        message_thread_id=TECHNO_ORIGINALS,
                        parse_mode="HTML",
                    )
                except asyncio.TimeoutError:
                    LOGGER.error(
                        "%s:@%s Timeout error while sending message to ORIGINALS",
                        author_id,
                        user_name,
                    )
                try:
                    await BOT.forward_message(
                        TECHNOLOG_GROUP_ID,
                        channel_id,
                        message_id,
                        disable_notification=True,
                        message_thread_id=TECHNO_ORIGINALS,
                    )
                except (
                    MessageToForwardNotFound,
                    MessageCantBeForwarded,
                    MessageIdInvalid,
                ) as e:
                    LOGGER.error(
                        "%s:%s Failed to forward message %s in chat %s: %s",
                        author_id,
                        user_name,
                        message_id,
                        channel_id,
                        e,
                    )
                # Set default username if not available
                user_name = user_name if user_name else "!UNDEFINED!"
                retry_attempts = 3  # number of attempts to delete the message

                # Attempt to delete the message with retry logic
                for attempt in range(retry_attempts):
                    try:
                        await BOT.delete_message(
                            chat_id=channel_id, message_id=message_id
                        )
                        LOGGER.debug(
                            "\033[91m%s:@%s message %s deleted from chat %s (%s).\033[0m",
                            author_id,
                            user_name,
                            message_id,
                            CHANNEL_DICT[channel_id],
                            channel_id,
                        )
                        break  # break the loop if the message was deleted successfully
                    except RetryAfter as e:
                        wait_time = (
                            e.retry_after
                        )  # This gives you the time to wait in seconds
                        if (
                            attempt < retry_attempts - 1
                        ):  # Don't wait after the last attempt
                            LOGGER.warning(
                                "%s:@%s Rate limited. Waiting for %s seconds.",
                                author_id,
                                user_name,
                                wait_time,
                            )
                            time.sleep(wait_time)
                        else:
                            continue  # Move to the next message after the last attempt
                    except TelegramBadRequest as inner_e:
                        # Covers MessageToDeleteNotFound, MessageCantBeDeleted
                        LOGGER.warning(
                            "%s:@%s Message %s in chat %s (%s) could not be deleted: %s",
                            author_id,
                            user_name,
                            message_id,
                            CHANNEL_DICT[channel_id],
                            channel_id,
                            inner_e,
                        )
                        break  # Cancel current attempt
                    except TelegramForbiddenError as inner_e:
                        # Covers ChatAdminRequired
                        LOGGER.error(
                            "\033[91mBot is not an admin in chat %s (%s). Error: %s\033[0m",
                            CHANNEL_DICT[channel_id],
                            channel_id,
                            inner_e,
                        )
                        await safe_send_message(
                            BOT,
                            TECHNOLOG_GROUP_ID,
                            f"Bot is not an admin in chat {CHANNEL_DICT[channel_id]} ({channel_id}). Error: {inner_e}",
                            LOGGER,
                        )
                        break  # Cancel current attempt
                    # except Exception as inner_e:
                    #     LOGGER.error(
                    #         "Failed to delete message %s in chat %s (%s). Error: %s",
                    #         message_id,
                    #         channels_dict[chat_id],
                    #         chat_id,
                    #         inner_e,
                    #     )
                    #     await BOT.send_message(
                    #         TECHNOLOG_GROUP_ID,
                    #         f"Failed to delete message {message_id} in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}",
                    #     )

            # Attempting to ban user from channels
            for channel_id in CHANNEL_IDS:
                # LOGGER.debug(
                #     f"Attempting to ban user {author_id} from chat {channels_dict[chat_id]} ({chat_id})"
                # )

                try:
                    # pause 0.02 second to prevent flood control errors
                    await asyncio.sleep(0.02)

                    # ban the user and delete their messages if revoke is wotking
                    await BOT.ban_chat_member(
                        chat_id=channel_id,
                        user_id=author_id,
                        revoke_messages=True,
                    )

                    # LOGGER.debug(
                    #     "User %s banned and their messages deleted from chat %s (%s).",
                    #     author_id,
                    #     channels_dict[chat_id],
                    #     chat_id,
                    # )
                except (TelegramBadRequest, TelegramForbiddenError) as inner_e:
                    LOGGER.error(
                        "%s:%s Failed to ban and delete messages in chat %s (%s). Error: %s",
                        author_id,
                        f"@{user_name}" if user_name else "!UNDEFINED!",
                        CHANNEL_DICT[channel_id],
                        channel_id,
                        inner_e,
                    )
                    await safe_send_message(
                        BOT,
                        TECHNOLOG_GROUP_ID,
                        f"Failed to ban and delete messages in chat {CHANNEL_DICT[channel_id]} ({channel_id}). Error: {inner_e}",
                        LOGGER,
                    )
            # Set default username from result if available
            _raw_result_name = result[0][2] if result else None
            user_name = _raw_result_name if _raw_result_name and str(_raw_result_name) not in ["None", "0"] else None
            LOGGER.debug(
                "\033[91m%s:%s manually banned and their messages deleted where applicable.\033[0m",
                author_id,
                f"@{user_name}" if user_name else "!UNDEFINED!",
            )
            # Take actions to ban channels
            channel_id_to_ban = (
                original_spam_message.forward_from_chat.id
                if original_spam_message.forward_from_chat
                else (
                    original_spam_message.sender_chat.id
                    if original_spam_message.sender_chat
                    else None
                )
            )
            if channel_id_to_ban:
                del forwarded_report_state
                del forwarded_reports_states[report_id_to_ban]
                await ban_rogue_chat_everywhere(
                    channel_id_to_ban,
                    CHANNEL_IDS,
                )
                # Use cached username if available for public channel link
                chan_link_html = build_chat_link(channel_id_to_ban, get_cached_chat_username(channel_id_to_ban), "Channel")
                chan_ban_msg = f"{chan_link_html}:(<code>{channel_id_to_ban}</code>) also banned by AUTOREPORT#{report_id_to_ban}. "
            else:
                chan_ban_msg = ""

            # Note: add the timestamp of the button press and how much time passed since
            # button_timestamp = datetime.now()

            lols_check_kb = make_lols_kb(author_id)
            _display_user = f"@{user_name}" if user_name else "!UNDEFINED!"
            _admin_display = f"@{button_pressed_by}" if button_pressed_by else "!UNDEFINED!"
            await safe_send_message(
                BOT,
                ADMIN_GROUP_ID,
                f"Report <code>{report_id_to_ban}</code> action taken by {_admin_display}: User {_display_user} (<code>{author_id}</code>) banned and their messages deleted where applicable.\n{chan_ban_msg}",
                LOGGER,
                message_thread_id=callback_query.message.message_thread_id,
                parse_mode="HTML",
                reply_markup=lols_check_kb.as_markup(),
                reply_to_message_id=callback_query.message.message_id,
            )
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                f"Report <code>{report_id_to_ban}</code> action taken by {_admin_display}: User {_display_user} (<code>{author_id}</code>) banned and their messages deleted where applicable.\n{chan_ban_msg}",
                LOGGER,
                parse_mode="HTML",
                reply_markup=lols_check_kb.as_markup(),
            )
            _uname_3088 = normalize_username(forwarded_message_data[4])
            if _uname_3088 and _uname_3088 not in POSTED_USERNAMES:
                POSTED_USERNAMES.add(_uname_3088)
                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"<code>{author_id}</code> @{_uname_3088} (3088)",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )
            banned_users_dict[author_id] = (
                forwarded_message_data[4]
                if forwarded_message_data[4] not in [0, "0", None]
                else "!UNDEFINED!"
            )
            if forwarded_message_data[3] in active_user_checks_dict:
                banned_users_dict[forwarded_message_data[3]] = (
                    active_user_checks_dict.pop(forwarded_message_data[3], None)
                )
                LOGGER.info(
                    "\033[91m%s:@%s removed from active_user_checks_dict and stored to banned_users_dict during handle_ban by admin:\n\t\t\t%s\033[0m",
                    forwarded_message_data[3],
                    user_name,
                    active_user_checks_dict,
                )
            LOGGER.info(
                "\033[95m%s:@%s Report <code>%s</code> action taken by @%s: User @%s banned and their messages deleted where applicable.\033[0m",
                author_id,
                user_name,
                report_id_to_ban,
                button_pressed_by,
                (
                    forwarded_message_data[4]
                    if forwarded_message_data[4] not in [0, "0", None]
                    else "!UNDEFINED!"
                ),
            )

        except TelegramBadRequest as e:
            LOGGER.error("Error in handle_ban function: %s", e)
            await callback_query.message.reply(f"Error in handle_ban function: {e}")

        # report spam to the P2P spamcheck server
        await report_spam_2p2p(author_id, LOGGER)
        _display_name = user_name if user_name and str(user_name) not in ["None", "0", "!UNDEFINED!"] else None
        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP_ID,
            f"{author_id}:{f'@{_display_name}' if _display_name else '!UNDEFINED!'} reported to P2P spamcheck server.",
            LOGGER,
            parse_mode="HTML",
            disable_web_page_preview=True,
            message_thread_id=TECHNO_ADMIN,
        )

    @DP.callback_query(
        lambda c: c.data.startswith("resetban_")
    )  # MODIFIED: Renamed callback prefix
    async def reset_ban(callback_query: CallbackQuery):
        """Function to reset the ban button."""
        # MODIFIED: Parse actual_user_id and original_report_id from callback data
        parts = callback_query.data.split("_")
        actual_user_id_str = parts[1]  # The spammer's actual user ID
        original_report_id_str = parts[
            2
        ]  # The original report_id (chat_id+message_id combo)

        actual_user_id = int(actual_user_id_str)
        # original_report_id = int(original_report_id_str) # For DB operations if needed, or logging

        # remove buttons from the admin group
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
        )

        button_pressed_by = callback_query.from_user.username
        admin_id = callback_query.from_user.id
        # DEBUG:
        # logger.debug("Button pressed by the admin: @%s", button_pressed_by)

        LOGGER.info(
            "\033[95m%s Report %s button ACTION CANCELLED by %s !!! (User ID for LOLS: %s)\033[0m",
            admin_id,
            original_report_id_str,  # Log the original report identifier
            f"@{button_pressed_by}" if button_pressed_by else "!UNDEFINED!",
            actual_user_id,
        )

        # FIXED BUG: Use actual_user_id for the LOLS bot link
        inline_kb = make_lols_kb(actual_user_id)
        _admin_display = f"@{button_pressed_by}" if button_pressed_by else "!UNDEFINED!"
        await safe_send_message(
            BOT,
            ADMIN_GROUP_ID,
            f"Button ACTION CANCELLED by {_admin_display}: Report WAS NOT PROCESSED!!! "
            f"Report them again if needed or use <code>/ban {original_report_id_str}</code> command.",
            LOGGER,
            message_thread_id=callback_query.message.message_thread_id,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb.as_markup(),
            reply_to_message_id=callback_query.message.message_id,
        )
        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP_ID,
            f"CANCEL button pressed by {_admin_display}. "
            f"Button ACTION CANCELLED: Report WAS NOT PROCESSED. "
            f"Report them again if needed or use <code>/ban {original_report_id_str}</code> command.",
            LOGGER,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb.as_markup(),
        )

    @DP.callback_query(lambda c: c.data.startswith("banuser_"))
    async def ask_ban_confirmation(callback_query: CallbackQuery):
        """Function to ask for confirmation before banning the user from all chats."""
        # Parse user_id from callback data
        parts = callback_query.data.split("_")
        user_id_str = parts[1]
        user_id = int(user_id_str)

        # Get user info for display
        try:
            user_info = await BOT.get_chat(user_id)
            username = user_info.username or "!UNDEFINED!"
            first_name = user_info.first_name or ""
            last_name = user_info.last_name or ""
            _display_name = f"{first_name} {last_name}".strip() or username
        except (TelegramBadRequest, TelegramNotFound):
            username = "!UNDEFINED!"
            _display_name = "Unknown User"

        keyboard = KeyboardBuilder()
        confirm_btn = InlineKeyboardButton(
            text="✅ Yes, Ban", callback_data=f"confirmbanuser_{user_id_str}"
        )
        cancel_btn = InlineKeyboardButton(
            text="❌ No, Cancel", callback_data=f"cancelbanuser_{user_id_str}"
        )
        keyboard.add(confirm_btn, cancel_btn)

        # Edit the message to show confirmation
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=keyboard.as_markup(),
        )

        # Send confirmation message
        # await callback_query.answer(
        #     f"Confirm ban for {display_name} (@{username})?", show_alert=True
        # )

    @DP.callback_query(lambda c: c.data.startswith("confirmbanuser_"))
    async def handle_user_inout_ban(callback_query: CallbackQuery):
        """Function to ban the user from all chats."""
        # Parse user_id from callback data
        parts = callback_query.data.split("_")
        user_id_str = parts[1]
        user_id = int(user_id_str)

        button_pressed_by = callback_query.from_user.username or "!UNDEFINED!"
        _admin_id = callback_query.from_user.id

        # Create response message
        lols_check_and_banned_kb = make_lols_kb(user_id)
        api_url = f"https://api.lols.bot/account?id={user_id}"
        lols_check_and_banned_kb.add(
            InlineKeyboardButton(text="💀💀💀 B.A.N.N.E.D. 💀💀💀", url=api_url)
        )

        # Remove buttons
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=lols_check_and_banned_kb.as_markup(),
        )

        try:
            # Get user info
            try:
                user_info = await BOT.get_chat(user_id)
                username = user_info.username or "!UNDEFINED!"
                first_name = user_info.first_name or ""
                last_name = user_info.last_name or ""
            except (TelegramBadRequest, TelegramNotFound):
                username = "!UNDEFINED!"
                first_name = "Unknown"
                last_name = "User"

            # Remove from active checks if present
            if user_id in active_user_checks_dict:
                banned_users_dict[user_id] = active_user_checks_dict.pop(user_id, None)
                LOGGER.info(
                    "%s:@%s removed from active_user_checks_dict during manual ban",
                    user_id,
                    username,
                )

            # Ban user from all chats
            _success_count, _fail_count, _total_count = await ban_user_from_all_chats(
                user_id, username, CHANNEL_IDS, CHANNEL_DICT
            )

            # Add to banned users dict
            banned_users_dict[user_id] = username

            # Create event record
            _admin_for_record = f"@{button_pressed_by}" if button_pressed_by else "!UNDEFINED!"
            _user_for_record = f"@{username}" if username else "!UNDEFINED!"
            event_record = (
                f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "
                f"{user_id:<10} "
                f"❌  {_user_for_record} {first_name} {last_name}            "
                f" member          --> kicked          in "
                f"ALL_CHATS                          by {_admin_for_record}\n"
            )
            await save_report_file("inout_", "mbn" + event_record)

            # Report to spam servers
            await report_spam_2p2p(user_id, LOGGER)

            ban_message = (
                f"Manual ban completed by {_admin_for_record}:\n"
                f"User {_user_for_record} ({first_name} {last_name}) <code>{user_id}</code> "
                f"banned from all monitored chats and reported to spam servers."
            )

            # Send to technolog group
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                ban_message,
                LOGGER,
                parse_mode="HTML",
                reply_markup=lols_check_and_banned_kb.as_markup(),
                message_thread_id=TECHNO_ADMIN,
            )

            # Send to admin group
            await safe_send_message(
                BOT,
                ADMIN_GROUP_ID,
                ban_message,
                LOGGER,
                parse_mode="HTML",
                reply_markup=lols_check_and_banned_kb.as_markup(),
                message_thread_id=ADMIN_MANBAN,
            )

            # Log username if available
            _uname_manual = normalize_username(username)
            if _uname_manual and _uname_manual not in POSTED_USERNAMES:
                POSTED_USERNAMES.add(_uname_manual)
                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code> @{_uname_manual} (manual)",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )

            LOGGER.info(
                "\033[91m%s:@%s manually banned from all chats by @%s\033[0m",
                user_id,
                username,
                button_pressed_by,
            )

            # await callback_query.answer("User banned successfully!", show_alert=True)

        except (TelegramBadRequest, TelegramForbiddenError) as e:
            error_msg = f"Error banning user {user_id}: {str(e)}"
            LOGGER.error(error_msg)
            await callback_query.answer(f"Error: {str(e)}", show_alert=True)

            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                f"❌ {error_msg}",
                LOGGER,
                parse_mode="HTML",
                message_thread_id=TECHNO_ADMIN,
            )

    @DP.callback_query(lambda c: c.data.startswith("cancelbanuser_"))
    async def cancel_user_ban(callback_query: CallbackQuery):
        """Function to cancel the ban and restore original buttons."""
        # Parse user_id from callback data
        parts = callback_query.data.split("_")
        user_id_str = parts[1]
        user_id = int(user_id_str)

        # Restore original buttons
        lols_url = f"https://t.me/oLolsBot?start={user_id}"
        inline_kb = KeyboardBuilder()
        inline_kb.add(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_url))
        inline_kb.add(
            InlineKeyboardButton(text="🚫 Ban User", callback_data=f"banuser_{user_id_str}")
        )

        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=inline_kb.as_markup(),
        )

        await callback_query.answer("Ban cancelled.", show_alert=False)

    @DP.callback_query(lambda c: c.data.startswith("banchannelconfirm_"))
    async def ban_channel_confirm(callback_query: CallbackQuery):
        """Function to show confirmation buttons for channel ban."""
        # Parse channel_id and source_chat_id from callback data
        parts = callback_query.data.split("_")
        channel_id = int(parts[1])
        source_chat_id = int(parts[2])

        # Answer callback immediately
        try:
            await callback_query.answer()
        except (InvalidQueryID, BadRequest) as answer_error:
            LOGGER.debug("Could not answer callback: %s", answer_error)

        # Create confirmation keyboard
        confirm_kb = KeyboardBuilder()
        confirm_kb.row(
            InlineKeyboardButton(
                text="✅ Confirm Ban",
                callback_data=f"banchannelexecute_{channel_id}_{source_chat_id}",
            ),
            InlineKeyboardButton(
                text="❌ Cancel",
                callback_data=f"banchannelcancel_{channel_id}_{source_chat_id}",
            ),
        )

        # Update message with confirmation buttons (no popup alert)
        try:
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=confirm_kb.as_markup(),
            )
        except (MessageNotModified, InvalidQueryID, BadRequest) as e:
            LOGGER.debug("Could not update buttons: %s", e)

    @DP.callback_query(lambda c: c.data.startswith("banchannelexecute_"))
    async def ban_channel_execute(callback_query: CallbackQuery):
        """Function to execute the channel ban."""
        # Parse channel_id from callback data
        parts = callback_query.data.split("_")
        channel_id = int(parts[1])
        _source_chat_id = int(parts[2])

        admin_username = callback_query.from_user.username
        admin_id = callback_query.from_user.id

        # Answer callback immediately to prevent timeout (no popup alert)
        try:
            await callback_query.answer()
        except TelegramBadRequest as answer_error:
            # Query might be too old, but continue with ban anyway
            LOGGER.debug("Could not answer callback query: %s", answer_error)

        try:
            # Ban channel from all monitored chats
            success, channel_name, channel_username, failed_chats = await ban_rogue_chat_everywhere(
                channel_id, CHANNEL_IDS
            )

            # Remove buttons from message
            try:
                await BOT.edit_message_reply_markup(
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.message_id,
                    reply_markup=None,
                )
            except (MessageNotModified, InvalidQueryID, BadRequest) as edit_error:
                # Ignore errors when trying to remove buttons (already removed, message too old, etc.)
                LOGGER.debug("Could not remove buttons: %s", edit_error)

            if success:
                _admin_display = f"@{admin_username}" if admin_username else "!UNDEFINED!"
                result_message = (
                    f"✅ Channel {channel_name} {channel_username} "
                    f"(<code>{channel_id}</code>) banned from all {len(CHANNEL_IDS)} monitored chats "
                    f"by admin {_admin_display} (<code>{admin_id}</code>)"
                )
                LOGGER.info(
                    "Channel %s %s (%s) banned by admin %s(%s)",
                    channel_name,
                    channel_username,
                    channel_id,
                    _admin_display,
                    admin_id,
                )
            else:
                # Build detailed failure report
                success_count = len(CHANNEL_IDS) - len(failed_chats)
                failed_details = []
                for failed_chat_id, error_msg in failed_chats:
                    # Try to get chat name for better readability
                    chat_name = CHANNEL_DICT.get(failed_chat_id, str(failed_chat_id))
                    failed_details.append(f"   • {chat_name} (<code>{failed_chat_id}</code>): {html.escape(error_msg)}")
                
                failed_list = "\n".join(failed_details)
                result_message = (
                    f"⚠️ Channel {channel_name} {channel_username} "
                    f"(<code>{channel_id}</code>) ban partially completed.\n"
                    f"✅ Success: {success_count}/{len(CHANNEL_IDS)} chats\n"
                    f"❌ Failed in {len(failed_chats)} chat(s):\n{failed_list}"
                )

            # Send result to admin thread
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                result_message,
                LOGGER,
                parse_mode="HTML",
                message_thread_id=TECHNO_ADMIN,
            )

        except TelegramBadRequest as e:
            LOGGER.error("Failed to execute channel ban for %s: %s", channel_id, e)

    @DP.callback_query(lambda c: c.data.startswith("banchannelcancel_"))
    async def ban_channel_cancel(callback_query: CallbackQuery):
        """Function to cancel the channel ban."""
        # Parse channel_id from callback data
        parts = callback_query.data.split("_")
        channel_id = int(parts[1])
        source_chat_id = int(parts[2])

        # Answer callback immediately
        try:
            await callback_query.answer("Cancelled", show_alert=False)
        except (InvalidQueryID, BadRequest) as answer_error:
            LOGGER.debug("Could not answer callback: %s", answer_error)

        # Restore original button
        channel_ban_kb = KeyboardBuilder()
        channel_ban_kb.add(
            InlineKeyboardButton(
                text="🚫 Ban Channel",
                callback_data=f"banchannelconfirm_{channel_id}_{source_chat_id}",
            )
        )

        try:
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=channel_ban_kb.as_markup(),
            )
        except (MessageNotModified, InvalidQueryID, BadRequest) as e:
            LOGGER.debug("Could not restore buttons: %s", e)

    @DP.message(is_in_monitored_channel, F.text.regexp(r"^/\w+@\w+"))
    async def handle_bot_command_in_group(message: Message):
        """Detect and handle commands directed at this bot in monitored groups.
        
        When a user sends /command@botname where botname matches our bot,
        notify the superadmin with detailed user info and provide a button
        to reply with the easter egg response.
        """
        if not message.text or not BOT_USERNAME:
            return
        
        # Check if command is directed at our bot
        # Pattern: /command@botusername
        command_match = re.match(r'^/(\w+)@(\w+)', message.text)
        if not command_match:
            return
        
        command_name = command_match.group(1)
        target_bot = command_match.group(2).lower()
        
        if target_bot != BOT_USERNAME.lower():
            # Command is for a different bot, ignore
            return
        
        user_id = message.from_user.id
        user_firstname = message.from_user.first_name or ""
        user_lastname = message.from_user.last_name or ""
        user_full_name = html.escape(f"{user_firstname} {user_lastname}".strip() or "Unknown")
        user_name = message.from_user.username
        
        LOGGER.info(
            "Bot command detected in group: /%s@%s from %s:@%s in %s (%s)",
            command_name,
            BOT_USERNAME,
            user_id,
            user_name or "!UNDEFINED!",
            message.chat.title,
            message.chat.id,
        )
        
        # Construct message link
        if message.chat.username:
            message_link = f"https://t.me/{message.chat.username}/{message.message_id}"
        else:
            # Private group - use t.me/c/ format
            chat_id_str = str(message.chat.id)
            if chat_id_str.startswith("-100"):
                chat_id_short = chat_id_str[4:]
            else:
                chat_id_short = chat_id_str.lstrip("-")
            message_link = f"https://t.me/c/{chat_id_short}/{message.message_id}"
        
        # Build detailed notification for superadmin
        notification_text = (
            f"🤖 <b>Bot Command Detected in Group</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<b>Command:</b> <code>/{command_name}@{BOT_USERNAME}</code>\n"
            f"<b>Chat:</b> {html.escape(message.chat.title)} (<code>{message.chat.id}</code>)\n"
            f"<b>Message Link:</b> <code>{message_link}</code>\n\n"
            f"<b>User Info:</b>\n"
            f"  ├ Name: {user_full_name}\n"
            f"  ├ Username: @{user_name if user_name else '!UNDEFINED!'}\n"
            f"  ├ ID: <code>{user_id}</code>\n"
            f"  └ Profile Links:\n"
            f"      ├ <a href='tg://user?id={user_id}'>ID Profile Link</a>\n"
            f"      ├ <a href='tg://openmessage?user_id={user_id}'>Android</a>\n"
            f"      ├ <a href='https://t.me/@id{user_id}'>iOS (Apple)</a>\n"
            f"      └ <a href='tg://resolve?domain={user_name}'>{f'@{user_name}' if user_name else 'N/A'}</a>\n\n"
            f"<b>Reply with COMM:</b>\n"
            f"<code>/reply {message_link} Your response here</code>"
        )
        
        # Build keyboard with LOLS check and reply button
        inline_kb = InlineKeyboardBuilder()
        inline_kb.add(
            InlineKeyboardButton(
                text="ℹ️ Check LOLS",
                url=f"https://t.me/oLolsBot?start={user_id}",
            )
        )
        if user_name:
            inline_kb.add(
                InlineKeyboardButton(
                    text=f"🔍 Check @{user_name}",
                    url=f"https://t.me/oLolsBot?start=u-{user_name}",
                )
            )
        inline_kb.add(
            InlineKeyboardButton(
                text="💬 Reply with Easter Egg",
                callback_data=f"botcmdreply_{message.chat.id}_{message.message_id}_{user_id}",
            )
        )
        inline_kb.adjust(2, 1)  # 2 buttons on first row, 1 on second
        
        # Send notification to superadmin
        await safe_send_message(
            BOT,
            ADMIN_USER_ID,
            notification_text,
            LOGGER,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb.as_markup(),
        )
        
        # Forward the original message to superadmin
        try:
            await message.forward(ADMIN_USER_ID, disable_notification=True)
        except TelegramBadRequest as e:
            LOGGER.warning("Could not forward bot command message to admin: %s", e)
        
        # Don't return here - let the message continue to store_recent_messages handler

    @DP.callback_query(lambda c: c.data.startswith("botcmdreply_"))
    async def handle_bot_command_reply(callback_query: CallbackQuery):
        """Handle the reply button for bot commands detected in groups.
        
        After sending the easter egg reply:
        - After 3 minutes: delete the bot's response message
        - After 3 minutes 10 seconds: delete the original command message
        """
        try:
            parts = callback_query.data.split("_")
            if len(parts) != 4:
                await callback_query.answer("Invalid callback data", show_alert=True)
                return
            
            _, chat_id_str, message_id_str, user_id_str = parts
            chat_id = int(chat_id_str)
            message_id = int(message_id_str)  # Original command message ID
            user_id = int(user_id_str)
            
            # Send the easter egg reply to the original message
            easter_egg_response = (
                "Everything that follows is a result of what you see here.\n"
                "I'm sorry. My responses are limited. You must ask the right questions.\n\n"
                "Send me a direct message."
            )
            
            sent_msg = await safe_send_message(
                BOT,
                chat_id,
                easter_egg_response,
                LOGGER,
                reply_to_message_id=message_id,
            )
            
            if sent_msg:
                await callback_query.answer("Easter egg reply sent! Will auto-delete in 3 min 🤖", show_alert=False)
                
                # Schedule message deletions
                async def delayed_cleanup():
                    """Delete bot response after 3 min, then command message after 3:10."""
                    try:
                        # Wait 3 minutes, then delete bot's response
                        await asyncio.sleep(180)  # 3 minutes
                        try:
                            await BOT.delete_message(chat_id, sent_msg.message_id)
                            LOGGER.debug(
                                "Deleted easter egg response %s in chat %s after 3 min",
                                sent_msg.message_id, chat_id
                            )
                        except TelegramBadRequest as e:
                            LOGGER.debug("Could not delete easter egg response: %s", e)
                        
                        # Wait 10 more seconds, then delete the original command message
                        await asyncio.sleep(10)  # 10 more seconds
                        try:
                            await BOT.delete_message(chat_id, message_id)
                            LOGGER.debug(
                                "Deleted original command message %s in chat %s after 3:10",
                                message_id, chat_id
                            )
                        except TelegramBadRequest as e:
                            LOGGER.debug("Could not delete original command message: %s", e)
                            
                    except (asyncio.CancelledError, TelegramBadRequest) as e:
                        LOGGER.error("Error in delayed_cleanup for easter egg: %s", e)
                
                # Start the cleanup task in the background
                asyncio.create_task(delayed_cleanup())
                
                # Update the message to show it was handled
                try:
                    new_text = callback_query.message.text + "\n\n✅ <b>Replied with easter egg</b> (auto-deletes in 3 min)"
                    # Remove the reply button, keep LOLS buttons
                    new_kb = InlineKeyboardBuilder()
                    new_kb.add(
                        InlineKeyboardButton(
                            text="ℹ️ Check LOLS",
                            url=f"https://t.me/oLolsBot?start={user_id}",
                        )
                    )
                    await BOT.edit_message_text(
                        chat_id=callback_query.message.chat.id,
                        message_id=callback_query.message.message_id,
                        text=new_text,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=new_kb.as_markup(),
                    )
                except TelegramBadRequest as e:
                    LOGGER.debug("Could not update message after reply: %s", e)
            else:
                await callback_query.answer("Failed to send reply", show_alert=True)
                
        except TelegramBadRequest as e:
            LOGGER.error("Error in handle_bot_command_reply: %s", e)
            await callback_query.answer(f"Error: {e}", show_alert=True)

    @DP.message(is_in_monitored_channel)
    async def store_recent_messages(message: Message):
        """Function to store recent messages in the database.
        And check senders for spam records."""

        # check if message is Channel message and DELETE it and stop processing
        if (
            message.sender_chat
            and message.sender_chat.id not in ALLOWED_FORWARD_CHANNEL_IDS
            and message.sender_chat.id not in CHANNEL_IDS
            # or message.from_user.id == TELEGRAM_CHANNEL_BOT_ID
        ):
            try:  # Log messages in TECHNOLOG_GROUP_ID
                await BOT.forward_message(
                    TECHNOLOG_GROUP_ID,
                    message.chat.id,
                    message.message_id,
                    message_thread_id=TECHNO_ORIGINALS,
                    disable_notification=True,
                )

                # DELETE CHANNEL message immediately after forwarding
                try:
                    await BOT.delete_message(message.chat.id, message.message_id)
                    LOGGER.info(
                        "🔴 CHANNEL MESSAGE deleted: %s (%s) from chat %s - message forwarded to admins",
                        message.sender_chat.title or "Unknown",
                        message.sender_chat.id,
                        message.chat.title,
                    )
                except TelegramBadRequest as del_error:
                    LOGGER.warning(
                        "🔴 CHANNEL MESSAGE: Could not delete message %s in chat %s: %s",
                        message.message_id,
                        message.chat.id,
                        del_error,
                    )

                message_link = construct_message_link(
                    [
                        message.chat.id,
                        message.message_id,
                        message.chat.username if message.chat.username else None,
                    ]
                )
                # Create keyboard with LOLS check and Ban Channel buttons
                channel_ban_kb = KeyboardBuilder()
                # Add LOLS check button for the channel
                lols_url = f"https://t.me/oLolsBot?start={message.sender_chat.id}"
                channel_ban_kb.add(
                    InlineKeyboardButton(text="ℹ️ Check Channel Data ℹ️", url=lols_url)
                )
                channel_ban_kb.add(
                    InlineKeyboardButton(
                        text="🚫 Ban Channel",
                        callback_data=f"banchannelconfirm_{message.sender_chat.id}_{message.chat.id}",
                    )
                )

                channel_msg_info = "<b>⚠️ CHANNEL MESSAGE DETECTED</b>\n\n"
                channel_msg_info += (
                    f"<b>Channel:</b> {message.sender_chat.title or 'Unknown'}\n"
                )
                if message.sender_chat.username:
                    channel_msg_info += (
                        f"<b>Username:</b> @{message.sender_chat.username}\n"
                    )
                channel_msg_info += (
                    f"<b>Channel ID:</b> <code>{message.sender_chat.id}</code>\n"
                )
                channel_msg_info += f"<b>Posted in:</b> {message.chat.title}\n"
                channel_msg_info += "<b>Status:</b> ❌ Deleted from chat"

                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"{channel_msg_info}\n\nMessage link (deleted): <a href='{message_link}'>Click here</a>",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=TECHNO_ORIGINALS,
                    disable_notification=True,
                    reply_markup=channel_ban_kb.as_markup(),
                )
            except TelegramBadRequest as e:
                # Covers MessageIdInvalid, MessageToForwardNotFound, MessageCantBeForwarded
                LOGGER.error(
                    "🔴 CHANNEL MESSAGE: Processing error (bad request): %s",
                    e,
                )
                # Continue processing despite error
            try:
                # Convert the Message object to a dictionary
                message_dict = message.model_dump(mode="json")
                formatted_message = json.dumps(
                    message_dict, indent=4, ensure_ascii=False
                )  # Convert back to a JSON string with indentation and human-readable characters
                formatted_message_tlgrm: str = None
                if len(formatted_message) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
                    formatted_message_tlgrm = (
                        formatted_message[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
                    )
                LOGGER.debug(
                    "\n🔴 CHANNEL MESSAGE object received:\n %s\n",
                    formatted_message,
                )
                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"🔴 <b>CHANNEL MESSAGE DEBUG:</b>\n\n<pre>{formatted_message_tlgrm if formatted_message_tlgrm else formatted_message}</pre>",
                    LOGGER,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    message_thread_id=TECHNO_ADMIN,
                )
            except TelegramBadRequest as e:
                LOGGER.error("🔴 CHANNEL MESSAGE: Already deleted! %s", e)

            return  # Stop processing - don't store channel messages in DB

        # Update chat username cache for future link construction
        update_chat_username_cache(message.chat.id, message.chat.username)

        # create unified message link
        message_link = construct_message_link(
            [message.chat.id, message.message_id, message.chat.username]
        )

        # check if sender is an admin in the channel or admin group then log and skip the message
        if await is_admin(message.from_user.id, message.chat.id) or await is_admin(
            message.from_user.id, ADMIN_GROUP_ID
        ):
            LOGGER.debug(
                "\033[95m%s:@%s is admin, skipping the message %s in the chat %s.\033[0m\n\t\t\tMessage link: %s",
                message.from_user.id,
                (
                    message.from_user.username
                    if message.from_user.username
                    else "!UNDEFINED!"
                ),
                message.message_id,
                message.chat.title,
                message_link,
            )
            return  # Stop processing - don't track admin messages

        # check if message is forward from allowed channels
        if message.forward_from_chat and message.forward_from_chat.id in {
            message.chat.id,
            *ALLOWED_FORWARD_CHANNEL_IDS,
        }:
            LOGGER.debug(
                "\033[95m%s:@%s FORWARDED from allowed channel, skipping the message %s in the chat %s.\033[0m\n\t\t\tMessage link: %s",
                message.from_user.id,
                (
                    message.from_user.username
                    if message.from_user.username
                    else "!UNDEFINED!"
                ),
                message.message_id,
                message.chat.title,
                message_link,
            )
            return

        lols_link = f"https://t.me/oLolsBot?start={message.from_user.id}"

        inline_kb = create_inline_keyboard(message_link, lols_link, message)

        # If user is under active checks and changed profile, immediately forward to ADMIN_SUSPICIOUS with buttons
        try:
            _uid = message.from_user.id
            _entry = active_user_checks_dict.get(_uid)
            if isinstance(_entry, dict):
                _baseline = _entry.get("baseline")
                _already_notified = _entry.get("notified_profile_change", False)
                if _baseline and not _already_notified:
                    old_first = _baseline.get("first_name", "")
                    old_last = _baseline.get("last_name", "")
                    old_usern = _baseline.get("username", "")
                    old_pcnt = _baseline.get("photo_count", 0)

                    new_first = getattr(message.from_user, "first_name", "") or ""
                    new_last = getattr(message.from_user, "last_name", "") or ""
                    new_usern = getattr(message.from_user, "username", "") or ""
                    new_pcnt = old_pcnt
                    # Try to detect uploaded photo (0 -> >0)
                    try:
                        _p = await BOT.get_user_profile_photos(_uid, limit=1)
                        new_pcnt = getattr(_p, "total_count", 0) if _p else old_pcnt
                    except TelegramBadRequest as _e:
                        LOGGER.debug(
                            "%s:@%s unable to fetch photo count on message: %s",
                            _uid,
                            new_usern or "!UNDEFINED!",
                            _e,
                        )

                    changed = []
                    diffs = []
                    if new_first != old_first:
                        changed.append("first name")
                        diffs.append(
                            f"first name: '{html.escape(old_first)}' -> '{html.escape(new_first)}'"
                        )
                    if new_last != old_last:
                        changed.append("last name")
                        diffs.append(
                            f"last name: '{html.escape(old_last)}' -> '{html.escape(new_last)}'"
                        )
                    # Normalize usernames before comparison to handle !UNDEFINED!/None/empty equivalence
                    if normalize_username(new_usern) != normalize_username(old_usern):
                        changed.append("username")
                        diffs.append(
                            f"username: @{old_usern or '!UNDEFINED!'} -> @{new_usern or '!UNDEFINED!'}"
                        )
                    if old_pcnt == 0 and new_pcnt > 0:
                        changed.append("profile photo")
                        diffs.append("profile photo: none -> set")

                    if changed:
                        # Forward the triggering message (skip if already autoreported)
                        if not was_autoreported(message):
                            try:
                                await message.forward(
                                    ADMIN_GROUP_ID,
                                    ADMIN_SUSPICIOUS,
                                    disable_notification=True,
                                )
                            except (TelegramBadRequest, TelegramForbiddenError) as _e:
                                LOGGER.debug(
                                    "%s:@%s forward to admin/suspicious failed: %s",
                                    _uid,
                                new_usern or "!UNDEFINED!",
                                _e,
                            )

                        kb = make_lols_kb(_uid)
                        # Use 0 for message_id - this is a profile change event, not a message
                        kb.add(
                            InlineKeyboardButton(
                                text="⚙️ Actions (Ban / Delete) ⚙️",
                                callback_data=f"suspiciousactions_{message.chat.id}_0_{_uid}",
                            )
                        )

                        _ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                        chat_title_safe = html.escape(message.chat.title)
                        chat_link_html = build_chat_link(message.chat.id, message.chat.username, message.chat.title)

                        # Build unified diff-style lines
                        def _fmt(old, new, label, username=False):
                            if username:
                                old_disp = ("@" + old) if old else "@!UNDEFINED!"
                                new_disp = ("@" + new) if new else "@!UNDEFINED!"
                            else:
                                old_disp = html.escape(old) if old else ""
                                new_disp = html.escape(new) if new else ""
                            if old != new:
                                return f"{label}: {old_disp or '∅'} ➜ <b>{new_disp or '∅'}</b>"
                            return f"{label}: {new_disp or '∅'}"

                        field_lines = [
                            _fmt(old_first, new_first, "First name"),
                            _fmt(old_last, new_last, "Last name"),
                            _fmt(old_usern, new_usern, "Username", username=True),
                            f"User ID: <code>{_uid}</code>",
                        ]
                        if old_pcnt == 0 and new_pcnt > 0:
                            field_lines.append("Profile photo: none ➜ <b>set</b>")

                        profile_links = (
                            f"🔗 <b>Profile links:</b>\n"
                            f"   ├ <a href='tg://user?id={_uid}'>id based profile link</a>\n"
                            f"   └ <a href='tg://openmessage?user_id={_uid}'>Android</a>, <a href='https://t.me/@id{_uid}'>IOS (Apple)</a>"
                        )
                        # Elapsed time since join
                        joined_at_raw = (
                            _baseline.get("joined_at")
                            if isinstance(_baseline, dict)
                            else None
                        )
                        elapsed_line = ""
                        if joined_at_raw:
                            try:
                                # Strip timezone if present
                                _ja_str = str(joined_at_raw)
                                if "+" in _ja_str:
                                    _ja_str = _ja_str.split("+")[0].strip()
                                _jdt = datetime.strptime(
                                    _ja_str, "%Y-%m-%d %H:%M:%S"
                                )
                                _delta = datetime.now() - _jdt
                                _days = _delta.days
                                _hours, _rem = divmod(_delta.seconds, 3600)
                                _minutes, _seconds = divmod(_rem, 60)
                                _parts = []
                                if _days:
                                    _parts.append(f"{_days}d")
                                if _hours:
                                    _parts.append(f"{_hours}h")
                                if _minutes and not _days:
                                    _parts.append(f"{_minutes}m")
                                if _seconds and not _days and not _hours:
                                    _parts.append(f"{_seconds}s")
                                _human_elapsed = " ".join(_parts) or f"{_seconds}s"
                                elapsed_line = f"\nJoined at: {joined_at_raw} (elapsed: {_human_elapsed})"
                            except ValueError:
                                elapsed_line = f"\nJoined at: {joined_at_raw}"

                        message_text = (
                            "Suspicious profile change detected while under watch.\n"
                            f"In chat: {chat_link_html}\n"
                            f"🔗 <a href='{message_link}'>Original message</a>\n"
                            + "\n".join(field_lines)
                            + f"\nChanges: <b>{', '.join(changed)}</b> at {_ts}."
                            + elapsed_line
                            + "\n"
                            + profile_links
                        )

                        await safe_send_message(
                            BOT,
                            ADMIN_GROUP_ID,
                            message_text,
                            LOGGER,
                            message_thread_id=ADMIN_SUSPICIOUS,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                            reply_markup=kb.as_markup(),
                        )
                        # Log immediate profile change
                        await log_profile_change(
                            user_id=_uid,
                            username=new_usern,
                            context="immediate",
                            chat_id=message.chat.id,
                            chat_title=getattr(message.chat, "title", None),
                            changed=changed,
                            old_values=make_profile_dict(
                                old_first,
                                old_last,
                                old_usern,
                                old_pcnt,
                            ),
                            new_values=make_profile_dict(
                                new_first,
                                new_last,
                                new_usern,
                                new_pcnt,
                            ),
                            photo_changed=("profile photo" in changed),
                        )
                        active_user_checks_dict[_uid]["notified_profile_change"] = True
        except (TelegramBadRequest, KeyError, TypeError) as _e:
            LOGGER.debug("Immediate profile-change check failed: %s", _e)

        ### AUTOBAHN MESSAGE CHECKING ###
        # check if message is from user from active_user_checks_dict
        # and banned_users_dict set
        # Note: Edge case - user in both active checks and banned (race condition)
        if (
            message.from_user.id in active_user_checks_dict
            and message.from_user.id in banned_users_dict
        ):
            LOGGER.warning(
                "\033[47m\033[34m%s is in both active_user_checks_dict and banned_users_dict, check the message %s in the chat %s (%s)\033[0m",
                message.from_user.id,
                message.message_id,
                message.chat.title,
                message.chat.id,
            )
        elif (
            (
                message.from_user.id in banned_users_dict
                or await spam_check(message.from_user.id) is True
            )
            or (
                message.forward_from_chat
                and (
                    message.forward_from_chat.id in banned_users_dict
                    or await spam_check(message.forward_from_chat.id) is True
                )
            )
            or (
                message.forward_from
                and (
                    message.forward_from.id in banned_users_dict
                    or await spam_check(message.forward_from.id) is True
                )
            )
        ):
            if (
                message.from_user and message.from_user.id in banned_users_dict
            ):  # user_id BANNED
                logger_text = f"\033[41m\033[37m{message.from_user.id}:@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} is in banned_users_dict, DELETING the message {message.message_id} in the chat {message.chat.title} ({message.chat.id})\033[0m"
            # elif (
            #     message.sender_chat and message.sender_chat.id in banned_users_dict
            # ):  # sender_chat_id BANNED
            #     logger_text = f"\033[41m\033[37m{message.from_user.id}:@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} SENDER CHAT: {message.forward_from_chat.id}:@{getattr(message.forward_from_chat, 'username', None) or message.forward_from_chat.title} is in banned_users_dict, DELETING the message {message.message_id} in the chat {message.chat.title} ({message.chat.id})\033[0m"
            elif (
                message.forward_from_chat
                and message.forward_from_chat.id in banned_users_dict
            ):  # forward_from_chat_id BANNED
                logger_text = f"\033[41m\033[37m{message.from_user.id}:@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} FORWARDED FROM CHAT: {message.forward_from_chat.id}:@{getattr(message.forward_from_chat, 'username', None) or message.forward_from_chat.title} is in banned_users_dict, DELETING the message {message.message_id} in the chat {message.chat.title} ({message.chat.id})\033[0m"
            elif (
                message.forward_from and message.forward_from.id in banned_users_dict
            ):  # forward_from.id BANNED
                logger_text = f"\033[41m\033[37m{message.from_user.id}:@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} FORWARDED FROM USER: {message.forward_from.id}:@{getattr(message.forward_from, 'username', None) or message.forward_from.first_name} is in banned_users_dict, DELETING the message {message.message_id} in the chat {message.chat.title} ({message.chat.id})\033[0m"
            else:  # marked as a SPAM by P2P server
                logger_text = f"\033[41m\033[37m{message.from_user.id}:@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} is marked as SPAMMER by spam_check, DELETING the message {message.message_id} in the chat {message.chat.title} ({message.chat.id})\033[0m"

            # Forward banned user message to ADMIN AUTOBAN
            try:
                await BOT.forward_message(
                    ADMIN_GROUP_ID,
                    message.chat.id,
                    message.message_id,
                    message_thread_id=ADMIN_AUTOBAN,
                    disable_notification=True,
                )
            except (TelegramBadRequest, TelegramForbiddenError) as e:
                LOGGER.debug("Could not forward banned user message to admin: %s", e)

            # report ids of sender_chat, forward_from and forward_from_chat as SPAM to p2p server
            await report_spam_from_message(message, LOGGER, TELEGRAM_CHANNEL_BOT_ID)
            LOGGER.warning(logger_text)

            # delete message immidiately
            await BOT.delete_message(message.chat.id, message.message_id)

            # Send info to ADMIN_AUTOBAN
            chat_title_safe = html.escape(message.chat.title)
            chat_link_html = build_chat_link(message.chat.id, message.chat.username, message.chat.title)
            # Add @username to display if available
            if message.chat.username:
                chat_link_html = chat_link_html.replace(f">{chat_title_safe}</a>", f">{chat_title_safe} (@{message.chat.username})</a>")

            admin_notification_text = (
                f"Deleted message: <code>{message_link}</code>\n"
                f"{html.escape(message.from_user.first_name)}{f' {html.escape(message.from_user.last_name)}' if message.from_user.last_name else ''} "
                f"@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} (<code>{message.from_user.id}</code>)\n"
                f"In chat: {chat_link_html} (<code>{message.chat.id}</code>)"
            )
            
            # Build keyboard with LOLS check for banned user and any mentioned users
            autoban_kb = KeyboardBuilder()
            autoban_kb.add(
                InlineKeyboardButton(
                    text="ℹ️ Check Spam Data ℹ️",
                    url=f"https://t.me/oLolsBot?start={message.from_user.id}",
                )
            )
            # Add LOLS check buttons for mentioned users in the spam message (up to 3)
            if message.entities and message.text:
                max_mention_buttons = 3
                mention_buttons_added = 0
                for entity in message.entities:
                    if mention_buttons_added >= max_mention_buttons:
                        break
                    entity_type = entity.get("type") if isinstance(entity, dict) else getattr(entity, "type", None)
                    if entity_type == "mention":
                        offset = entity.get("offset") if isinstance(entity, dict) else getattr(entity, "offset", 0)
                        length = entity.get("length") if isinstance(entity, dict) else getattr(entity, "length", 0)
                        mention = message.text[offset:offset + length]
                        if mention.startswith("@"):
                            username_clean = mention.lstrip("@")
                            mention_lols_link = f"https://t.me/oLolsBot?start=u-{username_clean}"
                            autoban_kb.add(
                                InlineKeyboardButton(text=f"🔍 Check {mention}", url=mention_lols_link)
                            )
                            mention_buttons_added += 1
                    elif entity_type == "text_mention":
                        user = entity.get("user") if isinstance(entity, dict) else getattr(entity, "user", None)
                        if user:
                            user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
                            if user_id:
                                mention_lols_link = f"https://t.me/oLolsBot?start={user_id}"
                                first_name = user.get("first_name", "") if isinstance(user, dict) else getattr(user, "first_name", "")
                                display = first_name[:15] + "..." if len(first_name) > 15 else first_name
                                autoban_kb.add(
                                    InlineKeyboardButton(text=f"🔍 Check ID:{user_id} ({display})", url=mention_lols_link)
                                )
                                mention_buttons_added += 1

            await safe_send_message(
                BOT,
                ADMIN_GROUP_ID,
                admin_notification_text,
                LOGGER,
                message_thread_id=ADMIN_AUTOBAN,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=autoban_kb.as_markup(),
            )

            # Check if message is forward from banned channel
            rogue_chan_id = (
                # message.sender_chat.id
                # if message.sender_chat
                # else (
                message.forward_from_chat.id
                if message.forward_from_chat
                else None
                # )
            )
            rogue_chan_username = (
                getattr(message.sender_chat, "username", None)
                if message.sender_chat
                else (
                    getattr(message.forward_from_chat, "username", None)
                    if message.forward_from_chat
                    else "!UNDEFINED!"
                )
            )
            rogue_chan_name = (
                message.sender_chat.title
                if message.sender_chat
                else (
                    message.forward_from_chat.title
                    if message.forward_from_chat
                    else "!UNDEFINED!"
                )
            )
            escaped_user_name = (
                html.escape(message.from_user.first_name)
                + " "
                + html.escape(message.from_user.last_name)
                if message.from_user.last_name
                else ""
            )
            if rogue_chan_id and (
                message.from_user.id in banned_users_dict
                or rogue_chan_id in banned_users_dict
                or await spam_check(message.from_user.id)
            ):
                try:
                    # Determine sender/forwarder details
                    if message.sender_chat:
                        sender_or_forwarder_title = message.sender_chat.title
                        sender_or_forwarder_username = message.sender_chat.username
                        sender_or_forwarder_id = message.sender_chat.id
                    elif message.forward_from_chat:
                        sender_or_forwarder_title = message.forward_from_chat.title
                        sender_or_forwarder_username = (
                            message.forward_from_chat.username
                        )
                        sender_or_forwarder_id = message.forward_from_chat.id
                    else:
                        sender_or_forwarder_title = "!NO sender/forwarder chat TITLE!"
                        sender_or_forwarder_username = "!NONAME!"
                        sender_or_forwarder_id = "!NO sender/forwarder chat ID!"

                    # Determine the HTML link for the chat where the ban occurred
                    _escaped_chat_title_for_link = html.escape(
                        message.chat.title, quote=True
                    )
                    _escaped_chat_title_for_display = html.escape(
                        message.chat.title
                    )  # Used when no link is formed

                    banned_in_chat_link_html = build_chat_link(message.chat.id, message.chat.username, message.chat.title)
                    # ban spammer in all chats
                    ban_member_task = await check_and_autoban(
                        f"{escaped_user_name} @{message.from_user.username if message.from_user.username else '!UNDEFINED!'} ({message.from_user.id}) CHANNELLED a SPAM message from ___{rogue_chan_name}___ @{rogue_chan_username} ({rogue_chan_id})",
                        message.from_user.id,
                        f"{escaped_user_name} @{message.from_user.username if message.from_user.username else '!UNDEFINED!'} (<code>{message.from_user.id}</code>) CHANNELLED a SPAM message from ___{rogue_chan_name}___ @{rogue_chan_username} ({rogue_chan_id})",
                        (
                            message.from_user.username
                            if message.from_user.username
                            else "!UNDEFINED!"
                        ),
                        lols_spam=True,
                        message_to_delete=None,
                    )
                    # ban channel in the rest of chats
                    ban_rogue_chan_task = await ban_rogue_chat_everywhere(
                        rogue_chan_id,
                        CHANNEL_IDS,
                    )
                    # add rogue channel to banned_users_dict
                    if (
                        message.sender_chat
                        and message.sender_chat.id not in banned_users_dict
                    ):
                        banned_users_dict[message.sender_chat.id] = (
                            getattr(message.sender_chat, "username", None)
                            or message.sender_chat.title
                        )
                    elif (
                        message.forward_from_chat
                        and message.forward_from_chat.id not in banned_users_dict
                    ):
                        banned_users_dict[message.forward_from_chat.id] = (
                            getattr(message.forward_from_chat, "username", None)
                            or message.forward_from_chat.title
                        )
                    elif rogue_chan_id in banned_users_dict:
                        ban_rogue_chan_task = (
                            None  # Prevent banning already banned channel
                        )

                    tasks = [
                        ban_member_task,
                        ban_rogue_chan_task if rogue_chan_id else None,
                    ]

                    # Filter out None values
                    tasks = [task for task in tasks if task is not None]

                    # Ensure all tasks are coroutines or awaitables
                    tasks = [
                        task
                        for task in tasks
                        if asyncio.iscoroutine(task) or isinstance(task, asyncio.Future)
                    ]

                    await asyncio.gather(*tasks)

                    # admin_log_chan_data = (
                    #     f"Channel <b>___{message.sender_chat.title if message.sender_chat else (message.forward_from_chat.title if message.forward_from_chat else '!NO sender/forwarder chat TITLE!')}___</b> "
                    #     f"@{(message.sender_chat.username if message.sender_chat else (message.forward_from_chat.username if message.forward_from_chat else '!NONAME!'))} "
                    #     f"(<code>{message.sender_chat.id if message.sender_chat else (message.forward_from_chat.id if message.forward_from_chat else '!NO sender/forwarder chat ID!')}</code>)"
                    #     f"banned in chat {(f'<a href="https://t.me/{message.chat.username}">{html.escape(message.chat.title, quote=True)}</a>' if message.chat.username else (f'<a href="https://t.me/c/{str(message.chat.id)[4:]}">{html.escape(message.chat.title, quote=True)}</a>' if str(message.chat.id).startswith('-100') else html.escape(message.chat.title)))} (<code>{message.chat.id}</code>)"
                    # )
                    admin_log_chan_data = (
                        f"Spam from channel <b>''{sender_or_forwarder_title}''</b> @{sender_or_forwarder_username} "
                        f"(<code>{sender_or_forwarder_id}</code>) "
                        f"forwarded by {html.escape(message.from_user.first_name)}{f' {html.escape(message.from_user.last_name)}' if message.from_user.last_name else ''} "
                        f"@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} (<code>{message.from_user.id}</code>) "
                        f"banned in chat {banned_in_chat_link_html} (<code>{message.chat.id}</code>)"
                    )
                    log_chan_data = (
                        f"Channel {message.sender_chat.title if message.sender_chat else (message.forward_from_chat.title if message.forward_from_chat else '!NO sender/forwarder chat TITLE!')} "
                        f"({message.sender_chat.id if message.sender_chat else (message.forward_from_chat.id if message.forward_from_chat else '!NO sender/forwarder chat ID!')}):"
                        f"@{(message.sender_chat.username if message.sender_chat else (message.forward_from_chat.username if message.forward_from_chat else '!NONAME!'))} "
                        f"banned in chat {message.chat.title} ({message.chat.id})"
                    )
                    LOGGER.info(log_chan_data)
                    await safe_send_message(
                        BOT,
                        ADMIN_GROUP_ID,
                        admin_log_chan_data,
                        LOGGER,
                        parse_mode="HTML",
                        message_thread_id=ADMIN_AUTOBAN,
                        disable_web_page_preview=True,
                        disable_notification=True,
                    )
                    return  # stop actions for this message forwarded from channel/chat and do not record to DB
                except TelegramBadRequest as e:
                    LOGGER.error(
                        "Error banning channel %s in chat %s: %s",
                        message.sender_chat,
                        message.chat.id,
                        e,
                    )
                    return  # stop processing further this message
            else:
                # LSS LATENCY - spammer detected by LOLS after message was processed
                # Try to delete the message (may already be deleted by earlier handler - that's OK)
                try:
                    await BOT.delete_message(message.chat.id, message.message_id)
                    LOGGER.debug(
                        "\033[91m%s:@%s message %s deleted (late LOLS detection) in chat %s (%s) @%s #LSS\033[0m",
                        message.from_user.id,
                        message.from_user.username or "!UNDEFINED!",
                        message.message_id,
                        message.chat.title,
                        message.chat.id,
                        message.chat.username or "NoName",
                    )
                except TelegramBadRequest as e:
                    # Message already deleted by earlier spam handler - this is expected race condition
                    LOGGER.debug(
                        "\033[93m%s:@%s message %s already deleted (race condition OK) in chat %s (%s) @%s #LSS\033[0m",
                        message.from_user.id,
                        message.from_user.username or "!UNDEFINED!",
                        message.message_id,
                        message.chat.title,
                        message.chat.id,
                        message.chat.username or "NoName",
                    )
                _success_count, _fail_count, _total_count = await ban_user_from_all_chats(
                    message.from_user.id,
                    (
                        message.from_user.username
                        if message.from_user.username
                        else "!UNDEFINED!"
                    ),
                    CHANNEL_IDS,
                    CHANNEL_DICT,
                )
                # BOT.ban_chat_member(
                #     message.chat.id, message.from_user.id, revoke_messages=True
                # )
                return

        ### STORE MESSAGES AND AUTOREPORT EM###
        try:
            # Store message data to DB
            store_message_to_db(CURSOR, CONN, message)

            # search for the latest user join chat event date using user_id in the DB
            user_join_chat_date_str = CURSOR.execute(
                "SELECT received_date FROM recent_messages WHERE user_id = ? AND new_chat_member = 1 ORDER BY received_date DESC LIMIT 1",
                (message.from_user.id,),
            ).fetchone()
            
            # If no join record, bot may have been offline when user joined
            # Check for earliest message from this user as fallback "first seen" date
            user_first_seen_unknown = False
            missed_join_notification_sent = False  # Track if we sent missed join notification
            if not user_join_chat_date_str:
                user_first_message_date = CURSOR.execute(
                    "SELECT received_date FROM recent_messages WHERE user_id = ? ORDER BY received_date ASC LIMIT 1",
                    (message.from_user.id,),
                ).fetchone()
                if user_first_message_date:
                    # Use first message date as proxy for join date
                    user_join_chat_date_str = user_first_message_date
                    
                    # Check if this is the CURRENT message (first time we're seeing this user)
                    # Only send notification if this is the actual first message we stored
                    current_msg_date_str = message.date.strftime("%Y-%m-%d %H:%M:%S") if message.date else None
                    first_msg_date_str = user_first_message_date[0] if user_first_message_date else None
                    
                    # Only notify if dates match (this IS the first message being processed)
                    # or if user is not yet in active checks (to avoid spam notifications)
                    should_notify_missed_join = (
                        current_msg_date_str == first_msg_date_str
                        or message.from_user.id not in active_user_checks_dict
                    )
                    
                    LOGGER.debug(
                        "No join record for %s, using first message date: %s",
                        message.from_user.id,
                        user_first_message_date[0],
                    )
                    
                    # Check if this is an established user - skip suspicious banner if so
                    # Established = (messages >= MIN AND first_msg_age >= DAYS) OR any legit marker
                    _skip_missed_join_banner = False
                    if should_notify_missed_join:
                        # Count user's messages
                        _user_msg_count = CURSOR.execute(
                            "SELECT COUNT(*) FROM recent_messages WHERE user_id = ?",
                            (message.from_user.id,),
                        ).fetchone()[0]
                        
                        # Check if user has any legit marker (either in recent_messages or baselines)
                        _is_user_legit = check_user_legit(CURSOR, message.from_user.id)
                        if not _is_user_legit:
                            # Also check baseline for is_legit flag
                            _user_baseline = get_user_baseline(CONN, message.from_user.id)
                            if _user_baseline and _user_baseline.get("is_legit"):
                                _is_user_legit = True
                        
                        # Parse first message date and check if older than threshold
                        _first_msg_old_enough = False
                        try:
                            # Handle both formats: with and without timezone
                            _first_msg_dt = datetime.fromisoformat(user_first_message_date[0].replace(" ", "T"))
                            _threshold_date = datetime.now() - timedelta(days=ESTABLISHED_USER_FIRST_MSG_DAYS)
                            _first_msg_old_enough = _first_msg_dt < _threshold_date
                        except (ValueError, TypeError) as parse_err:
                            LOGGER.warning(
                                "Failed to parse first message date '%s' for user %s: %s",
                                user_first_message_date[0],
                                message.from_user.id,
                                parse_err,
                            )
                        
                        # Skip if (messages >= threshold AND first_msg old enough) OR legit
                        if (_user_msg_count >= ESTABLISHED_USER_MIN_MESSAGES and _first_msg_old_enough) or _is_user_legit:
                            _skip_missed_join_banner = True
                            LOGGER.info(
                                "\033[92mSkipping missed join banner for established user %s:@%s "
                                "(messages: %d/%d, legit: %s, first_msg: %s, threshold: %d days)\033[0m",
                                message.from_user.id,
                                message.from_user.username or "!NO_USERNAME!",
                                _user_msg_count,
                                ESTABLISHED_USER_MIN_MESSAGES,
                                _is_user_legit,
                                user_first_message_date[0],
                                ESTABLISHED_USER_FIRST_MSG_DAYS,
                            )
                            # Mark first message as join event (just like after notification)
                            try:
                                CURSOR.execute(
                                    """
                                    UPDATE recent_messages 
                                    SET new_chat_member = 1 
                                    WHERE user_id = ? AND received_date = ?
                                    """,
                                    (
                                        message.from_user.id,
                                        user_first_message_date[0],
                                    ),
                                )
                                CONN.commit()
                                LOGGER.debug(
                                    "Marked first message as join event for established user %s",
                                    message.from_user.id,
                                )
                            except sqlite3.Error as db_err:
                                LOGGER.warning(
                                    "Failed to mark first message as join event for established user %s: %s",
                                    message.from_user.id,
                                    db_err,
                                )
                            # Skip the notification
                            should_notify_missed_join = False
                    
                    # Bot was offline when user joined - send suspicious notification
                    # This user might be a spammer who joined while bot wasn't watching
                    # Only send notification once per user (when first detected)
                    if should_notify_missed_join:
                        # Check if user is in active monitoring AND message contains bot mention
                        # If so, treat as autoreport instead of suspicious notification
                        _has_bot_mention = False
                        if message.entities and message.text:
                            for entity in message.entities:
                                entity_type = entity.get("type") if isinstance(entity, dict) else getattr(entity, "type", None)
                                if entity_type == "mention":
                                    offset = entity.get("offset") if isinstance(entity, dict) else getattr(entity, "offset", 0)
                                    length = entity.get("length") if isinstance(entity, dict) else getattr(entity, "length", 0)
                                    mention = message.text[offset:offset + length].lower()
                                    if mention.endswith("bot"):
                                        _has_bot_mention = True
                                        break
                        
                        # If user is being monitored and mentions a bot, send to autoreport instead
                        if message.from_user.id in active_user_checks_dict and _has_bot_mention:
                            LOGGER.info(
                                "User %s:@%s is in active checks and mentioned a bot - sending to AUTOREPORT instead of SUSPICIOUS",
                                message.from_user.id,
                                message.from_user.username or "!UNDEFINED!",
                            )
                            await submit_autoreport(message, "Bot mention by monitored user (missed join)")
                            missed_join_notification_sent = True
                        else:
                            # Regular missed join notification to ADMIN_SUSPICIOUS
                            # Use actual message_id since we have a message to link to
                            _chat_link_html = build_chat_link(message.chat.id, message.chat.username, message.chat.title)
                            _first_seen_date = user_first_message_date[0]
                        
                            # Build message link
                            if message.chat.username:
                                _msg_link = f"https://t.me/{message.chat.username}/{message.message_id}"
                            else:
                                _chat_id_str = str(message.chat.id)[4:] if message.chat.id < 0 else str(message.chat.id)
                                _msg_link = f"https://t.me/c/{_chat_id_str}/{message.message_id}"
                            
                            _missed_join_message = (
                                f"⚠️ <b>Missed Join Detected</b>\n"
                                f"User: @{message.from_user.username if message.from_user.username else '!UNDEFINED!'} "
                                f"(<code>{message.from_user.id}</code>)\n"
                                f"Name: {html.escape(message.from_user.first_name or '')} {html.escape(message.from_user.last_name or '')}\n"
                                f"Chat: {_chat_link_html}\n\n"
                                f"📅 <b>First message seen:</b> {_first_seen_date}\n"
                                f"ℹ️ Bot was offline when user joined - no join event recorded\n"
                                f"🔗 <a href='{_msg_link}'>Current message</a>\n\n"
                                f"🔗 <b>Profile links:</b>\n"
                                f"   ├ <a href='tg://user?id={message.from_user.id}'>ID based profile link</a>\n"
                                f"   └ <a href='tg://openmessage?user_id={message.from_user.id}'>Android</a>, "
                                f"<a href='https://t.me/@id{message.from_user.id}'>iOS</a>"
                            )
                            
                            _missed_join_kb = make_lols_kb(message.from_user.id)
                            _missed_join_kb.add(
                                InlineKeyboardButton(
                                    text="⚙️ Actions (Ban / Delete) ⚙️",
                                    callback_data=f"suspiciousactions_{message.chat.id}_{message.message_id}_{message.from_user.id}",
                                )
                            )
                            _missed_join_kb.add(
                                InlineKeyboardButton(
                                    text="✅ Mark as Legit",
                                    callback_data=f"stopchecks_{message.from_user.id}_{message.chat.id}_{message.message_id}",
                                )
                            )
                            
                            # Add mention check buttons if message has mentions
                            mention_analysis = analyze_mentions_in_message(message)
                            for mention_type, mention_value, display_name in mention_analysis["mentions"]:
                                if mention_type == "username":
                                    mention_lols_link = f"https://t.me/oLolsBot?start=u-{mention_value}"
                                    _missed_join_kb.add(
                                        InlineKeyboardButton(text=f"🔍 Check @{mention_value}", url=mention_lols_link)
                                    )
                                elif mention_type == "user_id":
                                    mention_lols_link = f"https://t.me/oLolsBot?start={mention_value}"
                                    _missed_join_kb.add(
                                        InlineKeyboardButton(text=f"🔍 Check ID:{mention_value} ({display_name})", url=mention_lols_link)
                                    )
                            
                            # Add mention info to message if needed
                            if mention_analysis["has_more"] or mention_analysis["hidden_mentions"]:
                                if mention_analysis["has_more"]:
                                    _missed_join_message += f"\n⚠️ <b>{mention_analysis['total_count']} mentions found</b> (showing first 3)"
                                if mention_analysis["hidden_mentions"]:
                                    hidden_list = ", ".join(mention_analysis["hidden_mentions"][:5])
                                    _missed_join_message += f"\n🕵️ <b>Hidden mentions:</b> {hidden_list}"
                            
                            # Forward the message first
                            try:
                                await message.forward(
                                    ADMIN_GROUP_ID,
                                    ADMIN_SUSPICIOUS,
                                    disable_notification=True,
                                )
                            except (TelegramBadRequest, TelegramForbiddenError) as fwd_err:
                                LOGGER.warning("Failed to forward message for missed join: %s", fwd_err)
                            
                            await safe_send_message(
                                BOT,
                                ADMIN_GROUP_ID,
                                _missed_join_message,
                                LOGGER,
                                message_thread_id=ADMIN_SUSPICIOUS,
                                parse_mode="HTML",
                                disable_web_page_preview=True,
                                reply_markup=_missed_join_kb.as_markup(),
                            )
                            missed_join_notification_sent = True
                            mark_suspicious_reported(message)  # Prevent duplicate suspicious content report
                            LOGGER.info(
                                "Sent missed join notification for %s:@%s to ADMIN_SUSPICIOUS",
                                message.from_user.id,
                                message.from_user.username or "!NO_USERNAME!",
                            )
                        
                        # After sending notification (either autoreport or suspicious), mark first message as join event
                        # This prevents duplicate notifications for the same user
                        if missed_join_notification_sent:
                            try:
                                # Update the first message record to mark it as a join event
                                CURSOR.execute(
                                    """
                                    UPDATE recent_messages 
                                    SET new_chat_member = 1 
                                    WHERE user_id = ? AND received_date = ?
                                    """,
                                    (
                                        message.from_user.id,
                                        user_first_message_date[0],  # Use original first seen date
                                    ),
                                )
                                CONN.commit()
                                LOGGER.info(
                                    "Marked first message as join event for %s (date: %s) to prevent duplicate notifications",
                                    message.from_user.id,
                                    user_first_message_date[0],
                                )
                            except sqlite3.Error as db_err:
                                LOGGER.warning(
                                    "Failed to mark first message as join event for %s: %s",
                                    message.from_user.id,
                                    db_err,
                                )
                else:
                    # No records at all - this is their first interaction we've seen
                    # Treat as unknown (new) - safer to check them
                    user_first_seen_unknown = True
                    user_join_chat_date_str = (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),)
                    LOGGER.info(
                        "No records for user %s - first time seen, treating as new",
                        message.from_user.id,
                    )
                    
                    # Save synthetic join event to DB so future messages know when we first saw them
                    try:
                        CURSOR.execute(
                            """
                            INSERT INTO recent_messages
                            (chat_id, message_id, user_id, user_name, user_first_name, user_last_name, received_date, new_chat_member, left_chat_member)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                message.chat.id,
                                int(datetime.now().timestamp()),  # synthetic message_id from timestamp
                                message.from_user.id,
                                message.from_user.username if message.from_user.username else None,
                                message.from_user.first_name if message.from_user.first_name else None,
                                message.from_user.last_name if message.from_user.last_name else None,
                                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                1,  # new_chat_member = 1 (synthetic join)
                                None,  # left_chat_member = NULL
                            ),
                        )
                        CONN.commit()
                        LOGGER.info(
                            "Saved synthetic join event for user %s:%s (first message seen)",
                            message.from_user.id,
                            message.from_user.username or "!NO_USERNAME!",
                        )
                    except sqlite3.Error as db_err:
                        LOGGER.warning(
                            "Failed to save synthetic join event for %s: %s",
                            message.from_user.id,
                            db_err,
                        )
            
            # Extract string from tuple
            user_join_chat_date_str = (
                user_join_chat_date_str[0]
                if user_join_chat_date_str
                else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

            # Convert the string to a datetime object
            # Handle both naive and timezone-aware datetime strings
            try:
                # Try parsing with timezone first (e.g., "2025-12-01 17:29:12+00:00")
                from datetime import timezone
                user_join_chat_date = datetime.fromisoformat(user_join_chat_date_str)
                # Ensure timezone-aware for comparison with message.date (which is UTC)
                if user_join_chat_date.tzinfo is None:
                    user_join_chat_date = user_join_chat_date.replace(tzinfo=timezone.utc)
            except ValueError:
                # Fallback to naive datetime format - make it UTC
                from datetime import timezone
                user_join_chat_date = datetime.strptime(
                    user_join_chat_date_str, "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)

            # flag true if user joined the chat more than 1 week ago
            # BUT: if user_first_seen_unknown, treat as NOT old (do checks)
            user_is_old = (
                not user_first_seen_unknown
                and (message.date - user_join_chat_date).total_seconds() > 604805
            )
            # user_is_between_3hours_and_1week_old = (
            #     10805  # 3 hours in seconds
            #     <= (message.date - user_join_chat_date).total_seconds()
            #     < 604805  # 3 hours in seconds and 1 week in seconds
            # )
            # user_is_1day_old = (
            #     message.date - user_join_chat_date
            # ).total_seconds() < 86400  # 1 days and 5 seconds
            user_is_1hr_old = (
                message.date - user_join_chat_date
            ).total_seconds() < 3600
            user_is_10sec_old = (
                message.date - user_join_chat_date
            ).total_seconds() < 10

            # check if user flagged legit by setting
            # new_chat_member and left_chat_member in the DB to 1
            # to indicate that checks were cancelled
            user_flagged_legit = check_user_legit(CURSOR, message.from_user.id)

            # check if the message is a spam by checking the entities
            entity_spam_trigger = has_spam_entities(SPAM_TRIGGERS, message)

            # initialize the autoreport_sent flag based on whether message was already autoreported
            # (e.g., by missed join detection earlier in the flow)
            autoreport_sent = was_autoreported(message)

            # Skip duplicate processing for media groups (multi-photo messages)
            # Only process the first message in a media group for ALL spam checks
            if was_media_group_processed(message):
                LOGGER.debug(
                    "%s:@%s skipping duplicate media group message (group_id: %s) - early check",
                    message.from_user.id,
                    message.from_user.username or "!UNDEFINED!",
                    message.media_group_id,
                )
                return

            # Check if user is in the banned list (latency edge case)
            # Note: User may have been banned but message was already in flight
            if message.from_user.id in banned_users_dict:
                the_reason = f"{message.from_user.id}:@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} is banned before sending a message, but squizzed due to latency..."
                latency_message_link = construct_message_link(
                    [
                        message.chat.id,
                        message.message_id,
                        message.chat.username,
                    ]
                )
                LOGGER.info(
                    "%s:@%s latency message link: %s",
                    message.from_user.id,
                    (
                        message.from_user.username
                        if message.from_user.username
                        else "!UNDEFINED!"
                    ),
                    latency_message_link,
                )
                if await check_n_ban(message, the_reason):
                    return
                else:
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            # Check if the message is forwarded and ensure forward_from is not None
            # In aiogram 3.x, use forward_origin instead of is_forward()
            if (
                message.forward_origin is not None
                and message.forward_from
                and message.forward_from.id != message.from_user.id
            ):
                # this is possibly a spam
                the_reason = f"{message.from_user.id}:@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} forwarded message from unknown channel or user"
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "\033[93m%s:@%s possibly forwarded a spam from unknown channel or user in chat %s\033[0m",
                        message.from_user.id,
                        (
                            message.from_user.username
                            if message.from_user.username
                            else "!UNDEFINED!"
                        ),
                        message.chat.title,
                    )
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            elif has_custom_emoji_spam(
                message
            ):  # check if the message contains spammy custom emojis
                the_reason = (
                    f"{message.from_user.id} message contains 5 or more spammy custom emojis"
                )
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "\033[93m%s possibly sent a spam with 5+ spammy custom emojis in chat %s\033[0m",
                        message.from_user.id,
                        message.chat.title,
                    )
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            elif check_message_for_sentences(message, PREDETERMINED_SENTENCES, LOGGER):
                the_reason = f"{message.from_user.id} message contains spammy sentences"
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "\033[93m%s possibly sent a spam with spammy sentences in chat %s\033[0m",
                        message.from_user.id,
                        message.chat.title,
                    )
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            elif check_message_for_capital_letters(
                message
            ) and check_message_for_emojis(message):
                the_reason = f"{message.from_user.id} message contains 5+ spammy capital letters and 5+ spammy regular emojis"
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "\033[93m%s possibly sent a spam with 5+ spammy capital letters and 5+ spammy regular emojis in chat %s\033[0m",
                        message.from_user.id,
                        message.chat.title,
                    )
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            # check if the message is sent less then 10 seconds after joining the chat
            elif user_is_10sec_old:
                # this is possibly a bot
                the_reason = f"{message.from_user.id} message is sent less then 10 seconds after joining the chat"
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "%s is possibly a bot typing histerically...",
                        message.from_user.id,
                    )
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            # check if the message is sent less then 1 hour after joining the chat
            elif user_is_1hr_old and entity_spam_trigger:
                # this is possibly a spam
                the_reason = (
                    f"(<code>{message.from_user.id}</code>) sent message less then 1 hour after joining the chat and have "
                    + entity_spam_trigger
                    + " inside"
                )
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "%s possibly sent a spam with (%s) links or other entities in less than 1 hour after joining the chat",
                        message.from_user.id,
                        entity_spam_trigger,
                    )
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            elif message.via_bot:
                # check if the message is sent via inline bot comand
                the_reason = f"{message.from_user.id} message sent via inline bot"
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "%s possibly sent a spam via inline bot", message.from_user.id
                    )
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            elif message_sent_during_night(message):  # disabled for now only logging
                # await BOT.set_message_reaction(message, "🌙")
                # NOTE switch to aiogram 3.13.1 or higher
                the_reason = f"{message.from_user.id} message {message.message_id} in chat {message.chat.title} sent during the night"
                if await check_n_ban(message, the_reason):
                    return
                elif message.from_user.id not in active_user_checks_dict:
                    active_user_checks_dict[message.from_user.id] = {
                        "username": (
                            message.from_user.username
                            if message.from_user.username
                            else "!UNDEFINED!"
                        )
                    }

                    # Store the message link in the active_user_checks_dict
                    message_key = f"{message.chat.id}_{message.message_id}"
                    active_user_checks_dict[message.from_user.id][message_key] = message_link

                    # start the perform_checks coroutine
                    # Note: need to delete the message if user is spammer
                    message_to_delete = message.chat.id, message.message_id
                    # Note: -100 prefix is required for supergroup API calls
                    LOGGER.info(
                        "%s:@%s Nightwatch Message to delete: %s",
                        message.from_user.id,
                        (
                            message.from_user.username
                            if message.from_user.username
                            else "!UNDEFINED!"
                        ),
                        message_to_delete,
                    )
                    asyncio.create_task(
                        perform_checks(
                            message_to_delete=message_to_delete,
                            event_record=f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: {message.from_user.id:<10} night message in {'@' + message.chat.username + ': ' if message.chat.username else ''}{message.chat.title:<30}",
                            user_id=message.from_user.id,
                            inout_logmessage=f"{message.from_user.id} message sent during the night, in {message.chat.title}, checking user activity...",
                            user_name=(
                                message.from_user.username
                                if message.from_user.username
                                else "!UNDEFINED!"
                            ),
                        ),
                        name=str(message.from_user.id),
                    )
                # if not autoreport_sent:
                #         autoreport_sent = True
                #         await submit_autoreport(message, the_reason)
            # elif check_message_for_capital_letters(message):
            #     the_reason = "Message contains 5+ spammy capital letters"
            #     await take_heuristic_action(message, the_reason)

            # elif check_message_for_emojis(message):
            #     the_reason = "Message contains 5+ spammy regular emojis"
            #     await take_heuristic_action(message, the_reason)

            # CHECK FOR BOT MENTIONS BY USERS IN ACTIVE MONITORING
            # This must run BEFORE "SUSPICIOUS MESSAGE CHECKING" to prioritize AUTOREPORT
            if not autoreport_sent and message.from_user.id in active_user_checks_dict:
                _bot_mentions = []
                # Check message text for bot mentions
                if message.entities and message.text:
                    for entity in message.entities:
                        entity_type = entity.type if hasattr(entity, 'type') else entity.get("type")
                        if entity_type == "mention":
                            offset = entity.offset if hasattr(entity, 'offset') else entity.get("offset", 0)
                            length = entity.length if hasattr(entity, 'length') else entity.get("length", 0)
                            mention = message.text[offset:offset + length].lower()
                            if mention.endswith("bot"):
                                _bot_mentions.append(mention)
                # Check caption for bot mentions
                if message.caption_entities and message.caption:
                    for entity in message.caption_entities:
                        entity_type = entity.type if hasattr(entity, 'type') else entity.get("type")
                        if entity_type == "mention":
                            offset = entity.offset if hasattr(entity, 'offset') else entity.get("offset", 0)
                            length = entity.length if hasattr(entity, 'length') else entity.get("length", 0)
                            mention = message.caption[offset:offset + length].lower()
                            if mention.endswith("bot"):
                                _bot_mentions.append(mention)
                
                if _bot_mentions:
                    bot_mentions_str = ", ".join(_bot_mentions)
                    LOGGER.info(
                        "User %s:@%s (in active checks) mentioned bots (%s) - sending to AUTOREPORT and deleting",
                        message.from_user.id,
                        message.from_user.username or "!UNDEFINED!",
                        bot_mentions_str,
                    )
                    await submit_autoreport(message, f"Bot mention by monitored user: {bot_mentions_str}")
                    
                    # Delete the message and store deletion reason in database
                    try:
                        await message.delete()
                        # Store deletion reason in database
                        received_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if message.chat.id < 0:
                            report_id = int(str(message.chat.id)[4:] + str(message.message_id))
                        else:
                            report_id = int(str(message.chat.id) + str(message.message_id))
                        CURSOR.execute(
                            """
                            INSERT OR REPLACE INTO recent_messages 
                            (chat_id, message_id, user_id, user_name, user_first_name, user_last_name, 
                             received_date, from_chat_title, deletion_reason)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                message.chat.id,
                                report_id,
                                message.from_user.id,
                                message.from_user.username,
                                message.from_user.first_name,
                                message.from_user.last_name,
                                received_date,
                                message.chat.title,
                                f"bot_mention: {bot_mentions_str}",
                            ),
                        )
                        CONN.commit()
                        LOGGER.info(
                            "Deleted message %s from chat %s - mentioned bots: %s (reason stored in DB)",
                            message.message_id,
                            message.chat.id,
                            bot_mentions_str,
                        )
                    except TelegramBadRequest as del_err:
                        LOGGER.warning(
                            "Failed to delete message %s with bot mentions: %s",
                            message.message_id,
                            del_err,
                        )
                    return  # Don't process further - already sent to autoreport

            # FINALLY:
            ### SUSPICIOUS MESSAGE CHECKING ###
            # Skip if we already sent a missed join notification for this message
            if (
                not autoreport_sent
                and not missed_join_notification_sent
                and (
                    message.from_user.id in active_user_checks_dict
                    or not (user_is_old or user_flagged_legit)
                )
            ):
                # Ensure active_user_checks_dict[message.from_user.id] is a dictionary
                if not isinstance(
                    active_user_checks_dict.get(message.from_user.id), dict
                ):
                    # Initialize with the username if it exists, otherwise with "!UNDEFINED!"
                    active_user_checks_dict[message.from_user.id] = {
                        "username": (
                            message.from_user.username
                            if message.from_user.username
                            else "!UNDEFINED!"
                        )
                    }

                # Store the message link in the active_user_checks_dict
                message_key = f"{message.chat.id}_{message.message_id}"
                active_user_checks_dict[message.from_user.id][
                    message_key
                ] = message_link
                
                # START INTENSIVE WATCHDOG: User from active_checks posted a message!
                # This triggers aggressive spam checking (every 10s for 1min, then every 30s for 4min)
                # to catch spammers as soon as they get reported by external APIs
                if message.from_user.id in active_user_checks_dict:
                    asyncio.create_task(
                        start_intensive_watchdog(
                            user_id=message.from_user.id,
                            user_name=(
                                message.from_user.username
                                if message.from_user.username
                                else "!UNDEFINED!"
                            ),
                            message_chat_id=message.chat.id,
                            message_id=message.message_id,
                        )
                    )
                
                time_passed = message.date - user_join_chat_date
                human_readable_time = str(time_passed)
                if message.chat.username:
                    message_link = construct_message_link(
                        [message.chat.id, message.message_id, message.chat.username]
                    )
                if not user_flagged_legit:
                    if message_sent_during_night(message):
                        LOGGER.warning(
                            "\033[47m\033[34m%s:@%s sent a message during the night, check the message %s in the chat %s (%s).\033[0m\n\t\t\tSuspicious message link: %s",
                            message.from_user.id,
                            (
                                message.from_user.username
                                if message.from_user.username
                                else "!UNDEFINED!"
                            ),
                            message.message_id,
                            message.chat.title,
                            message.chat.id,
                            message_link,
                        )
                    else:
                        LOGGER.warning(
                            "\033[47m\033[34m%s:@%s is in active_user_checks_dict, check the message %s in the chat %s (%s).\033[0m\n\t\t\tSuspicious message link: %s",
                            message.from_user.id,
                            (
                                message.from_user.username
                                if message.from_user.username
                                else "!UNDEFINED!"
                            ),
                            message.message_id,
                            message.chat.title,
                            message.chat.id,
                            message_link,
                        )
                        LOGGER.info(
                            "\033[47m\033[34m%s:@%s sent message and joined the chat %s %s ago\033[0m\n\t\t\tMessage link: %s",
                            message.from_user.id,
                            (
                                message.from_user.username
                                if message.from_user.username
                                else "!UNDEFINED!"
                            ),
                            message.chat.title,
                            human_readable_time,
                            message_link,
                        )
                    the_reason = f"\033[91m{message.from_user.id}:@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} identified as a spammer when sending a message during the first WEEK after registration. Telefragged in {human_readable_time}...\033[0m"
                    if await check_n_ban(message, the_reason):

                        # At the point where you want to print the traceback
                        # snapshot = tracemalloc.take_snapshot()
                        # top_stats = snapshot.statistics('lineno')

                        # print("[ Top 10 ]")
                        # for stat in top_stats[:10]:
                        #     print(stat)

                        return
                    else:
                        # If lols check False - mark as suspicious and send to admin group
                        # Skip if message was already sent to autoreport thread
                        if was_autoreported(message):
                            LOGGER.debug(
                                "%s:@%s skipping suspicious notification - already autoreported",
                                message.from_user.id,
                                message.from_user.username or "!UNDEFINED!",
                            )
                            return
                        await message.forward(
                            ADMIN_GROUP_ID,
                            ADMIN_SUSPICIOUS,
                            disable_notification=True,
                        )
                        # Build clickable chat link (public @username or internal /c/ link) with safe fallback
                        _chat_title_safe = html.escape(message.chat.title)
                        _chat_link_html = build_chat_link(message.chat.id, message.chat.username, message.chat.title)

                        await safe_send_message(
                            BOT,
                            ADMIN_GROUP_ID,
                            f"WARNING! User @{message.from_user.username if message.from_user.username else 'UNDEFINED'} (<code>{message.from_user.id}</code>) sent a SUSPICIOUS message in {_chat_link_html} after {human_readable_time}.\n🔗 <a href='{message_link}'>Original message</a>\nPlease check it out!",
                            LOGGER,
                            message_thread_id=ADMIN_SUSPICIOUS,
                            reply_markup=inline_kb.as_markup(),
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                        return
                else:
                    return

            # Check if message contains suspicious content: links, mentions, or phone numbers
            has_suspicious_content = False
            suspicious_items = {
                "links": [],
                "mentions": [],
                "bot_mentions": [],  # Mentions of other bots (@somebot)
                "phones": [],
                "hashtags": [],
                "cashtags": [],
                "bot_commands": [],
                "emails": [],
                "high_user_id": False,
            }

            # Check for high user ID (accounts created recently have IDs > 8.2 billion)
            if message.from_user.id > HIGH_USER_ID_THRESHOLD:
                has_suspicious_content = True
                suspicious_items["high_user_id"] = True

            # Helper function to extract text from entity
            def extract_entity_text(text, entity):
                """Extract text from message entity."""
                offset = entity.get("offset", 0) if isinstance(entity, dict) else getattr(entity, "offset", 0)
                length = entity.get("length", 0) if isinstance(entity, dict) else getattr(entity, "length", 0)
                if text and offset is not None and length:
                    # Handle UTF-16 encoding (Telegram uses UTF-16 for offsets)
                    return text.encode("utf-16-le")[
                        offset * 2 : (offset + length) * 2
                    ].decode("utf-16-le")
                return None

            # Helper function to show invisible characters as unicode codepoints
            def make_visible(text, max_len=100):
                """Make invisible/special characters visible as unicode codepoints."""
                if not text:
                    return ""
                # Truncate if too long
                if len(text) > max_len:
                    text = text[:max_len] + "..."
                # Replace invisible/control characters with their unicode representation
                result = []
                for char in text:
                    # Check if character is invisible, whitespace, or control character
                    if char in [
                        "\u200b",
                        "\u200c",
                        "\u200d",
                        "\ufeff",
                        "\u00a0",
                        "\u2060",
                        "\u180e",
                    ]:
                        # Zero-width or invisible spaces
                        result.append(f"[U+{ord(char):04X}]")
                    elif ord(char) < 32 or (ord(char) >= 127 and ord(char) < 160):
                        # Control characters
                        result.append(f"[U+{ord(char):04X}]")
                    elif char == "\n":
                        result.append("\\n")
                    elif char == "\t":
                        result.append("\\t")
                    else:
                        result.append(char)
                return "".join(result)

            # Check message entities for links, mentions, phone numbers
            if message.entities and message.text:
                for entity in message.entities:
                    entity_type = entity.get("type") if isinstance(entity, dict) else getattr(entity, "type", None)
                    if entity_type in ["url", "text_link"]:
                        has_suspicious_content = True
                        # Extract URL from text_link or visible url
                        if entity_type == "text_link":
                            url = entity.get("url", "") if isinstance(entity, dict) else getattr(entity, "url", "")
                            visible_text = extract_entity_text(message.text, entity)
                            visible_clean = make_visible(visible_text, max_len=50)
                            suspicious_items["links"].append(
                                f"{url} (hidden as: {visible_clean})"
                            )
                        else:
                            url = extract_entity_text(message.text, entity)
                            if url:
                                suspicious_items["links"].append(url)
                    elif entity_type == "mention":
                        has_suspicious_content = True
                        mention = extract_entity_text(message.text, entity)
                        if mention:
                            suspicious_items["mentions"].append(mention)
                            # Check if this is a bot mention (ends with "bot", case insensitive)
                            if mention.lower().endswith("bot"):
                                suspicious_items["bot_mentions"].append(mention)
                    elif entity_type == "text_mention":
                        # Direct mention of user by ID (users without username)
                        has_suspicious_content = True
                        user = entity.get("user") if isinstance(entity, dict) else getattr(entity, "user", None)
                        if user:
                            user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
                            user_name = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
                            first_name = user.get("first_name", "") if isinstance(user, dict) else getattr(user, "first_name", "")
                            if user_name:
                                suspicious_items["mentions"].append(f"@{user_name}")
                            else:
                                # User has no username, show ID and first name
                                suspicious_items["mentions"].append(
                                    f"ID:{user_id} ({first_name})"
                                )
                    elif entity_type == "phone_number":
                        has_suspicious_content = True
                        phone = extract_entity_text(message.text, entity)
                        if phone:
                            suspicious_items["phones"].append(phone)
                    elif entity_type == "hashtag":
                        has_suspicious_content = True
                        hashtag = extract_entity_text(message.text, entity)
                        if hashtag:
                            suspicious_items["hashtags"].append(hashtag)
                    elif entity_type == "cashtag":
                        has_suspicious_content = True
                        cashtag = extract_entity_text(message.text, entity)
                        if cashtag:
                            suspicious_items["cashtags"].append(cashtag)
                    elif entity_type == "bot_command":
                        has_suspicious_content = True
                        bot_cmd = extract_entity_text(message.text, entity)
                        if bot_cmd:
                            suspicious_items["bot_commands"].append(bot_cmd)
                    elif entity_type == "email":
                        has_suspicious_content = True
                        email = extract_entity_text(message.text, entity)
                        if email:
                            suspicious_items["emails"].append(email)

            # Check caption entities for media messages
            if message.caption_entities and message.caption:
                for entity in message.caption_entities:
                    entity_type = entity.get("type") if isinstance(entity, dict) else getattr(entity, "type", None)
                    if entity_type in ["url", "text_link"]:
                        has_suspicious_content = True
                        # Extract URL from text_link or visible url
                        if entity_type == "text_link":
                            url = entity.get("url", "") if isinstance(entity, dict) else getattr(entity, "url", "")
                            visible_text = extract_entity_text(message.caption, entity)
                            visible_clean = make_visible(visible_text, max_len=50)
                            suspicious_items["links"].append(
                                f"{url} (hidden as: {visible_clean})"
                            )
                        else:
                            url = extract_entity_text(message.caption, entity)
                            if url:
                                suspicious_items["links"].append(url)
                    elif entity_type == "mention":
                        has_suspicious_content = True
                        mention = extract_entity_text(message.caption, entity)
                        if mention:
                            suspicious_items["mentions"].append(mention)
                    elif entity_type == "text_mention":
                        # Direct mention of user by ID (users without username)
                        has_suspicious_content = True
                        user = entity.get("user") if isinstance(entity, dict) else getattr(entity, "user", None)
                        if user:
                            user_id = user.get("id") if isinstance(user, dict) else getattr(user, "id", None)
                            user_name = user.get("username") if isinstance(user, dict) else getattr(user, "username", None)
                            first_name = user.get("first_name", "") if isinstance(user, dict) else getattr(user, "first_name", "")
                            if user_name:
                                suspicious_items["mentions"].append(f"@{user_name}")
                            else:
                                # User has no username, show ID and first name
                                suspicious_items["mentions"].append(
                                    f"ID:{user_id} ({first_name})"
                                )
                    elif entity_type == "phone_number":
                        has_suspicious_content = True
                        phone = extract_entity_text(message.caption, entity)
                        if phone:
                            suspicious_items["phones"].append(phone)
                    elif entity_type == "hashtag":
                        has_suspicious_content = True
                        hashtag = extract_entity_text(message.caption, entity)
                        if hashtag:
                            suspicious_items["hashtags"].append(hashtag)
                    elif entity_type == "cashtag":
                        has_suspicious_content = True
                        cashtag = extract_entity_text(message.caption, entity)
                        if cashtag:
                            suspicious_items["cashtags"].append(cashtag)
                    elif entity_type == "bot_command":
                        has_suspicious_content = True
                        bot_cmd = extract_entity_text(message.caption, entity)
                        if bot_cmd:
                            suspicious_items["bot_commands"].append(bot_cmd)
                    elif entity_type == "email":
                        has_suspicious_content = True
                        email = extract_entity_text(message.caption, entity)
                        if email:
                            suspicious_items["emails"].append(email)

            # Additional regex-based phone number detection for local numbers
            # Detect Mauritius numbers: +230, 00230, or plain 230 followed by digits
            phone_patterns = [
                r"\+230\s*\d{6,8}",  # +230 followed by 6-8 digits
                r"00230\s*\d{6,8}",  # 00230 followed by 6-8 digits
                r"(?<!\d)230\s*\d{6,8}",  # 230 followed by 6-8 digits (not preceded by digit)
                r"\+\d{10,15}",  # International format +XXXXXXXXXXX
                r"(?<!\d)\d{3}[-\s]?\d{3}[-\s]?\d{4}(?!\d)",  # Format: 123-456-7890 or 123 456 7890
            ]

            # Check message text
            if message.text:
                for pattern in phone_patterns:
                    matches = re.findall(pattern, message.text)
                    for match in matches:
                        # Clean up the matched phone number
                        cleaned_phone = match.strip()
                        # Avoid duplicates
                        if cleaned_phone not in suspicious_items["phones"]:
                            has_suspicious_content = True
                            suspicious_items["phones"].append(cleaned_phone)

            # Check caption text
            if message.caption:
                for pattern in phone_patterns:
                    matches = re.findall(pattern, message.caption)
                    for match in matches:
                        # Clean up the matched phone number
                        cleaned_phone = match.strip()
                        # Avoid duplicates
                        if cleaned_phone not in suspicious_items["phones"]:
                            has_suspicious_content = True
                            suspicious_items["phones"].append(cleaned_phone)

            # Log bot mentions for users NOT in active monitoring
            # (Users in active_checks with bot mentions are handled earlier and sent to AUTOREPORT)
            if suspicious_items["bot_mentions"] and not was_autoreported(message):
                bot_mentions_str = ", ".join(suspicious_items["bot_mentions"])
                # User is NOT in active monitoring - will be handled by suspicious content flow below
                LOGGER.info(
                    "User %s:@%s (not in active checks) mentioned bots (%s) - will send to SUSPICIOUS (no deletion)",
                    message.from_user.id,
                    message.from_user.username or "!UNDEFINED!",
                    bot_mentions_str,
                )
                # bot_mentions are already in suspicious_items, will be shown in the report

            # If suspicious content detected, forward to ADMIN_SUSPICIOUS thread
            # Skip if message was already sent to autoreport or suspicious thread
            if has_suspicious_content and not was_autoreported(message) and not was_suspicious_reported(message):
                try:
                    # Forward the message to suspicious thread
                    await message.forward(
                        ADMIN_GROUP_ID,
                        ADMIN_SUSPICIOUS,
                        disable_notification=True,
                    )

                    # Build clickable chat link
                    _chat_title_safe = html.escape(message.chat.title)
                    _chat_link_html = build_chat_link(message.chat.id, message.chat.username, message.chat.title)

                    # Get lols link and create keyboard
                    lols_link = f"https://t.me/oLolsBot?start={message.from_user.id}"
                    inline_kb = create_inline_keyboard(message_link, lols_link, message)

                    # Add check buttons for each mentioned username (up to 5 to avoid button overflow)
                    if suspicious_items["mentions"]:
                        max_mention_buttons = 5
                        for mention in suspicious_items["mentions"][
                            :max_mention_buttons
                        ]:
                            # Check if it's a username mention or ID mention
                            if mention.startswith("@"):
                                # Username mention - use u- prefix
                                username_clean = mention.lstrip("@")
                                mention_lols_link = (
                                    f"https://t.me/oLolsBot?start=u-{username_clean}"
                                )
                                button_text = f"🔍 Check {mention}"
                            elif mention.startswith("ID:"):
                                # ID mention format: "ID:12345 (FirstName)"
                                # Extract user ID
                                user_id = (
                                    mention.split("(")[0].replace("ID:", "").strip()
                                )
                                mention_lols_link = (
                                    f"https://t.me/oLolsBot?start={user_id}"
                                )
                                # Shorten display name if too long
                                display_name = (
                                    mention
                                    if len(mention) <= 25
                                    else mention[:22] + "..."
                                )
                                button_text = f"🔍 Check {display_name}"
                            else:
                                # Fallback - treat as username
                                username_clean = mention.lstrip("@")
                                mention_lols_link = (
                                    f"https://t.me/oLolsBot?start=u-{username_clean}"
                                )
                                button_text = f"🔍 Check {mention}"

                            inline_kb.add(
                                InlineKeyboardButton(
                                    text=button_text,
                                    url=mention_lols_link,
                                )
                            )

                    # Build detailed content list with length limiting
                    content_details = []
                    max_items_per_type = 10  # Limit items to prevent message overflow

                    if suspicious_items["links"]:
                        links_count = len(suspicious_items["links"])
                        content_details.append(f"<b>🔗 Links ({links_count}):</b>")
                        for _i, link in enumerate(
                            suspicious_items["links"][:max_items_per_type]
                        ):
                            # Truncate very long URLs
                            link_display = (
                                link if len(link) <= 200 else link[:200] + "..."
                            )
                            content_details.append(
                                f"  • <code>{html.escape(link_display)}</code>"
                            )
                        if links_count > max_items_per_type:
                            content_details.append(
                                f"  ... and {links_count - max_items_per_type} more"
                            )

                    if suspicious_items["mentions"]:
                        mentions_count = len(suspicious_items["mentions"])
                        content_details.append(
                            f"<b>👤 Mentions ({mentions_count}):</b>"
                        )
                        for _i, mention in enumerate(
                            suspicious_items["mentions"][:max_items_per_type]
                        ):
                            content_details.append(
                                f"  • <code>{html.escape(mention)}</code>"
                            )
                        if mentions_count > max_items_per_type:
                            content_details.append(
                                f"  ... and {mentions_count - max_items_per_type} more"
                            )

                    if suspicious_items["bot_mentions"]:
                        # Bot mentions from non-monitored users (not deleted, just reported)
                        bot_mentions_count = len(suspicious_items["bot_mentions"])
                        content_details.append(
                            f"<b>🤖 Bot Mentions ({bot_mentions_count}):</b>"
                        )
                        for bot_mention in suspicious_items["bot_mentions"][:max_items_per_type]:
                            content_details.append(
                                f"  • <code>{html.escape(bot_mention)}</code>"
                            )
                        if bot_mentions_count > max_items_per_type:
                            content_details.append(
                                f"  ... and {bot_mentions_count - max_items_per_type} more"
                            )

                    if suspicious_items["phones"]:
                        phones_count = len(suspicious_items["phones"])
                        content_details.append(
                            f"<b>📞 Phone Numbers ({phones_count}):</b>"
                        )
                        for _i, phone in enumerate(
                            suspicious_items["phones"][:max_items_per_type]
                        ):
                            content_details.append(
                                f"  • <code>{html.escape(phone)}</code>"
                            )
                        if phones_count > max_items_per_type:
                            content_details.append(
                                f"  ... and {phones_count - max_items_per_type} more"
                            )

                    if suspicious_items["hashtags"]:
                        hashtags_count = len(suspicious_items["hashtags"])
                        content_details.append(f"<b>#️⃣ Hashtags ({hashtags_count}):</b>")
                        for _i, hashtag in enumerate(
                            suspicious_items["hashtags"][:max_items_per_type]
                        ):
                            content_details.append(
                                f"  • <code>{html.escape(hashtag)}</code>"
                            )
                        if hashtags_count > max_items_per_type:
                            content_details.append(
                                f"  ... and {hashtags_count - max_items_per_type} more"
                            )

                    if suspicious_items["cashtags"]:
                        cashtags_count = len(suspicious_items["cashtags"])
                        content_details.append(
                            f"<b>💰 Cashtags ({cashtags_count}):</b>"
                        )
                        for _i, cashtag in enumerate(
                            suspicious_items["cashtags"][:max_items_per_type]
                        ):
                            content_details.append(
                                f"  • <code>{html.escape(cashtag)}</code>"
                            )
                        if cashtags_count > max_items_per_type:
                            content_details.append(
                                f"  ... and {cashtags_count - max_items_per_type} more"
                            )

                    if suspicious_items["bot_commands"]:
                        bot_commands_count = len(suspicious_items["bot_commands"])
                        content_details.append(
                            f"<b>🤖 Bot Commands ({bot_commands_count}):</b>"
                        )
                        for _i, bot_cmd in enumerate(
                            suspicious_items["bot_commands"][:max_items_per_type]
                        ):
                            content_details.append(
                                f"  • <code>{html.escape(bot_cmd)}</code>"
                            )
                        if bot_commands_count > max_items_per_type:
                            content_details.append(
                                f"  ... and {bot_commands_count - max_items_per_type} more"
                            )

                    if suspicious_items["emails"]:
                        emails_count = len(suspicious_items["emails"])
                        content_details.append(f"<b>📧 Emails ({emails_count}):</b>")
                        for _i, email in enumerate(
                            suspicious_items["emails"][:max_items_per_type]
                        ):
                            content_details.append(
                                f"  • <code>{html.escape(email)}</code>"
                            )
                        if emails_count > max_items_per_type:
                            content_details.append(
                                f"  ... and {emails_count - max_items_per_type} more"
                            )

                    if suspicious_items["high_user_id"]:
                        content_details.insert(0, "<b>🆕 Very New Account (ID &gt; 8.2B)</b>")

                    content_report = "\n".join(content_details)

                    # Build the full message
                    full_message = (
                        f"⚠️ <b>Suspicious Content Detected</b>\n"
                        f"From: @{message.from_user.username if message.from_user.username else 'UNDEFINED'} "
                        f"(<code>{message.from_user.id}</code>)\n"
                        f"Chat: {_chat_link_html}\n"
                        f"🔗 <a href='{message_link}'>Original message</a>\n\n"
                        f"{content_report}"
                    )

                    # Check if message exceeds Telegram's limit (4096 chars)
                    if len(full_message) > 4000:  # Leave some margin
                        # Truncate the content report
                        available_space = 4000 - len(full_message) + len(content_report)
                        content_report = (
                            content_report[:available_space]
                            + "\n\n... (message truncated)"
                        )
                        full_message = (
                            f"⚠️ <b>Suspicious Content Detected</b>\n"
                            f"From: @{message.from_user.username if message.from_user.username else 'UNDEFINED'} "
                            f"(<code>{message.from_user.id}</code>)\n"
                            f"Chat: {_chat_link_html}\n"
                            f"🔗 <a href='{message_link}'>Original message</a>\n\n"
                            f"{content_report}"
                        )

                    await safe_send_message(
                        BOT,
                        ADMIN_GROUP_ID,
                        full_message,
                        LOGGER,
                        message_thread_id=ADMIN_SUSPICIOUS,
                        reply_markup=inline_kb.as_markup(),
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    
                    # Start monitoring for users reported to SUSPICIOUS thread
                    # This activates watchdog and intensive checks (can be cancelled by legitimization button)
                    _user_id = message.from_user.id
                    _username = message.from_user.username
                    
                    # Only start monitoring if user is not already being monitored
                    if _user_id not in active_user_checks_dict:
                        LOGGER.info(
                            "%s:%s Starting monitoring due to suspicious content report",
                            _user_id,
                            format_username_for_log(_username),
                        )
                        
                        # Get profile photo count for baseline
                        try:
                            _photos = await BOT.get_user_profile_photos(_user_id, limit=1)
                            _photo_count = _photos.total_count if _photos else 0
                        except TelegramBadRequest:
                            _photo_count = 0
                        
                        # Save baseline to database
                        save_user_baseline(
                            conn=CONN,
                            user_id=_user_id,
                            username=_username,
                            first_name=message.from_user.first_name or "",
                            last_name=message.from_user.last_name or "",
                            photo_count=_photo_count,
                            join_chat_id=message.chat.id,
                            join_chat_username=getattr(message.chat, "username", None),
                            join_chat_title=getattr(message.chat, "title", "") or "",
                        )
                        
                        # Add to active checks dict
                        active_user_checks_dict[_user_id] = {
                            "username": _username,
                            "baseline": {
                                "first_name": message.from_user.first_name or "",
                                "last_name": message.from_user.last_name or "",
                                "username": _username or "",
                                "photo_count": _photo_count,
                                "joined_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "chat": {
                                    "id": message.chat.id,
                                    "username": getattr(message.chat, "username", None),
                                    "title": getattr(message.chat, "title", "") or "",
                                },
                            },
                        }
                        
                        # Start regular watchdog (24h monitoring)
                        asyncio.create_task(
                            perform_checks(
                                event_record=f"SUSPICIOUS:{_user_id}:{_username}",
                                user_id=_user_id,
                                inout_logmessage=f"Suspicious content triggered monitoring for {_user_id}:@{_username or '!UNDEFINED!'}",
                                user_name=_username or "!UNDEFINED!",
                            ),
                            name=str(_user_id),
                        )
                        
                        # Start intensive watchdog (first few hours)
                        await start_intensive_watchdog(
                            user_id=_user_id,
                            user_name=_username or "!UNDEFINED!",
                            message_chat_id=message.chat.id,
                            message_id=message.message_id,
                        )
                    else:
                        LOGGER.debug(
                            "%s:%s Already in active checks, suspicious report sent but not starting new monitoring",
                            _user_id,
                            format_username_for_log(_username),
                        )
                        
                except (TelegramBadRequest, TelegramForbiddenError) as e:
                    LOGGER.error("Error forwarding suspicious content message: %s", e)

        # If other user/admin or bot deletes message earlier than this bot we got an error
        except TelegramBadRequest as e:
            LOGGER.error(
                "Error storing/deleting recent %s message, %s - someone deleted it already?",
                message.message_id,
                e,
            )

    @DP.message(Command("ban"), F.chat.id == ADMIN_GROUP_ID)
    # NOTE: Manual typing command ban - useful if ban were postponed
    async def ban(message: Message):
        """Function to ban the user and delete all known to bot messages using '/ban reportID' text command."""
        try:
            # logger.debug("ban triggered.")

            command_args = message.text.split()
            LOGGER.debug("Command arguments received: %s", command_args)

            if len(command_args) < 2:
                raise ValueError("Please provide the message ID of the report.")

            report_msg_id = int(command_args[1])
            LOGGER.debug("Report message ID parsed: %d", report_msg_id)

            CURSOR.execute(
                "SELECT chat_id, message_id, forwarded_message_data, received_date FROM recent_messages WHERE message_id = ?",
                (report_msg_id,),
            )
            result = CURSOR.fetchone()
            LOGGER.debug(
                "Database query result for forwarded_message_data %d: %s",
                report_msg_id,
                result,
            )
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                f"Database query result for forwarded_message_data {report_msg_id}: {result}",
                LOGGER,
            )

            if not result:
                await message.reply("Error: Report not found in database.")
                return

            (
                original_chat_id,
                original_message_id,
                forwarded_message_data,
                original_message_timestamp,
            ) = result
            LOGGER.debug(
                "\033[93mOriginal chat ID: %s, Original message ID: %s,\n\t\t\tForwarded message data: %s,\n\t\t\tOriginal message timestamp: %s\033[0m",
                original_chat_id,
                original_message_id,
                forwarded_message_data,
                original_message_timestamp,
            )

            # MODIFIED: Use ast.literal_eval for safety
            author_id = ast.literal_eval(forwarded_message_data)[3]
            LOGGER.debug("%s author ID retrieved for original message", author_id)
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                f"Author ID (<code>{author_id}</code>) retrieved for original message.",
                LOGGER,
                parse_mode="HTML",
            )
            if not author_id:
                await message.reply(
                    "Could not retrieve the author's user ID from the report."
                )
                return

            # remove userid from the active_user_checks_dict
            if author_id in active_user_checks_dict:
                banned_users_dict[author_id] = active_user_checks_dict.pop(
                    author_id, None
                )
                if len(active_user_checks_dict) > 3:
                    active_user_checks_dict_last3_list = list(
                        active_user_checks_dict.items()
                    )[-3:]
                    active_user_checks_dict_last3_str = ", ".join(
                        [
                            f"{uid}: {uname}"
                            for uid, uname in active_user_checks_dict_last3_list
                        ]
                    )
                    LOGGER.info(
                        "\033[91m%s:@%s removed from active_user_checks_dict during ban by admin:\n\t\t\t%s... %d totally\033[0m",
                        author_id,
                        (
                            forwarded_message_data[4]
                            if forwarded_message_data[4] not in [0, "0", None]
                            else "!UNDEFINED!"
                        ),
                        active_user_checks_dict_last3_str,  # Last 3 elements
                        len(active_user_checks_dict),  # Number of elements left
                    )
                else:
                    LOGGER.info(
                        "\033[91m%s:@%s removed from active_user_checks_dict during ban by admin:\n\t\t\t%s\033[0m",
                        author_id,
                        (
                            forwarded_message_data[4]
                            if forwarded_message_data[4] not in [0, "0", None]
                            else "!UNDEFINED!"
                        ),
                        active_user_checks_dict,
                    )
                # stop the perform_checks coroutine if it is running for author_id
                for task in asyncio.all_tasks():
                    if task.get_name() == str(author_id):
                        task.cancel()

            # add to the banned users set
            banned_users_dict[int(author_id)] = (
                forwarded_message_data[4] if forwarded_message_data[4] else "NoUserName"
            )

            # Attempting to ban user from channels
            for chat_id in CHANNEL_IDS:
                # LOGGER.debug(
                #     f"Attempting to ban user {author_id} from chat {channels_dict[chat_id]} ({chat_id})"
                # )

                try:
                    await BOT.ban_chat_member(
                        chat_id=chat_id,
                        user_id=author_id,
                        revoke_messages=True,
                    )
                    LOGGER.debug(
                        "User (<code>%s</code>)> banned and their messages deleted from chat %s (%s).",
                        # user_name,
                        author_id,
                        CHANNEL_DICT[chat_id],
                        chat_id,
                    )
                    await safe_send_message(
                        BOT,
                        TECHNOLOG_GROUP_ID,
                        f"User {author_id} banned and their messages deleted from chat {CHANNEL_DICT[chat_id]} ({chat_id}).",
                        LOGGER,
                    )
                except (TelegramBadRequest, TelegramForbiddenError) as inner_e:
                    LOGGER.error(
                        "Failed to ban and delete messages in chat %s (%s). Error: %s",
                        CHANNEL_DICT[chat_id],
                        chat_id,
                        inner_e,
                    )
                    await safe_send_message(
                        BOT,
                        TECHNOLOG_GROUP_ID,
                        f"Failed to ban and delete messages in chat {CHANNEL_DICT[chat_id]} ({chat_id}). Error: {inner_e}",
                        LOGGER,
                    )
            # select all messages from the user in the chat
            # and this is not records about join or leave
            # and this record have name of the chat
            # NOTE private chats do not have names :(
            query = """
                SELECT chat_id, message_id, user_name
                FROM recent_messages 
                WHERE user_id = :author_id
                AND new_chat_member IS NULL
                AND left_chat_member IS NULL
                AND chat_username IS NOT NULL
                """
            params = {"author_id": author_id}
            result = CURSOR.execute(query, params).fetchall()
            # delete them one by one
            for chat_id, message_id, user_name in result:
                try:
                    await BOT.delete_message(chat_id=chat_id, message_id=message_id)
                    LOGGER.debug(
                        "Message %s deleted from chat %s (%s) for user @%s (%s).",
                        message_id,
                        CHANNEL_DICT[chat_id],
                        chat_id,
                        user_name,
                        author_id,
                    )
                except TelegramBadRequest as inner_e:
                    LOGGER.error(
                        "Failed to delete message %s in chat %s (%s). Error: %s",
                        message_id,
                        CHANNEL_DICT[chat_id],
                        chat_id,
                        inner_e,
                    )
                    await safe_send_message(
                        BOT,
                        TECHNOLOG_GROUP_ID,
                        f"Failed to delete message {message_id} in chat {CHANNEL_DICT[chat_id]} ({chat_id}). Error: {inner_e}",
                        LOGGER,
                    )
            LOGGER.debug(
                "\033[91m%s banned and their messages deleted where applicable.\033[0m",
                author_id,
            )

            lols_url = f"https://t.me/oLolsBot?start={author_id}"
            lols_check_kb = KeyboardBuilder().add(
                InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_url)
            )
            # user_name comes from DB query loop - use a safe default if not defined
            try:
                _ban_user_name = user_name if user_name and str(user_name) not in ["None", "0"] else None
            except NameError:
                _ban_user_name = None
            _display_user = f"@{_ban_user_name}" if _ban_user_name else "!UNDEFINED!"
            await message.reply(
                f"Action taken: User {_display_user} (<code>{author_id}</code>) banned and their messages deleted where applicable.",
                parse_mode="HTML",
                reply_markup=lols_check_kb.as_markup(),
            )

        except (sqlite3.Error, ValueError, TypeError) as e:
            LOGGER.error("Error in ban function: %s", e)
            await message.reply(f"Error: {e}")

        # report spammer to P2P spam checker server
        await report_spam_2p2p(author_id, LOGGER)
        user_name = (
            forwarded_message_data[4]
            if forwarded_message_data[4] not in [0, "0", None, "None"]
            else None
        )
        lols_check_kb = make_lols_kb(author_id)
        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP_ID,
            f"{author_id}:{f'@{user_name}' if user_name else '!UNDEFINED!'} reported to P2P spamcheck server.",
            LOGGER,
            parse_mode="HTML",
            disable_web_page_preview=True,
            message_thread_id=TECHNO_ADMIN,
            reply_markup=lols_check_kb.as_markup(),
        )

    @DP.message(Command("check"), F.chat.id == ADMIN_GROUP_ID)
    async def check_user(message: Message):
        """Function to start lols_cas check coroutine to monitor user for spam."""
        try:
            command_args = message.text.split()
            # LOGGER.debug("Command arguments received: %s", command_args)

            if len(command_args) < 2:
                raise ValueError("Please provide the user ID to check.")

            user_id = int(command_args[1])
            LOGGER.debug(
                "\033[95m%d:@!UNDEFINED! - User ID to check, requested by admin @%s (%s %s)\033[0m",
                user_id,
                (
                    message.from_user.username
                    if message.from_user.username
                    else "!UNDEFINED!"
                ),
                message.from_user.first_name,
                message.from_user.last_name if message.from_user.last_name else "",
            )

            if user_id in active_user_checks_dict:
                _val = active_user_checks_dict.get(user_id)
                _disp = (
                    _val.get("username", "!UNDEFINED!")
                    if isinstance(_val, dict)
                    else (_val or "!UNDEFINED!")
                )
                await message.reply(
                    f"User <code>{_disp}</code> is already being checked.",
                    parse_mode="HTML",
                )
                return
            else:
                active_user_checks_dict[user_id] = "!UNDEFINED!"

            # start the perform_checks coroutine
            asyncio.create_task(
                perform_checks(
                    event_record=f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: {user_id:<10} 👀 manual check requested by admin {message.from_user.id}",
                    user_id=user_id,
                    inout_logmessage=f"{user_id} manual check requested, checking user activity requested by admin {message.from_user.id}...",
                    user_name=active_user_checks_dict[user_id],
                ),
                name=str(user_id),
            )

            await message.reply(
                f"User {user_id} {MONITORING_DURATION_HOURS}hr monitoring activity check started."
            )
        except ValueError as ve:
            await message.reply(str(ve))
        except (TelegramBadRequest, RuntimeError) as e:
            LOGGER.error("Error in check_user: %s", e)
            await message.reply("An error occurred while trying to check the user.")

    @DP.message(Command("whois"), F.chat.id == ADMIN_GROUP_ID)
    async def whois_user(message: Message):
        """Lookup comprehensive user data from database.
        
        Available in:
        - ADMIN_GROUP orders thread (ADMIN_ORDERS)
        - Direct messages with superadmin (ADMIN_USER_ID)
        
        Usage:
            /whois 123456789  - lookup by user ID
            /whois @username  - lookup by username
        """
        try:
            # Restrict to orders thread (ADMIN_ORDERS) in admin group
            if message.message_thread_id != ADMIN_ORDERS:
                await message.reply(
                    "⚠️ This command is only available in the Orders thread.",
                    parse_mode="HTML",
                )
                return
            
            await _perform_whois_lookup(message, thread_id=ADMIN_ORDERS)
            
        except (sqlite3.Error, TelegramBadRequest) as e:
            LOGGER.error("Error in whois_user: %s", e)
            await message.reply("An error occurred while looking up user data.")

    @DP.message(Command("whois"), F.chat.type == ChatType.PRIVATE, F.from_user.id == ADMIN_USER_ID)
    async def whois_user_superadmin(message: Message):
        """Lookup comprehensive user data - superadmin private chat version."""
        try:
            await _perform_whois_lookup(message, thread_id=None)
        except (sqlite3.Error, TelegramBadRequest) as e:
            LOGGER.error("Error in whois_user_superadmin: %s", e)
            await message.reply("An error occurred while looking up user data.")

    async def _perform_whois_lookup(message: Message, thread_id: int = None):
        """Shared whois lookup logic for both admin group and superadmin DM.
        
        Args:
            message: The command message
            thread_id: Thread ID to reply in (None for private chats)
        """
        command_args = message.text.split()
        
        if len(command_args) < 2:
            await message.reply(
                "Usage:\n"
                "<code>/whois 123456789</code> - lookup by user ID\n"
                "<code>/whois @username</code> - lookup by username",
                parse_mode="HTML",
            )
            return
        
        lookup_value = command_args[1].strip()
        user_id = None
        username = None
        
        # Determine if lookup is by ID or username
        if lookup_value.startswith("@"):
            username = lookup_value.lstrip("@")
            LOGGER.info(
                "Whois lookup by username @%s requested by admin @%s",
                username,
                message.from_user.username or message.from_user.id,
            )
        else:
            try:
                user_id = int(lookup_value)
                LOGGER.info(
                    "Whois lookup by ID %d requested by admin @%s",
                    user_id,
                    message.from_user.username or message.from_user.id,
                )
            except ValueError:
                # Might be username without @
                username = lookup_value
                LOGGER.info(
                    "Whois lookup by username %s requested by admin @%s",
                    username,
                    message.from_user.username or message.from_user.id,
                )
        
        # Perform the lookup
        whois_data = get_user_whois(CONN, user_id=user_id, username=username)
        if whois_data is None:
            LOGGER.error("get_user_whois returned None for user_id=%s, username=%s", user_id, username)
            whois_data = {"found": False, "user_id": user_id, "username": username}
        found_user_id = whois_data.get("user_id")

        # Check if user is admin in any monitored chat
        admin_in_chats = []
        if found_user_id:
            for chat_id in CHANNEL_IDS:
                try:
                    is_admin_there = await is_admin(found_user_id, chat_id)
                    if is_admin_there:
                        # Get actual chat info for proper title
                        try:
                            chat_info = await BOT.get_chat(chat_id)
                            chat_name = chat_info.title or CHANNEL_DICT.get(chat_id, str(chat_id))
                            chat_username = chat_info.username
                        except Exception:
                            chat_name = CHANNEL_DICT.get(chat_id, str(chat_id))
                            chat_username = get_cached_chat_username(chat_id)
                        admin_in_chats.append({"chat_id": chat_id, "chat_name": chat_name, "chat_username": chat_username})
                except TelegramBadRequest:
                    pass  # User might not be in chat or bot has no access
        
        # Add admin info to whois_data
        whois_data["admin_in_chats"] = admin_in_chats
        
        # Format and send response
        response_text = format_whois_response(whois_data)
        
        # Create keyboard with action buttons if user found
        keyboard = None
        baseline = whois_data.get("baseline") or {}
        if whois_data.get("found") and found_user_id:
            keyboard = KeyboardBuilder()
            # Add check button if not already monitoring
            if not baseline.get("monitoring_active"):
                keyboard.add(
                    InlineKeyboardButton(
                        text="👁 Start Monitoring",
                        callback_data=f"startcheck_{found_user_id}",
                    )
                )
            # Add ban button if not banned
            # Use 0 for message_id - this is from /whois command, not a message report
            if not baseline.get("is_banned"):
                keyboard.add(
                    InlineKeyboardButton(
                        text="⚙️ Actions (Ban / Delete)",
                        callback_data=f"suspiciousactions_{message.chat.id}_0_{found_user_id}",
                    )
                )
        # Note: LOLS check link is already included in the message text,
        # so we don't need a separate button for it
        
        # Send response - use thread_id if provided (admin group), otherwise no thread (private chat)
        await safe_send_message(
            BOT,
            message.chat.id,
            response_text,
            LOGGER,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=keyboard.as_markup(),
            reply_to_message_id=message.message_id,
            message_thread_id=thread_id,
        )

    @DP.message(Command("delmsg"), F.chat.id == ADMIN_GROUP_ID)
    async def delete_message(message: Message):
        """Function to delete the message by its link."""
        try:
            command_args = message.text.split()
            LOGGER.debug("Command arguments received: %s", command_args)

            if len(command_args) < 2:
                raise ValueError("Please provide the message link to delete.")

            message_link = command_args[1]
            LOGGER.debug("Message link to delete: %s", message_link)

            # Admin_ID
            admin_id = message.from_user.id
            # Extract the chat ID and message ID from the message link
            chat_username, message_id = extract_chat_name_and_message_id_from_link(
                message_link
            )
            LOGGER.debug("Chat ID: %s, Message ID: %d", chat_username, message_id)

            if not chat_username or not message_id:
                raise ValueError("Invalid message link provided.")

            # Fetch user details from the database before deleting the message
            deleted_message_user_id = None
            deleted_message_user_name = None
            deleted_message_user_first_name = None
            deleted_message_user_last_name = None
            user_details_log_str = "user details not found in DB"

            try:
                CURSOR.execute(
                    """
                    SELECT user_id, user_name, user_first_name, user_last_name
                    FROM recent_messages
                    WHERE chat_username = ? AND message_id = ?
                    ORDER BY received_date DESC
                    LIMIT 1
                    """,
                    (chat_username, message_id),
                )
                result = CURSOR.fetchone()

                if result:
                    (
                        deleted_message_user_id,
                        deleted_message_user_name,
                        deleted_message_user_first_name,
                        deleted_message_user_last_name,
                    ) = result
                    user_details_log_str = (
                        f"from user: {html.escape(deleted_message_user_first_name or '')} "
                        f"{html.escape(deleted_message_user_last_name or '')} "
                        f"@{deleted_message_user_name or '!NoName!'} "
                        f"(<code>{deleted_message_user_id}</code>)"
                    )
                else:
                    LOGGER.warning(
                        "Could not retrieve user details for message %d in chat %s from the database.",
                        message_id,
                        chat_username,
                    )
            except sqlite3.Error as e_db:
                LOGGER.error(
                    "Database error while fetching user details for deleted message: %s",
                    e_db,
                )
                user_details_log_str = "DB error fetching user details"

            try:
                await message.forward(
                    TECHNOLOG_GROUP_ID,
                )
                await BOT.delete_message(chat_id=chat_username, message_id=message_id)
                LOGGER.info(
                    "%s Message %d deleted from chat %s by admin request. Original message %s",
                    deleted_message_user_id,
                    message_id,
                    chat_username,
                    user_details_log_str.replace("<code>", "")
                    .replace("</code>", "")
                    .replace("<b>", "")
                    .replace("</b>", ""),
                )
                await message.reply(
                    f"Message {message_id} deleted from chat {chat_username}.\n"
                    f"Original message {user_details_log_str}",
                    parse_mode="HTML",
                )
                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"{message_link} Message {message_id} deleted from chat {chat_username} by admin <code>{admin_id}</code> request.\n"
                    f"Original message {user_details_log_str}",
                    LOGGER,
                    parse_mode="HTML",
                )
                await safe_send_message(
                    BOT,
                    ADMIN_GROUP_ID,
                    f"{message_link} Message {message_id} deleted from chat {chat_username} by admin <code>{admin_id}</code> request.\n"
                    f"Original message {user_details_log_str}",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=ADMIN_MANBAN,
                )

            except TelegramNotFound as e:
                LOGGER.error(
                    "Failed to delete message %d in chat %s. Error: %s",
                    message_id,
                    chat_username,
                    e,
                )
                await message.reply(
                    f"Failed to delete message {message_id} in chat {chat_username}. Error: {e}"
                )

        except ValueError as ve:
            await message.reply(str(ve))
        except TelegramBadRequest as e:
            LOGGER.error("Error in delete_message: %s", e)
            await message.reply("An error occurred while trying to delete the message.")

    @DP.message(Command("banchan"), F.chat.id == ADMIN_GROUP_ID)
    @DP.message(Command("unbanchan"), F.chat.id == ADMIN_GROUP_ID)
    async def manage_channel(message: Message):
        """Function to ban or unban a channel by its id."""
        command = message.text.split()[0].lower()
        action = "ban" if command == "/banchan" else "unban"

        try:
            command_args = message.text.split()
            LOGGER.debug(
                "\033[95m%s admin command arguments received:\033[0m %s",
                message.from_user.id,
                command_args,
            )

            if len(command_args) < 2:
                raise ValueError("No channel ID provided.")

            rogue_chan_id = command_args[1].strip()
            if not rogue_chan_id.startswith("-100") or not rogue_chan_id[4:].isdigit():
                raise ValueError(
                    "Invalid channel ID format. Please provide a valid channel ID."
                )
            try:
                rogue_chan_id = int(rogue_chan_id)
            except ValueError:
                LOGGER.error(
                    "%s Invalid channel ID format. Please provide a valid channel ID.",
                    rogue_chan_id,
                )
                await message.reply(
                    "Invalid channel ID format. Please provide a valid channel ID."
                )
                return  # stop processing command

            if action == "ban":
                if rogue_chan_id in banned_users_dict:
                    LOGGER.debug(
                        "\033[93mRogue channel ID to ban: %s already banned. Skipping actions.\033[0m",
                        rogue_chan_id,
                    )
                    await message.reply(f"Channel {rogue_chan_id} already banned.")
                    return

            LOGGER.debug(
                "\033[93mRogue channel ID to %s: %s\033[0m", action, rogue_chan_id
            )

            # Admin_ID
            admin_id = message.from_user.id
            admin_username = (
                message.from_user.username
                if message.from_user.username
                else "!UNDEFINED!"
            )
            admin_name = (
                message.from_user.first_name + message.from_user.last_name
                if message.from_user.last_name
                else message.from_user.first_name
            )

            if action == "ban":
                try:
                    result, rogue_chan_name, rogue_chan_username = (
                        await ban_rogue_chat_everywhere(rogue_chan_id, CHANNEL_IDS)
                    )
                    if result is True:
                        LOGGER.info(
                            "\033[91mChannel %s %s(%s) banned where it is possible.\033[0m",
                            rogue_chan_name,
                            rogue_chan_username,
                            rogue_chan_id,
                        )
                        await message.reply(
                            f"Channel {rogue_chan_name} @{rogue_chan_username}(<code>{rogue_chan_id}</code>) banned where it is possible."
                        )
                        await safe_send_message(
                            BOT,
                            TECHNOLOG_GROUP_ID,
                            f"Channel {rogue_chan_name} @{rogue_chan_username}(<code>{rogue_chan_id}</code>) banned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            LOGGER,
                            parse_mode="HTML",
                        )
                        await safe_send_message(
                            BOT,
                            ADMIN_GROUP_ID,
                            f"Channel {rogue_chan_name} @{rogue_chan_username}(<code>{rogue_chan_id}</code>) banned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            LOGGER,
                            parse_mode="HTML",
                            message_thread_id=ADMIN_MANBAN,
                        )
                    else:
                        await message.reply(
                            f"Banning channel {rogue_chan_id} generated error: {result}."
                        )
                except TelegramBadRequest as e:
                    LOGGER.error(
                        "Failed to ban channel %d. Error: %s", rogue_chan_id, e
                    )
                    await message.reply(
                        f"Failed to ban channel {rogue_chan_id}. Error: {e}"
                    )
            else:  # action == "unban"
                try:
                    result, rogue_chan_name, rogue_chan_username = (
                        await unban_rogue_chat_everywhere(rogue_chan_id, CHANNEL_IDS)
                    )
                    if result is True:
                        LOGGER.info(
                            "\033[91mChannel %s @%s(%s) unbanned where it is possible.\033[0m",
                            rogue_chan_name,
                            rogue_chan_username,
                            rogue_chan_id,
                        )
                        await message.reply(
                            f"Channel {rogue_chan_name} @{rogue_chan_username}(<code>{rogue_chan_id}</code>) unbanned where it is possible."
                        )
                        await safe_send_message(
                            BOT,
                            TECHNOLOG_GROUP_ID,
                            f"Channel {rogue_chan_name} @{rogue_chan_username}(<code>{rogue_chan_id}</code>) unbanned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            LOGGER,
                            parse_mode="HTML",
                        )
                        await safe_send_message(
                            ADMIN_GROUP_ID,
                            f"Channel {rogue_chan_name} @{rogue_chan_username}(<code>{rogue_chan_id}</code>) unbanned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            LOGGER,
                            parse_mode="HTML",
                            message_thread_id=ADMIN_MANBAN,
                        )
                    else:
                        await message.reply(
                            f"Unbanning channel {rogue_chan_id} generated error: {result}."
                        )

                    # Remove the channel from the banned_users_dict
                    if rogue_chan_id in banned_users_dict:
                        del banned_users_dict[rogue_chan_id]
                        LOGGER.info(
                            "\033[91mChannel (%s) unbanned.\033[0m",
                            rogue_chan_id,
                        )
                        await message.reply(
                            f"Channel {rogue_chan_name} @{rogue_chan_username}(<code>{rogue_chan_id}</code>) unbanned."
                        )
                        await safe_send_message(
                            BOT,
                            TECHNOLOG_GROUP_ID,
                            f"Channel {rogue_chan_name} @{rogue_chan_username}(<code>{rogue_chan_id}</code>) unbanned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            LOGGER,
                            parse_mode="HTML",
                        )
                        await safe_send_message(
                            BOT,
                            ADMIN_GROUP_ID,
                            f"Channel {rogue_chan_name} @{rogue_chan_username}(<code>{rogue_chan_id}</code>) unbanned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            LOGGER,
                            parse_mode="HTML",
                            message_thread_id=ADMIN_MANBAN,
                        )
                    else:
                        await message.reply(f"Channel {rogue_chan_id} was not banned.")
                except TelegramBadRequest as e:
                    LOGGER.error(
                        "Failed to unban channel %d. Error: %s", rogue_chan_id, e
                    )
                    await message.reply(
                        f"Failed to unban channel {rogue_chan_id}. Error: {e}"
                    )

        except ValueError as ve:
            await message.reply(str(ve))
            LOGGER.error("No channel ID provided!")

    @DP.message(Command("loglists"), F.chat.id == ADMIN_GROUP_ID)
    async def log_lists_handler(message: Message):
        """Function to log active checks and banned users dict."""
        await log_lists(message.chat.id, message.message_thread_id)

    # Helper to check if message is from superadmin in allowed location
    def is_superadmin_context(message: Message) -> bool:
        """Check if message is from superadmin in private chat or superadmin group."""
        if message.from_user.id != ADMIN_USER_ID:
            return False
        # Allow in private chat
        if message.chat.type == "private":
            return True
        # Allow in superadmin group (if configured)
        if SUPERADMIN_GROUP_ID and message.chat.id == SUPERADMIN_GROUP_ID:
            return True
        return False

    # Lambda for handlers - checks superadmin in private chat OR superadmin group
    def superadmin_filter(m: Message) -> bool:
        """Filter for superadmin commands - private chat or superadmin group."""
        if m.from_user.id != ADMIN_USER_ID:
            return False
        if m.chat.type == "private":
            return True
        if SUPERADMIN_GROUP_ID and m.chat.id == SUPERADMIN_GROUP_ID:
            return True
        return False

    @DP.message(superadmin_filter, Command("help"))
    @DP.message(superadmin_filter, Command("adminhelp"))
    async def superadmin_help(message: Message):
        """Show help for superadmin communication commands.
        
        NOTE: Only available to superadmin in private chat.
        """
        # Split help into two messages to avoid Telegram's 4096 char limit
        help_text_1 = (
            "🤖 <b>Superadmin Communication Commands</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            "📤 <b>/say</b> <code>&lt;target&gt; &lt;message&gt;</code>\n"
            "Send a message to a specific chat.\n"
            "  • Target: chat ID, <code>@username</code>, or <code>t.me/chat</code>\n"
            "  • Topic support: <code>-100123:456</code> or <code>t.me/chat/456</code>\n"
            "  • Auto-delete: <code>/say -t 60 @chat Message</code> (deletes in 60s)\n\n"
            
            "↩️ <b>/reply</b> <code>&lt;message_link&gt; &lt;text&gt;</code>\n"
            "Reply to a specific message in a chat.\n"
            "  • Link: <code>https://t.me/chat/123</code> or <code>t.me/c/123/456</code>\n\n"
            
            "📩 <b>/forward</b> <code>&lt;message_link&gt; &lt;target&gt;</code>\n"
            "Forward message (shows \"Forwarded from\" header).\n"
            "  • Source must be accessible by bot\n"
            "  • Auto-delete: <code>/forward -t 60 link target</code>\n\n"
            
            "📋 <b>/copy</b> <code>&lt;message_link&gt; &lt;target&gt;</code>\n"
            "Copy message (appears as bot's own message).\n"
            "  • No forwarding attribution shown\n"
            "  • Auto-delete: <code>/copy -t 60 link target</code>\n\n"
            
            "📢 <b>/broadcast</b> <code>&lt;message&gt;</code>\n"
            "Send to ALL monitored chats.\n"
            "  • Use <code>-list chat1,chat2</code> for specific chats\n"
            "  • ⚠️ Two-step confirmation: button + type <code>CONFIRM BROADCAST</code>\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💬 <b>Replying to User DMs</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• <b>Reply</b> to forwarded message → sends as threaded reply\n"
            "• Start with <code>/</code> or <code>\\</code> → sends as standalone message\n"
        )
        
        help_text_2 = (
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <b>Common Errors</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• <b>\"Failed to send\"</b> - Bot not in chat or no permission\n"
            "• <b>\"Invalid link\"</b> - Wrong format, use \"Copy Message Link\"\n"
            "• <b>\"Invalid chat ID\"</b> - Use <code>-100...</code> or <code>@username</code>\n"
            "• <b>\"BadRequest\"</b> - Malformed HTML or deleted message\n\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <b>Tips</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• <b>HTML:</b> &lt;b&gt;, &lt;i&gt;, &lt;u&gt;, &lt;code&gt;, &lt;a href=\"\"&gt;\n"
            "• <b>Get chat ID:</b> Forward msg to @userinfobot\n"
            "• <b>All commands:</b> Private chat only\n"
        )
        
        await message.reply(help_text_1, parse_mode="HTML")
        await message.reply(help_text_2, parse_mode="HTML")

    @DP.message(superadmin_filter, Command("say"))
    async def say_to_chat(message: Message):
        """Send a message to a specific chat as the bot.
        
        Usage: /say <chat_id_or_link> <message>
        Usage: /say -t <seconds> <chat_id_or_link> <message>  (auto-delete after timeout)
        Example: /say -1001234567890 Hello everyone!
        Example: /say @chatusername Hello everyone!
        Example: /say -t 30 @chatusername This disappears in 30 seconds!
        
        NOTE: Only available to superadmin in private chat or superadmin group.
        """
        LOGGER.info(
            "%s:%s COMM /say in chat %s",
            message.from_user.id,
            f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
            message.chat.id,
        )
        try:
            # Parse command: /say [-t <seconds>] <target> <message>
            parts = message.text.split()
            
            # Check for timeout flag
            delete_after = None
            if len(parts) >= 4 and parts[1] == "-t":
                try:
                    delete_after = int(parts[2])
                    if delete_after < 1 or delete_after > 86400:  # Max 24 hours
                        await message.reply("Timeout must be between 1 and 86400 seconds (24 hours).")
                        return
                    # Re-parse with timeout removed
                    remaining = message.text.split(maxsplit=3)
                    if len(remaining) < 4:
                        await message.reply("Please provide target and message after timeout.")
                        return
                    target = remaining[3].split(maxsplit=1)[0]
                    text_to_send = remaining[3].split(maxsplit=1)[1] if len(remaining[3].split(maxsplit=1)) > 1 else ""
                except (ValueError, IndexError):
                    await message.reply("Invalid timeout format. Use: <code>/say -t &lt;seconds&gt; &lt;target&gt; message</code>", parse_mode="HTML")
                    return
            else:
                # Standard parsing without timeout
                parts = message.text.split(maxsplit=2)
                if len(parts) < 3:
                    await message.reply(
                        "Usage: <code>/say &lt;target&gt; message</code>\n"
                        "Usage: <code>/say -t &lt;seconds&gt; &lt;target&gt; message</code> (auto-delete)\n"
                        "Examples:\n"
                        "  <code>/say -1001234567890 Hello!</code>\n"
                        "  <code>/say -1001234567890:123 Hello to topic!</code>\n"
                        "  <code>/say @chatusername Hello!</code>\n"
                        "  <code>/say t.me/chatname Hello!</code>\n"
                        "  <code>/say t.me/chatname/456 Hello to topic!</code>\n"
                        "  <code>/say t.me/chatname/1/9221 Reply to message!</code>\n"
                        "  <code>/say -t 60 @chat Message deleted in 60s!</code>",
                        parse_mode="HTML",
                    )
                    return
                target = parts[1]
                text_to_send = parts[2]
            
            thread_id = None  # For forum topics
            reply_to_msg_id = None  # For replying to specific message

            # Determine target chat and optional thread
            if target.startswith("@"):
                chat_id = target  # Use username directly
            elif ":" in target and target.split(":")[0].lstrip("-").isdigit():
                # Format: -1001234567890:123 (chat_id:thread_id)
                parts_target = target.split(":", 1)
                chat_id = int(parts_target[0])
                if parts_target[1].isdigit():
                    thread_id = int(parts_target[1])
            elif target.lstrip("-").isdigit():
                chat_id = int(target)
            elif "t.me/" in target:
                # Extract chat and optional topic/message from t.me link
                # (re is imported at module level)
                
                # Check for private link format: t.me/c/chat_id/... 
                if "t.me/c/" in target:
                    # Private link: t.me/c/chat_id/msg_id or t.me/c/chat_id/topic_id/msg_id
                    match_private_with_topic = re.search(r't\.me/c/(\d+)/(\d+)/(\d+)', target)
                    match_private = re.search(r't\.me/c/(\d+)/(\d+)', target)
                    
                    if match_private_with_topic:
                        # t.me/c/chat_id/topic_id/msg_id - reply to message in topic
                        chat_id = int(f"-100{match_private_with_topic.group(1)}")
                        thread_id = int(match_private_with_topic.group(2))
                        reply_to_msg_id = int(match_private_with_topic.group(3))
                    elif match_private:
                        # t.me/c/chat_id/msg_id - could be topic or message
                        chat_id = int(f"-100{match_private.group(1)}")
                        # Treat second number as topic (send to topic, not reply)
                        thread_id = int(match_private.group(2))
                    else:
                        await message.reply(
                            "Invalid private link format.",
                            parse_mode="HTML",
                        )
                        return
                else:
                    # Public link: t.me/chatname/... 
                    # Try to match with topic and message: t.me/chatname/topic_id/msg_id
                    match_with_topic_msg = re.search(r't\.me/([a-zA-Z][a-zA-Z0-9_]{3,})/(\d+)/(\d+)', target)
                    match_with_topic = re.search(r't\.me/([a-zA-Z][a-zA-Z0-9_]{3,})/(\d+)', target)
                    match_simple = re.search(r't\.me/([a-zA-Z][a-zA-Z0-9_]{3,})', target)
                    
                    if match_with_topic_msg:
                        # t.me/chatname/topic_id/msg_id - reply to message in topic
                        chat_id = f"@{match_with_topic_msg.group(1)}"
                        thread_id = int(match_with_topic_msg.group(2))
                        reply_to_msg_id = int(match_with_topic_msg.group(3))
                    elif match_with_topic:
                        # t.me/chatname/topic_id - send to topic
                        chat_id = f"@{match_with_topic.group(1)}"
                        thread_id = int(match_with_topic.group(2))
                    elif match_simple:
                        # t.me/chatname - send to chat
                        chat_id = f"@{match_simple.group(1)}"
                    else:
                        await message.reply(
                            "Invalid t.me link format.",
                            parse_mode="HTML",
                        )
                        return
            else:
                await message.reply(
                    "Invalid target. Use:\n"
                    "• Numeric ID: <code>-1001234567890</code>\n"
                    "• With topic: <code>-1001234567890:123</code>\n"
                    "• Username: <code>@chatname</code>\n"
                    "• Link: <code>t.me/chatname</code> or <code>t.me/chatname/topic_id</code>\n"
                    "• Message link: <code>t.me/chatname/topic/msg_id</code> (will reply)",
                    parse_mode="HTML",
                )
                return

            # Build kwargs for send
            send_kwargs = {
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            if thread_id:
                send_kwargs["message_thread_id"] = thread_id
            if reply_to_msg_id:
                send_kwargs["reply_to_message_id"] = reply_to_msg_id

            # Send the message - try with thread first, then as reply_to, then plain
            sent_msg = None
            used_thread_id = thread_id  # Track what we actually used
            used_as_reply = False  # Track if we used reply_to instead of thread
            try:
                sent_msg = await BOT.send_message(
                    chat_id,
                    text_to_send,
                    **send_kwargs,
                )
            except TelegramBadRequest as send_error:
                error_str = str(send_error).lower()
                # If thread not found, try as reply_to_message_id (non-forum group)
                if thread_id and ("thread not found" in error_str or "message thread" in error_str):
                    LOGGER.info(
                        "Thread %s not found in %s, trying as reply_to_message_id",
                        thread_id, chat_id,
                    )
                    send_kwargs.pop("message_thread_id", None)
                    send_kwargs["reply_to_message_id"] = thread_id
                    used_thread_id = None
                    try:
                        sent_msg = await BOT.send_message(
                            chat_id,
                            text_to_send,
                            **send_kwargs,
                        )
                        used_as_reply = True
                        LOGGER.info(
                            "Successfully sent as reply to message %s",
                            thread_id,
                        )
                    except TelegramBadRequest as reply_error:
                        # Reply also failed, try plain send without thread/reply
                        LOGGER.info(
                            "Reply to %s also failed (%s), falling back to plain send",
                            thread_id, reply_error,
                        )
                        send_kwargs.pop("reply_to_message_id", None)
                        try:
                            sent_msg = await BOT.send_message(
                                chat_id,
                                text_to_send,
                                **send_kwargs,
                            )
                        except TelegramBadRequest as plain_error:
                            await message.reply(f"❌ Failed to send message: {plain_error}")
                            return
                else:
                    await message.reply(f"❌ Failed to send message: {send_error}")
                    return

            if sent_msg:
                # Build link to sent message (include thread in link if applicable)
                if isinstance(chat_id, str) and chat_id.startswith("@"):
                    if used_thread_id:
                        msg_link = f"https://t.me/{chat_id[1:]}/{used_thread_id}/{sent_msg.message_id}"
                    else:
                        msg_link = f"https://t.me/{chat_id[1:]}/{sent_msg.message_id}"
                else:
                    chat_id_str = str(chat_id)[4:] if str(chat_id).startswith("-100") else str(chat_id)
                    if used_thread_id:
                        msg_link = f"https://t.me/c/{chat_id_str}/{used_thread_id}/{sent_msg.message_id}"
                    else:
                        msg_link = f"https://t.me/c/{chat_id_str}/{sent_msg.message_id}"
                
                # Build target description
                target_desc = f"<code>{chat_id}</code>"
                if used_thread_id:
                    target_desc += f" (topic {used_thread_id})"
                elif used_as_reply:
                    target_desc += f" (reply to msg {thread_id})"
                
                # Build action description
                if reply_to_msg_id and not used_as_reply:
                    action_desc = f"✅ Reply sent to message {reply_to_msg_id} in {target_desc}"
                else:
                    action_desc = f"✅ Message sent to {target_desc}"
                
                # Add timeout info if set
                if delete_after:
                    action_desc += f"\n⏱ Auto-delete in {delete_after} seconds"
                
                await message.reply(
                    f"{action_desc}\n"
                    f"🔗 <a href='{msg_link}'>View message</a>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                
                # Schedule message deletion if timeout is set
                if delete_after:
                    async def delete_message_later():
                        await asyncio.sleep(delete_after)
                        try:
                            await BOT.delete_message(sent_msg.chat.id, sent_msg.message_id)
                            LOGGER.info(
                                "%s:%s auto-deleted message %s in chat %s after %ds",
                                message.from_user.id,
                                f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
                                sent_msg.message_id,
                                chat_id,
                                delete_after,
                            )
                        except TelegramBadRequest as del_e:
                            LOGGER.warning("Failed to auto-delete message: %s", del_e)
                    
                    asyncio.create_task(delete_message_later())

                LOGGER.info(
                    "%s:%s sent message to chat %s (thread=%s, reply_to=%s, used_as_reply=%s, delete_after=%s)",
                    message.from_user.id,
                    f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
                    chat_id,
                    used_thread_id,
                    reply_to_msg_id if not used_as_reply else thread_id,
                    used_as_reply,
                    delete_after,
                )

        except (TelegramBadRequest, ValueError) as e:
            LOGGER.error("%s:%s Error in say_to_chat: %s", message.from_user.id, f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!", e)
            await message.reply(f"Error: {e}")

    @DP.message(superadmin_filter, Command("reply"))
    async def reply_to_message(message: Message):
        """Reply to a specific message in a chat as the bot.
        
        Usage: /reply <message_link> <reply_text>
        Example: /reply https://t.me/chatname/123 Thanks for your message!
        
        NOTE: Only available to superadmin in private chat or superadmin group.
        """
        LOGGER.info(
            "%s:%s COMM /reply in chat %s",
            message.from_user.id,
            f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
            message.chat.id,
        )
        try:
            # Parse command: /reply <link> <text>
            parts = message.text.split(maxsplit=2)
            if len(parts) < 3:
                await message.reply(
                    "Usage: <code>/reply &lt;message_link&gt; reply_text</code>\n"
                    "Example: <code>/reply https://t.me/chatname/123 Thanks!</code>",
                    parse_mode="HTML",
                )
                return

            message_link = parts[1]
            reply_text = parts[2]

            # Extract chat and message ID from link
            chat_username, target_message_id = extract_chat_name_and_message_id_from_link(message_link)
            
            if not chat_username or not target_message_id:
                await message.reply("Invalid message link format.")
                return

            # Determine chat_id (may already be int from private link, or string for public)
            if isinstance(chat_username, int):
                chat_id = chat_username
            elif str(chat_username).lstrip("-").isdigit():
                chat_id = int(chat_username)
            else:
                chat_id = chat_username  # Already has @ prefix from parser

            # Send reply
            sent_msg = await safe_send_message(
                BOT,
                chat_id,
                reply_text,
                LOGGER,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_to_message_id=target_message_id,
            )

            if sent_msg:
                # Build link to sent reply
                if isinstance(chat_id, str) and chat_id.startswith("@"):
                    msg_link = f"https://t.me/{chat_id[1:]}/{sent_msg.message_id}"
                else:
                    chat_id_str = str(chat_id)[4:] if str(chat_id).startswith("-100") else str(chat_id)
                    msg_link = f"https://t.me/c/{chat_id_str}/{sent_msg.message_id}"

                await message.reply(
                    f"✅ Reply sent to message in <code>{chat_id}</code>\n"
                    f"🔗 <a href='{msg_link}'>View reply</a>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )

                LOGGER.info(
                    "%s:%s replied to message %s in chat %s",
                    message.from_user.id,
                    f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
                    target_message_id,
                    chat_id,
                )
            else:
                await message.reply(f"❌ Failed to reply to message in {chat_id}")

        except (TelegramBadRequest, ValueError) as e:
            LOGGER.error("%s:%s Error in reply_to_message: %s", message.from_user.id, f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!", e)
            await message.reply(f"Error: {e}")

    def parse_target_with_thread(target: str):
        """Parse target string and extract chat_id and optional thread_id.
        
        Supports:
        - Numeric ID: -1001234567890
        - With thread: -1001234567890:123
        - Username: @chatname
        - t.me link: t.me/chatname or t.me/chatname/456
        - t.me/c link: t.me/c/1234567890 or t.me/c/1234567890/456
        
        Returns: (chat_id, thread_id) where thread_id may be None
        """
        # re is imported at module level
        thread_id = None
        
        if target.startswith("@"):
            chat_id = target
        elif ":" in target and target.split(":")[0].lstrip("-").isdigit():
            parts = target.split(":", 1)
            chat_id = int(parts[0])
            if parts[1].isdigit():
                thread_id = int(parts[1])
        elif target.lstrip("-").isdigit():
            chat_id = int(target)
        elif "t.me/c/" in target:
            # Private chat link: t.me/c/1234567890 or t.me/c/1234567890/456
            match_with_topic = re.search(r't\.me/c/(\d+)/(\d+)', target)
            if match_with_topic:
                # Convert to full chat ID format: -100 + chat_id
                chat_id = int(f"-100{match_with_topic.group(1)}")
                thread_id = int(match_with_topic.group(2))
            else:
                match = re.search(r't\.me/c/(\d+)', target)
                if match:
                    chat_id = int(f"-100{match.group(1)}")
                else:
                    return None, None
        elif "t.me/" in target:
            # Public chat link: t.me/chatname or t.me/chatname/456
            match_with_topic = re.search(r't\.me/([a-zA-Z][a-zA-Z0-9_]{3,})/(\d+)', target)
            if match_with_topic:
                chat_id = f"@{match_with_topic.group(1)}"
                thread_id = int(match_with_topic.group(2))
            else:
                match = re.search(r't\.me/([a-zA-Z][a-zA-Z0-9_]{3,})', target)
                if match:
                    chat_id = f"@{match.group(1)}"
                else:
                    return None, None
        else:
            return None, None
        
        return chat_id, thread_id

    @DP.message(superadmin_filter, Command("forward"))
    async def forward_message_cmd(message: Message):
        """Forward a message to a target chat (shows 'Forwarded from' header).
        
        Usage: /forward <message_link> <target>
        Usage: /forward -t <seconds> <message_link> <target>  (auto-delete)
        Example: /forward https://t.me/source/123 -1001234567890
        
        NOTE: Only available to superadmin in private chat or superadmin group.
        """
        LOGGER.info(
            "%s:%s COMM /forward in chat %s",
            message.from_user.id,
            f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
            message.chat.id,
        )
        try:
            # Check for timeout flag
            parts = message.text.split()
            delete_after = None
            
            if len(parts) >= 5 and parts[1] == "-t":
                try:
                    delete_after = int(parts[2])
                    if delete_after < 1 or delete_after > 86400:
                        await message.reply("Timeout must be between 1 and 86400 seconds.")
                        return
                    message_link = parts[3]
                    target = parts[4]
                except (ValueError, IndexError):
                    await message.reply("Invalid timeout format. Use: <code>/forward -t &lt;seconds&gt; &lt;link&gt; &lt;target&gt;</code>", parse_mode="HTML")
                    return
            else:
                parts = message.text.split(maxsplit=2)
                if len(parts) < 3:
                    await message.reply(
                        "Usage: <code>/forward &lt;message_link&gt; &lt;target&gt;</code>\n"
                        "Usage: <code>/forward -t &lt;seconds&gt; &lt;link&gt; &lt;target&gt;</code> (auto-delete)\n"
                        "Example: <code>/forward https://t.me/source/123 -1001234567890</code>\n"
                        "Example: <code>/forward -t 60 https://t.me/source/123 @chat</code>",
                        parse_mode="HTML",
                    )
                    return
                message_link = parts[1]
                target = parts[2]

            # Extract source chat and message ID
            try:
                source_chat, source_msg_id = extract_chat_name_and_message_id_from_link(message_link)
            except ValueError as e:
                await message.reply(f"❌ Invalid message link: {e}")
                return

            # Parse target
            target_chat, thread_id = parse_target_with_thread(target)
            if target_chat is None:
                await message.reply(
                    "❌ Invalid target. Use:\n"
                    "• Numeric ID: <code>-1001234567890</code>\n"
                    "• With topic: <code>-1001234567890:123</code>\n"
                    "• Username: <code>@chatname</code>\n"
                    "• Link: <code>t.me/chatname</code> or <code>t.me/chatname/topic_id</code>",
                    parse_mode="HTML",
                )
                return

            # Forward the message - try with thread first, fallback to reply-to or plain forward
            try:
                forwarded = None
                used_thread_id = thread_id
                used_as_reply = False  # Track if we used reply_to instead of thread
                try:
                    if thread_id:
                        forwarded = await BOT.forward_message(
                            chat_id=target_chat,
                            from_chat_id=source_chat,
                            message_id=source_msg_id,
                            message_thread_id=thread_id,
                        )
                    else:
                        forwarded = await BOT.forward_message(
                            chat_id=target_chat,
                            from_chat_id=source_chat,
                            message_id=source_msg_id,
                        )
                except TelegramBadRequest as fwd_error:
                    error_str = str(fwd_error).lower()
                    if thread_id and ("thread not found" in error_str or "message thread" in error_str):
                        # Thread not found - this might be a non-forum group where the ID is a message to reply to
                        # Try copy_message with reply_to_message_id instead (forward doesn't support reply_to)
                        LOGGER.info(
                            "Thread %s not found, trying as reply_to_message_id using copy_message",
                            thread_id,
                        )
                        try:
                            forwarded = await BOT.copy_message(
                                chat_id=target_chat,
                                from_chat_id=source_chat,
                                message_id=source_msg_id,
                                reply_to_message_id=thread_id,
                            )
                            used_thread_id = None
                            used_as_reply = True
                            LOGGER.info(
                                "Successfully sent as reply to message %s (used copy_message)",
                                thread_id,
                            )
                        except TelegramBadRequest as reply_error:
                            # Reply also failed, try plain forward without thread
                            LOGGER.info(
                                "Reply to %s also failed (%s), falling back to plain forward",
                                thread_id,
                                reply_error,
                            )
                            used_thread_id = None
                            forwarded = await BOT.forward_message(
                                chat_id=target_chat,
                                from_chat_id=source_chat,
                                message_id=source_msg_id,
                            )
                    else:
                        raise fwd_error

                # Build success message
                target_desc = f"<code>{target_chat}</code>"
                if used_thread_id:
                    target_desc += f" (topic {used_thread_id})"
                elif used_as_reply:
                    target_desc += f" (reply to msg {thread_id})"

                # Build link to forwarded message
                if isinstance(target_chat, str) and target_chat.startswith("@"):
                    if used_thread_id:
                        msg_link = f"https://t.me/{target_chat[1:]}/{used_thread_id}/{forwarded.message_id}"
                    else:
                        msg_link = f"https://t.me/{target_chat[1:]}/{forwarded.message_id}"
                else:
                    chat_id_str = str(target_chat)[4:] if str(target_chat).startswith("-100") else str(target_chat)
                    if used_thread_id:
                        msg_link = f"https://t.me/c/{chat_id_str}/{used_thread_id}/{forwarded.message_id}"
                    else:
                        msg_link = f"https://t.me/c/{chat_id_str}/{forwarded.message_id}"

                # Build action description
                action_desc = f"✅ Message forwarded to {target_desc}"
                if delete_after:
                    action_desc += f"\n⏱ Auto-delete in {delete_after} seconds"

                await message.reply(
                    f"{action_desc}\n"
                    f"🔗 <a href='{msg_link}'>View message</a>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )

                # Schedule message deletion if timeout is set
                if delete_after:
                    async def delete_forwarded_later():
                        await asyncio.sleep(delete_after)
                        try:
                            await BOT.delete_message(forwarded.chat.id, forwarded.message_id)
                            LOGGER.info("%s:%s auto-deleted forwarded message after %ds", message.from_user.id, f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!", delete_after)
                        except TelegramBadRequest as del_e:
                            LOGGER.warning("Failed to auto-delete forwarded message: %s", del_e)
                    asyncio.create_task(delete_forwarded_later())

                LOGGER.info(
                    "%s:%s forwarded message %s from %s to %s (thread=%s, reply_to=%s, delete_after=%s)",
                    message.from_user.id,
                    f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
                    source_msg_id,
                    source_chat,
                    target_chat,
                    used_thread_id,
                    thread_id if used_as_reply else None,
                    delete_after,
                )

            except TelegramBadRequest as e:
                await message.reply(f"❌ Failed to forward message: {e}")

        except (TelegramBadRequest, ValueError) as e:
            LOGGER.error("%s:%s Error in forward_message_cmd: %s", message.from_user.id, f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!", e)
            await message.reply(f"Error: {e}")

    @DP.message(superadmin_filter, Command("copy"))
    async def copy_message_cmd(message: Message):
        """Copy a message to a target chat (no 'Forwarded from' header).
        
        Usage: /copy <message_link> <target>
        Usage: /copy -t <seconds> <message_link> <target>  (auto-delete after timeout)
        Example: /copy https://t.me/source/123 -1001234567890
        Example: /copy -t 60 https://t.me/source/123 @targetgroup
        
        NOTE: Only available to superadmin in private chat or superadmin group.
        """
        LOGGER.info(
            "%s:%s COMM /copy in chat %s",
            message.from_user.id,
            f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
            message.chat.id,
        )
        try:
            # Parse optional -t timeout for auto-delete
            delete_timeout = None
            remaining_text = message.text
            if " -t " in remaining_text:
                match = re.search(r'-t\s+(\d+)', remaining_text)
                if match:
                    delete_timeout = int(match.group(1))
                    remaining_text = re.sub(r'-t\s+\d+\s*', '', remaining_text)

            parts = remaining_text.split(maxsplit=2)
            if len(parts) < 3:
                await message.reply(
                    "Usage: <code>/copy &lt;message_link&gt; &lt;target&gt;</code>\n"
                    "Usage: <code>/copy -t &lt;seconds&gt; &lt;message_link&gt; &lt;target&gt;</code>\n"
                    "Example: <code>/copy https://t.me/source/123 -1001234567890</code>\n"
                    "Example: <code>/copy -t 60 https://t.me/source/123 @targetgroup</code>\n"
                    "💡 No 'Forwarded from' header - appears as bot's message\n"
                    "💡 Use <code>-t &lt;seconds&gt;</code> to auto-delete after timeout",
                    parse_mode="HTML",
                )
                return

            message_link = parts[1]
            target = parts[2]

            # Extract source chat and message ID
            try:
                source_chat, source_msg_id = extract_chat_name_and_message_id_from_link(message_link)
            except ValueError as e:
                await message.reply(f"❌ Invalid message link: {e}")
                return

            # Parse target
            target_chat, thread_id = parse_target_with_thread(target)
            if target_chat is None:
                await message.reply(
                    "❌ Invalid target. Use:\n"
                    "• Numeric ID: <code>-1001234567890</code>\n"
                    "• With topic: <code>-1001234567890:123</code>\n"
                    "• Username: <code>@chatname</code>\n"
                    "• Link: <code>t.me/chatname</code> or <code>t.me/chatname/topic_id</code>",
                    parse_mode="HTML",
                )
                return

            # Copy the message (no forwarded header)
            copied = None
            used_thread_id = thread_id
            used_as_reply = False
            try:
                if thread_id:
                    copied = await BOT.copy_message(
                        chat_id=target_chat,
                        from_chat_id=source_chat,
                        message_id=source_msg_id,
                        message_thread_id=thread_id,
                    )
                else:
                    copied = await BOT.copy_message(
                        chat_id=target_chat,
                        from_chat_id=source_chat,
                        message_id=source_msg_id,
                    )
            except TelegramBadRequest as copy_err:
                error_str = str(copy_err).lower()
                # If thread not found, try as reply_to_message_id instead
                if thread_id and ("thread not found" in error_str or "message thread" in error_str):
                    LOGGER.info(
                        "Thread %s not found, trying as reply_to_message_id",
                        thread_id,
                    )
                    try:
                        copied = await BOT.copy_message(
                            chat_id=target_chat,
                            from_chat_id=source_chat,
                            message_id=source_msg_id,
                            reply_to_message_id=thread_id,
                        )
                        used_thread_id = None
                        used_as_reply = True
                        LOGGER.info(
                            "Successfully copied as reply to message %s",
                            thread_id,
                        )
                    except TelegramBadRequest as reply_err:
                        # Reply also failed, try plain copy
                        LOGGER.info(
                            "Reply to %s also failed (%s), falling back to plain copy",
                            thread_id,
                            reply_err,
                        )
                        used_thread_id = None
                        copied = await BOT.copy_message(
                            chat_id=target_chat,
                            from_chat_id=source_chat,
                            message_id=source_msg_id,
                        )
                else:
                    raise

            if copied:
                # Schedule auto-delete if timeout specified
                if delete_timeout and delete_timeout > 0:
                    async def auto_delete():
                        await asyncio.sleep(delete_timeout)
                        try:
                            await BOT.delete_message(target_chat, copied.message_id)
                            LOGGER.info("Auto-deleted copied message %s in %s after %ds", copied.message_id, target_chat, delete_timeout)
                        except TelegramBadRequest as del_err:
                            LOGGER.warning("Failed to auto-delete copied message %s in %s: %s", copied.message_id, target_chat, del_err)
                    asyncio.create_task(auto_delete())

                # Build success message
                target_desc = f"<code>{target_chat}</code>"
                if used_thread_id:
                    target_desc += f" (topic {used_thread_id})"
                elif used_as_reply:
                    target_desc += f" (reply to msg {thread_id})"

                # Build link to copied message
                if isinstance(target_chat, str) and target_chat.startswith("@"):
                    if used_thread_id:
                        msg_link = f"https://t.me/{target_chat[1:]}/{used_thread_id}/{copied.message_id}"
                    else:
                        msg_link = f"https://t.me/{target_chat[1:]}/{copied.message_id}"
                else:
                    chat_id_str = str(target_chat)[4:] if str(target_chat).startswith("-100") else str(target_chat)
                    if used_thread_id:
                        msg_link = f"https://t.me/c/{chat_id_str}/{used_thread_id}/{copied.message_id}"
                    else:
                        msg_link = f"https://t.me/c/{chat_id_str}/{copied.message_id}"

                await message.reply(
                    f"✅ Message copied to {target_desc}\n"
                    f"🔗 <a href='{msg_link}'>View message</a>",
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )

                LOGGER.info(
                    "%s:%s copied message %s from %s to %s (thread=%s, reply_to=%s, timeout=%s)",
                    message.from_user.id,
                    f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
                    source_msg_id,
                    source_chat,
                    target_chat,
                    used_thread_id,
                    thread_id if used_as_reply else None,
                    delete_timeout,
                )

        except (TelegramBadRequest, ValueError) as e:
            LOGGER.error("%s:%s Error in copy_message_cmd: %s", message.from_user.id, f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!", e)
            await message.reply(f"Error: {e}")

    @DP.message(superadmin_filter, Command("broadcast"))
    async def broadcast_message(message: Message):
        """Broadcast a message to all or selected monitored chats.
        
        Usage: /broadcast <message>              - Send to ALL monitored chats
        Usage: /broadcast -list chat1,chat2 <message> - Send to specific chats
        Example: /broadcast Hello everyone!
        Example: /broadcast -list -1001234,-1005678 Hello!
        
        NOTE: Only available to superadmin in private chat or superadmin group.
        """
        LOGGER.info(
            "%s:%s COMM /broadcast in chat %s",
            message.from_user.id,
            f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
            message.chat.id,
        )
        try:
            text = message.text
            
            # Check for -list flag
            if " -list " in text:
                # Parse: /broadcast -list chat1,chat2,... message
                match = text.split(" -list ", 1)
                if len(match) < 2:
                    await message.reply("Invalid format. Use: /broadcast -list chat1,chat2 message")
                    return
                
                rest = match[1].split(maxsplit=1)
                if len(rest) < 2:
                    await message.reply("Please provide both chat list and message.")
                    return
                
                chat_list_str = rest[0]
                broadcast_text = rest[1]
                
                # Parse chat IDs
                target_chats = []
                for chat_str in chat_list_str.split(","):
                    chat_str = chat_str.strip()
                    if chat_str.startswith("@"):
                        target_chats.append(chat_str)
                    elif chat_str.lstrip("-").isdigit():
                        target_chats.append(int(chat_str))
                    else:
                        await message.reply(f"Invalid chat ID: {chat_str}")
                        return
            else:
                # Broadcast to all monitored chats
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    await message.reply(
                        "Usage: <code>/broadcast message</code> - Send to all monitored chats\n"
                        "Usage: <code>/broadcast -list chat1,chat2 message</code> - Send to specific chats\n\n"
                        f"📋 Monitored chats ({len(CHANNEL_IDS)}):\n" +
                        "\n".join([f"  • <code>{cid}</code> - {CHANNEL_DICT.get(cid, 'Unknown')}" for cid in CHANNEL_IDS[:10]]) +
                        (f"\n  ... and {len(CHANNEL_IDS) - 10} more" if len(CHANNEL_IDS) > 10 else ""),
                        parse_mode="HTML",
                    )
                    return
                
                broadcast_text = parts[1]
                target_chats = list(CHANNEL_IDS)

            # Confirm before broadcasting to all
            if len(target_chats) == len(CHANNEL_IDS) and len(target_chats) > 3:
                confirm_kb = KeyboardBuilder()
                # Store broadcast text temporarily in callback data (limited to 64 bytes)
                # For longer messages, we'll need a different approach
                if len(broadcast_text) > 40:
                    # Store in a temp dict for retrieval
                    broadcast_id = int(datetime.now().timestamp())
                    if not hasattr(DP, 'pending_broadcasts'):
                        DP.pending_broadcasts = {}
                    DP.pending_broadcasts[broadcast_id] = {
                        "text": broadcast_text,
                        "chats": target_chats,
                        "admin_id": message.from_user.id,
                    }
                    confirm_kb.add(
                        InlineKeyboardButton(text="✅ Confirm", callback_data=f"broadcast_confirm_{broadcast_id}"),
                        InlineKeyboardButton(text="❌ Cancel", callback_data=f"broadcast_cancel_{broadcast_id}"),
                    )
                else:
                    # Short message - encode directly (not recommended, but as fallback)
                    broadcast_id = int(datetime.now().timestamp())
                    if not hasattr(DP, 'pending_broadcasts'):
                        DP.pending_broadcasts = {}
                    DP.pending_broadcasts[broadcast_id] = {
                        "text": broadcast_text,
                        "chats": target_chats,
                        "admin_id": message.from_user.id,
                    }
                    confirm_kb.add(
                        InlineKeyboardButton(text="✅ Confirm", callback_data=f"broadcast_confirm_{broadcast_id}"),
                        InlineKeyboardButton(text="❌ Cancel", callback_data=f"broadcast_cancel_{broadcast_id}"),
                    )
                
                await message.reply(
                    f"⚠️ <b>Broadcast Confirmation</b>\n\n"
                    f"You are about to send a message to <b>{len(target_chats)}</b> chats.\n\n"
                    f"<b>Message preview:</b>\n<i>{html.escape(broadcast_text[:200])}{'...' if len(broadcast_text) > 200 else ''}</i>",
                    parse_mode="HTML",
                    reply_markup=confirm_kb.as_markup(),
                )
                return

            # Send to target chats (for small lists, send directly)
            success_count = 0
            fail_count = 0
            failed_chats = []

            status_msg = await message.reply(f"📤 Broadcasting to {len(target_chats)} chats...")

            for chat_id in target_chats:
                try:
                    await safe_send_message(
                        BOT,
                        chat_id,
                        broadcast_text,
                        LOGGER,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    success_count += 1
                except TelegramBadRequest as e:
                    fail_count += 1
                    failed_chats.append(f"{chat_id}: {str(e)[:30]}")
                    LOGGER.error("Broadcast failed to %s: %s", chat_id, e)

            # Update status message
            result_text = (
                f"✅ <b>Broadcast Complete</b>\n\n"
                f"Sent: {success_count}/{len(target_chats)}\n"
                f"Failed: {fail_count}"
            )
            if failed_chats and len(failed_chats) <= 5:
                result_text += "\n\nFailed chats:\n" + "\n".join([f"  • {fc}" for fc in failed_chats])
            elif failed_chats:
                result_text += f"\n\nFailed chats: {len(failed_chats)} (check logs)"

            await status_msg.edit_text(result_text, parse_mode="HTML")

            LOGGER.info(
                "%s:%s broadcast message to %d chats (success: %d, failed: %d)",
                message.from_user.id,
                f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
                len(target_chats),
                success_count,
                fail_count,
            )

        except (TelegramBadRequest, ValueError) as e:
            LOGGER.error("%s:%s Error in broadcast_message: %s", message.from_user.id, f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!", e)
            await message.reply(f"Error: {e}")

    @DP.callback_query(lambda c: c.data.startswith("broadcast_"))
    async def handle_broadcast_callback(callback_query: CallbackQuery):
        """Handle broadcast confirmation/cancellation."""
        try:
            parts = callback_query.data.split("_")
            action = parts[1]  # confirm, final, or cancel
            broadcast_id = int(parts[2])

            if not hasattr(DP, 'pending_broadcasts') or broadcast_id not in DP.pending_broadcasts:
                await callback_query.answer("Broadcast expired or not found.", show_alert=True)
                await callback_query.message.edit_reply_markup(reply_markup=None)
                return

            broadcast_data = DP.pending_broadcasts.get(broadcast_id)

            # Verify admin
            if callback_query.from_user.id != broadcast_data["admin_id"]:
                await callback_query.answer("Only the admin who initiated can confirm.", show_alert=True)
                return

            if action == "cancel":
                DP.pending_broadcasts.pop(broadcast_id, None)
                await callback_query.message.edit_text("❌ Broadcast cancelled.")
                await callback_query.answer("Cancelled.")
                return

            if action == "confirm":
                # First level confirmation passed - now require text confirmation
                target_chats = broadcast_data["chats"]
                broadcast_text = broadcast_data["text"]
                
                # Mark as awaiting final confirmation
                broadcast_data["awaiting_text_confirm"] = True
                
                cancel_kb = KeyboardBuilder()
                cancel_kb.add(
                    InlineKeyboardButton(text="❌ Cancel Broadcast", callback_data=f"broadcast_cancel_{broadcast_id}")
                )
                
                await callback_query.message.edit_text(
                    f"⚠️ <b>FINAL CONFIRMATION REQUIRED</b>\n\n"
                    f"You are about to send a message to <b>{len(target_chats)}</b> chats.\n\n"
                    f"<b>Message preview:</b>\n<i>{html.escape(broadcast_text[:200])}{'...' if len(broadcast_text) > 200 else ''}</i>\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚠️ To confirm, type exactly:\n"
                    f"<code>CONFIRM BROADCAST {broadcast_id}</code>\n\n"
                    f"Or click Cancel below.",
                    parse_mode="HTML",
                    reply_markup=cancel_kb.as_markup(),
                )
                await callback_query.answer("Type confirmation phrase to proceed.")
                return

            # action == "final" - this shouldn't be hit via callback anymore
            await callback_query.answer("Use text confirmation.", show_alert=True)

        except (TelegramBadRequest, ValueError) as e:
            LOGGER.error("Error in handle_broadcast_callback: %s", e)
            await callback_query.answer(f"Error: {e}", show_alert=True)

    @DP.message(lambda m: superadmin_filter(m) and m.text and m.text.startswith("CONFIRM BROADCAST"))
    async def handle_broadcast_text_confirm(message: Message):
        """Handle text confirmation for broadcast."""
        try:
            # Parse: CONFIRM BROADCAST <broadcast_id>
            parts = message.text.split()
            if len(parts) != 3:
                await message.reply("Invalid confirmation format.")
                return
            
            try:
                broadcast_id = int(parts[2])
            except ValueError:
                await message.reply("Invalid broadcast ID.")
                return

            if not hasattr(DP, 'pending_broadcasts') or broadcast_id not in DP.pending_broadcasts:
                await message.reply("Broadcast expired or not found. Start a new /broadcast command.")
                return

            broadcast_data = DP.pending_broadcasts.pop(broadcast_id)

            # Verify admin and that text confirmation was requested
            if message.from_user.id != broadcast_data["admin_id"]:
                await message.reply("You are not authorized to confirm this broadcast.")
                return

            if not broadcast_data.get("awaiting_text_confirm"):
                await message.reply("This broadcast was not awaiting text confirmation.")
                return

            # Execute broadcast
            target_chats = broadcast_data["chats"]
            broadcast_text = broadcast_data["text"]

            status_msg = await message.reply(f"📤 Broadcasting to {len(target_chats)} chats...")

            success_count = 0
            fail_count = 0
            failed_chats = []

            for chat_id in target_chats:
                try:
                    await safe_send_message(
                        BOT,
                        chat_id,
                        broadcast_text,
                        LOGGER,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                    success_count += 1
                except TelegramBadRequest as e:
                    fail_count += 1
                    failed_chats.append(f"{chat_id}: {str(e)[:30]}")
                    LOGGER.error("Broadcast failed to %s: %s", chat_id, e)

            # Update with results
            result_text = (
                f"✅ <b>Broadcast Complete</b>\n\n"
                f"Sent: {success_count}/{len(target_chats)}\n"
                f"Failed: {fail_count}"
            )
            if failed_chats and len(failed_chats) <= 5:
                result_text += "\n\nFailed chats:\n" + "\n".join([f"  • {fc}" for fc in failed_chats])
            elif failed_chats:
                result_text += f"\n\nFailed chats: {len(failed_chats)} (check logs)"

            await status_msg.edit_text(result_text, parse_mode="HTML")

            LOGGER.info(
                "%s:%s broadcast CONFIRMED via text to %d chats (success: %d, failed: %d)",
                message.from_user.id,
                f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!",
                len(target_chats),
                success_count,
                fail_count,
            )

        except (TelegramBadRequest, ValueError) as e:
            LOGGER.error("%s:%s Error in handle_broadcast_text_confirm: %s", message.from_user.id, f"@{message.from_user.username}" if message.from_user.username else "!UNDEFINED!", e)
            await message.reply(f"Error: {e}")

    @DP.message(Command("unban"), F.chat.id == ADMIN_GROUP_ID)
    async def unban_user(message: Message):
        """Function to unban the user with userid in all channels listed in CHANNEL_NAMES."""
        try:
            command_args = message.text.split()
            LOGGER.debug("Command arguments received: %s", command_args)

            if len(command_args) < 2:
                raise ValueError("Please provide the user ID to unban.")

            user_id = int(command_args[1])
            LOGGER.debug("%d - User ID to unban", user_id)

            # Get username before removing from dicts
            user_name_data = active_user_checks_dict.get(user_id) or banned_users_dict.get(user_id)
            user_name = "!UNDEFINED!"
            if isinstance(user_name_data, dict):
                user_name = str(user_name_data.get("username", "!UNDEFINED!")).lstrip("@")
            elif isinstance(user_name_data, str):
                user_name = (
                    user_name_data.lstrip("@")
                    if user_name_data != "None"
                    else "!UNDEFINED!"
                )

            # Cancel any active watchdog for this user
            await cancel_named_watchdog(user_id, user_name)

            # remove from banned and checks dicts
            if user_id in active_user_checks_dict:
                del active_user_checks_dict[user_id]
            if user_id in banned_users_dict:
                del banned_users_dict[user_id]

            # Mark monitoring as ended and user as legit in baselines DB
            update_user_baseline_status(CONN, user_id, monitoring_active=False, is_legit=True)

            # Mark user as legit in database
            admin_id = message.from_user.id
            admin_username = message.from_user.username
            try:
                CURSOR.execute(
                    """
                    INSERT OR REPLACE INTO recent_messages
                    (chat_id, message_id, user_id, user_name, user_first_name, user_last_name, received_date, new_chat_member, left_chat_member)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ADMIN_GROUP_ID,
                        message.message_id,
                        user_id,
                        user_name if user_name != "!UNDEFINED!" else None,
                        None,
                        None,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        1,
                        1,
                    ),
                )
                CONN.commit()
                LOGGER.info(
                    "\033[92m%s:@%s marked as legitimate in database by admin %s:@%s\033[0m",
                    user_id,
                    user_name,
                    admin_id,
                    admin_username,
                )
            except sqlite3.Error as db_err:
                LOGGER.error(
                    "Database error while marking user %d as legit: %s", user_id, db_err
                )

            # Remove from P2P network spam list
            try:
                p2p_removed = await remove_spam_from_2p2p(user_id, LOGGER)
                if p2p_removed:
                    LOGGER.info("\033[92m%d removed from P2P spam list\033[0m", user_id)
                else:
                    LOGGER.warning("\033[93m%d could not be removed from P2P spam list\033[0m", user_id)
            except (aiohttp.ClientError, asyncio.TimeoutError) as p2p_e:
                LOGGER.error("Failed to remove user %d from P2P: %s", user_id, p2p_e)

            for channel_name in CHANNEL_NAMES:
                channel_id = get_channel_id_by_name(CHANNEL_DICT, channel_name)
                if channel_id:
                    try:
                        await BOT.unban_chat_member(
                            chat_id=channel_id, user_id=user_id, only_if_banned=True
                        )
                        LOGGER.info(
                            "Unbanned user %d in channel %s (ID: %d)",
                            user_id,
                            channel_name,
                            channel_id,
                        )
                    except (TelegramBadRequest, TelegramForbiddenError) as e:
                        LOGGER.error(
                            "Failed to unban user %d in channel %s (ID: %d): %s",
                            user_id,
                            channel_name,
                            channel_id,
                            e,
                        )

            await message.reply(
                f"User {user_id} (@{user_name}) has been unbanned in all specified channels and marked as legitimate."
            )
            
            # Notify tech group
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                f"User {user_id} (@{user_name}) unbanned by admin {admin_id}:@{admin_username}. Marked as legitimate.",
                LOGGER,
                message_thread_id=TECHNO_ADMIN,
            )
        except ValueError as ve:
            await message.reply(str(ve))
        except (TelegramBadRequest, sqlite3.Error) as e:  # Note:: Specify more specific exception types
            LOGGER.error("Error in unban_user: %s", e)
            await message.reply("An error occurred while trying to unban the user.")

    @DP.callback_query(lambda c: c.data.startswith("stopchecks_"))
    async def stop_checks(callback_query: CallbackQuery):
        """Function to stop checks for the user and mark them as legit."""
        try:
            _prefix, user_id_legit_str, orig_chat_id_str, orig_message_id_str = (
                callback_query.data.split("_")
            )
            user_id_legit = int(user_id_legit_str)
            orig_chat_id = int(orig_chat_id_str)
            orig_message_id = int(orig_message_id_str)
        except ValueError as e:
            LOGGER.error(
                "Invalid callback data for stop_checks: %s, Error: %s",
                callback_query.data,
                e,
            )
            await callback_query.answer(
                "Invalid data format for stop_checks.", show_alert=True
            )
            return

        button_pressed_by = callback_query.from_user.username
        admin_id = callback_query.from_user.id

        user_name_data = active_user_checks_dict.get(user_id_legit)
        user_name = "!UNDEFINED!"
        if isinstance(user_name_data, dict):
            raw_username = user_name_data.get("username")
            if raw_username and raw_username != "None" and str(raw_username) != "None":
                user_name = str(raw_username).lstrip("@")
        elif isinstance(user_name_data, str):
            user_name = (
                user_name_data.lstrip("@")
                if user_name_data != "None"
                else "!UNDEFINED!"
            )

        lols_link = f"https://t.me/oLolsBot?start={user_id_legit}"

        inline_kb = KeyboardBuilder()
        inline_kb.add(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))

        try:
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=inline_kb.as_markup(),
            )
        except TelegramBadRequest as e_edit:
            LOGGER.error(
                "Error editing message markup in stop_checks for user %s: %s",
                user_id_legit,
                e_edit,
            )

        _admin_display = f"@{button_pressed_by}" if button_pressed_by else "!UNDEFINED!"
        _user_display = f"@{user_name}" if user_name and user_name not in ("!UNDEFINED!", "None") else "!UNDEFINED!"
        LOGGER.info(
            "\033[95m%s:%s Identified as a legit user by admin %s:%s!!! Future checks cancelled...\033[0m",
            user_id_legit,
            _user_display,
            admin_id,
            _admin_display,
        )

        common_message_text = (
            f"Future checks for {_user_display} (<code>{user_id_legit}</code>) cancelled by Admin {_admin_display}. "
            f"User marked as legitimate. To re-check, use <code>/check {user_id_legit}</code>."
        )
        try:
            await safe_send_message(
                BOT,
                callback_query.message.chat.id,
                common_message_text,
                LOGGER,
                message_thread_id=callback_query.message.message_thread_id,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_to_message_id=callback_query.message.message_id,
            )
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                common_message_text,
                LOGGER,
                parse_mode="HTML",
                message_thread_id=TECHNO_ADMIN,
                disable_web_page_preview=True,
            )
        except TelegramBadRequest as e_send:
            LOGGER.error(
                "Error sending notification messages in stop_checks for user %s: %s",
                user_id_legit,
                e_send,
            )

        if user_id_legit in active_user_checks_dict:
            del active_user_checks_dict[user_id_legit]
            # Mark monitoring as ended and user as legit in baselines DB
            update_user_baseline_status(CONN, user_id_legit, monitoring_active=False, is_legit=True)
            task_cancelled = False
            for task in asyncio.all_tasks():
                if task.get_name() == str(user_id_legit):
                    task.cancel()
                    task_cancelled = True
                    LOGGER.info(
                        "%s:%s Watchdog task cancelled by admin %s:%s",
                        user_id_legit,
                        _user_display,
                        admin_id,
                        _admin_display,
                    )
                    break
            if not task_cancelled:
                LOGGER.warning(
                    "%s:%s Watchdog task not found for cancellation, though user was in active_user_checks_dict",
                    user_id_legit,
                    _user_display,
                )

            if len(active_user_checks_dict) > 3:
                active_user_checks_dict_last3_list = list(
                    active_user_checks_dict.items()
                )[-3:]
                active_user_checks_dict_last3_str = ", ".join(
                    [
                        f"{uid}: {str(uname.get('username', uname) if isinstance(uname, dict) else uname).lstrip('@')}"
                        for uid, uname in active_user_checks_dict_last3_list
                    ]
                )
                LOGGER.info(
                    "\033[92m%s:@%s removed from active checks dict by admin %s:@%s:\n\t\t\t%s... %d left\033[0m",
                    user_id_legit,
                    user_name,
                    admin_id,
                    button_pressed_by,
                    active_user_checks_dict_last3_str,
                    len(active_user_checks_dict),
                )
            else:
                LOGGER.info(
                    "\033[92m%s:@%s removed from active checks dict by admin %s:@%s:\n\t\t\t%s\033[0m",
                    user_id_legit,
                    user_name,
                    admin_id,
                    button_pressed_by,
                    active_user_checks_dict,
                )
        else:
            LOGGER.info(
                "%s:@%s was marked legit by %s(%s), but was not found in active_user_checks_dict. Checks might have already completed or been stopped.",
                user_id_legit,
                user_name,
                button_pressed_by,
                admin_id,
            )

        try:
            CURSOR.execute(
                """
                INSERT OR REPLACE INTO recent_messages
                (chat_id, message_id, user_id, user_name, user_first_name, user_last_name, received_date, new_chat_member, left_chat_member)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    orig_chat_id,
                    orig_message_id,
                    user_id_legit,
                    user_name if user_name != "!UNDEFINED!" else None,
                    None,
                    None,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    1,
                    1,
                ),
            )
            CONN.commit()
            LOGGER.info(
                "%s:%s Recorded/Updated legitimization status in DB, linked to original context %s/%s",
                user_id_legit,
                format_username_for_log(user_name),
                orig_chat_id,
                orig_message_id,
            )
        except sqlite3.Error as e_db:
            LOGGER.error(
                "%s:%s Error updating DB in stop_checks: %s",
                user_id_legit,
                format_username_for_log(user_name),
                e_db,
            )

        await callback_query.answer(
            "Checks stopped. User marked as legit.", show_alert=False
        )

    @DP.message(
        is_valid_message,
        F.content_type.in_(ALLOWED_CONTENT_TYPES),
    )  # exclude admins and technolog group, exclude join/left messages
    async def log_all_unhandled_messages(message: Message):
        """Function to log all unhandled messages to the technolog group and admin."""
        try:
            # Convert the Message object to a dictionary
            message_dict = message.model_dump(mode="json")
            full_formatted_message = json.dumps(
                message_dict, indent=4, ensure_ascii=False
            )  # Convert back to a JSON string with indentation and human-readable characters

            # process unhandled messages
            if len(full_formatted_message) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
                formatted_message = (
                    formatted_message[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
                )
            else:
                formatted_message = full_formatted_message
            # Check if the message was sent in a chat with the bot
            # and not directly to the bot private chat
            # skip bot private message logging to TECHNOLOG group
            if message.chat.type in ["group", "supergroup", "channel"]:

                # logger.debug(f"Received UNHANDLED message object:\n{message}")

                # Send unhandled message to the technolog group
                # Intentionally not sending the raw object text; we forward the message instead
                await message.forward(
                    TECHNOLOG_GROUP_ID, message_thread_id=TECHNO_UNHANDLED
                )  # forward all unhandled messages to technolog group

                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    formatted_message,
                    LOGGER,
                    message_thread_id=TECHNO_UNHANDLED,
                )
                # LOGGER.debug(
                #     "\nReceived message object:\n %s\n",
                #     formatted_message,
                # )
            elif (
                # allow /start command only in private chat with bot
                message.chat.type == "private"
                and message.text == "/start"
            ):
                # /start easteregg
                await message.reply(
                    "Everything that follows is a result of what you see here.\n I'm sorry. My responses are limited. You must ask the right questions.",
                )

            # LOGGER.debug("Received message %s", message)
            LOGGER.debug("-----------UNHANDLED MESSAGE INFO-----------")
            LOGGER.debug("From ID: %s", message.from_user.id)
            LOGGER.debug("From username: %s", message.from_user.username)
            LOGGER.debug("From first name: %s", message.from_user.first_name)

            LOGGER.debug("Message ID: %s", message.message_id)
            LOGGER.debug("Message from chat title: %s", message.chat.title)
            LOGGER.debug("Message Chat ID: %s", message.chat.id)
            LOGGER.debug("Message JSON:\n%s", full_formatted_message)
            LOGGER.debug("-----------END OF UNHANDLED MESSAGE INFO-----------")

            user_id = message.from_user.id
            user_firstname = message.from_user.first_name
            user_lastname = (
                message.from_user.last_name if message.from_user.last_name else ""
            )
            user_full_name = html.escape(user_firstname + user_lastname)
            user_name = (
                message.from_user.username
                if message.from_user.username
                else user_full_name
            )

            bot_received_message = (
                f" Message received in chat {message.chat.title} ({message.chat.id})\n"
                f" Message chat username: @{message.chat.username}\n"
                f" From user {user_full_name}\n"
                f" Profile links:\n"
                f"   ├ <a href='tg://user?id={user_id}'>{user_full_name} ID based profile link</a>\n"
                f"   ├ <a href='tg://openmessage?user_id={user_id}'>Android</a>\n"
                f"   ├ <a href='https://t.me/@id{user_id}'>IOS (Apple)</a>\n"
                f"   └ <a href='tg://resolve?domain={user_name}'>@{user_name}</a>\n"
            )

            # Create an inline keyboard with two buttons
            inline_kb = KeyboardBuilder()
            button1 = InlineKeyboardButton(
                text="SRY",
                callback_data="button_sry",
            )
            button2 = InlineKeyboardButton(
                text="END",
                callback_data="button_end",
            )
            button3 = InlineKeyboardButton(
                text="RND",
                callback_data="button_rnd",
            )
            inline_kb.add(button1, button2, button3)

            _reply_message = (
                f"Received message from {message.from_user.first_name}:\n{bot_received_message}\n"
                f"I'm sorry. My responses are limited. You must ask the right questions.\n"
            )

            # _reply_message = f"Received message from {message.from_user.first_name}:\n{bot_received_message}\n"

            # Send the message with the inline keyboard
            await safe_send_message(
                BOT,
                ADMIN_USER_ID,
                _reply_message,
                LOGGER,
                reply_markup=inline_kb.as_markup(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

            admin_message = await BOT.forward_message(
                ADMIN_USER_ID, message.chat.id, message.message_id
            )

            # Store the mapping of unhandled message to admin's message
            # Note:: Move unhandled_messages storage to DB
            unhandled_messages[admin_message.message_id] = [
                message.chat.id,
                message.message_id,
                message.from_user.first_name,
            ]

            return

        except (TelegramBadRequest, sqlite3.Error) as e:
            LOGGER.error("Error in log_all_unhandled_messages function: %s", e)
            await message.reply(f"Error: {e}")

    async def simulate_admin_reply(
        original_message_chat_id, original_message_chat_reply_id, response_text
    ):
        """Simulate an admin reply with the given response text."""
        await safe_send_message(
            BOT,
            original_message_chat_id,
            response_text,
            LOGGER,
            reply_to_message_id=original_message_chat_reply_id,
        )

    @DP.callback_query(
        # lambda c: c.data in ["button_sry", "button_end", "button_rnd"]
        lambda c: c.data.startswith("button_")
    )
    async def process_callback(callback_query: CallbackQuery):
        """Function to process the callback query for the easter egg buttons."""
        # LOGGER.debug("Callback query received: %s", callback_query)
        try:
            # Determine the response based on the button pressed
            if callback_query.data == "button_sry":
                response_text = "I'm sorry. My responses are limited. You must ask the right questions."
            elif callback_query.data == "button_end":
                response_text = (
                    "That, detective, is the right question. Program terminated."
                )
            elif callback_query.data == "button_rnd":
                motd = (
                    "That, detective, is the right question. Program terminated.\n"
                    "If the laws of physics no longer apply in the future… God help you.\n"
                    "Well done. Here are the test results: You are a horrible person. I'm serious, that's what it says: 'A horrible person.' We weren't even testing for that!\n"
                    "William Shakespeare did not exist. His plays were masterminded in 1589 by Francis Bacon, who used a Ouija board to enslave play-writing ghosts.\n"
                    "The square root of rope is string.\n"
                    "While the submarine is vastly superior to the boat in every way, over 97 percent of people still use boats for aquatic transportation.\n"
                    "The Adventure Sphere is a blowhard and a coward.\n"
                    "Remember When The Platform Was Sliding Into The Fire Pit, And I Said 'Goodbye,' And You Were Like 'No Way!' And Then I Was All, 'We Pretended We Were Going To Murder You.' That Was Great.\n"
                    "It Made Shoes For Orphans. Nice Job Breaking It. Hero.\n"
                    "The Birth Parents You Are Trying To Reach Do Not Love You.\n"
                    "Don’t Believe Me? Here, I’ll Put You on: [Hellooo!] That’s You! That’s How Dumb You Sound.\n"
                    "Nobody But You Is That Pointlessly Cruel.\n"
                    "I'm Afraid You’re About To Become The Immediate Past President Of The Being Alive Club.\n"
                    "How Are You Holding Up? Because I’m A Potato.\n"
                    "If You Become Light Headed From Thirst, Feel Free To Pass Out.\n"
                    "Any Feelings You Think It Has For You Are Simply By-Products Of Your Sad, Empty Life.\n"
                    "-Не шалю, никого не трогаю, починяю примус,- недружелюбно насупившись, проговорил бот, - и еще считаю своим долгом предупредить, что бот древнее и неприкосновенное животное.\n"
                )
                # Split the motd string into individual lines
                motd_lines = motd.split("\n")
                # Select a random line
                random_motd = random.choice(motd_lines)
                # Assign the selected line to a variable
                response_text = random_motd
            else:
                response_text = "I'm sorry. My responses are limited. You must ask the right questions."

            # Simulate admin reply
            message_id_to_reply = (
                int(callback_query.message.message_id) + 1
            )  # shift the message ID by 1 since we send original message right after banner
            if message_id_to_reply in unhandled_messages:
                (
                    original_message_chat_id,
                    original_message_chat_reply_id,
                    original_message_user_name,
                ) = unhandled_messages[message_id_to_reply]

                # Simulate the admin reply
                await simulate_admin_reply(
                    original_message_chat_id,
                    original_message_chat_reply_id,
                    response_text,
                )

                # Reply with the predetermined sentence
                await safe_send_message(
                    BOT,
                    callback_query.message.chat.id,
                    "Replied to " + original_message_user_name + ": " + response_text,
                    LOGGER,
                )

                # Edit the original message to remove the buttons
                await BOT.edit_message_reply_markup(
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.message_id,
                    reply_markup=None,
                )

        except TelegramBadRequest as e:
            LOGGER.error("Error in process_callback function: %s", e)

        # Acknowledge the callback query
        await callback_query.answer()

    @DP.callback_query(
        # MODIFIED: Renamed callback prefixes and adjusted lambda
        lambda c: c.data.startswith("suspiciousglobalban_")
        or c.data.startswith("suspiciousban_")
        or c.data.startswith("suspiciousdelmsg_")
        or c.data.startswith("suspiciousactions_")
        or c.data.startswith("suspiciouscancel_")
        or c.data.startswith("confirmdelmsg_")
        or c.data.startswith("canceldelmsg_")
        or c.data.startswith("confirmban_")
        or c.data.startswith("cancelban_")
        or c.data.startswith("confirmglobalban_")
        or c.data.startswith("cancelglobalban_")
    )
    async def handle_suspicious_sender(callback_query: CallbackQuery):
        """Function to handle the suspicious sender."""
        # MODIFIED: Adjusted parsing for single-word prefixes and data extraction
        data = callback_query.data
        parts = data.split("_")

        action_prefix = parts[0]
        susp_chat_id_str = parts[1]
        susp_message_id_str = parts[2]
        susp_user_id_str = parts[3]

        susp_user_id = int(susp_user_id_str)
        susp_message_id = int(susp_message_id_str)
        susp_chat_id = int(susp_chat_id_str)

        # If user pressed global cancel/close in expanded actions menu, collapse back to original single Actions button layout
        if action_prefix == "suspiciouscancel":
            lols_link = f"https://t.me/oLolsBot?start={susp_user_id}"
            collapsed_kb = KeyboardBuilder()
            collapsed_kb.add(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))
            collapsed_kb.add(
                InlineKeyboardButton(
                    text="⚙️ Actions (Ban / Delete) ⚙️",
                    callback_data=f"suspiciousactions_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                )
            )
            collapsed_kb.add(
                InlineKeyboardButton(
                    text="✅ Mark as Legit",
                    callback_data=f"stopchecks_{susp_user_id}_{susp_chat_id}_{susp_message_id}",
                )
            )
            try:
                await BOT.edit_message_reply_markup(
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.message_id,
                    reply_markup=collapsed_kb.as_markup(),
                )
            except TelegramBadRequest as e:  # noqa
                LOGGER.debug("Failed to collapse suspicious actions menu: %s", e)
            await callback_query.answer("Menu closed.")
            return

        # If the consolidated actions button was pressed, expand available actions and return
        if action_prefix == "suspiciousactions":
            susp_user_id = int(susp_user_id_str)
            susp_message_id = int(susp_message_id_str)
            susp_chat_id = int(susp_chat_id_str)
            lols_link = f"https://t.me/oLolsBot?start={susp_user_id}"
            expand_kb = KeyboardBuilder()
            expand_kb.add(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))
            expand_kb.add(
                InlineKeyboardButton(
                    text="🌐 Global Ban",
                    callback_data=f"suspiciousglobalban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
                InlineKeyboardButton(
                    text="🚫 Ban User",
                    callback_data=f"suspiciousban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
            )
            expand_kb.add(
                InlineKeyboardButton(
                    text="🗑 Delete Msg",
                    callback_data=f"suspiciousdelmsg_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                )
            )
            # Global cancel button to revert view
            expand_kb.add(
                InlineKeyboardButton(
                    text="🔙 Cancel / Close",
                    callback_data=f"suspiciouscancel_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                )
            )
            try:
                await BOT.edit_message_reply_markup(
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.message_id,
                    reply_markup=expand_kb.as_markup(),
                )
            except TelegramBadRequest as e:  # noqa
                LOGGER.error("Failed to expand suspicious actions keyboard: %s", e)
            await callback_query.answer()
            return

        # Determine 'comand' (action) based on the prefix
        comand = ""
        if action_prefix == "suspiciousglobalban":
            comand = "globalban"
        elif action_prefix == "suspiciousban":
            comand = "ban"
        elif action_prefix == "suspiciousdelmsg":
            comand = "delmsg"
        elif action_prefix == "confirmglobalban":
            comand = "confirmglobalban"
        elif action_prefix == "cancelglobalban":
            comand = "cancelglobalban"
        elif action_prefix == "confirmban":
            comand = "confirmban"
        elif action_prefix == "cancelban":
            comand = "cancelban"
        elif action_prefix == "confirmdelmsg":
            comand = "confirmdelmsg"
        elif action_prefix == "canceldelmsg":
            comand = "canceldelmsg"
        else:
            LOGGER.error("Unknown prefix in handle_suspicious_sender: %s", action_prefix)
            await callback_query.answer(
                "Internal error processing action.", show_alert=True
            )
            return

        susp_chat_title = CHANNEL_DICT.get(susp_chat_id, "!UNKNOWN!")
        admin_id = callback_query.from_user.id
        admin_username = callback_query.from_user.username if callback_query.from_user.username else None
        callback_answer = None

        # Unpack user_name
        susp_user_name_dict = active_user_checks_dict.get(susp_user_id, "!UNDEFINED!")
        # check if user_name_dict is a dict
        if isinstance(susp_user_name_dict, dict):
            _uname = susp_user_name_dict.get("username")
            susp_user_name = str(_uname).lstrip("@") if _uname and str(_uname) not in ["None", "0"] else "!UNDEFINED!"
        else:
            susp_user_name = susp_user_name_dict if susp_user_name_dict and str(susp_user_name_dict) not in ["None", "0"] else "!UNDEFINED!"

        # create unified message link (used in action confirmation message)
        # Note: susp_message_id = 0 indicates a join/event-based report with no actual message
        # When susp_message_id > 0, it's a real message ID that can be linked to
        is_real_message_id = susp_message_id > 0
        message_link = construct_message_link([susp_chat_id, susp_message_id, None]) if is_real_message_id else None
        # create lols check link
        lols_link = f"https://t.me/oLolsBot?start={susp_user_id}"

        # Create the inline keyboard
        inline_kb = KeyboardBuilder()
        inline_kb.add(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))

        if comand == "globalban":
            inline_kb.add(
                InlineKeyboardButton(
                    text="Confirm global ban",
                    callback_data=f"confirmglobalban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
                InlineKeyboardButton(
                    text="Cancel global ban",
                    callback_data=f"cancelglobalban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
            )
            # remove buttons from the admin group and add cancel/confirm buttons
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=inline_kb.as_markup(),
            )
            return
        elif comand == "ban":
            inline_kb.add(
                InlineKeyboardButton(
                    text="Confirm ban",
                    callback_data=f"confirmban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
                InlineKeyboardButton(
                    text="Cancel ban",
                    callback_data=f"cancelban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
            )
            # remove buttons from the admin group and add cancel/confirm buttons
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=inline_kb.as_markup(),
            )
            return
        elif comand == "delmsg":
            inline_kb.add(
                InlineKeyboardButton(
                    text="Confirm delmsg",
                    callback_data=f"confirmdelmsg_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
                InlineKeyboardButton(
                    text="Cancel delmsg",
                    callback_data=f"canceldelmsg_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
            )
            # remove buttons from the admin group and add cancel/confirm buttons
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=inline_kb.as_markup(),
            )
            return

        # remove buttons from the admin group
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=inline_kb.as_markup(),
        )

        if comand == "confirmglobalban":
            # ban user in all chats
            # First, try to delete the original suspicious message (non-blocking)
            try:
                # Guard: skip deletion if message_id looks synthetic (epoch seconds or constructed report id)
                # Heuristic: if length >= 13 (milliseconds-like) or > 4_000_000_000 treat as synthetic
                if len(str(susp_message_id)) < 13 and susp_message_id < 4_000_000_000:
                    await BOT.delete_message(susp_chat_id, susp_message_id)
                else:
                    LOGGER.debug(
                        "Skip delete_message for synthetic suspicious message_id=%s chat_id=%s",
                        susp_message_id,
                        susp_chat_id,
                    )
            except TelegramBadRequest as e_del_orig:
                LOGGER.debug(
                    "Could not delete original suspicious message %s in chat %s: %s",
                    susp_message_id,
                    susp_chat_id,
                    e_del_orig,
                )
            
            try:
                # Bulk delete all known recent messages from this user across chats
                try:
                    CURSOR.execute(
                        "SELECT chat_id, message_id FROM recent_messages WHERE user_id = ?",
                        (susp_user_id,),
                    )
                    rows = CURSOR.fetchall()
                    deleted_cnt = 0
                    db_pairs = set()
                    for _c, _m in rows:
                        db_pairs.add((_c, _m))
                    for _c, _m in rows:
                        try:
                            # Skip obviously synthetic ids as above
                            if len(str(_m)) < 13 and _m < 4_000_000_000:
                                await BOT.delete_message(_c, _m)
                                deleted_cnt += 1
                        except TelegramBadRequest as _e_del:
                            LOGGER.debug(
                                "Unable to delete message %s in chat %s for global ban cleanup: %s",
                                _m,
                                _c,
                                _e_del,
                            )
                    # Also inspect active_user_checks_dict entry for any extra message references not in DB
                    try:
                        _active_entry = active_user_checks_dict.get(susp_user_id)
                        extra_attempts = 0
                        extra_deleted = 0
                        if isinstance(_active_entry, dict):
                            # Heuristically look for list-like values that may contain message tuples or ids
                            for _k, _v in _active_entry.items():
                                # Possible patterns: list of (chat_id, message_id) tuples OR list of message_ids with stored chat id
                                if isinstance(_v, list):
                                    for item in _v:
                                        _chat_id_candidate = None
                                        _msg_id_candidate = None
                                        if (
                                            isinstance(item, tuple)
                                            and len(item) >= 2
                                            and all(
                                                isinstance(x, int) for x in item[:2]
                                            )
                                        ):
                                            _chat_id_candidate, _msg_id_candidate = (
                                                item[0],
                                                item[1],
                                            )
                                        elif isinstance(item, int):
                                            # fall back: assume current suspicious chat
                                            _chat_id_candidate, _msg_id_candidate = (
                                                susp_chat_id,
                                                item,
                                            )
                                        if (
                                            _chat_id_candidate is None
                                            or _msg_id_candidate is None
                                        ):
                                            continue
                                        if (
                                            _chat_id_candidate,
                                            _msg_id_candidate,
                                        ) in db_pairs:
                                            continue  # already processed from DB
                                        extra_attempts += 1
                                        try:
                                            if (
                                                len(str(_msg_id_candidate)) < 13
                                                and _msg_id_candidate < 4_000_000_000
                                            ):
                                                await BOT.delete_message(
                                                    _chat_id_candidate,
                                                    _msg_id_candidate,
                                                )
                                                extra_deleted += 1
                                        except TelegramBadRequest as _e_del2:
                                            LOGGER.debug(
                                                "Active-check cleanup miss delete message %s in chat %s: %s",
                                                _msg_id_candidate,
                                                _chat_id_candidate,
                                                _e_del2,
                                            )
                        if extra_attempts:
                            LOGGER.info(
                                "%s:@%s globalban active-check extra cleanup attempted %d, deleted %d",
                                susp_user_id,
                                susp_user_name,
                                extra_attempts,
                                extra_deleted,
                            )
                    except (TelegramBadRequest, KeyError) as _e_active_extra:
                        LOGGER.debug(
                            "Globalban active-check extra cleanup skipped (user %s): %s",
                            susp_user_id,
                            _e_active_extra,
                        )
                    if rows:
                        LOGGER.info(
                            "%s:@%s globalban cleanup attempted %d messages, deleted %d",
                            susp_user_id,
                            susp_user_name,
                            len(rows),
                            deleted_cnt,
                        )
                except (TelegramBadRequest, sqlite3.Error) as _e_bulk:
                    LOGGER.error(
                        "Error bulk-deleting messages for global ban user %s:@%s: %s",
                        susp_user_id,
                        susp_user_name,
                        _e_bulk,
                    )
                # Ban user from all monitored chats
                success_count, _fail_count, total_count = await ban_user_from_all_chats(
                    susp_user_id,
                    susp_user_name,
                    CHANNEL_IDS,
                    CHANNEL_DICT,
                )
                # Log admin global ban action
                await log_profile_change(
                    user_id=susp_user_id,
                    username=susp_user_name,
                    context="admin-globalban",
                    chat_id=susp_chat_id,
                    chat_title=susp_chat_title,
                    changed=["GLOBAL BAN"],
                    old_values={},
                    new_values={},
                    photo_changed=False,
                )
                LOGGER.info(
                    "%s:@%s SUSPICIOUS banned globally by admin @%s(%s) - %d/%d chats",
                    susp_user_id,
                    susp_user_name,
                    admin_username,
                    admin_id,
                    success_count,
                    total_count,
                )
                callback_answer = f"User banned globally! ({success_count}/{total_count} chats) Messages deleted!"
            except TelegramBadRequest as e:
                LOGGER.error("Suspicious user not found: %s", e)
                callback_answer = "User not found in chat."
            # report spammer to the P2P spam check server
            await report_spam_2p2p(susp_user_id, LOGGER)
            _display_name = susp_user_name if susp_user_name and str(susp_user_name) not in ["None", "0", "!UNDEFINED!"] else None
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                f"{susp_user_id}:{f'@{_display_name}' if _display_name else '!UNDEFINED!'} reported to P2P spamcheck server.",
                LOGGER,
                parse_mode="HTML",
                disable_web_page_preview=True,
                message_thread_id=TECHNO_ADMIN,
            )
            # Cancel watchdog and update tracking dicts
            await cancel_named_watchdog(susp_user_id)
            
            # Update tracking dicts
            if susp_user_id in active_user_checks_dict:
                banned_users_dict[susp_user_id] = active_user_checks_dict.pop(susp_user_id, None)
            else:
                banned_users_dict[susp_user_id] = susp_user_name

        elif comand == "confirmban":
            # ban user in chat
            # First, try to delete the original suspicious message (non-blocking)
            try:
                if len(str(susp_message_id)) < 13 and susp_message_id < 4_000_000_000:
                    await BOT.delete_message(susp_chat_id, susp_message_id)
                else:
                    LOGGER.debug(
                        "Skip delete_message for synthetic suspicious message_id=%s chat_id=%s",
                        susp_message_id,
                        susp_chat_id,
                    )
            except TelegramBadRequest as e_del_orig:
                LOGGER.debug(
                    "Could not delete original suspicious message %s in chat %s: %s",
                    susp_message_id,
                    susp_chat_id,
                    e_del_orig,
                )
            
            # Delete all messages from this user in THIS chat only (non-blocking)
            try:
                CURSOR.execute(
                    "SELECT message_id FROM recent_messages WHERE user_id = ? AND chat_id = ?",
                    (susp_user_id, susp_chat_id),
                )
                rows = CURSOR.fetchall()
                chat_deleted = 0
                chat_db_ids = set(_mid for (_mid,) in rows)
                for (_mid,) in rows:
                    try:
                        if len(str(_mid)) < 13 and _mid < 4_000_000_000:
                            await BOT.delete_message(susp_chat_id, _mid)
                            chat_deleted += 1
                    except TelegramBadRequest as _e_del:
                        LOGGER.debug(
                            "Unable to delete message %s in chat %s for local ban cleanup: %s",
                            _mid,
                            susp_chat_id,
                            _e_del,
                        )
                # Active user checks extra messages possibly not flushed to DB
                try:
                    _active_entry = active_user_checks_dict.get(susp_user_id)
                    extra_attempts = 0
                    extra_deleted = 0
                    if isinstance(_active_entry, dict):
                        for _k, _v in _active_entry.items():
                            if isinstance(_v, list):
                                for item in _v:
                                    _msg_id_candidate = None
                                    if (
                                        isinstance(item, tuple)
                                        and len(item) >= 2
                                        and all(
                                            isinstance(x, int) for x in item[:2]
                                        )
                                    ):
                                        _chat_id_candidate, _msg_id_candidate = (
                                            item[0],
                                            item[1],
                                        )
                                        if _chat_id_candidate != susp_chat_id:
                                            continue
                                    elif isinstance(item, int):
                                        _msg_id_candidate = item
                                    else:
                                        continue
                                    if _msg_id_candidate in chat_db_ids:
                                        continue
                                    extra_attempts += 1
                                    try:
                                        if (
                                            len(str(_msg_id_candidate)) < 13
                                            and _msg_id_candidate < 4_000_000_000
                                        ):
                                            await BOT.delete_message(
                                                susp_chat_id, _msg_id_candidate
                                            )
                                            extra_deleted += 1
                                    except TelegramBadRequest as _e_del2:
                                        LOGGER.debug(
                                            "Local ban active-check cleanup failed msg %s chat %s: %s",
                                            _msg_id_candidate,
                                            susp_chat_id,
                                            _e_del2,
                                        )
                    if extra_attempts:
                        LOGGER.info(
                            "%s:@%s local ban active-check extra cleanup chat %s attempted %d, deleted %d",
                            susp_user_id,
                            susp_user_name,
                            susp_chat_id,
                            extra_attempts,
                            extra_deleted,
                        )
                except (TelegramBadRequest, KeyError) as _e_active_local:
                    LOGGER.debug(
                        "Local ban active-check extra cleanup skipped (user %s chat %s): %s",
                        susp_user_id,
                        susp_chat_id,
                        _e_active_local,
                    )
                if rows:
                    LOGGER.info(
                        "%s:@%s local ban cleanup in chat %s attempted %d messages, deleted %d",
                        susp_user_id,
                        susp_user_name,
                        susp_chat_id,
                        len(rows),
                        chat_deleted,
                    )
            except (TelegramBadRequest, sqlite3.Error) as _e_bulk:
                LOGGER.error(
                    "Error deleting messages for local ban user %s:@%s in chat %s: %s",
                    susp_user_id,
                    susp_user_name,
                    susp_chat_id,
                    _e_bulk,
                )
            
            # NOW BAN THE USER - this is the critical part that must execute
            try:
                await BOT.ban_chat_member(
                    chat_id=susp_chat_id,
                    user_id=susp_user_id,
                    revoke_messages=True,
                )
                await log_profile_change(
                    user_id=susp_user_id,
                    username=susp_user_name,
                    context="admin-ban",
                    chat_id=susp_chat_id,
                    chat_title=susp_chat_title,
                    changed=["BAN"],
                    old_values={},
                    new_values={},
                    photo_changed=False,
                )
                LOGGER.info(
                    "%s:@%s SUSPICIOUS banned in chat %s (%s) by admin @%s(%s)",
                    susp_user_id,
                    susp_user_name,
                    susp_chat_title,
                    susp_chat_id,
                    admin_username,
                    admin_id,
                )
                callback_answer = "User banned in ONE chat and the message were deleted.\nForward message to the bot to ban user everywhere!"
            except TelegramBadRequest as e:
                LOGGER.error("Suspicious user ban failed: %s", e)
                callback_answer = "User not found in chat or ban failed."
            
            # Report to P2P network
            await report_spam_2p2p(susp_user_id, LOGGER)
            
            # Cancel watchdog and update tracking dicts
            await cancel_named_watchdog(susp_user_id)
            if susp_user_id in active_user_checks_dict:
                banned_users_dict[susp_user_id] = active_user_checks_dict.pop(susp_user_id, None)
            else:
                banned_users_dict[susp_user_id] = susp_user_name
                
        elif comand == "confirmdelmsg":
            callback_answer = "User suspicious message were deleted.\nForward message to the bot to ban user everywhere!"
            # delete suspicious message
            try:
                if len(str(susp_message_id)) < 13 and susp_message_id < 4_000_000_000:
                    await BOT.delete_message(susp_chat_id, susp_message_id)
                else:
                    LOGGER.debug(
                        "Skip delete_message for synthetic suspicious message_id=%s chat_id=%s (delmsg)",
                        susp_message_id,
                        susp_chat_id,
                    )
                LOGGER.info(
                    "%s:@%s SUSPICIOUS message %d were deleted from chat (%s)",
                    susp_user_id,
                    susp_user_name,
                    susp_message_id,
                    susp_chat_id,
                )
                await log_profile_change(
                    user_id=susp_user_id,
                    username=susp_user_name,
                    context="admin-delmsg",
                    chat_id=susp_chat_id,
                    chat_title=susp_chat_title,
                    changed=["DELMSG"],
                    old_values={},
                    new_values={},
                    photo_changed=False,
                )
            except TelegramBadRequest as e:
                LOGGER.error("Suspicious message to delete not found: %s", e)
                callback_answer = "Suspicious message to delete not found."
        elif comand in ["canceldelmsg", "cancelban", "cancelglobalban"]:
            LOGGER.info("Action cancelled by admin: @%s(%s)", admin_username, admin_id)
            callback_answer = "Action cancelled."
            # Restore the collapsed keyboard with all buttons
            collapsed_kb = KeyboardBuilder()
            collapsed_kb.add(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))
            collapsed_kb.add(
                InlineKeyboardButton(
                    text="⚙️ Actions (Ban / Delete) ⚙️",
                    callback_data=f"suspiciousactions_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                )
            )
            collapsed_kb.add(
                InlineKeyboardButton(
                    text="✅ Mark as Legit",
                    callback_data=f"stopchecks_{susp_user_id}_{susp_chat_id}_{susp_message_id}",
                )
            )
            try:
                await BOT.edit_message_reply_markup(
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.message_id,
                    reply_markup=collapsed_kb.as_markup(),
                )
            except TelegramBadRequest as e:
                LOGGER.debug("Failed to restore collapsed keyboard after cancel: %s", e)

        await callback_query.answer(
            callback_answer,
            show_alert=True,
            cache_time=0,
        )

        # Build action confirmation message - only include message link if it's a real message (not a join event)
        message_origin_text = (
            f"Message origin: <a href='{message_link}'>{message_link}</a>\n"
            if message_link else "(join event - no message)\n"
        )
        bot_reply_action_message = (
            f"{callback_answer}\n"
            f"Suspicious user {f'@{susp_user_name}' if susp_user_name and susp_user_name != '!UNDEFINED!' else '!UNDEFINED!'} (<code>{susp_user_id}</code>) "
            f"{message_origin_text}"
            f"Action done by Admin {f'@{admin_username}' if admin_username else '!UNDEFINED!'}"
        )

        await safe_send_message(
            BOT,
            callback_query.message.chat.id,
            bot_reply_action_message,
            LOGGER,
            parse_mode="HTML",
            disable_web_page_preview=True,
            message_thread_id=callback_query.message.message_thread_id,
            reply_to_message_id=callback_query.message.message_id,
        )

        return

    @DP.message(is_admin_user_message, F.text)
    async def handle_admin_reply(message: Message):
        """Function to handle replies from the admin to unhandled messages."""
        try:
            # Check if the message is a reply to an unhandled message
            if (
                message.reply_to_message
                and message.reply_to_message.message_id in unhandled_messages
            ):
                [
                    original_message_chat_id,
                    original_message_chat_reply_id,
                    _original_message_sender_name,
                ] = unhandled_messages[message.reply_to_message.message_id]
                # LOGGER.info('Admin replied to message from %s: %s', original_message_sender_name, message.text)
                # Forward the admin's reply to the original sender
                _message_text = message.text
                if message.text.startswith("/") or message.text.startswith("\\"):
                    await safe_send_message(
                        BOT,
                        original_message_chat_id,
                        _message_text[1:],
                        LOGGER,
                    )
                else:
                    await safe_send_message(
                        BOT,
                        original_message_chat_id,
                        _message_text,
                        LOGGER,
                        reply_to_message_id=original_message_chat_reply_id,
                    )

                # Optionally, you can delete the mapping after the reply is processed
                # del unhandled_messages[message.reply_to_message.message_id]

        except TelegramBadRequest as e:
            LOGGER.error("Error in handle_admin_reply function: %s", e)
            await message.reply(f"Error: {e}")

    @DP.message(F.new_chat_members | F.left_chat_member)
    async def user_changed_message(message: Message):
        """Function to handle users joining or leaving the chat."""

        # handle user join/left events
        # with message.new_chat_members and message.left_chat_member
        # for chats with small amount of members

        # LOGGER.info("Users changed", message.new_chat_members, message.left_chat_member)

        LOGGER.info(
            "%s:@%s changed in user_changed_message function:\n\t\t\t%s --> %s, deleting system message...",
            message.from_user.id,
            message.from_user.username if message.from_user.username else "!UNDEFINED!",
            getattr(message, "left_chat_member", ""),
            getattr(message, "new_chat_members", ""),
        )

        # remove system message about user join/left where applicable
        try:
            await BOT.delete_message(
                message_id=message.message_id, chat_id=message.chat.id
            )
        except TelegramBadRequest as e:
            LOGGER.error("Message can't be deleted: %s", e)
            await safe_send_message(
                BOT,
                message.chat.id,
                "Sorry, I can't delete this message.",
                LOGGER,
                reply_to_message_id=message.message_id,
            )

    # scheduler to run the log_lists function daily at 04:00
    @aiocron.crontab("0 4 * * *", tz=ZoneInfo("Indian/Mauritius"))
    async def scheduled_log():
        """Function to schedule the log_lists function to run daily at 00:00."""
        await log_lists()
        # empty banned_users_dict
        banned_users_dict.clear()

    # NOTE: Night message check happens twice intentionally:
    #   1. First check (line ~5500) triggers perform_checks watchdog for new users
    #   2. Second check (line ~5590) logs additional messages from users already being watched
    #
    # NOTE: Message deletion on ban uses recent_messages DB + active_user_checks_dict entries
    #
    # === BACKLOG / FUTURE IMPROVEMENTS ===
    #
    # Spam detection improvements:
    # Note:: Hash banned spam messages and check signature for autoreport
    # Note:: Extract and store links/channels from banned messages for auto-blacklist matching
    # NOTE: Messages from users with IDs > 8.2B are flagged as suspicious (very new accounts)
    # Note:: Check for message edits and name changes after joining
    # Note:: Check profile photo date/DC location - warn if just uploaded
    #
    # Database improvements:
    # Note:: Move all temp storage to DB (messages, banned IDs, bot_unhandled, active_checks)
    # Note:: Fix database spammer store - use indexes instead of date
    # Note:: Store banned channels list in DB
    # Note:: Mark banned users in DB instead of file
    # Note:: Store sender_chat/forward_from_chat for triple ID checking
    #
    # Channel/Forward handling:
    # Note:: Autoban rogue channels
    # Note:: Manage forwards from banned users as spam
    #
    # Other:
    # Note:: Fix message_forward_date consistency in get_spammer_details and store_recent_messages
    # Note:: Implement scheduler for chat closure at night
    # NOTE: Admin can reply/send messages via /say, /reply, /broadcast commands

    # Uncomment this to get the chat ID of a group or channel
    # @dp.message(Command("getid"))
    # async def cmd_getid(message: Message):
    #     await message.answer(f"This chat's ID is: {message.chat.id}")

    async def main():
        """Main function to start the bot."""
        # Register startup and shutdown callbacks
        DP.startup.register(on_startup)
        DP.shutdown.register(on_shutdown)
        
        # Delete webhook and skip pending updates before polling
        await BOT.delete_webhook(drop_pending_updates=True)
        
        # Start polling with close_bot_session=False to prevent flood errors
        # We handle cleanup ourselves in on_shutdown
        await DP.start_polling(BOT, allowed_updates=ALLOWED_UPDATES, close_bot_session=False)
    
    try:
        asyncio.run(main())
    except TelegramRetryAfter as e:
        LOGGER.warning("Bot shutdown rate limited by Telegram (retry after %s seconds). Exiting anyway.", e.retry_after)
    finally:
        # Close SQLite connection
        CONN.close()
