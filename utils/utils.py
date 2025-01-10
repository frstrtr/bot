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
import subprocess
import re
from datetime import datetime
from typing import Optional, Tuple

import os
import sys
import pytz
import emoji

from aiogram import types


def initialize_logger():
    """Initialize the logger."""
    # Configure logging to use UTF-8 encoding
    logger = logging.getLogger(__name__)
    if not logger.hasHandlers():
        logger.setLevel(
            logging.DEBUG
        )  # Set the logging level to INFO for detailed output

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


def extract_chat_id_and_message_id_from_link(message_link):
    """Extract chat ID and message ID from a message link."""
    if not str(message_link).startswith("https://t.me/"):
        raise ValueError("Invalid message link format")
    try:
        parts = message_link.split("/")
        if len(parts) == 5:
            chat_id = parts[3]
            message_id = int(parts[-1])
        elif "c" in parts:
            chat_id = parts[4]
            message_id = int(parts[-1])
        else:
            chat_id = parts[3]
            message_id = int(parts[-1])

        if "c" in parts:
            chat_id = int("-100" + chat_id)
        elif chat_id != "":
            chat_id = "@" + chat_id
        else:
            raise ValueError("Invalid message link format")

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
