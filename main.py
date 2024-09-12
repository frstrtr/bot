from datetime import datetime
import os
import random
import sqlite3
import xml.etree.ElementTree as ET
import logging
import json
import subprocess
import time

from typing import Optional, Tuple
import re
import pytz
from aiogram import Bot, Dispatcher, types
import emoji
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ChatMemberUpdated,
    ChatMemberStatus,
)
from aiogram import executor

# from aiogram.types import Message
from aiogram.utils.exceptions import (
    MessageToDeleteNotFound,
    # MessageCantBeDeleted,
    RetryAfter,
)

# If adding new column for the first time, uncomment below
# cursor.execute("ALTER TABLE recent_messages ADD COLUMN new_chat_member BOOL")
# conn.commit()
# cursor.execute("ALTER TABLE recent_messages ADD COLUMN left_chat_member BOOL")
# conn.commit()
# Setting up SQLite Database
conn = sqlite3.connect("messages.db")
cursor = conn.cursor()
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


# Load predetermined sentences from a plain text file and normalize to lowercase
def load_predetermined_sentences(txt_file):
    """Load predetermined sentences from a plain text file, normalize to lowercase,
    remove extra spaces and punctuation marks, check for duplicates, rewrite the file
    excluding duplicates if any, and log the results. Return None if the file doesn't exist.
    """
    if not os.path.exists(txt_file):
        return None

    try:
        with open(txt_file, "r", encoding="utf-8") as file:
            lines = [line.strip().lower() for line in file if line.strip()]

        # Normalize lines by removing extra spaces and punctuation marks
        normalized_lines = [re.sub(r"[^\w\s]", "", line).strip() for line in lines]

        unique_lines = list(set(normalized_lines))
        duplicates = [
            line for line in normalized_lines if normalized_lines.count(line) > 1
        ]

        # Check if there are duplicates or normalization changes
        if len(unique_lines) != len(lines) or lines != normalized_lines:
            # Rewrite the file with unique and normalized lines
            with open(txt_file, "w", encoding="utf-8") as file:
                for line in unique_lines:
                    file.write(line + "\n")

            # Log the results
            LOGGER.info(
                "\nNumber of lines after checking for duplicates: %s", len(unique_lines)
            )
            LOGGER.info("Number of duplicate lines removed: %s", len(duplicates))
            if duplicates:
                LOGGER.info("Contents of removed duplicate lines:")
                for line in set(duplicates):
                    LOGGER.info(line)
            else:
                LOGGER.info("No duplicates found in spam dictionary.\n")
        else:
            LOGGER.info(
                "No duplicates or normalization changes found. File not rewritten.\n"
            )

        return unique_lines
    except FileNotFoundError:
        return None


# Custom filter function to exclude specific content types and groups for the message handler
def custom_filter(message: types.Message):
    """Function to filter messages based on the chat ID and content type.
    Custom filter function to exclude specific content types and groups for the message handler
    Do not record join/left chat member events
    """
    excluded_content_types = {
        types.ContentType.NEW_CHAT_MEMBERS,
        types.ContentType.LEFT_CHAT_MEMBER,
    }
    return (
        message.chat.id in CHANNEL_IDS
        and message.content_type not in excluded_content_types
    )


def get_latest_commit_info():
    """Function to get the latest commit info."""
    try:
        _commit_info = (
            subprocess.check_output(["git", "show", "-s"]).decode("utf-8").strip()
        )
        return _commit_info
    except subprocess.CalledProcessError as e:
        print(f"Error getting git commit info: {e}")
        return None


def extract_spammer_info(message):
    """Extract the spammer's details from the message."""
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


