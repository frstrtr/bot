#! module utils
"""utils.py
This module provides various utility functions for logging, message processing,
and spam detection in a Telegram bot.
Functions:
    construct_message_link(message_data_list: list) -> str:
        Construct a link to the original message (assuming it's a supergroup or channel).
    load_predetermined_sentences(txt_file: str):
        Load predetermined sentences from a plain text file, normalize to lowercase, remove extra spaces and punctuation marks,
        check for duplicates, rewrite the file excluding duplicates if any, and log the results.
    get_latest_commit_info():
        Function to get the latest commit info.
    extract_spammer_info(message: types.Message):
        Extract the spammer's details from the message.
    get_daily_spam_filename():
        Function to get the daily spam filename.
    get_inout_filename():
        Generate the filename for in/out events based on the current date.
    extract_status_change(chat_member_update: types.ChatMemberUpdated) -> Optional[Tuple[bool, bool]]:
        Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member' was a member of the chat
        and whether the 'new_chat_member' is a member of the chat.
    message_sent_during_night(message: types.Message):
        Function to check if the message was sent during the night.
    check_message_for_emojis(message: types.Message):
        Function to check if the message contains 5 or more emojis in a single line.
    check_message_for_capital_letters(message: types.Message):
        Function to check if the message contains 5 or more consecutive capital letters in a line, excluding URLs.
    has_custom_emoji_spam(message):
        Function to check if a message contains spammy custom emojis.
    format_spam_report(message: types.Message) -> str:
        Function to format the message one line for logging.
    extract_chat_id_and_message_id_from_link(message_link):
        Extract chat ID and message ID from a message link.
"""


import logging
import asyncio
import subprocess
import re
from datetime import datetime
from typing import Optional, Tuple
from enum import Enum

from sqlite3 import Connection, Cursor

import os
import sys
import aiohttp
import pytz
import emoji


# ============================================================================
# Offense Types - standardized values for ban/report tracking
# ============================================================================

class BanSource(str, Enum):
    """Ban source identifiers for tracking which system detected/banned the user.
    
    These can be combined (e.g., "lols+cas" if detected by multiple systems).
    Use build_ban_source() helper to create combined sources.
    """
    # External API detection
    LOLS = "lols"           # LOLS anti-spam database
    CAS = "cas"             # Combot Anti-Spam database  
    P2P = "p2p"             # P2P spamcheck network
    LOCAL = "local"         # Local spam database (127.0.0.1:8081)
    
    # Bot detection
    AUTOREPORT = "autoreport"   # Bot's automatic report system
    AUTOBAN = "autoban"         # Bot's automatic ban system
    
    # Manual actions
    ADMIN = "admin"         # Manually banned by admin
    
    @classmethod
    def combine(cls, *sources) -> str:
        """Combine multiple ban sources into a single string.
        
        Args:
            *sources: BanSource values or strings
            
        Returns:
            Combined source string (e.g., "lols+cas+p2p")
        """
        unique_sources = []
        for src in sources:
            val = src.value if isinstance(src, cls) else str(src)
            if val and val not in unique_sources:
                unique_sources.append(val)
        return "+".join(sorted(unique_sources)) if unique_sources else None


def build_ban_source(
    lols: bool = False,
    cas: bool = False, 
    p2p: bool = False,
    local: bool = False,
    admin: bool = False,
    autoreport: bool = False,
    autoban: bool = False,
) -> str:
    """Build a combined ban source string from detection flags.
    
    Args:
        lols: Detected by LOLS database
        cas: Detected by CAS database
        p2p: Detected by P2P network
        local: Detected by local database
        admin: Manually banned by admin
        autoreport: Bot's autoreport triggered
        autoban: Bot's autoban triggered
        
    Returns:
        Combined source string (e.g., "cas+lols+p2p") or None
        
    Example:
        >>> build_ban_source(lols=True, cas=True)
        'cas+lols'
        >>> build_ban_source(admin=True)
        'admin'
        >>> build_ban_source(lols=True, p2p=True, autoban=True)
        'autoban+lols+p2p'
    """
    sources = []
    if lols:
        sources.append(BanSource.LOLS.value)
    if cas:
        sources.append(BanSource.CAS.value)
    if p2p:
        sources.append(BanSource.P2P.value)
    if local:
        sources.append(BanSource.LOCAL.value)
    if admin:
        sources.append(BanSource.ADMIN.value)
    if autoreport:
        sources.append(BanSource.AUTOREPORT.value)
    if autoban:
        sources.append(BanSource.AUTOBAN.value)
    
    return "+".join(sorted(sources)) if sources else None


def parse_ban_source(source_str: str) -> dict:
    """Parse a combined ban source string back into individual flags.
    
    Args:
        source_str: Combined source string (e.g., "cas+lols+p2p")
        
    Returns:
        Dictionary with boolean flags for each source
        
    Example:
        >>> parse_ban_source("cas+lols+p2p")
        {'lols': True, 'cas': True, 'p2p': True, 'local': False, 'admin': False, ...}
    """
    sources = source_str.lower().split("+") if source_str else []
    return {
        "lols": "lols" in sources,
        "cas": "cas" in sources,
        "p2p": "p2p" in sources,
        "local": "local" in sources,
        "admin": "admin" in sources,
        "autoreport": "autoreport" in sources,
        "autoban": "autoban" in sources,
    }


def build_admin_ban_info(
    admin_id: int,
    admin_username: str = None,
    admin_first_name: str = None,
    admin_last_name: str = None,
) -> dict:
    """Build admin info dictionary for manual ban tracking.
    
    Args:
        admin_id: Telegram user ID of the admin
        admin_username: Admin's username (without @)
        admin_first_name: Admin's first name
        admin_last_name: Admin's last name
        
    Returns:
        Dictionary with admin profile info for storage in offense_details
        
    Example:
        >>> build_admin_ban_info(123456, "admin_user", "John", "Doe")
        {'admin_id': 123456, 'admin_username': 'admin_user', 'admin_name': 'John Doe'}
    """
    admin_name_parts = []
    if admin_first_name:
        admin_name_parts.append(admin_first_name)
    if admin_last_name:
        admin_name_parts.append(admin_last_name)
    
    return {
        "admin_id": admin_id,
        "admin_username": admin_username,
        "admin_name": " ".join(admin_name_parts) if admin_name_parts else None,
    }


def build_detection_details(
    lols_result: dict = None,
    cas_result: dict = None,
    p2p_result: dict = None,
    local_result: dict = None,
    admin_info: dict = None,
    additional_info: dict = None,
) -> str:
    """Build JSON string with detailed detection information.
    
    Args:
        lols_result: Raw response from LOLS API
        cas_result: Raw response from CAS API (includes offenses count)
        p2p_result: Raw response from P2P network
        local_result: Raw response from local DB
        admin_info: Admin info dict from build_admin_ban_info()
        additional_info: Any additional context
        
    Returns:
        JSON string for storage in offense_details field
        
    Example:
        >>> build_detection_details(
        ...     lols_result={"banned": True, "reason": "spam"},
        ...     cas_result={"ok": True, "result": {"offenses": 5}},
        ...     admin_info=build_admin_ban_info(123, "admin")
        ... )
        '{"lols": {"banned": true, ...}, "cas": {...}, "admin": {...}}'
    """
    import json
    
    details = {}
    
    if lols_result:
        details["lols"] = lols_result
    if cas_result:
        details["cas"] = cas_result
    if p2p_result:
        details["p2p"] = p2p_result
    if local_result:
        details["local"] = local_result
    if admin_info:
        details["admin"] = admin_info
    if additional_info:
        details["info"] = additional_info
    
    return json.dumps(details) if details else None


class OffenseType(str, Enum):
    """Standardized offense types for spam detection and ban tracking.
    
    Auto-ban triggers (immediate action):
        FAST_MESSAGE: Message within 10s of join
        SPAM_PATTERN: Matched spam dictionary pattern
        SPAM_SENTENCES: Matched predetermined spam sentences
        CUSTOM_EMOJI_SPAM: 5+ spammy custom emojis in message
        CAPS_EMOJI_SPAM: 5+ capital letters AND 5+ emojis combined
        VIA_INLINE_BOT: Message sent via inline bot
        NIGHT_MESSAGE: Message sent during suspicious hours
        LATENCY_BANNED: User was already banned but message squeezed through
        
    Bot mention triggers:
        BOT_MENTION: Mentioned @...bot in message
        BOT_MENTION_MONITORED: Bot mention by user under active monitoring
        BOT_MENTION_MISSED_JOIN: Bot mention by user whose join was missed
        
    Forward/Channel spam:
        FORWARDED_SPAM: Forwarded spam content from unknown source
        CHANNEL_SPAM: Spam via linked channel
        FORWARDED_CHANNEL_SPAM: Forwarded from banned channel
        
    Account-based triggers:
        HIGH_ID_SPAM: Very new account (ID > 8.2B) + spam indicators
        HIGH_ID_JOIN: Very new account flagged on join
        
    Content-based detection (suspicious thread):
        SUSPICIOUS_LINKS: Links/URLs in message
        SUSPICIOUS_MENTIONS: User mentions (@ mentions) in message
        SUSPICIOUS_PHONES: Phone numbers detected
        SUSPICIOUS_EMAILS: Email addresses detected
        SUSPICIOUS_BOT_COMMANDS: Bot commands in message
        HIDDEN_MENTIONS: Invisible/obfuscated chars in mentions
        
    Profile-based triggers:
        PROFILE_CHANGE_WATCH: Profile changed while under monitoring
        PROFILE_CHANGE_LEAVE: Profile changed between join and leave
        PROFILE_CHANGE_PERIODIC: Profile changed during periodic check
        
    External database detection:
        LOLS_BANNED: Detected by LOLS anti-spam database
        CAS_BANNED: Detected by CAS (Combot Anti-Spam) database
        P2P_BANNED: Detected by P2P spamcheck network
        LOCAL_DB_BANNED: Detected by local spam database
        
    Manual admin actions:
        ADMIN_BAN: Manually banned by admin
        ADMIN_REPORT: Reported by admin
        
    Join/Leave behavior:
        QUICK_LEAVE: Left chat within 1 minute of join
        JOIN_LEAVE_PATTERN: Suspicious join/leave pattern detected
        
    Week-old user monitoring:
        WEEK_OLD_SUSPICIOUS: User under week-old monitoring posted suspicious content
    """
    
    # Auto-ban triggers
    FAST_MESSAGE = "fast_message"
    SPAM_PATTERN = "spam_pattern"
    SPAM_SENTENCES = "spam_sentences"
    CUSTOM_EMOJI_SPAM = "custom_emoji_spam"
    CAPS_EMOJI_SPAM = "caps_emoji_spam"
    VIA_INLINE_BOT = "via_inline_bot"
    NIGHT_MESSAGE = "night_message"
    LATENCY_BANNED = "latency_banned"
    
    # Bot mention triggers
    BOT_MENTION = "bot_mention"
    BOT_MENTION_MONITORED = "bot_mention_monitored"
    BOT_MENTION_MISSED_JOIN = "bot_mention_missed_join"
    
    # Forward/Channel spam
    FORWARDED_SPAM = "forwarded_spam"
    CHANNEL_SPAM = "channel_spam"
    FORWARDED_CHANNEL_SPAM = "forwarded_channel_spam"
    
    # Account-based
    HIGH_ID_SPAM = "high_id_spam"
    HIGH_ID_JOIN = "high_id_join"
    
    # Content-based (suspicious)
    SUSPICIOUS_LINKS = "suspicious_links"
    SUSPICIOUS_MENTIONS = "suspicious_mentions"
    SUSPICIOUS_PHONES = "suspicious_phones"
    SUSPICIOUS_EMAILS = "suspicious_emails"
    SUSPICIOUS_BOT_COMMANDS = "suspicious_bot_commands"
    HIDDEN_MENTIONS = "hidden_mentions"
    SUSPICIOUS_CONTENT = "suspicious_content"  # Generic for multiple types
    
    # Profile-based
    PROFILE_CHANGE_WATCH = "profile_change_watch"
    PROFILE_CHANGE_LEAVE = "profile_change_leave"
    PROFILE_CHANGE_PERIODIC = "profile_change_periodic"
    
    # External database detection
    LOLS_BANNED = "lols_banned"
    CAS_BANNED = "cas_banned"
    P2P_BANNED = "p2p_banned"
    LOCAL_DB_BANNED = "local_db_banned"
    
    # Admin actions
    ADMIN_BAN = "admin_ban"
    ADMIN_REPORT = "admin_report"
    
    # Join/Leave behavior
    QUICK_LEAVE = "quick_leave"
    JOIN_LEAVE_PATTERN = "join_leave_pattern"
    
    # Week-old monitoring
    WEEK_OLD_SUSPICIOUS = "week_old_suspicious"


# Helper to get offense type from reason string
def classify_offense_from_reason(reason: str) -> str:
    """Classify offense type from a reason string.
    
    Args:
        reason: The ban/report reason string
        
    Returns:
        Matching OffenseType value or the original reason if no match
    """
    reason_lower = reason.lower() if reason else ""
    
    # Fast message detection
    if "10 second" in reason_lower or "10s" in reason_lower or "less then 10" in reason_lower:
        return OffenseType.FAST_MESSAGE.value
    
    # Spam patterns
    if "spam" in reason_lower and "sentence" in reason_lower:
        return OffenseType.SPAM_SENTENCES.value
    if "spam pattern" in reason_lower or "spam dict" in reason_lower:
        return OffenseType.SPAM_PATTERN.value
    
    # Custom emoji spam
    if "custom emoji" in reason_lower or "spammy custom emojis" in reason_lower:
        return OffenseType.CUSTOM_EMOJI_SPAM.value
    
    # Caps + emoji spam
    if "capital letter" in reason_lower and "emoji" in reason_lower:
        return OffenseType.CAPS_EMOJI_SPAM.value
    
    # Bot mention
    if "bot mention" in reason_lower:
        if "missed join" in reason_lower:
            return OffenseType.BOT_MENTION_MISSED_JOIN.value
        if "monitored" in reason_lower:
            return OffenseType.BOT_MENTION_MONITORED.value
        return OffenseType.BOT_MENTION.value
    if "@" in reason_lower and "bot" in reason_lower:
        return OffenseType.BOT_MENTION.value
    
    # Forwarded content
    if "forward" in reason_lower:
        if "channel" in reason_lower:
            return OffenseType.FORWARDED_CHANNEL_SPAM.value
        return OffenseType.FORWARDED_SPAM.value
    
    # Channel spam
    if "channel" in reason_lower and "spam" in reason_lower:
        return OffenseType.CHANNEL_SPAM.value
    
    # High ID
    if "high" in reason_lower and "id" in reason_lower:
        return OffenseType.HIGH_ID_SPAM.value
    if "> 8.2b" in reason_lower or ">8.2b" in reason_lower:
        return OffenseType.HIGH_ID_JOIN.value
    
    # Inline bot
    if "inline bot" in reason_lower or "via bot" in reason_lower:
        return OffenseType.VIA_INLINE_BOT.value
    
    # Night message
    if "night" in reason_lower:
        return OffenseType.NIGHT_MESSAGE.value
    
    # Latency
    if "latency" in reason_lower or "squizzed" in reason_lower:
        return OffenseType.LATENCY_BANNED.value
    
    # 1 hour entity spam
    if "1 hour" in reason_lower or "less then 1 hour" in reason_lower:
        if "link" in reason_lower or "url" in reason_lower:
            return OffenseType.SUSPICIOUS_LINKS.value
        if "mention" in reason_lower:
            return OffenseType.SUSPICIOUS_MENTIONS.value
        return OffenseType.SUSPICIOUS_CONTENT.value
    
    # Profile changes
    if "profile" in reason_lower and "change" in reason_lower:
        if "periodic" in reason_lower:
            return OffenseType.PROFILE_CHANGE_PERIODIC.value
        if "leave" in reason_lower:
            return OffenseType.PROFILE_CHANGE_LEAVE.value
        return OffenseType.PROFILE_CHANGE_WATCH.value
    
    # External databases
    if "lols" in reason_lower:
        return OffenseType.LOLS_BANNED.value
    if "cas" in reason_lower:
        return OffenseType.CAS_BANNED.value
    if "p2p" in reason_lower:
        return OffenseType.P2P_BANNED.value
    
    # Admin actions
    if "admin" in reason_lower and ("ban" in reason_lower or "report" in reason_lower):
        return OffenseType.ADMIN_BAN.value
    
    # Quick leave
    if ("left" in reason_lower or "leave" in reason_lower) and ("minute" in reason_lower or "quick" in reason_lower):
        return OffenseType.QUICK_LEAVE.value
    
    # Week-old monitoring
    if "week" in reason_lower and ("old" in reason_lower or "suspicious" in reason_lower):
        return OffenseType.WEEK_OLD_SUSPICIOUS.value
    
    # Default: return original reason
    return reason