def get_spammer_details(
    spammer_id,
    spammer_first_name,
    spammer_last_name,
    message_forward_date,
    forward_sender_name="",
    forward_from_chat_title="",
    forwarded_from_id=None,
):
    """Function to get chat ID and message ID by sender name and date
    or if the message is a forward of a forward then using
    forwarded_from_id and message_forward_date.
    forwarded_from_username, forwarded_from_first_name,
    forward_from_last_name are used only for forwarded forwarded messages
    and reserved for future use"""

    spammer_id = spammer_id or None
    # spammer_id = spammer_id or MANUALLY ENTERED SPAMMER_ID INT 5338846489
    spammer_last_name = spammer_last_name or ""

    LOGGER.debug(
        "Getting chat ID and message ID for\n"
        "spammerID: %s : firstName : %s : lastName : %s,\n"
        "messageForwardDate: %s, forwardedFromChatTitle: %s,\n"
        "forwardSenderName: %s, forwardedFromID: %s\n",
        spammer_id,
        spammer_first_name,
        spammer_last_name,
        message_forward_date,
        forward_from_chat_title,
        forward_sender_name,
        forwarded_from_id,
    )

    # Common SQL and parameters for both cases
    base_query = """
        SELECT chat_id, message_id, chat_username, user_id, user_name, user_first_name, user_last_name
        FROM recent_messages
        WHERE {condition}
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
        # TODO is it neccessary below?
        params.update(
            {
                "forward_date": message_forward_date,
                "forwarded_from_id": forwarded_from_id,
            }
        )

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

    # TODO
    # use message hash future field

    query = base_query.format(condition=condition)
    result = cursor.execute(query, params).fetchone()

    if not spammer_first_name:
        spammer_first_name, spammer_last_name = (
            result[5],
            result[6],
        )  # get names from db

    LOGGER.debug(
        "Result for sender: %s : %s %s, date: %s, from chat title: %s\nResult: %s",
        spammer_id,
        spammer_first_name,
        spammer_last_name,
        message_forward_date,
        forward_from_chat_title,
        result,
    )

    return result


def load_config():
    """Load configuration values from an XML file."""
    global CHANNEL_IDS, ADMIN_AUTOREPORTS, TECHNO_LOGGING, TECHNO_ORIGINALS, TECHNO_UNHANDLED
    global TECHNO_RESTART, TECHNO_INOUT, ADMIN_USER_ID, SPAM_TRIGGERS
    global CHANNEL_NAMES
    global PREDETERMINED_SENTENCES, ALLOWED_FORWARD_CHANNELS, ADMIN_GROUP_ID, TECHNOLOG_GROUP_ID
    global ALLOWED_FORWARD_CHANNEL_IDS, MAX_TELEGRAM_MESSAGE_LENGTH
    global BOT_NAME, LOG_GROUP, LOG_GROUP_NAME, TECHNO_LOG_GROUP, TECHNO_LOG_GROUP_NAME
    global DP, BOT, LOGGER, channels_dict

    #     # Attempt to extract the schedule, if present
    #     schedule = group.find('schedule')
    #     if schedule is not None and schedule.get('trigger') == "1":
    #         start_time = schedule.find('start').text
    #         end_time = schedule.find('end').text
    #         scheduler_dict[channel_id] = {'start': start_time, 'end': end_time}

    # commit_info = get_latest_commit_info()
    # if commit_info:
    #     logger.info("Bot starting with commit info:\n%s", commit_info)
    # else:
    #     logger.warning("Bot starting without git info.")

    # logging.basicConfig(level=logging.DEBUG)
    # To debug the bot itself (e.g., to see the messages it receives)
    LOGGER = logging.getLogger(
        __name__
    )  # To debug the script (e.g., to see if the XML is loaded correctly)
    LOGGER.setLevel(
        logging.DEBUG
    )  # To debug the script (e.g., to see if the XML is loaded correctly)

    # Create handlers
    file_handler = logging.FileHandler("bancop_BOT.log")  # For writing logs to a file
    stream_handler = logging.StreamHandler()  # For writing logs to the console

    # Create formatters and add them to handlers
    FROMAT_STR = "%(message)s"  # Excludes timestamp, logger's name, and log level
    formatter = logging.Formatter(FROMAT_STR)
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)

    # Add handlers to the logger
    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(stream_handler)

    # List of predetermined sentences to check for
    PREDETERMINED_SENTENCES = load_predetermined_sentences("spam_dict.txt")
    if not PREDETERMINED_SENTENCES:
        LOGGER.warning(
            "spam_dict.txt not found. Automated spam detection will not check for predetermined sentences."
        )
    # print ("spam_dict.txt loaded>:", PREDETERMINED_SENTENCES)

    try:

        # Load the XML
        config_XML = ET.parse("config.xml")
        config_XML_root = config_XML.getroot()

        channels_XML = ET.parse("groups.xml")
        channels_root = channels_XML.getroot()

        # Assign configuration values to variables
        ADMIN_AUTOREPORTS = int(config_XML_root.find("admin_autoreports").text)
        TECHNO_LOGGING = int(config_XML_root.find("techno_logging").text)
        TECHNO_ORIGINALS = int(config_XML_root.find("techno_originals").text)
        TECHNO_UNHANDLED = int(config_XML_root.find("techno_unhandled").text)
        TECHNO_RESTART = int(config_XML_root.find("techno_restart").text)
        TECHNO_INOUT = int(config_XML_root.find("techno_inout").text)

        ADMIN_USER_ID = int(config_XML_root.find("admin_id").text)
        CHANNEL_IDS = [
            int(group.find("id").text) for group in channels_root.findall("group")
        ]
        CHANNEL_NAMES = [
            group.find("name").text for group in channels_root.findall("group")
        ]

        # add channels to dict for logging
        channels_dict = {}
        for group in channels_root.findall("group"):
            channel_id = int(group.find("id").text)
            channel_name = group.find("name").text
            channels_dict[channel_id] = channel_name

        SPAM_TRIGGERS = [
            trigger.text
            for trigger in config_XML_root.find("spam_triggers").findall("trigger")
        ]

        ALLOWED_FORWARD_CHANNELS = [
            {"id": int(channel.find("id").text), "name": channel.find("name").text}
            for channel in config_XML_root.find("allowed_forward_channels").findall(
                "channel"
            )
        ]
        ALLOWED_FORWARD_CHANNEL_IDS = {d["id"] for d in ALLOWED_FORWARD_CHANNELS}

        MAX_TELEGRAM_MESSAGE_LENGTH = 4096

        # Get config data
        API_TOKEN = config_XML_root.find("bot_token").text
        ADMIN_GROUP_ID = int(config_XML_root.find("log_group").text)
        TECHNOLOG_GROUP_ID = int(config_XML_root.find("techno_log_group").text)

        BOT_NAME = config_XML_root.find("bot_name").text
        LOG_GROUP = config_XML_root.find("log_group").text
        LOG_GROUP_NAME = config_XML_root.find("log_group_name").text
        TECHNO_LOG_GROUP = config_XML_root.find("techno_log_group").text
        TECHNO_LOG_GROUP_NAME = config_XML_root.find("techno_log_group_name").text

        BOT = Bot(token=API_TOKEN)
        DP = Dispatcher(BOT)

    except FileNotFoundError as e:
        LOGGER.error("File not found: %s", e.filename)
    except ET.ParseError as e:
        LOGGER.error("Error parsing XML: %s", e)


def extract_status_change(
    chat_member_update: ChatMemberUpdated,
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
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.OWNER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.RESTRICTED,
    ]
    is_member = new_status in [
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.OWNER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.RESTRICTED,
    ]

    return was_member, is_member


# Function to check if the message was sent during the night
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


# Function to check if message contains 5 or more any regular emojis in a single line
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


# Function to check if the message text contains 5 or more consecutive capital letters in a line, excluding URLs
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


# Function to check message for predetermined word sentences
def check_message_for_sentences(message: types.Message):
    """Function to check the message for predetermined word sentences."""
    # Check if the message contains text
    if message.text is None:
        return False

    # Convert the message text to lowercase and tokenize it into words
    message_words = re.findall(r"\b\w+\b", message.text.lower())

    # Check if the message contains any of the predetermined sentences
    for sentence in PREDETERMINED_SENTENCES:
        # Tokenize the predetermined sentence into words
        sentence_words = re.findall(r"\b\w+\b", sentence.lower())

        # Check if all words in the predetermined sentence are in the message words
        if all(word in message_words for word in sentence_words):
            return True
    return False


# Check for spam indicator: 5 or more entities of type 'custom_emoji'
def has_custom_emoji_spam(message):
    """Function to check if a message contains spammy custom emojis."""
    message_dict = message.to_python()
    entities = message_dict.get("entities", [])
    custom_emoji_count = sum(
        1 for entity in entities if entity.get("type") == "custom_emoji"
    )
    return custom_emoji_count >= 5


def has_spam_entities(message: types.Message):
    """
    Check if the message is a spam by checking the entities.

    Args:
        message (types.Message): The message to check.

    Returns:
        bool: True if the message is spam, False otherwise.
    """
    if message.entities:
        for entity in message.entities:
            if entity["type"] in SPAM_TRIGGERS:
                # Spam detected
                return entity["type"]
    return None


def get_channel_id_by_name(channel_name):
    """Function to get the channel ID by its name."""
    for _id, name in channels_dict.items():
        if name == channel_name:
            return _id
    raise ValueError(f"Channel name {channel_name} not found in channels_dict.")


async def take_heuristic_action(message: types.Message, reason):
    """Function to take heuristically invoked action on the message."""

    LOGGER.warning(
        "%s. Sending automated report to the admin group for review...", reason
    )

    # Use the current date if message.forward_date is None
    forward_date = message.forward_date if message.forward_date else datetime.now()

    # process the message automatically
    found_message_data = get_spammer_details(
        message.from_user.id,
        message.from_user.first_name,
        message.from_user.last_name,
        forward_date,  # to see the script latency and reaction time
        message.forward_sender_name,
        message.forward_from_chat.title if message.forward_from_chat else None,
        forwarded_from_id=message.from_user.id,
    )
    await handle_forwarded_reports_with_details(
        message,
        message.from_user.id,
        message.from_user.first_name,
        message.from_user.last_name,
        message.forward_from_chat.title if message.forward_from_chat else None,
        message.forward_sender_name,
        found_message_data,
        reason=reason,
    )


async def on_startup(_dp: Dispatcher):
    """Function to handle the bot startup."""
    bot_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _commit_info = get_latest_commit_info()
    bot_start_message = (
        f"\nBot restarted at {bot_start_time}\n{'-' * 40}\n"
        f"Commit info: {_commit_info}\n"
        "Финальная битва между людьми и роботами...\n"
    )
    LOGGER.info(bot_start_message)

    # TODO Leave chats which is not in settings file
    # await BOT.leave_chat(-1002174154456)
    # await BOT.leave_chat(-1001876523135) # @lalaland_classy

    # start message to the Technolog group
    await BOT.send_message(
        TECHNOLOG_GROUP_ID, bot_start_message, message_thread_id=TECHNO_RESTART
    )


async def is_admin(reporter_user_id: int, admin_group_id_check: int) -> bool:
    """Function to check if the reporter is an admin in the Admin group."""
    chat_admins = await BOT.get_chat_administrators(admin_group_id_check)
    for admin in chat_admins:
        if admin.user.id == reporter_user_id:
            return True
    return False


async def handle_forwarded_reports_with_details(
    message: types.Message,
    spammer_id: int,
    spammer_first_name: str,
    spammer_last_name: str,
    forward_from_chat_title: str,
    forward_sender_name: str,
    found_message_data: dict,
    reason: str = "Automated report",
):
    """Function to handle forwarded messages with provided user details."""
    LOGGER.debug("############################################################")
    LOGGER.debug("                                                            ")
    LOGGER.debug("------------------------------------------------------------")
    LOGGER.debug(f"Received forwarded message for the investigation: {message}")
    # Send a thank you note to the user we dont need it for the automated reports anymore
    # await message.answer("Thank you for the report. We will investigate it.")
    # Forward the message to the admin group
    technnolog_spamMessage_copy = await BOT.forward_message(
        TECHNOLOG_GROUP_ID, message.chat.id, message.message_id
    )
    message_as_json = json.dumps(message.to_python(), indent=4, ensure_ascii=False)
    # Truncate and add an indicator that the message has been truncated
    if len(message_as_json) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
        message_as_json = message_as_json[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
    await BOT.send_message(TECHNOLOG_GROUP_ID, message_as_json)
    await BOT.send_message(TECHNOLOG_GROUP_ID, "Please investigate this message.")

    if not found_message_data:
        if forward_sender_name == "Deleted Account":
            found_message_data = get_spammer_details(
                spammer_id,
                spammer_first_name,
                spammer_last_name,
                message.forward_date,
                forward_sender_name,
                forward_from_chat_title,
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
        return

    LOGGER.debug("Message data: %s", found_message_data)
    # logger.debug("message object: %s", message)

    # Save both the original message_id and the forwarded message's date
    received_date = message.date if message.date else None
    report_id = int(str(message.chat.id) + str(message.message_id))
    # if report_id:
    # send report ID to the reporter - no need since this is automated report by condition now
    # await message.answer(f"Report ID: {report_id}")
    cursor.execute(
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
            message.forward_date if message.forward_date else None,
            received_date,
            str(found_message_data),
        ),
    )

    conn.commit()

    # Construct a link to the original message (assuming it's a supergroup or channel)
    # Extract the chat ID and remove the '-100' prefix if it exists
    chat_id = str(found_message_data[0])
    if chat_id.startswith("-100"):
        chat_id = chat_id[4:]  # remove leading -100
        # Construct the message link with the modified chat ID
        message_link = f"https://t.me/c/{chat_id}/{found_message_data[1]}"
    if found_message_data[2]:  # this is public chat
        message_link = f"https://t.me/{found_message_data[2]}/{found_message_data[1]}"

    # Get the username, first name, and last name of the user who forwarded the message and handle the cases where they're not available
    if message.forward_from:
        first_name = message.forward_from.first_name or ""
        last_name = message.forward_from.last_name or ""
    else:
        first_name = found_message_data[5]
        last_name = found_message_data[6]

    # Get the username
    username = found_message_data[4]
    if not username:
        username = "!UNDEFINED!"

    # Initialize user_id and user_link with default values
    user_id = found_message_data[3]

    technolog_chat_id = int(
        str(technnolog_spamMessage_copy.chat.id)[4:]
    )  # Remove -100 from the chat ID
    technnolog_spamMessage_copy_link = (
        f"https://t.me/c/{technolog_chat_id}/{technnolog_spamMessage_copy.message_id}"
    )

    # fix if message not forwarded and autoreported
    if message.forward_date:
        message_report_date = message.forward_date
    else:
        message_report_date = datetime.now()

    # Log the information with the link
    log_info = (
        f"💡 Report timestamp: {message.date}\n"
        f"💡 Spam message timestamp: {message_report_date}\n"
        f"💡 Reaction time: {message_report_date - message.date}\n"
        f"💔 Reported by automated spam detection system\n"
        f"💔 {reason}\n"
        f"💀 Forwarded from <a href='tg://resolve?domain={username}'>@{username}</a> : "
        f"{message.forward_sender_name or f'{first_name} {last_name}'}\n"
        f"💀 SPAMMER ID profile links:\n"
        f"   ├☠️ <a href='tg://user?id={user_id}'>Spammer ID based profile link</a>\n"
        f"   ├☠️ Plain text: tg://user?id={user_id}\n"
        f"   ├☠️ <a href='tg://openmessage?user_id={user_id}'>Android</a>\n"
        f"   └☠️ <a href='https://t.me/@id{user_id}'>IOS (Apple)</a>\n"
        f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
        f"ℹ️ <a href='{technnolog_spamMessage_copy_link}'>Technolog copy</a>\n"
        f"ℹ️ <a href='https://t.me/lolsbotcatcherbot?start={user_id}'>Profile spam check (@lolsbotcatcherbot)</a>\n"
        f"❌ <b>Use /ban {report_id}</b> to take action.\n"
    )
    LOGGER.debug("Report banner content:")
    LOGGER.debug(log_info)

    admin_ban_banner = (
        f"💡 Reaction time: {message_report_date - message.date}\n"
        f"💔 {reason}\n"
        f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
        f"ℹ️ <a href='{technnolog_spamMessage_copy_link}'>Technolog copy</a>\n"
        f"❌ <b>Use /ban {report_id}</b> to take action.\n"
    )

    # Send the banner to the technolog group
    await BOT.send_message(TECHNOLOG_GROUP_ID, log_info, parse_mode="HTML")

    # Keyboard ban/cancel/confirm buttons
    keyboard = InlineKeyboardMarkup()
    ban_btn = InlineKeyboardButton("Ban", callback_data=f"confirm_ban_{report_id}")
    keyboard.add(ban_btn)

    # Forward original message to the admin group
    await BOT.forward_message(
        ADMIN_GROUP_ID,
        found_message_data[0],
        found_message_data[1],
        message_thread_id=ADMIN_AUTOREPORTS,
    )
    # Show ban banner with buttons in the admin group to confirm or cancel the ban
    await BOT.send_message(
        ADMIN_GROUP_ID,
        admin_ban_banner,
        reply_markup=keyboard,
        parse_mode="HTML",
        message_thread_id=ADMIN_AUTOREPORTS,
        disable_web_page_preview=False,
    )

    # Construct link to the published banner and send it to the reporter
    # private_chat_id = int(
    #     str(admin_group_banner_message.chat.id)[4:]
    # Remove -100 from the chat ID
    # banner_link = (
    #     f"https://t.me/c/{private_chat_id}/{admin_group_banner_message.message_id}"
    # )

    # Check if the reporter is an admin in the admin group:
    # if await is_admin(message.from_user.id, ADMIN_GROUP_ID):
    #     # Send the banner link to the reporter
    #     await message.answer(f"Admin group banner link: {banner_link}")


if __name__ == "__main__":

    # scheduler_dict = {} TODO: Implement scheduler to manage chat closure at night for example

    # Dictionary to store the mapping of unhandled messages to admin's replies
    global unhandled_messages
    unhandled_messages = {}

    # Load configuration values from the XML file
    load_config()

    print("Using bot: " + BOT_NAME)
    print("Using log group: " + LOG_GROUP_NAME + ", id:" + LOG_GROUP)
    print(
        "Using techno log group: " + TECHNO_LOG_GROUP_NAME + ", id: " + TECHNO_LOG_GROUP
    )
    channel_info = [f"{name}({id_})" for name, id_ in zip(CHANNEL_NAMES, CHANNEL_IDS)]
    print("Monitoring chats: " + ", ".join(channel_info))
    print("\n")
    print(
        "Excluding autoreport when forwarded from chats: @"
        + " @".join([d["name"] for d in ALLOWED_FORWARD_CHANNELS])
    )
    print("\n")


    # New inout handler TODO add db update
    @DP.chat_member_handler()
    async def greet_chat_members(update: types.ChatMemberUpdated):
        """Greets new users in chats and announces when someone leaves"""
        LOGGER.info("Chat member update received: %s", update)

        result = extract_status_change(update)
        if result is None:
            return

        was_member, is_member = result
        cause_name = update.from_user.get_mention(as_html=False)
        member_name = update.new_chat_member.user.get_mention(as_html=False)

        # Send user join/left details to the technolog group
        inout_userid = update.from_user.id
        inout_userfirstname = update.from_user.first_name
        inout_userlastname = update.from_user.last_name or ""  # optional
        inout_username = update.from_user.username or "!UNDEFINED!"  # optional
        inout_chatid = str(update.chat.id)[4:]
        # inout_action = "JOINED" if message.new_chat_members else "LEFT"
        inout_chatname = update.chat.title
        inout_logmessage = (
            f"💡 <a href='tg://resolve?domain={inout_username}'>@{inout_username}</a> : "
            f"{inout_userfirstname} {inout_userlastname}\n"
            f"💡 <a href='https://t.me/c/{inout_chatid}'>{inout_chatname}</a>\n"  # https://t.me/c/1902317320/27448/27778
            f"💡 USER ID profile links:\n"
            f"   ├ℹ️ <a href='tg://user?id={inout_userid}'>USER ID based profile link</a>\n"
            f"   ├ℹ️ Plain text: tg://user?id={inout_userid}\n"
            f"   ├ℹ️ <a href='tg://openmessage?user_id={inout_userid}'>Android</a>\n"
            f"   └ℹ️ <a href='https://t.me/@id{inout_userid}'>IOS (Apple)</a>\n"
        )

        if not was_member and is_member:
            inout_action = "JOINED\n"
            await BOT.send_message(
                TECHNO_LOG_GROUP,
                inout_action + inout_logmessage,
                message_thread_id=TECHNO_INOUT,
                parse_mode="HTML",
            )
            LOGGER.info(
                "%s added %s to the chat %s (ID: %d)",
                cause_name,
                member_name,
                update.chat.title,
                update.chat.id,
            )
        elif was_member and not is_member:
            inout_action = "LEFT\n"
            await BOT.send_message(
                TECHNO_LOG_GROUP,
                inout_action + inout_logmessage,
                message_thread_id=TECHNO_INOUT,
                parse_mode="HTML",
            )
            LOGGER.info(
                "%s removed %s from the chat %s (ID: %d)",
                cause_name,
                member_name,
                update.chat.title,
                update.chat.id,
            )


    @DP.message_handler(
        lambda message: message.forward_date is not None
        and message.chat.id not in CHANNEL_IDS
        and message.chat.id != ADMIN_GROUP_ID
        and message.chat.id != TECHNOLOG_GROUP_ID,
        content_types=types.ContentTypes.ANY,
    )
    async def handle_forwarded_reports(message: types.Message):
        """Function to handle forwarded messages."""
        LOGGER.debug("############################################################")
        LOGGER.debug("                                                            ")
        LOGGER.debug("------------------------------------------------------------")
        LOGGER.debug("Received forwarded message for the investigation: %s", message)
        # Send a thank you note to the user
        await message.answer("Thank you for the report. We will investigate it.")
        # Forward the message to the admin group
        technnolog_spam_message_copy = await BOT.forward_message(
            TECHNOLOG_GROUP_ID, message.chat.id, message.message_id
        )
        message_as_json = json.dumps(message.to_python(), indent=4, ensure_ascii=False)
        # Truncate and add an indicator that the message has been truncated
        if len(message_as_json) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
            message_as_json = message_as_json[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
        await BOT.send_message(TECHNOLOG_GROUP_ID, message_as_json)
        await BOT.send_message(TECHNOLOG_GROUP_ID, "Please investigate this message.")

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

        # message is forwarded from a user or forwarded forward from a user
        if spammer_id:
            found_message_data = get_spammer_details(
                spammer_id,
                spammer_first_name,
                spammer_last_name,
                message.forward_date,
                forward_sender_name,
                forward_from_chat_title,
                forwarded_from_id=spammer_id,
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
                )
                LOGGER.debug(
                    f"The requested data associated with the Deleted Account has been retrieved. Please verify the accuracy of this information, as it cannot be guaranteed due to the account's deletion."
                )
                await message.answer(
                    f"The requested data associated with the Deleted Account has been retrieved. Please verify the accuracy of this information, as it cannot be guaranteed due to the account's deletion."
                )
            else:
                e = "Renamed Account or wrong chat?"
                LOGGER.debug(
                    f"Could not retrieve the author's user ID. Please ensure you're reporting recent messages. {e}"
                )
                await message.answer(
                    f"Could not retrieve the author's user ID. Please ensure you're reporting recent messages. {e}"
                )

        if not found_message_data:  # Last resort. Give up.
            return
            # pass

        LOGGER.debug(f"Message data: {found_message_data}")

        # Save both the original message_id and the forwarded message's date
        received_date = message.date if message.date else None
        report_id = int(str(message.chat.id) + str(message.message_id))
        if report_id:
            # send report ID to the reporter
            await message.answer(f"Report ID: {report_id}")
        cursor.execute(
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
                message.forward_date if message.forward_date else None,
                received_date,
                str(found_message_data),
            ),
        )

        conn.commit()

        # Construct a link to the original message (assuming it's a supergroup or channel)
        message_link = f"https://t.me/{found_message_data[2]}/{found_message_data[1]}"

        # Get the username, first name, and last name of the user who forwarded the message and handle the cases where they're not available
        if message.forward_from:
            first_name = message.forward_from.first_name or ""
            last_name = message.forward_from.last_name or ""
        else:
            first_name = found_message_data[5]
            last_name = found_message_data[6]

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
        # print('Spam Message Technolog Copy: ', technnolog_spamMessage_copy)

        # print('##########----------DEBUG----------##########')

        # Log the information with the link
        log_info = (
            f"💡 Report timestamp: {message.date}\n"
            f"💡 Spam message timestamp: {message.forward_date}\n"
            f"💡 Reaction time: {message.date - message.forward_date}\n"
            f"💔 Reported by admin <a href='tg://user?id={message.from_user.id}'></a>"
            f"@{message.from_user.username or '!_U_N_D_E_F_I_N_E_D_!'}\n"
            f"💀 Forwarded from <a href='tg://resolve?domain={username}'>@{username}</a> : "
            f"{message.forward_sender_name or f'{first_name} {last_name}'}\n"
            f"💀 SPAMMER ID profile links:\n"
            f"   ├☠️ <a href='tg://user?id={user_id}'>Spammer ID based profile link</a>\n"
            f"   ├☠️ Plain text: tg://user?id={user_id}\n"
            f"   ├☠️ <a href='tg://openmessage?user_id={user_id}'>Android</a>\n"
            f"   └☠️ <a href='https://t.me/@id{user_id}'>IOS (Apple)</a>\n"
            f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
            f"ℹ️ <a href='{technnolog_spam_message_copy_link}'>Technolog copy</a>\n"
            f"ℹ️ <a href='https://t.me/lolsbotcatcherbot?start={user_id}'>Profile spam check (@lolsbotcatcherbot)</a>\n"
            f"❌ <b>Use /ban {report_id}</b> to take action.\n"
        )
        LOGGER.debug("Report banner content:")
        LOGGER.debug(log_info)

        admin_ban_banner = (
            f"💡 Reaction time: {message.date - message.forward_date}\n"
            f"💔 Reported by admin <a href='tg://user?id={message.from_user.id}'></a>"
            f"@{message.from_user.username or '!_U_N_D_E_F_I_N_E_D_!'}\n"
            f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
            f"ℹ️ <a href='{technnolog_spam_message_copy_link}'>Technolog copy</a>\n"
            f"❌ <b>Use /ban {report_id}</b> to take action.\n"
        )

        # Send the banner to the technolog group
        await BOT.send_message(TECHNOLOG_GROUP_ID, log_info, parse_mode="HTML")

        # Keyboard ban/cancel/confirm buttons
        keyboard = InlineKeyboardMarkup()
        ban_btn = InlineKeyboardButton("Ban", callback_data=f"confirm_ban_{report_id}")
        keyboard.add(ban_btn)

        # Show ban banner with buttons in the admin group to confirm or cancel the ban
        # And store published bunner message data to provide link to the reportee
        # admin_group_banner_message: Message = None # Type hinting
        if await is_admin(message.from_user.id, ADMIN_GROUP_ID):
            admin_group_banner_message = await BOT.send_message(
                ADMIN_GROUP_ID,
                admin_ban_banner,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        else:  # send report to AUTOREPORT thread of the admin group
            admin_group_banner_message = await BOT.send_message(
                ADMIN_GROUP_ID,
                admin_ban_banner,
                reply_markup=keyboard,
                parse_mode="HTML",
                message_thread_id=ADMIN_AUTOREPORTS,
            )

        # Log the banner message data
        # logger.debug(f"Admin group banner: {admin_group_banner_message}")
        # Construct link to the published banner and send it to the reporter
        private_chat_id = int(
            str(admin_group_banner_message.chat.id)[4:]
        )  # Remove -100 from the chat ID
        banner_link = (
            f"https://t.me/c/{private_chat_id}/{admin_group_banner_message.message_id}"
        )
        # Log the banner link
        # logger.debug(f"Banner link: {banner_link}")

        # Check if the reporter is an admin in the admin group:
        if await is_admin(message.from_user.id, ADMIN_GROUP_ID):
            # Send the banner link to the reporter
            await message.answer(f"Admin group banner link: {banner_link}")

    @DP.callback_query_handler(lambda c: c.data.startswith("confirm_ban_"))
    async def ask_confirmation(callback_query: CallbackQuery):
        """Function to ask for confirmation before banning the user."""
        *_, message_id_to_ban = callback_query.data.split("_")

        # DEBUG:
        # logger.debug(f"Report {callback_query} confirmed for banning.")

        keyboard = InlineKeyboardMarkup(row_width=2)
        confirm_btn = InlineKeyboardButton(
            "🟢 Confirm", callback_data=f"do_ban_{message_id_to_ban}"
        )
        cancel_btn = InlineKeyboardButton(
            "🔴 Cancel", callback_data=f"reset_ban_{message_id_to_ban}"
        )

        keyboard.add(confirm_btn, cancel_btn)

        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=keyboard,
        )

    @DP.callback_query_handler(lambda c: c.data.startswith("do_ban_"))
    async def handle_ban(callback_query: CallbackQuery):
        """Function to ban the user and delete all known to bot messages."""

        # remove buttons from the admin group first
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
        )

        # get the message ID to ban
        try:
            *_, message_id_to_ban = callback_query.data.split("_")
            message_id_to_ban = int(message_id_to_ban)

            cursor.execute(
                "SELECT chat_id, message_id, forwarded_message_data, received_date FROM recent_messages WHERE message_id = ?",
                (message_id_to_ban,),
            )
            result = cursor.fetchone()

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

            LOGGER.debug(
                f"Original chat ID: {original_chat_id}, Original message ID: {report_id}, Forwarded message data: {forwarded_message_data}, Original message timestamp: {original_message_timestamp}"
            )

            author_id = eval(forwarded_message_data)[3]
            LOGGER.debug(f"Author ID retrieved for original message: {author_id}")
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"Author ID retrieved for original message: {author_id}",
            )
            if not author_id:
                # show error message
                await callback_query.message.reply(
                    "Could not retrieve the author's user ID from the report."
                )
                return

            # Attempting to ban user from channels
            for chat_id in CHANNEL_IDS:
                LOGGER.debug(
                    f"Attempting to ban user {author_id} from chat {channels_dict[chat_id]} ({chat_id})"
                )

                try:
                    await BOT.ban_chat_member(
                        chat_id=chat_id,
                        user_id=author_id,
                        until_date=None,
                        revoke_messages=True,
                    )
                    LOGGER.debug(
                        f"User {author_id} banned and their messages deleted from chat {channels_dict[chat_id]} ({chat_id})."
                    )
                except Exception as inner_e:
                    LOGGER.error(
                        f"Failed to ban and delete messages in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}"
                    )
                    await BOT.send_message(
                        TECHNOLOG_GROUP_ID,
                        f"Failed to ban and delete messages in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}",
                    )

            # select all messages from the user in the chat
            query = """
                SELECT chat_id, message_id, user_name
                FROM recent_messages 
                WHERE user_id = :author_id
                """
            params = {"author_id": author_id}
            result = cursor.execute(query, params).fetchall()

            # delete them one by one
            for chat_id, message_id, user_name in result:
                retry_attempts = 3  # number of attempts to delete the message
                for attempt in range(retry_attempts):
                    try:
                        await BOT.delete_message(chat_id=chat_id, message_id=message_id)
                        LOGGER.debug(
                            f"Message {message_id} deleted from chat {channels_dict[chat_id]} ({chat_id}) for user @{user_name} ({author_id})."
                        )
                        break  # break the loop if the message was deleted successfully
                    except RetryAfter as e:
                        wait_time = (
                            e.timeout
                        )  # This gives you the time to wait in seconds
                        if (
                            attempt < retry_attempts - 1
                        ):  # Don't wait after the last attempt
                            LOGGER.warning(
                                f"Rate limited. Waiting for {wait_time} seconds."
                            )
                            time.sleep(wait_time)
                    except MessageToDeleteNotFound:
                        LOGGER.warning(
                            f"Message {message_id} in chat {channels_dict[chat_id]} ({chat_id}) not found for deletion."
                        )
                        break  # No need to retry in this case
                    # TODO manage the case when the bot is not an admin in the channel
                    except Exception as inner_e:
                        LOGGER.error(
                            f"Failed to delete message {message_id} in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}"
                        )
                        await BOT.send_message(
                            TECHNOLOG_GROUP_ID,
                            f"Failed to delete message {message_id} in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}",
                        )
            LOGGER.debug(
                f"User {author_id} banned and their messages deleted where applicable."
            )
            button_pressed_by = callback_query.from_user.username

            await BOT.send_message(
                ADMIN_GROUP_ID,
                f"Report {message_id_to_ban} action taken by @{button_pressed_by}: User {author_id} banned and their messages deleted where applicable.",
                message_thread_id=callback_query.message.message_thread_id,
            )
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"Report {message_id_to_ban} action taken by @{button_pressed_by}: User {author_id} banned and their messages deleted where applicable.",
            )

        except Exception as e:
            LOGGER.error(f"Error in handle_ban function: {e}")
            await callback_query.message.reply(f"Error: {e}")

    @DP.callback_query_handler(lambda c: c.data.startswith("reset_ban_"))
    async def reset_ban(callback_query: CallbackQuery):
        """Function to reset the ban button."""
        *_, report_id_to_ban = callback_query.data.split("_")

        # remove buttons from the admin group
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
        )

        # DEBUG:
        button_pressed_by = callback_query.from_user.username
        # logger.debug("Button pressed by the admin: @%s", button_pressed_by)

        LOGGER.info("Report %s button ACTION CANCELLED!!!", report_id_to_ban)

        await BOT.send_message(
            ADMIN_GROUP_ID,
            f"Button ACTION CANCELLED by @{button_pressed_by}: Report {report_id_to_ban} WAS NOT PROCESSED!!! "
            f"Report them again if needed or use /ban {report_id_to_ban} command.",
            message_thread_id=callback_query.message.message_thread_id,
        )
        await BOT.send_message(
            TECHNOLOG_GROUP_ID,
            f"CANCEL button pressed by @{button_pressed_by}. "
            f"Button ACTION CANCELLED: Report {report_id_to_ban} WAS NOT PROCESSED. "
            f"Report them again if needed or use /ban {report_id_to_ban} command.",
        )

    # check for users joining/leaving the chat TODO not functional!
    # @DP.message_handler(
    #     content_types=[
    #         types.ContentType.NEW_CHAT_MEMBERS,
    #         types.ContentType.LEFT_CHAT_MEMBER,
    #     ]
    # )
    # async def user_joined_chat(message: types.Message):
    #     """Function to handle users joining or leaving the chat."""
    #     # print("Users changed", message.new_chat_members, message.left_chat_member)

    #     # TODO add logic to store join/left events in the database
    #     new_chat_member = len(message.new_chat_members) > 0
    #     left_chat_member = bool(getattr(message.left_chat_member, "id", False))

    #     cursor.execute(
    #         """
    #         INSERT OR REPLACE INTO recent_messages
    #         (chat_id, chat_username, message_id, user_id, user_name, user_first_name, user_last_name, forward_date, forward_sender_name, received_date, from_chat_title, forwarded_from_id, forwarded_from_username, forwarded_from_first_name, forwarded_from_last_name, new_chat_member, left_chat_member)
    #         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    #         """,
    #         (
    #             getattr(message.chat, "id", None),
    #             getattr(message.chat, "username", ""),
    #             getattr(message, "message_id", None),
    #             getattr(message.from_user, "id", None),
    #             getattr(message.from_user, "username", ""),
    #             getattr(message.from_user, "first_name", ""),
    #             getattr(message.from_user, "last_name", ""),
    #             getattr(message, "forward_date", None),
    #             getattr(message, "forward_sender_name", ""),
    #             getattr(message, "date", None),
    #             getattr(message.forward_from_chat, "title", None),
    #             getattr(message.forward_from, "id", None),
    #             getattr(message.forward_from, "username", ""),
    #             getattr(message.forward_from, "first_name", ""),
    #             getattr(message.forward_from, "last_name", ""),
    #             new_chat_member,
    #             left_chat_member,
    #         ),
    #     )
    #     conn.commit()

    #     # Send user join/left details to the technolog group
    #     inout_userid = message.from_id
    #     inout_userfirstname = message.from_user.first_name
    #     inout_userlastname = message.from_user.last_name or ""  # optional
    #     inout_username = message.from_user.username or "!UNDEFINED!"  # optional
    #     inout_chatid = str(message.chat.id)[4:]
    #     inout_action = "JOINED" if message.new_chat_members else "LEFT"
    #     inout_chatname = message.chat.title
    #     inout_logmessage = (
    #         f"💡 <a href='tg://resolve?domain={inout_username}'>@{inout_username}</a> : "
    #         f"{inout_userfirstname} {inout_userlastname} {inout_action}\n"
    #         f"💡 <a href='https://t.me/c/{inout_chatid}'>{inout_chatname}</a>\n"  # https://t.me/c/1902317320/27448/27778
    #         f"💡 USER ID profile links:\n"
    #         f"   ├ℹ️ <a href='tg://user?id={inout_userid}'>USER ID based profile link</a>\n"
    #         f"   ├ℹ️ Plain text: tg://user?id={inout_userid}\n"
    #         f"   ├ℹ️ <a href='tg://openmessage?user_id={inout_userid}'>Android</a>\n"
    #         f"   └ℹ️ <a href='https://t.me/@id{inout_userid}'>IOS (Apple)</a>\n"
    #     )

    #     await BOT.send_message(
    #         TECHNOLOG_GROUP_ID,
    #         inout_logmessage,
    #         parse_mode="HTML",
    #         message_thread_id=TECHNO_INOUT,
    #     )


    @DP.message_handler(custom_filter, content_types=types.ContentTypes.ANY)
    # @DP.message_handler(
    #     lambda message: message.chat.id in CHANNEL_IDS,
    #     content_types=types.ContentTypes.ANY,
    # )
    async def store_recent_messages(message: types.Message):
        """Function to store recent messages in the database."""
        try:
            # Log the full message object for debugging
            # or/and forward the message to the technolog group
            # TODO remove exceptions
            if (
                message.chat.id == -1001461337235 or message.chat.id == -1001527478834
            ):  # mevrikiy or beautymauritius
                # temporal horse fighting
                await BOT.forward_message(
                    TECHNOLOG_GROUP_ID,
                    message.chat.id,
                    message.message_id,
                    message_thread_id=TECHNO_ORIGINALS,
                )
                LOGGER.info(
                    "Message ID: %s Forwarded from chat: %s with title: %s",
                    message.message_id,
                    message.chat.id,
                    message.chat.title,
                )
                # # Convert the Message object to a dictionary
                # message_dict = message.to_python()
                # formatted_message = json.dumps(
                #     message_dict, indent=4, ensure_ascii=False
                # )  # Convert back to a JSON string with indentation and human-readable characters
                # logger.debug(
                #     "\nReceived message object:\n %s\n",
                #     formatted_message,
                # )
                # if len(formatted_message) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
                #     formatted_message = (
                #         formatted_message[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
                #     )

                # TODO hash JSON to make signature
                # await BOT.send_message(
                #     TECHNOLOG_GROUP_ID,
                #     formatted_message,
                #     message_thread_id=TECHNO_ORIGINALS,
                # )

            # logger.debug(
            #     # f"Bot?: {message.from_user.is_bot}\n"
            #     # f"First Name?: {message.from_user.first_name}\n"
            #     # f"Username?: {message.from_user.username}\n"
            #     # f"Author signature?: {message.author_signature}\n"
            #     f"Forwarded from chat type?: {message.forward_from_chat.type=='channel'}\n"
            # )
            # TODO remove afer sandboxing

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
            # logger.info(f"Stored recent message: {message}")

            # check if the message is a spam by checking the entities
            entity_spam_trigger = has_spam_entities(message)

            # search for the user join chat event date using user_id in the DB
            user_join_chat_date_str = cursor.execute(
                "SELECT received_date FROM recent_messages WHERE user_id = ? AND new_chat_member = 1",
                (message.from_user.id,),
            ).fetchone()
            # if there is no such data assume user joined the chat 3 years ago in seconds
            user_join_chat_date_str = (
                user_join_chat_date_str[0]
                if user_join_chat_date_str
                else "2020-01-01 00:00:00"  # datetime(2020, 1, 1, 0, 0, 0)
            )
            # print(
            #     "USER JOINED: ",
            #     user_join_chat_date_str,
            # )

            # Convert the string to a datetime object
            user_join_chat_date = datetime.strptime(
                user_join_chat_date_str, "%Y-%m-%d %H:%M:%S"
            )

            # flag true if user joined the chat more than 3 days ago
            user_is_old = (message.date - user_join_chat_date).total_seconds() > 259200
            user_is_1hr_old = (
                message.date - user_join_chat_date
            ).total_seconds() < 3600
            user_is_10sec_old = (
                message.date - user_join_chat_date
            ).total_seconds() < 10
            # print("User is old: ", user_is_omake it external function getting message argument and returning true or falseld)
            # print("User is 1hr old: ", user_is_1hr_old)
            # print("User is 10sec old: ", user_is_10sec_old)

            if not user_is_old:
                # check if the message is sent less then 10 seconds after joining the chat
                if user_is_10sec_old:
                    # this is possibly a bot
                    print("This is possibly a bot")
                    the_reason = (
                        "Message is sent less then 10 seconds after joining the chat"
                    )
                    await take_heuristic_action(message, the_reason)
                # check if the message is sent less then 1 hour after joining the chat
                elif user_is_1hr_old:
                    # this is possibly a spam
                    print("This is possibly a spam with links or other entities")
                    if entity_spam_trigger:  # invoke heuristic action
                        the_reason = (
                            "Message is sent less then 1 hour after joining the chat and have "
                            + entity_spam_trigger
                            + " inside"
                        )
                        await take_heuristic_action(message, the_reason)
                    else:
                        # prevent NoneType error if there is no message.forward_from_chat.type
                        chat_type = (
                            message.forward_from_chat.type
                            if message.forward_from_chat
                            else None
                        )
                        # check if it is forward from channel
                        if chat_type == "channel":
                            # check for allowed channels for forwards
                            if (
                                message.forward_from_chat.id
                                not in ALLOWED_FORWARD_CHANNEL_IDS
                            ):
                                # this is possibly a spam
                                the_reason = "Message is forwarded from unknown channel"
                                await take_heuristic_action(message, the_reason)

            if has_custom_emoji_spam(
                message
            ):  # check if the message contains spammy custom emojis
                the_reason = "Message contains 5 or more spammy custom emojis"
                await take_heuristic_action(message, the_reason)

            elif message_sent_during_night(message):  # disabled for now only logging
                the_reason = "Message sent during the night"
                print(f"Message sent during the night: {message}")

            elif check_message_for_sentences(message):
                the_reason = "Message contains spammy sentences"
                await take_heuristic_action(message, the_reason)

            elif check_message_for_capital_letters(
                message
            ) and check_message_for_emojis(message):
                the_reason = "Message contains 5+ spammy capital letters and 5+ spammy regular emojis"
                await take_heuristic_action(message, the_reason)

            # elif check_message_for_capital_letters(message):
            #     the_reason = "Message contains 5+ spammy capital letters"
            #     await take_heuristic_action(message, the_reason)

            # elif check_message_for_emojis(message):
            #     the_reason = "Message contains 5+ spammy regular emojis"
            #     await take_heuristic_action(message, the_reason)

        except Exception as e:
            LOGGER.error("Error storing recent message: %s", e)

    # TODO: Remove this if the buttons works fine
    @DP.message_handler(commands=["ban"], chat_id=ADMIN_GROUP_ID)
    async def ban(message: types.Message):
        """Function to ban the user and delete all known to bot messages using '/ban reportID' text command."""
        try:
            # logger.debug("ban triggered.")

            command_args = message.text.split()
            LOGGER.debug("Command arguments received: %s", command_args)

            if len(command_args) < 2:
                raise ValueError("Please provide the message ID of the report.")

            report_msg_id = int(command_args[1])
            LOGGER.debug(f"Report message ID parsed: {report_msg_id}")

            cursor.execute(
                "SELECT chat_id, message_id, forwarded_message_data, received_date FROM recent_messages WHERE message_id = ?",
                (report_msg_id,),
            )
            result = cursor.fetchone()
            LOGGER.debug(
                f"Database query result for forwarded_message_data {report_msg_id}: {result}"
            )
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"Database query result for forwarded_message_data {report_msg_id}: {result}",
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
                f"Original chat ID: {original_chat_id}, Original message ID: {original_message_id}, Forwarded message data: {forwarded_message_data}, Original message timestamp: {original_message_timestamp}"
            )

            author_id = eval(forwarded_message_data)[3]
            LOGGER.debug(f"Author ID retrieved for original message: {author_id}")
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"Author ID retrieved for original message: {author_id}",
            )
            if not author_id:
                await message.reply(
                    "Could not retrieve the author's user ID from the report."
                )
                return

            # Attempting to ban user from channels
            for chat_id in CHANNEL_IDS:
                LOGGER.debug(
                    f"Attempting to ban user {author_id} from chat {channels_dict[chat_id]} ({chat_id})"
                )

                try:
                    await BOT.ban_chat_member(
                        chat_id=chat_id,
                        user_id=author_id,
                        until_date=None,
                        revoke_messages=True,
                    )
                    LOGGER.debug(
                        f"User {author_id} banned and their messages deleted from chat {channels_dict[chat_id]} ({chat_id})."
                    )
                    await BOT.send_message(
                        TECHNOLOG_GROUP_ID,
                        f"User {author_id} banned and their messages deleted from chat {channels_dict[chat_id]} ({chat_id}).",
                    )
                except Exception as inner_e:
                    LOGGER.error(
                        f"Failed to ban and delete messages in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}"
                    )
                    await BOT.send_message(
                        TECHNOLOG_GROUP_ID,
                        f"Failed to ban and delete messages in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}",
                    )
            # select all messages from the user in the chat
            query = """
                SELECT chat_id, message_id, user_name
                FROM recent_messages 
                WHERE user_id = :author_id
                """
            params = {"author_id": author_id}
            result = cursor.execute(query, params).fetchall()
            # delete them one by one
            for chat_id, message_id, user_name in result:
                try:
                    await BOT.delete_message(chat_id=chat_id, message_id=message_id)
                    LOGGER.debug(
                        f"Message {message_id} deleted from chat {channels_dict[chat_id]} ({chat_id}) for user @{user_name} ({author_id})."
                    )
                except Exception as inner_e:
                    LOGGER.error(
                        f"Failed to delete message {message_id} in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}"
                    )
                    await BOT.send_message(
                        TECHNOLOG_GROUP_ID,
                        f"Failed to delete message {message_id} in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}",
                    )
            LOGGER.debug(
                f"User {author_id} banned and their messages deleted where applicable."
            )
            await message.reply(
                "Action taken: User banned and their messages deleted where applicable."
            )

        except Exception as e:
            LOGGER.error("Error in ban function: %s", e)
            await message.reply(f"Error: {e}")

    # Handler for the /unban command
    @DP.message_handler(commands=["unban"], chat_id=ADMIN_GROUP_ID)
    async def unban_user(message: types.Message):
        """Function to unban the user with userid in all channels listed in CHANNEL_NAMES."""
        try:
            command_args = message.text.split()
            LOGGER.debug("Command arguments received: %s", command_args)

            if len(command_args) < 2:
                raise ValueError("Please provide the user ID to unban.")

            user_id = int(command_args[1])
            LOGGER.debug("User ID to unban: %d", user_id)

            for channel_name in CHANNEL_NAMES:
                channel_id = get_channel_id_by_name(channel_name)
                if channel_id:
                    try:
                        await BOT.unban_chat_member(chat_id=channel_id, user_id=user_id)
                        LOGGER.info(
                            "Unbanned user %d in channel %s (ID: %d)",
                            user_id,
                            channel_name,
                            channel_id,
                        )
                    except Exception as e:
                        LOGGER.error(
                            "Failed to unban user %d in channel %s (ID: %d): %s",
                            user_id,
                            channel_name,
                            channel_id,
                            e,
                        )

            await message.reply(
                f"User {user_id} has been unbanned in all specified channels."
            )
        except ValueError as ve:
            await message.reply(str(ve))
        except Exception as e:
            LOGGER.error("Error in unban_user: %s", e)
            await message.reply("An error occurred while trying to unban the user.")

    @DP.message_handler(
        lambda message: message.chat.id
        not in [ADMIN_GROUP_ID, TECHNOLOG_GROUP_ID, ADMIN_USER_ID, CHANNEL_IDS]
        and message.forward_from_chat is None,
        content_types=types.ContentTypes.ANY,
    )  # exclude admins and technolog group
    async def log_all_unhandled_messages(message: types.Message):
        """Function to log all unhandled messages to the technolog group and admin."""
        try:
            # logger.debug(f"Received UNHANDLED message object:\n{message}")

            # Send unhandled message to the technolog group
            # await BOT.send_message(
            #     TECHNOLOG_GROUP_ID,
            #     f"Received UNHANDLED message object:\n{message}",
            #     message_thread_id=TECHNO_UNHANDLED,
            # )
            await message.forward(
                TECHNOLOG_GROUP_ID, message_thread_id=TECHNO_UNHANDLED
            )  # forward all unhandled messages to technolog group

            # Convert the Message object to a dictionary
            message_dict = message.to_python()
            formatted_message = json.dumps(
                message_dict, indent=4, ensure_ascii=False
            )  # Convert back to a JSON string with indentation and human-readable characters

            # LOGGER.debug(
            #     "\nReceived message object:\n %s\n",
            #     formatted_message,
            # )

            if len(formatted_message) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
                formatted_message = (
                    formatted_message[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
                )

            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                formatted_message,
                message_thread_id=TECHNO_UNHANDLED,
            )

            # /start easteregg
            if message.text == "/start":
                await BOT.send_message(
                    message.chat.id,
                    "Everything that follows is a result of what you see here.\n I'm sorry. My responses are limited. You must ask the right questions.",
                )
                # await message.reply(
                #     "Everything that follows is a result of what you see here.\n I'm sorry. My responses are limited. You must ask the right questions.",
                # )

            user_id = message.chat.id

            if message.from_user.username:
                user_name = message.from_user.username
            else:
                user_name = user_id

            bot_received_message = (
                f" Profile links:\n"
                f"   ├ <a href='tg://user?id={user_id}'>ID based profile link</a>\n"
                f"   ├ Plain text: tg://user?id={user_id}\n"
                f"   ├ <a href='tg://openmessage?user_id={user_id}'>Android</a>\n"
                f"   ├ <a href='https://t.me/@id{user_id}'>IOS (Apple)</a>\n"
                f"   └ <a href='tg://resolve?domain={user_name}'>@{user_name}</a>\n"
            )

            # Create an inline keyboard with two buttons
            inline_kb = InlineKeyboardMarkup(row_width=3)
            button1 = InlineKeyboardButton(
                "SRY",
                callback_data="button_sry",
            )
            button2 = InlineKeyboardButton(
                "END",
                callback_data="button_end",
            )
            button3 = InlineKeyboardButton(
                "RND",
                callback_data="button_rnd",
            )
            inline_kb.add(button1, button2, button3)

            _reply_message = (
                f"Received message from {message.from_user.first_name}:\n{bot_received_message}\n"
                f"I'm sorry. My responses are limited. You must ask the right questions.\n"
            )

            # _reply_message = f"Received message from {message.from_user.first_name}:\n{bot_received_message}\n"

            # Send the message with the inline keyboard
            await BOT.send_message(
                ADMIN_USER_ID,
                _reply_message,
                reply_markup=inline_kb,
                parse_mode="HTML",
            )

            admin_message = await BOT.forward_message(
                ADMIN_USER_ID, message.chat.id, message.message_id
            )

            # Store the mapping of unhandled message to admin's message
            # TODO move it to DB
            unhandled_messages[admin_message.message_id] = [
                message.chat.id,
                message.message_id,
                message.from_user.first_name,
            ]

            return

        except Exception as e:
            LOGGER.error("Error in log_all_unhandled_messages function: %s", e)
            await message.reply(f"Error: {e}")

    # Function to simulate admin reply
    async def simulate_admin_reply(
        original_message_chat_id, original_message_chat_reply_id, response_text
    ):
        """Simulate an admin reply with the given response text."""
        await BOT.send_message(
            original_message_chat_id,
            response_text,
            reply_to_message_id=original_message_chat_reply_id,
        )

    # Callback query handler to handle button presses
    @DP.callback_query_handler(
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
                )
                # Split the motd string into individual lines
                motd_lines = motd.split("\n")
                # Select a random line
                random_motd = random.choice(motd_lines)
                # Assign the selected line to a variable
                response_text = random_motd

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
                await BOT.send_message(
                    callback_query.message.chat.id,
                    "Replied to " + original_message_user_name + ": " + response_text,
                )

                # Edit the original message to remove the buttons
                await BOT.edit_message_reply_markup(
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.message_id,
                    reply_markup=None,
                )

        except Exception as e:
            LOGGER.error("Error in process_callback function: %s", e)

        # Acknowledge the callback query
        await callback_query.answer()

    # Function to handle replies from the admin to unhandled messages excluding forwards
    @DP.message_handler(
        lambda message: message.forward_date is None
        and message.chat.id == ADMIN_USER_ID,
        content_types=types.ContentTypes.TEXT,
    )
    async def handle_admin_reply(message: types.Message):
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
                    await BOT.send_message(
                        original_message_chat_id,
                        _message_text[1:],
                    )
                else:
                    await BOT.send_message(
                        original_message_chat_id,
                        _message_text,
                        reply_to_message_id=original_message_chat_reply_id,
                    )

                # Optionally, you can delete the mapping after the reply is processed
                # del unhandled_messages[message.reply_to_message.message_id]

        except Exception as e:
            LOGGER.error(f"Error in handle_admin_reply function: {e}")
            await message.reply(f"Error: {e}")

    # TODO if failed to delete message  since the message is not found - delete corresponding record in the table
    # TODO if succeed to delete message also remove this record from the DB
    # TODO reply to individual messages by bot in the monitored groups or make posts
    # TODO hash all banned spam messages and check if the signature of new message is same as spam to produce autoreport

    # Uncomment this to get the chat ID of a group or channel
    # @dp.message_handler(commands=["getid"])
    # async def cmd_getid(message: types.Message):
    #     await message.answer(f"This chat's ID is: {message.chat.id}")

    executor.start_polling(DP, skip_updates=True, on_startup=on_startup)

    # Close SQLite connection
    conn.close()