from aiogram import types
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.exceptions import Unauthorized, BadRequest, RetryAfter

def initialize_logger(log_level="INFO"):
    """Initialize the logger."""

    # Configure logging to use UTF-8 encoding
    logger = logging.getLogger(__name__)
    if not logger.hasHandlers():
        log_level = getattr(logging, log_level.upper(), logging.INFO)
        logger.setLevel(log_level)  # Set the logging level based on the argument

        # Create handlers
        stream_handler = logging.StreamHandler(sys.stdout)
        file_handler = logging.FileHandler("bancop_BOT.log", encoding="utf-8")

        # Create a formatter and set it for all handlers
        # formatter = logging.Formatter("%(asctime)s - %(threadName)s - %(message)s")
        formatter = logging.Formatter("%(asctime)s - %(message)s")
        stream_handler.setFormatter(formatter)
        file_handler.setFormatter(formatter)

        # Ensure the stream handler uses UTF-8 encoding
        stream_handler.setStream(
            open(sys.stdout.fileno(), mode="w", encoding="utf-8", closefd=False)
        )

        # Add handlers to the logger
        logger.addHandler(stream_handler)
        logger.addHandler(file_handler)
    return logger


def construct_message_link(message_data_list: list) -> str:
    """Construct a link to the original message (assuming it's a supergroup or channel).
    Extract the chat ID and remove the '-100' prefix if it exists.

    Args:
        found_message_data (list): The spammer data extracted from the found message.
            [chatID, messageID, chatUsername]

    Returns:
        str: The constructed message link.
    """
    chat_id = str(message_data_list[0])
    message_id = message_data_list[1]
    chat_username = message_data_list[2]

    if chat_username:
        message_link = f"https://t.me/{chat_username}/{message_id}"
    else:
        if chat_id.startswith("-100"):
            chat_id = chat_id[4:]  # Remove leading -100 for public chats
        message_link = f"https://t.me/c/{chat_id}/{message_id}"

    return message_link


# ---------------------- Small reusable helpers ----------------------
def build_lols_url(user_id: int) -> str:
    """Return LOLS bot deep link for a given user id."""
    return f"https://t.me/oLolsBot?start={user_id}"


def make_lols_kb(user_id: int) -> InlineKeyboardMarkup:
    """Create a one-button keyboard with the LOLS check link.

    Button text must remain exactly as used elsewhere to preserve UX.
    """
    lols_url = build_lols_url(user_id)
    inline_kb = InlineKeyboardMarkup()
    inline_kb.add(InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_url))
    return inline_kb


async def safe_get_chat_name_username(bot, chat_id: int, logger=None):
    """Safely fetch chat title and username; return fallbacks on errors.

    Returns tuple: (title_or_default, username_or_default)
    """
    try:
        chat = await bot.get_chat(chat_id)
        title = getattr(chat, "title", None) or "!ROGUECHAT!"
        username = getattr(chat, "username", None) or "!@ROGUECHAT!"
        return title, username
    except (Unauthorized, BadRequest) as e:
        if logger:
            logger.warning(
                "Cannot get chat info for chat %s: %s. Using defaults.", chat_id, str(e)
            )
        return "!ROGUECHAT!", "!@ROGUECHAT!"


def get_forwarded_states(dp) -> dict:
    """Ensure and return dispatcher-level forwarded_reports_states dict."""
    states = dp.get("forwarded_reports_states")
    if states is None:
        states = {}
        dp["forwarded_reports_states"] = states
    return states


def set_forwarded_state(dp, report_id: int, state: dict):
    """Set/replace state for a report id in forwarded_reports_states."""
    states = get_forwarded_states(dp)
    states[report_id] = state
    dp["forwarded_reports_states"] = states


def get_forwarded_state(dp, report_id: int):
    """Get state for report id from forwarded_reports_states or None."""
    states = dp.get("forwarded_reports_states")
    if not states:
        return None
    return states.get(report_id)


async def safe_send_message(
    bot,
    chat_id: int,
    text: str,
    logger=None,
    retries: int = 2,
    retry_backoff: float = 1.2,
    **kwargs,
):
    """Safely call bot.send_message with simple RetryAfter handling.

    - Retries on aiogram RetryAfter using server-provided timeout.
    - Logs warnings/errors if a logger is provided.
    - Returns the Message on success, or None on final failure.
    """
    attempt = 0
    while True:
        try:
            return await bot.send_message(chat_id, text, **kwargs)
        except RetryAfter as e:
            wait = getattr(e, "timeout", 1) or 1
            if attempt < retries:
                if logger:
                    logger.warning(
                        "Rate limited on send_message to %s, retrying in %ss (attempt %s/%s)",
                        chat_id,
                        wait,
                        attempt + 1,
                        retries,
                    )
                await asyncio.sleep(wait * (retry_backoff ** attempt))
                attempt += 1
                continue
            else:
                if logger:
                    logger.error("Failed to send_message to %s after retries: %s", chat_id, e)
                return None
        except BadRequest as e:
            # Common harmless case when editing text with no changes; for send we still surface it
            if logger:
                logger.error("BadRequest sending message to %s: %s", chat_id, e)
            return None
        except Exception as e:
            if logger:
                logger.error("Unexpected error sending message to %s: %s", chat_id, e)
            return None


def load_predetermined_sentences(txt_file: str, logger):
    """Load predetermined sentences from a plain text file, normalize to lowercase,
    remove extra spaces and punctuation marks, check for duplicates, rewrite the file
    excluding duplicates if any, and log the results. Return None if the file doesn't exist.

    :param txt_file: str: The path to the plain text file containing predetermined sentences.
    """
    if not os.path.exists(txt_file):
        return None

    with open(txt_file, "r", encoding="utf-8") as file:
        lines = [line.strip().lower() for line in file if line.strip()]

    # Normalize lines by removing extra spaces and punctuation marks
    normalized_lines = [re.sub(r"[^\w\s]", "", line).strip() for line in lines]

    unique_lines = list(set(normalized_lines))
    duplicates = [line for line in normalized_lines if normalized_lines.count(line) > 1]

    # Check if there are duplicates or normalization changes
    if len(unique_lines) != len(lines) or lines != normalized_lines:
        # Rewrite the file with unique and normalized lines
        with open(txt_file, "w", encoding="utf-8") as file:
            for line in unique_lines:
                file.write(line + "\n")

        # Log the results
        logger.info(
            "\nNumber of lines after checking for duplicates: %s", len(unique_lines)
        )
        logger.info("Number of duplicate lines removed: %s", len(duplicates))
        if duplicates:
            logger.info("Contents of removed duplicate lines:")
            for line in set(duplicates):
                logger.info(line)
        else:
            logger.info("No duplicates found in spam dictionary.\n")
    else:
        logger.info(
            "No duplicates or normalization changes found. File not rewritten.\n"
        )

    return unique_lines


def get_latest_commit_info(logger):
    """Function to get the latest commit info."""
    try:
        _commit_info = (
            subprocess.check_output(["git", "show", "-s"]).decode("utf-8").strip()
        )
        return _commit_info
    except subprocess.CalledProcessError as e:
        logger.info("Error getting git commit info: %s", e)
        return None


def extract_spammer_info(message: types.Message):
    """Extract the spammer's details from the message.

    :param message: types.Message: The message to extract the spammer's details from."""
    if message.forward_from:
        first_name = message.forward_from.first_name or ""
        last_name = getattr(message.forward_from, "last_name", "") or ""
        user_id = getattr(message.forward_from, "id", None)
        return user_id, first_name, last_name

    if message.forward_from_chat:
        return None, message.forward_from_chat.title, ""

    names = (message.forward_sender_name or "").split(" ", 1)
    first_name = names[0] if names else ""
    last_name = names[1] if len(names) > 1 else ""
    # Check for the Deleted Account

    return None, first_name, last_name


def get_daily_spam_filename():
    """Function to get the daily spam filename."""
    # Get today's date
    today = datetime.now().strftime("%Y-%m-%d")
    # Construct the filename
    filename = f"daily_spam_{today}.txt"
    return filename


def get_inout_filename():
    """Generate the filename for in/out events based on the current date."""
    today = datetime.now().strftime("%d-%m-%Y")
    filename = f"inout_{today}.txt"
    return filename


def extract_status_change(
    chat_member_update: types.ChatMemberUpdated,
) -> Optional[Tuple[bool, bool]]:
    """Takes a ChatMemberUpdated instance and extracts whether the 'old_chat_member' was a member
    of the chat and whether the 'new_chat_member' is a member of the chat. Returns None, if
    the status didn't change.
    """
    old_status = chat_member_update.old_chat_member.status
    new_status = chat_member_update.new_chat_member.status

    if old_status == new_status:
        return None

    was_member = old_status in [
        types.ChatMemberStatus.MEMBER,
        types.ChatMemberStatus.OWNER,
        types.ChatMemberStatus.ADMINISTRATOR,
        types.ChatMemberStatus.RESTRICTED,
    ]
    is_member = new_status in [
        types.ChatMemberStatus.MEMBER,
        types.ChatMemberStatus.OWNER,
        types.ChatMemberStatus.ADMINISTRATOR,
        types.ChatMemberStatus.RESTRICTED,
    ]

    return was_member, is_member


def message_sent_during_night(message: types.Message):
    """Function to check if the message was sent during the night."""
    # Assume message.date is already a datetime object in UTC
    message_time = message.date

    # Convert the time to the user's timezone
    user_timezone = pytz.timezone("Indian/Mauritius")
    user_time = message_time.astimezone(user_timezone)

    # Get the current time in the user's timezone
    user_hour = user_time.hour

    # Check if the message was sent during the night
    return 1 <= user_hour < 6


def check_message_for_emojis(message: types.Message):
    """Function to check if the message contains 5 or more emojis in a single line."""
    # Check if the message contains text
    if message.text is None:
        return False

    # Split the message text into lines
    lines = message.text.split("\n")

    # Check each line for 5 or more emojis
    for line in lines:
        emojis = [char for char in line if emoji.is_emoji(char)]
        if len(emojis) >= 5:
            return True

    return False


def check_message_for_capital_letters(message: types.Message):
    """Function to check if the message contains 5 or more consecutive capital letters in a line, excluding URLs."""
    # Check if the message contains text
    if message.text is None:
        return False

    # Initialize a list to hold lines from the text
    lines = message.text.split("\n")

    # Regular expression to match URLs
    url_pattern = re.compile(r"https?://\S+|www\.\S+")

    # Regular expression to match 5 or more consecutive capital letters
    capital_pattern = re.compile(r"[A-Z]{5,}")

    # Check if any line contains 5 or more consecutive capital letters, excluding URLs
    for line in lines:
        # Remove URLs from the line
        line_without_urls = re.sub(url_pattern, "", line)
        # Check if the line contains 5 or more consecutive capital letters
        if capital_pattern.search(line_without_urls):
            return True

    return False


def has_custom_emoji_spam(message):
    """Function to check if a message contains spammy custom emojis."""
    message_dict = message.to_python()
    entities = message_dict.get("entities", [])
    custom_emoji_count = sum(
        1 for entity in entities if entity.get("type") == "custom_emoji"
    )
    return custom_emoji_count >= 5


def format_spam_report(message: types.Message) -> str:
    """Function to format the message one line for logging."""

    _reported_spam = (
        "###" + str(message.from_user.id) + " "
    )  # store user_id if no text or caption
    if message.text:
        _reported_spam += f"{message.text} "
    elif message.caption:
        _reported_spam += f"{message.caption} "
    _reported_spam = (
        _reported_spam.replace("\n", " ") + "\n"
    )  # replace newlines with spaces and add new line in the end

    return _reported_spam


def extract_chat_name_and_message_id_from_link(message_link):
    """Extract chat ID and message ID from a message link.
    
    Supports:
    - https://t.me/chatname/123
    - https://t.me/chatname/456/123 (with topic)
    - https://t.me/c/1234567890/123
    - https://t.me/c/1234567890/456/123 (with topic)
    """
    if not str(message_link).startswith("https://t.me/"):
        raise ValueError("Invalid message link format")
    try:
        parts = message_link.split("/")
        # parts[0] = 'https:', parts[1] = '', parts[2] = 't.me', parts[3+] = path
        
        if "c" in parts:
            # Private link: t.me/c/chat_id/msg_id or t.me/c/chat_id/topic_id/msg_id
            c_index = parts.index("c")
            chat_id_str = parts[c_index + 1]
            chat_id = int("-100" + chat_id_str)
            message_id = int(parts[-1])
        else:
            # Public link: t.me/chatname/msg_id or t.me/chatname/topic_id/msg_id
            chat_id = "@" + parts[3]
            message_id = int(parts[-1])

        return chat_id, message_id
    except (IndexError, ValueError) as e:
        raise ValueError(
            "Invalid message link format. https://t.me/ChatName/MessageID or https://t.me/ChatName/threadID/MessageID"
        ) from e


def check_message_for_sentences(
    message: types.Message, predetermined_sentences, logger
):
    """Function to check the message for predetermined word sentences."""

    if not predetermined_sentences:
        logger.warning(
            "spam_dict.txt not found. Automated spam detection will not check for predetermined sentences."
        )
    # Check if the message contains text
    if message.text is None:
        return False

    # Convert the message text to lowercase and tokenize it into words
    message_words = re.findall(r"\b\w+\b", message.text.lower())

    # Check if the message contains any of the predetermined sentences
    for sentence in predetermined_sentences:
        # Tokenize the predetermined sentence into words
        sentence_words = re.findall(r"\b\w+\b", sentence.lower())

        # Check if all words in the predetermined sentence are in the message words
        if all(word in message_words for word in sentence_words):
            return True
    return False


def get_channel_id_by_name(channel_dict, channel_name):
    """Function to get the channel ID by its name."""
    for _id, name in channel_dict.items():
        if name == channel_name:
            return _id
    raise ValueError(f"Channel name {channel_name} not found in channels_dict.")


def get_channel_name_by_id(channel_dict, channel_id):
    """Function to get the channel name by its ID."""
    return channel_dict.get(channel_id, None)


def has_spam_entities(spam_triggers, message: types.Message):
    """
    Check if the message is a spam by checking the entities.

    Args:
        message (types.Message): The message to check.

    Returns:
        bool: True if the message is spam, False otherwise.
    """
    if message.entities:
        for entity in message.entities:
            if entity["type"] in spam_triggers:
                # Spam detected
                return entity["type"]
    return None


def store_message_to_db(cursor: Cursor, conn: Connection, message: types.message):
    """store message data to DB"""
    cursor.execute(
        """
        INSERT OR REPLACE INTO recent_messages 
        (chat_id, chat_username, message_id, user_id, user_name, user_first_name, user_last_name, forward_date, forward_sender_name, received_date, from_chat_title, forwarded_from_id, forwarded_from_username, forwarded_from_first_name, forwarded_from_last_name, new_chat_member, left_chat_member) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            getattr(message.chat, "id", None),
            getattr(message.chat, "username", ""),
            getattr(message, "message_id", None),
            getattr(message.from_user, "id", None),
            getattr(message.from_user, "username", ""),
            getattr(message.from_user, "first_name", ""),
            getattr(message.from_user, "last_name", ""),
            getattr(message, "forward_date", None),
            getattr(message, "forward_sender_name", ""),
            getattr(message, "date", None),
            getattr(message.forward_from_chat, "title", None),
            getattr(message.forward_from, "id", None),
            getattr(message.forward_from, "username", ""),
            getattr(message.forward_from, "first_name", ""),
            getattr(message.forward_from, "last_name", ""),
            None,
            None,
        ),
    )
    conn.commit()


def db_init(cursor: Cursor, conn: Connection):
    """DB init function"""

    # If adding new column for the first time, uncomment below
    # cursor.execute("ALTER TABLE recent_messages ADD COLUMN new_chat_member BOOL")
    # conn.commit()
    # cursor.execute("ALTER TABLE recent_messages ADD COLUMN left_chat_member BOOL")
    # conn.commit()

    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS recent_messages (
        chat_id INTEGER NOT NULL,
        chat_username TEXT,
        message_id INTEGER NOT NULL,
        forwarded_message_data TEXT,
        user_id INTEGER NOT NULL,
        user_name TEXT,
        user_first_name TEXT,
        user_last_name TEXT,
        forward_date INTEGER,
        forward_sender_name TEXT,
        received_date INTEGER,
        from_chat_title TEXT,
        forwarded_from_id INTEGER,
        forwarded_from_username TEXT,
        forwarded_from_first_name TEXT,
        forwarded_from_last_name TEXT,
        new_chat_member BOOL,
        left_chat_member BOOL,
        PRIMARY KEY (chat_id, message_id)
    )
    """
    )
    conn.commit()

    # User baselines table - stores monitoring state and profile snapshots
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS user_baselines (
        user_id INTEGER PRIMARY KEY,
        -- Current profile info
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        photo_count INTEGER DEFAULT 0,
        -- Monitoring state
        monitoring_active INTEGER DEFAULT 1,
        joined_at TEXT,
        monitoring_ended_at TEXT,
        -- Join context
        join_chat_id INTEGER,
        join_chat_username TEXT,
        join_chat_title TEXT,
        -- Status flags
        is_legit INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0,
        -- Ban details
        ban_reason TEXT,
        ban_source TEXT,
        banned_at TEXT,
        banned_by_admin_id INTEGER,
        banned_by_admin_username TEXT,
        banned_in_chat_id INTEGER,
        banned_in_chat_title TEXT,
        -- Offense details (JSON for flexibility)
        offense_type TEXT,
        offense_details TEXT,
        time_to_first_message INTEGER,
        first_message_text TEXT,
        -- Detection flags
        detected_by_lols INTEGER DEFAULT 0,
        detected_by_cas INTEGER DEFAULT 0,
        detected_by_p2p INTEGER DEFAULT 0,
        detected_by_local INTEGER DEFAULT 0,
        detected_by_admin INTEGER DEFAULT 0,
        -- Reserved fields for future use
        bio TEXT,
        premium INTEGER,
        verified INTEGER,
        restriction_reason TEXT,
        language_code TEXT,
        -- Flexible metadata (JSON) for future extensions
        metadata TEXT,
        -- Reserved integer fields
        reserved_int1 INTEGER,
        reserved_int2 INTEGER,
        reserved_int3 INTEGER,
        -- Reserved text fields
        reserved_text1 TEXT,
        reserved_text2 TEXT,
        reserved_text3 TEXT,
        -- Timestamps
        created_at TEXT,
        updated_at TEXT
    )
    """
    )
    conn.commit()


# ============================================================================
# User Baselines Helper Functions
# ============================================================================

def save_user_baseline(
    conn: Connection,
    user_id: int,
    username: str = None,
    first_name: str = None,
    last_name: str = None,
    photo_count: int = 0,
    join_chat_id: int = None,
    join_chat_username: str = None,
    join_chat_title: str = None,
    metadata: dict = None,
) -> bool:
    """Save or update a user baseline record.
    
    Args:
        conn: Database connection
        user_id: Telegram user ID
        username: Telegram username (without @)
        first_name: User's first name
        last_name: User's last name
        photo_count: Number of profile photos at join time
        join_chat_id: Chat ID where user joined
        join_chat_username: Chat username where user joined
        join_chat_title: Chat title where user joined
        metadata: Additional JSON metadata
    
    Returns:
        True if saved successfully, False otherwise
    """
    import json
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    metadata_json = json.dumps(metadata) if metadata else None
    
    try:
        cursor.execute(
            """
            INSERT INTO user_baselines (
                user_id, username, first_name, last_name, photo_count,
                monitoring_active, joined_at,
                join_chat_id, join_chat_username, join_chat_title,
                metadata, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                photo_count = excluded.photo_count,
                monitoring_active = 1,
                joined_at = excluded.joined_at,
                join_chat_id = excluded.join_chat_id,
                join_chat_username = excluded.join_chat_username,
                join_chat_title = excluded.join_chat_title,
                metadata = excluded.metadata,
                updated_at = excluded.updated_at
            """,
            (
                user_id, username, first_name, last_name, photo_count,
                now, join_chat_id, join_chat_username, join_chat_title,
                metadata_json, now, now,
            ),
        )
        conn.commit()
        return True
    except Exception as e:
        logging.getLogger(__name__).error(
            "Error saving user baseline for %s: %s", user_id, e
        )
        return False


def get_user_baseline(conn: Connection, user_id: int) -> dict:
    """Get a user baseline record.
    
    Args:
        conn: Database connection
        user_id: Telegram user ID
    
    Returns:
        Dictionary with baseline data or None if not found
    """
    import json
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT user_id, username, first_name, last_name, photo_count,
               monitoring_active, joined_at, monitoring_ended_at,
               join_chat_id, join_chat_username, join_chat_title,
               is_legit, is_banned, ban_reason, banned_by_admin_id,
               bio, premium, verified, restriction_reason, language_code,
               metadata, created_at, updated_at
        FROM user_baselines WHERE user_id = ?
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    
    return {
        "user_id": row[0],
        "username": row[1],
        "first_name": row[2],
        "last_name": row[3],
        "photo_count": row[4],
        "monitoring_active": bool(row[5]),
        "joined_at": row[6],
        "monitoring_ended_at": row[7],
        "join_chat_id": row[8],
        "join_chat_username": row[9],
        "join_chat_title": row[10],
        "is_legit": bool(row[11]),
        "is_banned": bool(row[12]),
        "ban_reason": row[13],
        "banned_by_admin_id": row[14],
        "bio": row[15],
        "premium": bool(row[16]) if row[16] is not None else None,
        "verified": bool(row[17]) if row[17] is not None else None,
        "restriction_reason": row[18],
        "language_code": row[19],
        "metadata": json.loads(row[20]) if row[20] else None,
        "created_at": row[21],
        "updated_at": row[22],
    }


def get_active_user_baselines(conn: Connection) -> list:
    """Get all user baselines with active monitoring.
    
    Args:
        conn: Database connection
    
    Returns:
        List of dictionaries with baseline data
    """
    import json
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT user_id, username, first_name, last_name, photo_count,
               monitoring_active, joined_at, monitoring_ended_at,
               join_chat_id, join_chat_username, join_chat_title,
               is_legit, is_banned, metadata, created_at, updated_at
        FROM user_baselines WHERE monitoring_active = 1
        """
    )
    rows = cursor.fetchall()
    results = []
    for row in rows:
        results.append({
            "user_id": row[0],
            "username": row[1],
            "first_name": row[2],
            "last_name": row[3],
            "photo_count": row[4],
            "monitoring_active": bool(row[5]),
            "joined_at": row[6],
            "monitoring_ended_at": row[7],
            "join_chat_id": row[8],
            "join_chat_username": row[9],
            "join_chat_title": row[10],
            "is_legit": bool(row[11]),
            "is_banned": bool(row[12]),
            "metadata": json.loads(row[13]) if row[13] else None,
            "created_at": row[14],
            "updated_at": row[15],
        })
    return results


def update_user_baseline_status(
    conn: Connection,
    user_id: int,
    monitoring_active: bool = None,
    is_legit: bool = None,
    is_banned: bool = None,
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
) -> bool:
    """Update monitoring/ban status for a user.
    
    Args:
        conn: Database connection
        user_id: Telegram user ID
        monitoring_active: Set monitoring state
        is_legit: Mark user as legitimate
        is_banned: Mark user as banned
        ban_reason: Human-readable reason for ban
        ban_source: Source of ban detection (lols/cas/p2p/local/admin/autoreport)
        banned_by_admin_id: Admin who banned the user (if manual)
        banned_by_admin_username: Admin username
        banned_in_chat_id: Chat where offense occurred
        banned_in_chat_title: Chat title where offense occurred
        offense_type: Type of offense (fast_message, spam_pattern, bot_mention, etc.)
        offense_details: JSON with additional offense details
        time_to_first_message: Seconds between join and first message
        first_message_text: The offending message text (truncated)
        detected_by_*: Which detection systems flagged the user
    
    Returns:
        True if updated successfully, False otherwise
    """
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    updates = ["updated_at = ?"]
    params = [now]
    
    if monitoring_active is not None:
        updates.append("monitoring_active = ?")
        params.append(1 if monitoring_active else 0)
        if not monitoring_active:
            updates.append("monitoring_ended_at = ?")
            params.append(now)
    
    if is_legit is not None:
        updates.append("is_legit = ?")
        params.append(1 if is_legit else 0)
    
    if is_banned is not None:
        updates.append("is_banned = ?")
        params.append(1 if is_banned else 0)
        if is_banned:
            updates.append("banned_at = ?")
            params.append(now)
    
    if ban_reason is not None:
        updates.append("ban_reason = ?")
        params.append(ban_reason)
    
    if ban_source is not None:
        updates.append("ban_source = ?")
        params.append(ban_source)
    
    if banned_by_admin_id is not None:
        updates.append("banned_by_admin_id = ?")
        params.append(banned_by_admin_id)
    
    if banned_by_admin_username is not None:
        updates.append("banned_by_admin_username = ?")
        params.append(banned_by_admin_username)
    
    if banned_in_chat_id is not None:
        updates.append("banned_in_chat_id = ?")
        params.append(banned_in_chat_id)
    
    if banned_in_chat_title is not None:
        updates.append("banned_in_chat_title = ?")
        params.append(banned_in_chat_title)
    
    if offense_type is not None:
        updates.append("offense_type = ?")
        params.append(offense_type)
    
    if offense_details is not None:
        updates.append("offense_details = ?")
        params.append(offense_details)
    
    if time_to_first_message is not None:
        updates.append("time_to_first_message = ?")
        params.append(time_to_first_message)
    
    if first_message_text is not None:
        # Truncate to 500 chars to avoid bloating DB
        updates.append("first_message_text = ?")
        params.append(first_message_text[:500] if len(first_message_text) > 500 else first_message_text)
    
    if detected_by_lols is not None:
        updates.append("detected_by_lols = ?")
        params.append(1 if detected_by_lols else 0)
    
    if detected_by_cas is not None:
        updates.append("detected_by_cas = ?")
        params.append(1 if detected_by_cas else 0)
    
    if detected_by_p2p is not None:
        updates.append("detected_by_p2p = ?")
        params.append(1 if detected_by_p2p else 0)
    
    if detected_by_local is not None:
        updates.append("detected_by_local = ?")
        params.append(1 if detected_by_local else 0)
    
    if detected_by_admin is not None:
        updates.append("detected_by_admin = ?")
        params.append(1 if detected_by_admin else 0)
    
    params.append(user_id)
    
    try:
        cursor.execute(
            f"UPDATE user_baselines SET {', '.join(updates)} WHERE user_id = ?",
            params,
        )
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logging.getLogger(__name__).error(
            "Error updating user baseline status for %s: %s", user_id, e
        )
        return False


def delete_user_baseline(conn: Connection, user_id: int) -> bool:
    """Delete a user baseline record.
    
    Args:
        conn: Database connection
        user_id: Telegram user ID
    
    Returns:
        True if deleted successfully, False otherwise
    """
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM user_baselines WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logging.getLogger(__name__).error(
            "Error deleting user baseline for %s: %s", user_id, e
        )
        return False


def get_user_whois(conn: Connection, user_id: int = None, username: str = None) -> dict:
    """Get comprehensive user data for /whois command.
    
    Searches both user_baselines and recent_messages tables to build
    a complete picture of the user's history with the bot.
    
    Args:
        conn: Database connection
        user_id: Telegram user ID (optional if username provided)
        username: Telegram username without @ (optional if user_id provided)
    
    Returns:
        Dictionary with all available user data or None if not found
    """
    import json
    cursor = conn.cursor()
    result = {
        "found": False,
        "user_id": user_id,
        "username": username,
        "first_name": None,
        "last_name": None,
        "baseline": None,
        "messages": [],
        "chats_seen": set(),
        "join_events": [],
        "leave_events": [],
        "first_seen": None,
        "last_seen": None,
    }
    
    # If we only have username, try to find user_id from recent_messages
    if not user_id and username:
        clean_username = username.lstrip("@").lower()
        cursor.execute(
            """
            SELECT DISTINCT user_id, user_name, user_first_name, user_last_name
            FROM recent_messages 
            WHERE LOWER(user_name) = ?
            ORDER BY received_date DESC
            LIMIT 1
            """,
            (clean_username,),
        )
        row = cursor.fetchone()
        if row:
            user_id = row[0]
            result["user_id"] = user_id
            result["username"] = row[1]
            result["first_name"] = row[2]
            result["last_name"] = row[3]
    
    if not user_id:
        return result  # Not found
    
    # Get baseline data
    cursor.execute(
        """
        SELECT user_id, username, first_name, last_name, photo_count,
               monitoring_active, joined_at, monitoring_ended_at,
               join_chat_id, join_chat_username, join_chat_title,
               is_legit, is_banned, ban_reason, ban_source, banned_at,
               banned_by_admin_id, banned_by_admin_username,
               banned_in_chat_id, banned_in_chat_title,
               offense_type, offense_details, time_to_first_message, first_message_text,
               detected_by_lols, detected_by_cas, detected_by_p2p, detected_by_local, detected_by_admin,
               bio, premium, verified, restriction_reason, language_code,
               metadata, created_at, updated_at
        FROM user_baselines WHERE user_id = ?
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if row:
        result["found"] = True
        result["baseline"] = {
            "user_id": row[0],
            "username": row[1],
            "first_name": row[2],
            "last_name": row[3],
            "photo_count": row[4],
            "monitoring_active": bool(row[5]),
            "joined_at": row[6],
            "monitoring_ended_at": row[7],
            "join_chat_id": row[8],
            "join_chat_username": row[9],
            "join_chat_title": row[10],
            "is_legit": bool(row[11]),
            "is_banned": bool(row[12]),
            "ban_reason": row[13],
            "ban_source": row[14],
            "banned_at": row[15],
            "banned_by_admin_id": row[16],
            "banned_by_admin_username": row[17],
            "banned_in_chat_id": row[18],
            "banned_in_chat_title": row[19],
            "offense_type": row[20],
            "offense_details": json.loads(row[21]) if row[21] else None,
            "time_to_first_message": row[22],
            "first_message_text": row[23],
            "detected_by_lols": bool(row[24]),
            "detected_by_cas": bool(row[25]),
            "detected_by_p2p": bool(row[26]),
            "detected_by_local": bool(row[27]),
            "detected_by_admin": bool(row[28]),
            "bio": row[29],
            "premium": bool(row[30]) if row[30] is not None else None,
            "verified": bool(row[31]) if row[31] is not None else None,
            "restriction_reason": row[32],
            "language_code": row[33],
            "metadata": json.loads(row[34]) if row[34] else None,
            "created_at": row[35],
            "updated_at": row[36],
        }
        result["username"] = result["baseline"]["username"] or result["username"]
        result["first_name"] = result["baseline"]["first_name"]
        result["last_name"] = result["baseline"]["last_name"]
    
    # Get message history from recent_messages
    cursor.execute(
        """
        SELECT chat_id, chat_username, message_id, user_name, user_first_name, user_last_name,
               received_date, from_chat_title, new_chat_member, left_chat_member
        FROM recent_messages 
        WHERE user_id = ?
        ORDER BY received_date DESC
        LIMIT 50
        """,
        (user_id,),
    )
    rows = cursor.fetchall()
    
    for row in rows:
        result["found"] = True
        chat_id = row[0]
        chat_username = row[1]
        chat_title = row[7]
        received_date = row[6]
        new_chat_member = bool(row[8])
        left_chat_member = bool(row[9])
        
        # Update user info if not set
        if not result["username"] and row[3]:
            result["username"] = row[3]
        if not result["first_name"] and row[4]:
            result["first_name"] = row[4]
        if not result["last_name"] and row[5]:
            result["last_name"] = row[5]
        
        # Track chats
        chat_info = {
            "chat_id": chat_id,
            "chat_username": chat_username,
            "chat_title": chat_title,
        }
        result["chats_seen"].add((chat_id, chat_username or "", chat_title or ""))
        
        # Track dates
        if received_date:
            if not result["first_seen"] or received_date < result["first_seen"]:
                result["first_seen"] = received_date
            if not result["last_seen"] or received_date > result["last_seen"]:
                result["last_seen"] = received_date
        
        # Track join/leave events
        if new_chat_member:
            result["join_events"].append({
                "date": received_date,
                "chat_id": chat_id,
                "chat_username": chat_username,
                "chat_title": chat_title,
            })
        if left_chat_member:
            result["leave_events"].append({
                "date": received_date,
                "chat_id": chat_id,
                "chat_username": chat_username,
                "chat_title": chat_title,
            })
        
        result["messages"].append({
            "chat_id": chat_id,
            "chat_username": chat_username,
            "chat_title": chat_title,
            "message_id": row[2],
            "received_date": received_date,
            "new_chat_member": new_chat_member,
            "left_chat_member": left_chat_member,
        })
    
    # Convert set to list for JSON serialization
    result["chats_seen"] = [
        {"chat_id": c[0], "chat_username": c[1], "chat_title": c[2]}
        for c in result["chats_seen"]
    ]
    
    return result


def format_whois_response(data: dict, include_lols_link: bool = True) -> str:
    """Format whois data into a human-readable HTML message.
    
    Args:
        data: Dictionary from get_user_whois()
        include_lols_link: Whether to include LOLS check link
        
    Returns:
        HTML formatted string for Telegram message
    """
    import html
    
    if not data.get("found"):
        # User not found in database
        user_id = data.get("user_id")
        username = data.get("username")
        
        msg = "❓ <b>User Not Found</b>\n\n"
        msg += "User has not been seen by this bot.\n\n"
        
        if user_id:
            msg += f"🆔 User ID: <code>{user_id}</code>\n"
            msg += f"\n🔗 <b>External checks:</b>\n"
            msg += f"   └ <a href='https://t.me/oLolsBot?start={user_id}'>Check on LOLS</a>\n"
            msg += f"\n📱 <b>Profile links:</b>\n"
            msg += f"   ├ <a href='tg://user?id={user_id}'>ID based profile</a>\n"
            msg += f"   └ <a href='https://t.me/@id{user_id}'>iOS link</a>"
        elif username:
            clean_name = username.lstrip("@")
            msg += f"👤 Username: @{html.escape(clean_name)}\n"
            msg += f"\n🔗 <b>External checks:</b>\n"
            msg += f"   └ <a href='https://t.me/oLolsBot?start=u-{clean_name}'>Check on LOLS</a>"
        
        return msg
    
    # User found
    user_id = data.get("user_id")
    username = data.get("username")
    first_name = data.get("first_name") or ""
    last_name = data.get("last_name") or ""
    baseline = data.get("baseline") or {}
    
    # Header
    msg = "👤 <b>User Information</b>\n"
    msg += "─" * 25 + "\n"
    
    # Basic info
    msg += f"🆔 ID: <code>{user_id}</code>\n"
    if username:
        msg += f"👤 Username: @{html.escape(username)}\n"
    full_name = f"{html.escape(first_name)} {html.escape(last_name)}".strip()
    if full_name:
        msg += f"📛 Name: {full_name}\n"
    
    # Status badges
    status_parts = []
    if baseline.get("is_banned"):
        status_parts.append("🚫 BANNED")
    if baseline.get("is_legit"):
        status_parts.append("✅ LEGIT")
    if baseline.get("monitoring_active"):
        status_parts.append("👁 MONITORING")
    if baseline.get("premium"):
        status_parts.append("⭐ PREMIUM")
    if baseline.get("verified"):
        status_parts.append("✓ VERIFIED")
    
    if status_parts:
        msg += f"📌 Status: {' | '.join(status_parts)}\n"
    
    # Timestamps
    msg += "\n📅 <b>Timeline:</b>\n"
    if data.get("first_seen"):
        msg += f"   ├ First seen: {data['first_seen']}\n"
    if data.get("last_seen"):
        msg += f"   └ Last seen: {data['last_seen']}\n"
    if baseline.get("joined_at"):
        msg += f"   ├ Joined (monitored): {baseline['joined_at']}\n"
    if baseline.get("monitoring_ended_at"):
        msg += f"   └ Monitoring ended: {baseline['monitoring_ended_at']}\n"
    
    # Chats
    chats = data.get("chats_seen", [])
    if chats:
        msg += f"\n💬 <b>Seen in {len(chats)} chat(s):</b>\n"
        for i, chat in enumerate(chats[:5]):  # Limit to 5
            prefix = "└" if i == len(chats[:5]) - 1 else "├"
            chat_disp = chat.get("chat_title") or chat.get("chat_username") or str(chat.get("chat_id"))
            msg += f"   {prefix} {html.escape(str(chat_disp))}\n"
        if len(chats) > 5:
            msg += f"   ... and {len(chats) - 5} more\n"
    
    # Join/Leave events
    joins = data.get("join_events", [])
    leaves = data.get("leave_events", [])
    if joins or leaves:
        msg += f"\n🚪 <b>Activity:</b> {len(joins)} join(s), {len(leaves)} leave(s)\n"
    
    # Ban details
    if baseline.get("is_banned"):
        msg += "\n🚫 <b>Ban Details:</b>\n"
        if baseline.get("banned_at"):
            msg += f"   ├ Banned at: {baseline['banned_at']}\n"
        if baseline.get("ban_source"):
            msg += f"   ├ Source: <code>{baseline['ban_source']}</code>\n"
        if baseline.get("offense_type"):
            msg += f"   ├ Offense: <code>{baseline['offense_type']}</code>\n"
        if baseline.get("ban_reason"):
            reason = baseline['ban_reason'][:100] + "..." if len(baseline.get('ban_reason', '')) > 100 else baseline['ban_reason']
            msg += f"   ├ Reason: {html.escape(reason)}\n"
        
        # Admin who banned
        if baseline.get("banned_by_admin_id"):
            admin_disp = f"@{baseline['banned_by_admin_username']}" if baseline.get("banned_by_admin_username") else str(baseline['banned_by_admin_id'])
            msg += f"   ├ Banned by: {html.escape(admin_disp)}\n"
        
        # Chat where banned
        if baseline.get("banned_in_chat_title"):
            msg += f"   ├ In chat: {html.escape(baseline['banned_in_chat_title'])}\n"
        
        # Detection sources
        detection = []
        if baseline.get("detected_by_lols"):
            detection.append("LOLS")
        if baseline.get("detected_by_cas"):
            detection.append("CAS")
        if baseline.get("detected_by_p2p"):
            detection.append("P2P")
        if baseline.get("detected_by_local"):
            detection.append("LOCAL")
        if baseline.get("detected_by_admin"):
            detection.append("ADMIN")
        if detection:
            msg += f"   ├ Detected by: {', '.join(detection)}\n"
        
        # Time to first message
        if baseline.get("time_to_first_message") is not None:
            ttfm = baseline['time_to_first_message']
            if ttfm < 60:
                ttfm_str = f"{ttfm}s"
            elif ttfm < 3600:
                ttfm_str = f"{ttfm // 60}m {ttfm % 60}s"
            else:
                ttfm_str = f"{ttfm // 3600}h {(ttfm % 3600) // 60}m"
            msg += f"   └ Time to first msg: {ttfm_str}\n"
    
    # Profile links
    msg += f"\n🔗 <b>Profile links:</b>\n"
    msg += f"   ├ <a href='tg://user?id={user_id}'>ID based profile</a>\n"
    msg += f"   ├ <a href='tg://openmessage?user_id={user_id}'>Android</a>\n"
    msg += f"   └ <a href='https://t.me/@id{user_id}'>iOS</a>\n"
    
    # External check links
    if include_lols_link:
        msg += f"\n🔍 <b>External checks:</b>\n"
        msg += f"   └ <a href='https://t.me/oLolsBot?start={user_id}'>Check on LOLS</a>"
    
    return msg


def create_inline_keyboard(message_link, lols_link, message: types.Message):
    """Create the inline keyboard for a suspicious forwarded / monitored message.

    Original version included immediate Global BAN / BAN / Delete Message buttons whose
    callback prefixes (suspiciousglobalban_/suspiciousban_/suspiciousdelmsg_) are *also*
    produced elsewhere, leading to duplicate handling / double confirmation flows.

    To avoid duplicate ban handling we:
      - Keep non-destructive info buttons (Check Spam Data).
      - Provide a single consolidated "⚙️ Actions" menu via a neutral callback prefix
        that downstream code can expand into confirm/cancel buttons (re-using existing
        suspicious* prefixes only once).
      - Retain the existing stopchecks_* button (used to mark user legit & stop monitoring).

    Note: "View Original Message" button removed since the original message is always
    forwarded above this notification, and buttons don't work when forwarding reports.
    """
    inline_kb = InlineKeyboardMarkup()
    inline_kb.add(InlineKeyboardButton("ℹ️ Check LOLS Data ℹ️", url=lols_link))
    inline_kb.add(
        InlineKeyboardButton(
            "🟢 Seems legit, STOP checks 🟢",
            callback_data=f"stopchecks_{message.from_user.id}_{message.chat.id}_{message.message_id}",
        )
    )
    # Single actions button to open ban/delete choices (handled separately)
    inline_kb.add(
        InlineKeyboardButton(
            "⚙️ Actions (Ban / Delete) ⚙️",
            callback_data=f"suspiciousactions_{message.chat.id}_{message.message_id}_{message.from_user.id}",
        )
    )
    return inline_kb


def check_user_legit(cursor: Cursor, user_id: int) -> bool:
    """Function to check if user is marked as legit
    having new_chat_member and left_chat_member set to 1."""

    cursor.execute(
        """
        SELECT 1 FROM recent_messages
        WHERE user_id = ? AND new_chat_member = 1 AND left_chat_member = 1
        LIMIT 1
        """,
        (user_id,),
    )
    result = cursor.fetchone()
    return result is not None


async def report_spam_2p2p(spammer_id: int, logger) -> bool:
    """Function to report spammer to local P2P spamcheck server"""
    try:
        # local P2P spamcheck server
        url = f"http://localhost:8081/report_id?user_id={spammer_id}"
        async with aiohttp.ClientSession() as session:
            async with session.post(url) as response:
                if response.status == 200:
                    logger.info(
                        f"{spammer_id} successfully reported spammer to local P2P spamcheck server."
                    )
                    return True
                else:
                    return False
    except aiohttp.ServerTimeoutError as e:
        logger.error(f"Server timeout error reporting spammer: {e}")
        return False
    except aiohttp.ClientError as e:
        logger.error(f"Client error reporting spammer: {e}")
        return False


async def remove_spam_from_2p2p(user_id: int, logger) -> bool:
    """Function to remove user from P2P spamcheck server (mark as legit)"""
    try:
        # local P2P spamcheck server - assuming there's a whitelist/remove endpoint
        url = f"http://localhost:8081/remove_id?user_id={user_id}"
        async with aiohttp.ClientSession() as session:
            async with session.post(url) as response:
                if response.status == 200:
                    logger.info(
                        f"{user_id} successfully removed from P2P spamcheck server (marked as legit)."
                    )
                    return True
                else:
                    logger.warning(
                        f"{user_id} failed to remove from P2P server, status: {response.status}"
                    )
                    return False
    except aiohttp.ServerTimeoutError as e:
        logger.error(f"Server timeout error removing user from P2P: {e}")
        return False
    except aiohttp.ClientError as e:
        logger.error(f"Client error removing user from P2P: {e}")
        return False


async def report_spam_from_message(message: types.Message, logger, userid_toexclude):
    """
    Reports spam from various IDs found in a message.

    Args:
        message (types.Message): The message object.
        logger: The logger object.
        TELEGRAM_CHANNEL_BOT_ID: The ID of the telegram channel bot.
    """
    user_id = message.from_user.id if message.from_user else None
    sender_chat_id = message.sender_chat.id if message.sender_chat else None
    forward_from_id = message.forward_from.id if message.forward_from else None
    forward_from_chat_id = (
        message.forward_from_chat.id if message.forward_from_chat else None
    )

    if (
        user_id and user_id != userid_toexclude
    ):  # prevent banning system TELEGRAM_CHANNEL_BOT_ID
        await report_spam_2p2p(user_id, logger)
    if sender_chat_id:
        await report_spam_2p2p(sender_chat_id, logger)
    if forward_from_id:
        await report_spam_2p2p(forward_from_id, logger)
    if forward_from_chat_id:
        await report_spam_2p2p(forward_from_chat_id, logger)


# def get_spam_report_link(spammer_id:int) -> str:
#     """Function to get the spam report link"""
#     # Replace with the actual URL of your local P2P spamcheck server
#     url = f"http://localhost:5000/report_spam/{spammer_id}"


# Function to split lists into chunks
def split_list(lst, max_length):
    """Split a list into chunks that do not exceed max_length.
    Args:
        lst (list): The list to split.
        max_length (int): The maximum length of each chunk.
    Yields:
        list: A chunk of the list."""
    
    chunk = []
    current_length = 0
    for item in lst:
        item_length = len(item) + 1  # +1 for the space
        if current_length + item_length > max_length:
            yield chunk
            chunk = []
            current_length = 0
        chunk.append(item)
        current_length += item_length
    if chunk:
        yield chunk


def extract_username(uname):
    """Extract username from various formats.
    Args:
        uname (str or dict): The username to extract, can be a string or a dictionary.
    Returns:
        str: The extracted username in the format '@username' or '!UNDEFINED!' if not found.
    """
    
    if isinstance(uname, dict):
        # Only check the top-level 'username' key, don't search nested dicts
        # to avoid accidentally picking up chat usernames from baseline.chat.username
        username = uname.get('username', None)
        if username is not None and username != 'None' and username != '' and username != '!UNDEFINED!':
            return f'@{username}'
        else:
            return '!UNDEFINED!'
    elif uname is None or uname == 'None' or uname == '' or uname == '!UNDEFINED!':
        return '!UNDEFINED!'
    else:
        return f'@{uname}'


def normalize_username(value):
    """Return a sanitized username without leading '@' or an empty string if undefined.

    Accepts:
      - Plain string (with/without leading '@').
      - None / falsy -> '' (undefined)
      - Dict with possible structure { 'username': 'foo' } or nested via keys like
        { 'baseline': { 'username': 'foo' } } or { 'baseline': { 'user_name': 'foo' } }.

    Rules:
      - Trim whitespace.
      - Strip leading '@'.
      - Treat 'None', '!UNDEFINED!', empty string as undefined -> ''
      - Do NOT lowercase (preserve original casing) to keep display fidelity.
    """

    def _search(d):  # recursive search for username/user_name
        if not isinstance(d, dict):
            return None
        # Direct keys preference order
        for k in ("username", "user_name"):
            v = d.get(k)
            if isinstance(v, str) and v and v not in ("None", "!UNDEFINED!"):
                return v
        # Nested dicts (shallow-first)
        for v in d.values():
            if isinstance(v, dict):
                found = _search(v)
                if found:
                    return found
        return None

    uname = None
    if isinstance(value, dict):
        uname = _search(value)
    elif isinstance(value, str):
        uname = value
    elif value is None:
        uname = None
    else:
        uname = str(value)

    if not uname or uname in ("None", "!UNDEFINED!"):
        return ""
    uname = uname.strip()
    # Remove leading '@'
    if uname.startswith("@"):
        uname = uname[1:]
    if not uname:
        return ""
    return uname
