import asyncio
import aiocron
from datetime import datetime
import os
import random
import sqlite3
import xml.etree.ElementTree as ET
import json
import time
import html
import tracemalloc

# import tracemalloc # for memory usage debugging

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram import utils
from datetime import timedelta

# import requests
# from PIL import Image
# from io import BytesIO
# from io import BytesIO
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ChatMemberStatus,
)

from aiogram import executor

# from aiogram.types import Message
from aiogram.utils.exceptions import (
    MessageToDeleteNotFound,
    # MessageCantBeDeleted,
    RetryAfter,
)

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
    extract_chat_id_and_message_id_from_link,
    get_channel_id_by_name,
    get_channel_name_by_id,
    has_spam_entities,
    load_predetermined_sentences,
)
from utils.utils_decorators import (
    is_not_bot_action,
    is_forwarded_from_unknown_channel_message,
    is_admin_user_message,
    is_channel_message,
    is_valid_message,
)

from utils.utils_config import (
    CHANNEL_IDS,
    ADMIN_AUTOREPORTS,
    TECHNO_LOGGING,
    TECHNO_ORIGINALS,
    TECHNO_UNHANDLED,
    ADMIN_AUTOBAN,
    ADMIN_MANBAN,
    TECHNO_RESTART,
    TECHNO_INOUT,
    ADMIN_USER_ID,
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
    TECHNO_LOG_GROUP,
    TECHNO_LOG_GROUP_NAME,
    DP,
    BOT,
    LOGGER,
    ALLOWED_UPDATES,
    CHANNEL_DICT,
    ALLOWED_CONTENT_TYPES,
)


# LOGGER init
LOGGER = initialize_logger()

tracemalloc.start()

# List of predetermined sentences to check for
PREDETERMINED_SENTENCES = load_predetermined_sentences("spam_dict.txt", LOGGER)

bot_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# Set to keep track of active user IDs
active_user_checks_dict = dict()
banned_users_dict = dict()

# Dictionary to store running tasks by user ID
running_watchdogs = {}

# Initialize the event
shutdown_event = asyncio.Event()

# If adding new column for the first time, uncomment below
# cursor.execute("ALTER TABLE recent_messages ADD COLUMN new_chat_member BOOL")
# conn.commit()
# cursor.execute("ALTER TABLE recent_messages ADD COLUMN left_chat_member BOOL")
# conn.commit()

# Setting up SQLite Database
CONN = sqlite3.connect("messages.db")
CURSOR = CONN.cursor()
CURSOR.execute(
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
CONN.commit()


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
    and reserved for future use
    """

    spammer_id = spammer_id or None
    spammer_last_name = spammer_last_name or ""

    spammer_id_str = f"{spammer_id if spammer_id is not None else '':10}"

    LOGGER.debug(
        "\033[93m%s getting chat ID and message ID\n"
        "%s firstName : %s : lastName : %s,\n"
        "%s messageForwardDate: %s, forwardedFromChatTitle: %s,\n"
        "%s forwardSenderName: %s, forwardedFromID: %s\n\033[0m",
        spammer_id_str,
        spammer_id_str,
        spammer_first_name,
        spammer_last_name,
        spammer_id_str,
        message_forward_date,
        forward_from_chat_title,
        spammer_id_str,
        forward_sender_name,
        forwarded_from_id,
    )

    # Common SQL and parameters for both cases
    base_query = """
        SELECT chat_id, message_id, chat_username, user_id, user_name, user_first_name, user_last_name, received_date
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
        # FIXME is it neccessary below?
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

    query = base_query.format(condition=condition)
    result = CURSOR.execute(query, params).fetchone()

    # Ensure result is not None before accessing its elements
    if result is None:
        LOGGER.error(
            "\033[91mNo result found for the given query and parameters. GSD\033[0m"
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
        "\033[92m%-10s - result for sender: %s %s, date: %s, from chat title: %s Result: %s\033[0m",
        result_3_formatted,  # padding left align 10 chars
        spammer_first_name,
        spammer_last_name,
        message_forward_date,
        forward_from_chat_title,
        result,
    )
    LOGGER.debug(
        "\033[92m%-10s Result: %s\033[0m",
        result_3_formatted,  # padding left align 10 chars
        result,
    )

    return result


async def take_heuristic_action(message: types.Message, reason):
    """Function to take heuristically invoked action on the message."""

    LOGGER.info(
        "%-10s : %s. Sending automated report to the admin group for review...",
        f"{message.from_id:10}",
        reason,
    )

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
    _commit_info = get_latest_commit_info(LOGGER)

    bot_start_message = (
        f"\nBot restarted at {bot_start_time}\n{'-' * 40}\n"
        f"Commit info: {_commit_info}\n"
        "Финальная битва между людьми и роботами...\n"
    )
    LOGGER.info(bot_start_message)

    # NOTE Leave chats which is not in settings file
    # await BOT.leave_chat(-1002174154456)
    # await BOT.leave_chat(-1001876523135) # @lalaland_classy

    # start message to the Technolog group
    await BOT.send_message(
        TECHNOLOG_GROUP_ID, bot_start_message, message_thread_id=TECHNO_RESTART
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


async def load_and_start_checks():
    """Load all unfinished checks from file and start them with 1 sec interval"""
    active_checks_filename = "active_user_checks.txt"
    banned_users_filename = "banned_users.txt"  # TODO store banned user names too

    if not os.path.exists(active_checks_filename):
        LOGGER.error("File not found: %s", active_checks_filename)
        return

    try:
        with open(active_checks_filename, "r", encoding="utf-8") as file:
            for line in file:
                user_id = int(line.strip().split(":")[0])
                user_name = line.strip().split(":")[1]
                active_user_checks_dict[user_id] = user_name
                event_message = (
                    f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "
                    + str(user_id)
                    + " ❌ \t\t\tbanned everywhere during initial checks on_startup"
                )
                # Start the check with 1 sec interval
                asyncio.create_task(
                    perform_checks(
                        user_id=user_id,
                        event_record=event_message,
                        inout_logmessage=f"(<code>{user_id}</code>) banned using data loaded on_startup event",
                    )
                )
                # interval between checks
                await asyncio.sleep(1)
                LOGGER.info("%s loaded from file & 3hr monitoring started ...", user_id)

        if os.path.exists(banned_users_filename):
            with open(banned_users_filename, "r", encoding="utf-8") as file:
                for line in file:
                    user_id, user_name = (
                        int(line.strip().split(":")[0]),
                        line.strip().split(":")[1],
                    )
                    banned_users_dict[user_id] = user_name
                LOGGER.info(
                    "Banned users (%s) list loaded from file: %s",
                    len(banned_users_dict),
                    banned_users_dict,
                )

    except FileNotFoundError as e:
        LOGGER.error("Error loading checks and bans: %s", e)


async def sequential_shutdown_tasks(_id, _uname):
    """Define the new coroutine that runs two async functions sequentially"""
    # First async function
    lols_cas_result = await lols_cas_check(_id) is True
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


async def on_shutdown(_dp):
    """Function to handle the bot shutdown."""
    LOGGER.info("Bot is shutting down... Performing final spammer check...")

    # Create a list to hold all tasks
    tasks = []

    # Iterate over active user checks and create a task for each check
    for _id, _uname in active_user_checks_dict.items():
        LOGGER.info("%s:%s shutdown check for spam...", _id, _uname)

        # Create the task for the sequential coroutine without awaiting it immediately
        task = asyncio.create_task(
            sequential_shutdown_tasks(_id, _uname), name=str(_id) + "shutdown"
        )
        tasks.append(task)

    # Run all tasks concurrently
    await asyncio.gather(*tasks)

    # save all unbanned checks to temp file to restart checks after bot restart
    # check if active_user_checks_dict is not empty
    if active_user_checks_dict:
        with open("active_user_checks.txt", "w", encoding="utf-8") as file:
            for _id, _uname in active_user_checks_dict.items():
                file.write(f"{_id}:{_uname}\n")
    else:
        # clear the file if no active checks
        with open("active_user_checks.txt", "w", encoding="utf-8") as file:
            file.write("")

    # save all banned users to temp file to preserve list after bot restart
    banned_users_filename = "banned_users.txt"
    if os.path.exists(banned_users_filename) and banned_users_dict:
        with open(banned_users_filename, "a", encoding="utf-8") as file:
            for _id, _username in banned_users_dict.items():
                file.write(f"{_id}:{_username}\n")
    elif banned_users_dict:
        with open(banned_users_filename, "w", encoding="utf-8") as file:
            for _id, _username in banned_users_dict.items():
                file.write(f"{_id}:{_username}\n")

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

    await BOT.send_message(
        TECHNO_LOG_GROUP,
        (
            "Runtime session shutdown stats:\n"
            f"Bot started at: {bot_start_time}\n"
            f"Current active user checks: {len(active_user_checks_dict)}\n"
            f"Spammers detected: {len(banned_users_dict)}\n"
        ),
        message_thread_id=TECHNO_RESTART,
    )
    # Close the bot
    await BOT.close()

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

    reported_spam = "ADM" + format_spam_report(message)[3:]
    # store spam text and caption to the daily_spam file
    await save_report_file("daily_spam_", reported_spam)

    # LOGGER.debug(f"Received forwarded message for the investigation: {message}")
    # Send a thank you note to the user we dont need it for the automated reports anymore
    # await message.answer("Thank you for the report. We will investigate it.")
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

    LOGGER.debug(
        "%-10s - message data: %s", f"{found_message_data[3]:10}", found_message_data
    )
    # logger.debug("message object: %s", message)

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
            message.forward_date if message.forward_date else None,
            received_date,
            str(found_message_data),
        ),
    )

    CONN.commit()

    message_link = construct_message_link(found_message_data)

    # Get the username, first name, and last name of the user who forwarded the message and handle the cases where they're not available
    if message.forward_from:
        first_name = message.forward_from.first_name or ""
        last_name = message.forward_from.last_name or ""
    else:
        first_name = found_message_data[5]
        last_name = found_message_data[6]

    message_timestamp = datetime.strptime(found_message_data[7], "%Y-%m-%d %H:%M:%S")

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
        f"❌ <b>Use /ban {report_id}</b> to take action.\n"
    )

    admin_ban_banner = (
        f"💡 Reaction time: {message_report_date - message_timestamp}\n"
        f"💔 {reason}\n"
        f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
        f"ℹ️ <a href='{technnolog_spamMessage_copy_link}'>Technolog copy</a>\n"
        f"❌ <b>Use /ban {report_id}</b> to take action.\n"
    )

    # construct lols check link button
    inline_kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton(
            "Check lols data",
            url=f"https://t.me/lolsbotcatcherbot?start={user_id}",
        )
    )
    # Send the banner to the technolog group
    await BOT.send_message(
        TECHNOLOG_GROUP_ID, log_info, parse_mode="HTML", reply_markup=inline_kb
    )

    # Keyboard ban/cancel/confirm buttons
    keyboard = InlineKeyboardMarkup()
    ban_btn = InlineKeyboardButton("Ban", callback_data=f"confirm_ban_{report_id}")
    keyboard.add(ban_btn)

    # Forward original message to the admin group
    await BOT.forward_message(
        ADMIN_GROUP_ID,
        found_message_data[0],  # from_chat_id
        found_message_data[1],  # message_id
        message_thread_id=ADMIN_AUTOREPORTS,
    )
    # Show ban banner with buttons in the admin group to confirm or cancel the ban
    admin_group_banner_autoreport_message = await BOT.send_message(
        ADMIN_GROUP_ID,
        admin_ban_banner,
        reply_markup=keyboard,
        parse_mode="HTML",
        message_thread_id=ADMIN_AUTOREPORTS,
        disable_web_page_preview=True,
    )

    # TODO parameters to pass to callback function callback_query_handler() to prevent errors
    # Store the admin action banner message data
    # DP["admin_action_banner_message"] = admin_action_banner_message
    DP["admin_group_banner_autoreport_message"] = (
        admin_group_banner_autoreport_message  # AUTOREPORT manage state
    )
    # always store the report chat ID with admin personal chat ID
    # DP["report_chat_id"] = message.chat.id


async def lols_cas_check(user_id):
    """Function to check if a user is in the lols/cas bot database.
    var: user_id: int: The ID of the user to check."""
    # Check if the user is in the lols bot database
    # https://api.lols.bot/account?id=
    # https://api.cas.chat/check?user_id=
    async with aiohttp.ClientSession() as session:
        lols = False
        cas = 0
        try:
            async with session.get(
                f"https://api.lols.bot/account?id={user_id}"
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    lols = data["banned"]
                    # LOGGER.debug("LOLS CAS checks:")
                    # LOGGER.debug("LOLS data: %s", data)
            async with session.get(
                f"https://api.cas.chat/check?user_id={user_id}"
            ) as resp:
                if resp.status == 200:
                    # LOGGER.debug("CAS data: %s", data)
                    data = await resp.json()
                    ok = data["ok"]
                    if ok:
                        cas = data["result"]["offenses"]
                        # LOGGER.info("%s CAS offenses: %s", user_id, cas)
                    else:
                        cas = 0
            if lols is True or int(cas) > 0:
                return True
            else:
                return False
        except asyncio.TimeoutError:
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
    """
    try:
        for chat_id in channel_ids:
            await BOT.ban_chat_member(chat_id, user_id, revoke_messages=True)
        # RED color for the log
        LOGGER.info(
            "\033[91m%s:@%s has been banned from all chats.\033[0m",
            user_id,
            user_name if user_name else "!UNDEFINED!",
        )
    except (
        utils.exceptions.BadRequest
    ) as e:  # if user were Deleted Account while banning
        chat_name = get_channel_name_by_id(channel_dict, chat_id)
        LOGGER.error(
            "%s - error banning in chat %s (%s): %s. Deleted Account?",
            user_id,
            chat_name,
            chat_id,
            e,
        )
        # XXX remove user_id check coroutine and from monitoring list?


async def lols_autoban(_id, user_name="!UNDEFINED!"):
    """Function to ban a user from all chats using lols's data.
    id: int: The ID of the user to ban."""

    # remove user from all known chats first
    await ban_user_from_all_chats(_id, user_name, CHANNEL_IDS, CHANNEL_DICT)

    if _id in active_user_checks_dict:
        banned_users_dict[_id] = active_user_checks_dict.pop(
            _id, None
        )  # add and remove the user to the banned_users_dict
        LOGGER.info(
            "\033[91m%s:%s removed from active_user_checks_dict during lols_autoban: %s... %d totally\033[0m",
            _id,
            user_name,
            list(active_user_checks_dict.items())[-3:],  # Last 3 elements
            len(active_user_checks_dict),  # Number of elements left
        )
    else:
        banned_users_dict[_id] = user_name
        LOGGER.info(
            "\033[91m%s:%s added to banned_users_dict during lols_autoban: %s... %d totally\033[0m",
            _id,
            user_name if user_name else "!UNDEFINED!",
            list(banned_users_dict.items())[-3:],  # Last 3 elements
            len(banned_users_dict),  # Number of elements left
        )
    if user_name and user_name != "!UNDEFINED!":  # exclude noname users
        await BOT.send_message(
            TECHNOLOG_GROUP_ID,
            f"<code>{_id}</code>:@{user_name} (880)",
            parse_mode="HTML",
            message_thread_id=TECHNO_NAMES,
        )


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

    lols_url = f"https://t.me/lolsbotcatcherbot?start={user_id}"

    inline_kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("Check spammer profile", url=lols_url)
    )

    if lols_spam is True:  # not Timeout exaclty
        if user_id not in banned_users_dict:
            await lols_autoban(user_id, user_name)
            banned_users_dict[user_id] = user_name
            action = "added to"
        else:
            action = "is already added to"
        if len(banned_users_dict) > 3:  # prevent spamming the log
            last_3_users = list(banned_users_dict.items())[-3:]  # Last 3 elements
            last_3_users_str = ", ".join(
                [f"{uid}: {uname}" for uid, uname in last_3_users]
            )
            LOGGER.info(
                "\033[93m%s:@%s %s runtime banned users list: %s... %d totally\033[0m",
                user_id,
                user_name if user_name else "!UNDEFINED!",
                action,
                last_3_users_str,  # Last 3 elements as string
                len(banned_users_dict),  # Total number of elements
            )
        else:  # less than 3 banned users
            all_users_str = ", ".join(
                [f"{uid}: {uname}" for uid, uname in banned_users_dict.items()]
            )
            LOGGER.info(
                "\033[93m%s:@%s %s runtime banned users list: %s\033[0m",
                user_id,
                user_name if user_name else "!UNDEFINED!",
                action,
                all_users_str,  # All elements as string
            )
        if action == "is already added to":
            return True

        if message_to_delete:  # delete the message if it exists
            await BOT.delete_message(message_to_delete[0], message_to_delete[1])
        if "kicked" in inout_logmessage or "restricted" in inout_logmessage:
            await BOT.send_message(
                ADMIN_GROUP_ID,
                inout_logmessage.replace("kicked", "<b>KICKED BY ADMIN</b>", 1).replace(
                    "restricted", "<b>RESTRICTED BY ADMIN</b>", 1
                ),
                message_thread_id=ADMIN_MANBAN,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=inline_kb,
            )
            event_record = (
                event_record.replace("member", "kicked", 1).split(" by ")[0]
                + " by Хранитель Порядков\n"
            )
            await save_report_file("inout_", "cbk" + event_record)
        elif "manual check requested" in inout_logmessage:
            # XXX it was /check id command
            await BOT.send_message(
                ADMIN_GROUP_ID,
                inout_logmessage.replace(
                    "manual check requested,",
                    "<b>manually kicked</b> from all chats with /check id command while",
                    1,
                )
                + " please check for the other spammer messages!",
                message_thread_id=ADMIN_MANBAN,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=inline_kb,
            )
            if user_name:
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code>:@{user_name} (1061)",
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )
            event_record = (
                event_record.replace("member", "kicked", 1).split(" by ")[0]
                + " by Хранитель Порядков\n"
            )
            await save_report_file("inout_", "cbm" + event_record)
        else:  # done by bot but not yet detected by lols_cas XXX
            await BOT.send_message(
                ADMIN_GROUP_ID,
                inout_logmessage.replace(
                    "member", "<i>member</i> --> <b>KICKED</b>", 1
                ).replace("left", "<i>left</i> --> <b>KICKED</b>", 1),
                message_thread_id=ADMIN_AUTOBAN,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=inline_kb,
            )
            if user_name:
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code>:@{user_name} (1084)",
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
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
    ):  # XXX user is not in the lols database and kicked/restricted by admin

        # LOGGER.debug("inout_logmessage: %s", inout_logmessage)
        # LOGGER.debug("event_record: %s", event_record)
        # user is not spammer but kicked or restricted by admin
        LOGGER.info(
            "%s kicked/restricted by admin, but is not now in the lols database.",
            user_id,
        )
        await BOT.send_message(
            ADMIN_GROUP_ID,
            f"User with ID: {user_id} is not now in the lols database but kicked/restricted by admin.\n"
            + inout_logmessage,
            message_thread_id=ADMIN_MANBAN,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )
        if user_name:
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"<code>{user_id}</code>:@{user_name} (1122)",
                parse_mode="HTML",
                message_thread_id=TECHNO_NAMES,
            )
        return True

    return False


async def check_n_ban(message: types.Message, reason: str):
    """ "Helper function to check for spam and take action if necessary if heuristics check finds it suspicious.

    message: types.Message: The message to check for spam.

    reason: str: The reason for the check.
    """
    lolscheck = await lols_cas_check(message.from_user.id)
    if lolscheck is True:
        # send message to the admin group AUTOREPORT thread
        LOGGER.info(
            "%s in %s (%s) message %s",
            reason,
            message.chat.title,
            message.chat.id,
            message.message_id,
        )
        time_passed = reason.split("...")[0].split()[-1]
        # delete id from the active_user_checks_dict
        if message.from_user.id in active_user_checks_dict:
            banned_users_dict[message.from_user.id] = active_user_checks_dict.pop(
                message.from_user.id, None
            )
            if len(active_user_checks_dict) > 5:
                LOGGER.info(
                    "\033[91m%s removed from the active_user_checks_dict in check_n_ban: %s... %d totally\033[0m",
                    message.from_user.id,
                    list(active_user_checks_dict.items())[:3],  # First 2 elements
                    len(active_user_checks_dict),  # Number of elements left
                )
            else:
                banned_users_dict[message.from_user.id] = message.from_user.username
                LOGGER.info(
                    "\033[91m%s removed from the active_user_checks_dict in check_n_ban: %s\033[0m",
                    message.from_user.id,
                    active_user_checks_dict,
                )
            # stop the perform_checks coroutine if it is running for author_id
            for task in asyncio.all_tasks():
                if task.get_name() == str(message.from_user.id):
                    task.cancel()
        # forward the telefragged message to the admin group
        try:
            await BOT.forward_message(
                ADMIN_GROUP_ID,
                message.chat.id,
                message.message_id,
                message_thread_id=ADMIN_AUTOBAN,
            )
        except utils.exceptions.MessageToForwardNotFound as e:
            LOGGER.error(
                "\033[93m%s - message %s to forward using check_n_ban(1044) not found in %s (%s)\033[0m Already deleted? %s",
                message.from_user.id,
                message.message_id,
                message.chat.title,
                message.chat.id,
                e,
            )
        # send the telefrag log message to the admin group
        inline_kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton(
                "Check lols data",
                url=f"https://t.me/lolsbotcatcherbot?start={message.from_user.id}",
            )
        )
        chat_link = (
            f"https://t.me/{message.chat.username}"
            if message.chat.username
            else f"https://t.me/c/{message.chat.id}"
        )
        chat_link_name = (
            f"{message.chat.title}:@{message.chat.username}"
            if message.chat.username
            else message.chat.title
        )
        await BOT.send_message(
            ADMIN_GROUP_ID,
            (
                f"Alert! 🚨 User <code>{message.from_user.id}</code>:{message.from_user.username if message.from_user.username else message.from_user.first_name} has been caught red-handed spamming in <a href='{chat_link}'>{chat_link_name}</a>! Telefragged in {time_passed}..."
            ),
            message_thread_id=ADMIN_AUTOBAN,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )
        if message.from_user.username:
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"<code>{message.from_user.id}</code>:@{message.from_user.username} (1219)",
                parse_mode="HTML",
                message_thread_id=TECHNO_NAMES,
            )
        # remove spammer from all groups
        await lols_autoban(message.from_user.id, message.from_user.username)
        event_record = (
            f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "  # Date and time with milliseconds
            f"{message.from_id:<10} "
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
                    "\033[93m%s:%s added to banned users list in check_n_ban: %s... %d totally\033[0m",
                    message.from_user.id,
                    message.from_user.username,
                    last_3_users_str,  # First 2 elements
                    len(banned_users_dict),  # Number of elements left
                )
            else:
                LOGGER.info(
                    "\033[93m%s:%s added to banned users list in check_n_ban: %s\033[0m",
                    message.from_user.id,
                    message.from_user.username,
                    banned_users_dict,
                )

        # XXX message id invalid after the message is deleted? Or deleted by other bot?
        # TODO shift to delete_messages in aiogram 3.0
        try:
            await BOT.delete_message(message.chat.id, message.message_id)
        except utils.exceptions.MessageToDeleteNotFound:
            LOGGER.error(
                "\033[93m%s:%s - message %s to delete using check_n_ban(1132) not found in %s (%s)\033[0m Already deleted?",
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
):
    """Corutine to perform checks for spam and take action if necessary.

    param message_to_delete: tuple: chat_id, message_id: The message to delete.

    param event_record: str: The event record to log to inout file.

    param user_id: int: The ID of the user to check for spam.

    param inout_logmessage: str: The log message for the user's activity.
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

        # List of sleep times in seconds
        sleep_times = [
            65,
            125,
            185,
            245,
            305,
            605,
            1205,
            1805,
            3605,
            7205,
            10805,
        ]  # 1min, 2 min, 3min, 4 min, 5 min, 10min, 20min, 30min, 1hr, 2hrs, 3hrs

        for sleep_time in sleep_times:

            if user_id not in active_user_checks_dict:  # if user banned somewhere else
                return

            await asyncio.sleep(sleep_time)
            lols_spam = await lols_cas_check(user_id)

            # Get the color code based on the value of lols_spam
            color_code = color_map.get(
                lols_spam, "\033[93m"
            )  # Default to yellow if lols_spam is not in the map

            # Log the message with the appropriate color
            LOGGER.info(
                "%s%s:@%s %02dmin check lols_cas_spam: %s\033[0m IDs to check left: %s",
                color_code,
                user_id,
                user_name if user_name else "!UNDEFINED!",
                sleep_time // 60,
                lols_spam,
                len(active_user_checks_dict),
            )

            # getting message to delete link if it is in the checks dict
            # XXX removes only one recorded message!!! What if there is more than one?
            if isinstance(active_user_checks_dict[user_id], dict):
                suspicious_messages = {
                    k: v
                    for k, v in active_user_checks_dict[user_id].items()
                    if k != "username"
                }
                if suspicious_messages:
                    chat_id, message_id = next(iter(suspicious_messages)).split("_")
                    message_to_delete = [
                        int(str(chat_id).replace("-100", "", 1)),
                        int(message_id),
                    ]

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
            "\033[93m%s:%s 3hrs spam checking cancelled. %s\033[0m",
            user_id,
            user_name,
            e,
        )
        if user_id in active_user_checks_dict:
            active_user_checks_dict.pop(user_id, None)
            LOGGER.info(
                "\033[93m%s:%s removed from active_user_checks_dict during perform_checks: \033[0m%s",
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
            active_user_checks_dict.pop(user_id, None)
            if len(active_user_checks_dict) > 5:
                LOGGER.info(
                    "\033[92m%s:@%s removed from active_user_checks_dict in finally block: %s... %d totally\033[0m",
                    user_id,
                    user_name,
                    list(active_user_checks_dict.items())[:3],  # First 2 elements
                    len(active_user_checks_dict),  # Number of elements left
                )
            else:
                LOGGER.info(
                    "\033[92m%s:@%s removed from active_user_checks_dict in finally block: %s\033[0m",
                    user_id,
                    user_name,
                    active_user_checks_dict,
                )


async def create_named_watchdog(coro, user_id, user_name="!UNDEFINED!"):
    """Check if a task for the same user_id is already running

    :param coro: The coroutine to run

    :param user_id: The user ID to use as the key in the running_watchdogs dictionary

    """
    if user_id in running_watchdogs:
        LOGGER.info(
            "\033[93m%s:@%s Watchdog is already set. Skipping new task.\033[0m",
            user_id,
            user_name,
        )
        return  # Do nothing; a watchdog is already active.
        # return await running_watchdogs[
        #     user_id
        # ]  # Await the existing task to prevent RuntimeWarning: coroutine was never awaited

    # Create the task and store it in the running_watchdogs dictionary
    task = asyncio.create_task(coro, name=str(user_id))
    running_watchdogs[user_id] = task
    LOGGER.info(
        "\033[91m%s:@%s Watchdog assigned.\033[0m",
        user_id,
        user_name,
    )  # Include user_name

    # # Remove the task from the dictionary when it completes
    # def task_done_callback(t: asyncio.Task):
    #     running_watchdogs.pop(user_id, None)
    #     if t.exception():
    #         LOGGER.error("%s Task raised an exception: %s", user_id, t.exception())

    # task.add_done_callback(task_done_callback)
    task.add_done_callback(
        lambda t: (
            LOGGER.error("%s Task raised an exception: %s", user_id, t.exception())
            if t.exception()
            else None
        )
    )

    # Await the newly created task
    # await task  # Wait for check_and_autoban to finish before continuing

    # No need to return anything here as the function now awaits the task
    # return await task  # Await the new task

    return task  # Return the task so the caller can manage it


async def log_lists():
    """Function to log the banned users and active user checks lists."""
    # TODO log summary numbers of banned users and active user checks totals
    LOGGER.info(
        "\033[93m%s banned users list: %s\033[0m",
        len(banned_users_dict),
        banned_users_dict,
    )
    LOGGER.info(
        "\033[93m%s Active user checks list: %s\033[0m",
        len(active_user_checks_dict),
        active_user_checks_dict,
    )
    # TODO move inout and daily_spam logs to the dedicated folders
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
                user_id, user_name = line.strip().split(":")
                banned_users_dict[int(user_id)] = user_name
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
        active_user_checks_list = [
            (
                f"<code>{user}</code>:{uname}"
                if isinstance(uname, dict)
                else f"<code>{user}</code>:@{uname}"
            )  # if there were suspicious messages do not put @ in front of the dict
            for user, uname in active_user_checks_dict.items()
        ]
        banned_users_list = [
            f"<code>{user_id}</code>:@{user_name}"
            for user_id, user_name in banned_users_dict.items()
        ]

        # Function to split lists into chunks
        def split_list(lst, max_length):
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

        # Split lists into chunks
        max_message_length = (
            MAX_TELEGRAM_MESSAGE_LENGTH - 100
        )  # Reserve some space for other text
        active_user_chunks = list(
            split_list(active_user_checks_list, max_message_length)
        )
        banned_user_chunks = list(split_list(banned_users_list, max_message_length))
        await BOT.send_message(
            ADMIN_GROUP_ID,
            f"Current user checks list: {len(active_user_checks_dict)}",
            message_thread_id=ADMIN_AUTOBAN,
            parse_mode="HTML",
        )
        # Send active user checks list in chunks
        for chunk in active_user_chunks:
            await BOT.send_message(
                ADMIN_GROUP_ID,
                f"Active user checks list: {' '.join(chunk)}",
                message_thread_id=ADMIN_AUTOBAN,
                parse_mode="HTML",
            )
        await BOT.send_message(
            ADMIN_GROUP_ID,
            f"Current banned users list: {len(banned_users_dict)}",
            message_thread_id=ADMIN_AUTOBAN,
            parse_mode="HTML",
        )
        # Send banned users list in chunks
        for chunk in banned_user_chunks:
            await BOT.send_message(
                ADMIN_GROUP_ID,
                f"Banned users list: {' '.join(chunk)}",
                message_thread_id=ADMIN_AUTOBAN,
                parse_mode="HTML",
            )
    except utils.exceptions.BadRequest as e:
        LOGGER.error("Error sending active_user_checks_dict: %s", e)

    # empty banned_users_dict
    banned_users_dict.clear()


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
    )  # XXX need to store in the DB to preserve it between sessions

    # Load configuration values from the XML file
    # load_config()

    LOGGER.info("Using bot: %s", BOT_NAME)
    LOGGER.info("Using bot id: %s", BOT_USERID)
    LOGGER.info("Using log group: %s, id: %s", LOG_GROUP_NAME, LOG_GROUP)
    LOGGER.info(
        "Using techno log group: %s, id: %s", TECHNO_LOG_GROUP_NAME, TECHNO_LOG_GROUP
    )
    channel_info = [f"{name}({id_})" for name, id_ in zip(CHANNEL_NAMES, CHANNEL_IDS)]
    LOGGER.info("Monitoring chats: %s", ", ".join(channel_info))
    LOGGER.info("\n")
    LOGGER.info(
        "Excluding autoreport when forwarded from chats: @%s",
        " @".join([d["name"] for d in ALLOWED_FORWARD_CHANNELS]),
    )
    LOGGER.info("\n")

    @DP.chat_member_handler(is_not_bot_action)  # exclude bot's own actions
    async def greet_chat_members(update: types.ChatMemberUpdated):
        """Checks for change in the chat members statuses and check if they are spammers."""
        # Who did the action
        by_user = None
        # get photo upload date of the user profile with ID update.from_user.id
        # TODO: get the photo upload date of the user profile
        # photo_date = await BOT.get_user_profile_photos(update.from_user.id)

        # XXX
        # await get_photo_details(update.from_user.id)
        # XXX

        if update.from_user.id != update.old_chat_member.user.id:
            # Someone else changed user status
            by_username = update.from_user.username or "!UNDEFINED!"  # optional
            # by_userid = update.from_user.id
            by_userfirstname = update.from_user.first_name
            by_userlastname = update.from_user.last_name or ""  # optional
            # by_user = f"by @{by_username}(<code>{by_userid}</code>): {by_userfirstname} {by_userlastname}\n"
            by_user = f"by {update.from_user.id}:@{by_username}: {by_userfirstname} {by_userlastname}\n"

        inout_status = update.new_chat_member.status

        inout_chattitle = update.chat.title

        # Whoose this action is about
        inout_userid = update.old_chat_member.user.id
        inout_userfirstname = update.old_chat_member.user.first_name
        inout_userlastname = update.old_chat_member.user.last_name or ""  # optional
        inout_username = (
            update.old_chat_member.user.username or "!UNDEFINED!"
        )  # optional

        lols_spam = await lols_cas_check(update.old_chat_member.user.id)

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
        universal_chatlink = (
            f'<a href="https://t.me/{update.chat.username}">{update.chat.title}</a>'
            if update.chat.username
            else f'<a href="https://t.me/c/{str(update.chat.id)[4:] if str(update.chat.id).startswith("-100") else update.chat.id}">{update.chat.title}</a>'
        )
        # Construct the log message
        inout_logmessage = (
            f"<a href='tg://resolve?domain={inout_username}'>@{inout_username}</a> (<code>{inout_userid}</code>): "
            f"{escaped_inout_userfirstname} {escaped_inout_userlastname}\n"
            f"{'❌ -->' if lols_spam is True else '🟢 -->' if lols_spam is False else '❓ '}"
            f" {inout_status}\n"
            f"{by_user if by_user else ''}"
            f"💬 {universal_chatlink}\n"
            f"🔗 <b>profile links:</b>\n"
            f"   ├ <b><a href='tg://user?id={inout_userid}'>id based profile link</a></b>\n"
            f"   └ <a href='tg://openmessage?user_id={inout_userid}'>Android</a>, <a href='https://t.me/@id{inout_userid}'>IOS (Apple)</a>\n"
        )

        lols_url = f"https://t.me/lolsbotcatcherbot?start={inout_userid}"
        inline_kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("Check lols data", url=lols_url)
        )

        await BOT.send_message(
            TECHNO_LOG_GROUP,
            inout_logmessage,
            message_thread_id=TECHNO_INOUT,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )

        # different colors for inout status
        status_colors = {
            ChatMemberStatus.KICKED: "\033[91m",  # Red
            ChatMemberStatus.RESTRICTED: "\033[93m",  # Yellow
        }
        color = status_colors.get(inout_status, "")  # Default to no color
        reset_color = "\033[0m" if color else ""  # Reset color if a color was used
        LOGGER.info(
            "%s%s --> %s in %s%s",
            color,
            inout_userid,
            inout_status,
            inout_chattitle,
            reset_color,
        )

        # Extract the user status change
        result = extract_status_change(update)
        if result is None:
            return
        was_member, is_member = result
        # if already identified as a spammer and not TIMEOUT
        if lols_spam is True:
            await check_and_autoban(
                event_record,
                inout_userid,
                inout_logmessage,
                inout_username,
                lols_spam=lols_spam,
            )

        # Check lols after user join/leave event in 3hr and ban if spam
        if (
            inout_status == ChatMemberStatus.KICKED
            or inout_status == ChatMemberStatus.RESTRICTED
        ):  # not Timeout (lols_spam) exactly or if kicked/restricted by someone else
            # Call check_and_autoban with concurrency control using named tasks
            task_GCM = await create_named_watchdog(
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

            # Get the current timestamp

            # Log the message with the timestamp
            LOGGER.debug(
                "\033[96m%s:@%s Scheduling perform_checks coroutine\033[0m",
                inout_userid,
                inout_username,
            )
            # Check if the user ID is already being processed
            if inout_userid not in active_user_checks_dict:
                # Add the user ID to the active set
                active_user_checks_dict[inout_userid] = (
                    update.old_chat_member.user.username
                )
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
                    getattr(
                        update, "date", None
                    ),  # primary key to change to prevent overwriting DB
                    getattr(update.old_chat_member.user, "id", None),
                    getattr(update.old_chat_member.user, "username", ""),
                    getattr(update.old_chat_member.user, "first_name", ""),
                    getattr(update.old_chat_member.user, "last_name", ""),
                    getattr(update, "date", None),
                    getattr(update.from_user, "id", ""),
                    getattr(update, "date", None),
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
                time_diff = (
                    datetime.strptime(last2_join_left_event[0][0], "%Y-%m-%d %H:%M:%S")
                    - datetime.strptime(
                        last2_join_left_event[1][0], "%Y-%m-%d %H:%M:%S"
                    )
                ).total_seconds()

                if (
                    time_diff <= 60
                    and last2_join_left_event[0][2] == 1
                    and last2_join_left_event[1][1] == 1
                ):
                    LOGGER.debug(
                        "%s:@%s joined and left %s in 1 minute or less",
                        inout_userid,
                        inout_username,
                        inout_chattitle,
                    )
                    # ban user from all chats
                    await ban_user_from_all_chats(
                        inout_userid, inout_username, CHANNEL_IDS, CHANNEL_DICT
                    )
                    lols_url = f"https://t.me/lolsbotcatcherbot?start={inout_userid}"
                    inline_kb = InlineKeyboardMarkup().add(
                        InlineKeyboardButton("Check user profile", url=lols_url)
                    )
                    await BOT.send_message(
                        ADMIN_GROUP_ID,
                        f"(<code>{inout_userid}</code>) @{inout_username} {escaped_inout_userfirstname} {escaped_inout_userlastname} joined and left {universal_chatlink} in 1 minute or less. Telefragged...",
                        message_thread_id=ADMIN_AUTOBAN,
                        parse_mode="HTML",
                        reply_markup=inline_kb,
                        disable_web_page_preview=True,
                    )
                    if (
                        update.old_chat_member.user.username
                    ):  # post username if the user have it
                        await BOT.send_message(
                            TECHNOLOG_GROUP_ID,
                            f"<code>{inout_userid}</code>:@{update.old_chat_member.user.username} (1790)",
                            parse_mode="HTML",
                            message_thread_id=TECHNO_NAMES,
                        )
            except IndexError:
                LOGGER.debug(
                    "%s:%s left and has no previous join/leave events or was already in lols/cas spam",
                    inout_userid,
                    inout_username,
                )

    @DP.message_handler(
        is_forwarded_from_unknown_channel_message,
        content_types=types.ContentTypes.ANY,
    )
    async def handle_forwarded_reports(message: types.Message):
        """Function to handle forwarded messages."""

        reported_spam = format_spam_report(message)
        # store spam text and caption to the daily_spam file
        await save_report_file("daily_spam_", reported_spam)

        # LOGGER.debug("############################################################")
        # LOGGER.debug("                                                            ")
        # LOGGER.debug("------------------------------------------------------------")
        # LOGGER.debug("Received forwarded message for the investigation: %s", message)
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
                message.forward_date if message.forward_date else None,
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

        massage_timestamp = datetime.strptime(
            found_message_data[7], "%Y-%m-%d %H:%M:%S"
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
            f"❌ <b>Use /ban {report_id}</b> to take action.\n"
        )
        # LOGGER.debug("Report banner content:")
        # LOGGER.debug(log_info)

        admin_ban_banner = (
            f"💡 Reaction time: {message_report_date - massage_timestamp}\n"
            f"💔 Reported by admin <a href='tg://user?id={message.from_user.id}'></a>"
            f"@{message.from_user.username or '!UNDEFINED!'}\n"
            f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
            f"ℹ️ <a href='{technnolog_spam_message_copy_link}'>Technolog copy</a>\n"
            f"❌ <b>Use /ban {report_id}</b> to take action.\n"
        )

        # construct lols check link button
        inline_kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton(
                "Check lols data",
                url=f"https://t.me/lolsbotcatcherbot?start={user_id}",
            )
        )
        # Send the banner to the technolog group
        await BOT.send_message(
            TECHNOLOG_GROUP_ID,
            technolog_info,
            parse_mode="HTML",
            reply_markup=inline_kb,
        )

        # Keyboard ban/cancel/confirm buttons
        keyboard = InlineKeyboardMarkup()
        ban_btn = InlineKeyboardButton("Ban", callback_data=f"confirm_ban_{report_id}")
        keyboard.add(ban_btn)

        # Show ban banner with buttons in the admin group to confirm or cancel the ban
        # And store published banner message data to provide link to the reportee
        # admin_group_banner_message: Message = None # Type hinting
        try:  # If Topic_closed error
            if await is_admin(message.from_user.id, ADMIN_GROUP_ID):

                # NOTE how to remove buttons if it was pressed in other dialogue?

                # Send report to the admin group
                admin_group_banner_message = await BOT.send_message(
                    ADMIN_GROUP_ID,
                    admin_ban_banner,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                )
                # XXX Send report action banner to the reporter/var to revoke the message
                admin_action_banner_message = await message.answer(
                    admin_ban_banner,
                    parse_mode="HTML",
                    disable_notification=True,
                    protect_content=True,
                    allow_sending_without_reply=True,
                    disable_web_page_preview=False,
                    reply_markup=keyboard,
                )

                # Store the admin action banner message data
                DP["admin_action_banner_message"] = admin_action_banner_message
                DP["admin_group_banner_message"] = admin_group_banner_message
                # always store the report chat ID with admin personal chat ID
                DP["report_chat_id"] = message.chat.id

                # Construct link to the published banner and send it to the reporter
                private_chat_id = int(
                    str(admin_group_banner_message.chat.id)[4:]
                )  # Remove -100 from the chat ID
                banner_link = f"https://t.me/c/{private_chat_id}/{admin_group_banner_message.message_id}"
                # Send the banner link to the reporter-admin
                await message.answer(f"Admin group banner link: {banner_link}")

                # XXX return admin personal report banner message object
                return admin_action_banner_message

            else:  # send report to AUTOREPORT thread of the admin group
                admin_group_banner_message = await BOT.send_message(
                    ADMIN_GROUP_ID,
                    admin_ban_banner,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    message_thread_id=ADMIN_AUTOREPORTS,
                )

        except utils.exceptions.BadRequest as e:
            LOGGER.error("Error while sending the banner to the admin group: %s", e)
            await message.answer(
                "Error while sending the banner to the admin group. Please check the logs."
            )

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

        try:  # KeyError if it was reported by non-admin user
            banner_message_origin: types.Message = DP.get(
                "admin_group_banner_message"
            ) or DP.get(
                "admin_group_banner_autoreport_message"
            )  # check message object for AUTO/MANUAL report origin

            admin_action_banner_message: types.Message = DP.get(
                "admin_action_banner_message"
            )  # if this is MANUAL action by ADMIN

            report_chat_id = DP.get(
                "report_chat_id"
            )  # store chat where action happened

            # LOGGER.debug(
            #     "agbm: %s, agbam: %s, aabm: %s, rcid: %s",
            #     DP.get("admin_group_banner_message"),
            #     DP.get("admin_group_banner_autoreport_message"),
            #     DP.get("admin_action_banner_message"),
            #     DP.get("report_chat_id"),
            # )

            # clear states
            DP["admin_group_banner_message"] = None
            DP["admin_group_banner_autoreport_message"] = None
            DP["admin_action_banner_message"] = None
            DP["report_chat_id"] = None

            # Edit messages to remove buttons or messages
            # check where the callback_query was pressed
            # remove buttons and add Confirm/Cancel buttons in the same chat
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=keyboard,
            )

            if (
                callback_query.message.chat.id == ADMIN_GROUP_ID
                and admin_action_banner_message
            ):
                # remove personal report banner message if BAN button pressed in ADMIN group
                try:
                    await BOT.delete_message(
                        report_chat_id, admin_action_banner_message.message_id
                    )
                except (
                    MessageToDeleteNotFound
                ):  # Message already deleted when replied in personal messages? XXX
                    LOGGER.warning(
                        "%s Message %s in BOT PM to delete not found. Already deleted?",
                        callback_query.from_user.id,
                        callback_query.message.message_id,
                    )

            else:  # report was actioned in the personal chat
                # remove admin group banner buttons
                await BOT.edit_message_reply_markup(
                    chat_id=ADMIN_GROUP_ID,
                    message_id=banner_message_origin.message_id,
                )
        except KeyError as e:
            LOGGER.error(
                "\033[93m%s Error while removing the buttons: %s. Message reported by non-admin user?\033[0m",
                callback_query.from_user.id,
                e,
            )

    @DP.callback_query_handler(lambda c: c.data.startswith("do_ban_"))
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
            *_, message_id_to_ban = callback_query.data.split("_")
            message_id_to_ban = int(message_id_to_ban)

            CURSOR.execute(
                "SELECT chat_id, message_id, forwarded_message_data, received_date FROM recent_messages WHERE message_id = ?",
                (message_id_to_ban,),
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

            # XXXfixed find safe solution to get the author_id from the forwarded_message_data
            author_id = eval(forwarded_message_data)[3]
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

            LOGGER.debug(
                "%s Message timestamp:%-10s, Original chat ID: %s, Original report ID: %s, Forwarded message data: %s, Original message timestamp: %s",
                author_id,
                (
                    f"{result[3]:10}" if result[3] is not None else f"{' ' * 10}"
                ),  # padding left align 10 chars
                original_chat_id,
                report_id,
                forwarded_message_data,
                original_message_timestamp,
            )
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"Author ID retrieved for original message: (<code>{author_id}</code>)",
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
                if len(active_user_checks_dict) > 5:
                    LOGGER.info(
                        "\033[91m%s removed from active_user_checks_dict during handle_ban by admin: %s... %d totally\033[0m",
                        author_id,
                        list(active_user_checks_dict.items())[:3],  # First 2 elements
                        len(active_user_checks_dict),  # Number of elements left
                    )
                else:
                    LOGGER.info(
                        "\033[91m%s removed from active_user_checks_dict during handle_ban by admin: %s\033[0m",
                        author_id,
                        active_user_checks_dict,
                    )
                # stop the perform_checks coroutine if it is running for author_id
                for task in asyncio.all_tasks():
                    if task.get_name() == str(author_id):
                        task.cancel()

            # save event to the ban file
            # XXX save the event to the inout file
            # FIXME chat @name below
            event_record = (
                f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "  # Date and time with milliseconds
                f"{author_id:<10} "
                f"❌  {' '.join('@' + forwarded_message_data[4] if forwarded_message_data[4] is not None else forwarded_message_data[5]+' '+forwarded_message_data[6]):<32}"
                f" member          --> kicked          in "
                f"{'@' + forwarded_message_data[2] + ': ' if forwarded_message_data[2] else '':<24}{forwarded_message_data[0]:<30} by @{button_pressed_by}\n"
            )
            LOGGER.debug(
                "%s:@%s hbn forwared_message_data: %s",
                author_id,
                (
                    forwarded_message_data[4]
                    if forwarded_message_data[4]
                    else "!UNDEFINED!"
                ),
                forwarded_message_data,
            )
            await save_report_file("inout_", "hbn" + event_record)

            # add to the banned users set
            banned_users_dict[int(author_id)] = (
                forwarded_message_data[4] if forwarded_message_data[4] else "NoUserName"
            )

            # select all messages from the user in the chat
            # and this is not records about join or leave
            # and this record have name of the chat
            # FIXME private chats do not have names :(
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
            for channel_id, message_id, user_name in result:
                retry_attempts = 3  # number of attempts to delete the message
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
                            e.timeout
                        )  # This gives you the time to wait in seconds
                        if (
                            attempt < retry_attempts - 1
                        ):  # Don't wait after the last attempt
                            LOGGER.warning(
                                "Rate limited. Waiting for %s seconds.", wait_time
                            )
                            time.sleep(wait_time)
                    except MessageToDeleteNotFound:
                        LOGGER.warning(
                            "Message %s in chat %s (%s) not found for deletion.",
                            message_id,
                            CHANNEL_DICT[channel_id],
                            channel_id,
                        )
                        break  # No need to retry in this case
                    except utils.exceptions.ChatAdminRequired as inner_e:
                        LOGGER.error(
                            "Bot is not an admin in chat %s (%s). Error: %s",
                            CHANNEL_DICT[channel_id],
                            channel_id,
                            inner_e,
                        )
                        await BOT.send_message(
                            TECHNOLOG_GROUP_ID,
                            f"Bot is not an admin in chat {CHANNEL_DICT[channel_id]} ({channel_id}). Error: {inner_e}",
                        )
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
                except Exception as inner_e:
                    LOGGER.error(
                        "Failed to ban and delete messages in chat %s (%s). Error: %s",
                        CHANNEL_DICT[channel_id],
                        channel_id,
                        inner_e,
                    )
                    await BOT.send_message(
                        TECHNOLOG_GROUP_ID,
                        f"Failed to ban and delete messages in chat {CHANNEL_DICT[channel_id]} ({channel_id}). Error: {inner_e}",
                    )
            # unpack user_name correctly XXX
            user_name = result[0][2] if result else "!UNDEFINED!"
            LOGGER.debug(
                "\033[91m%s:@%s manually banned and their messages deleted where applicable.\033[0m",
                author_id,
                user_name,
            )

            # TODO add the timestamp of the button press and how much time passed since
            # button_timestamp = datetime.now()

            await BOT.send_message(
                ADMIN_GROUP_ID,
                f"Report {message_id_to_ban} action taken by @{button_pressed_by}: User (<code>{author_id}</code>) banned and their messages deleted where applicable.",
                message_thread_id=callback_query.message.message_thread_id,
                parse_mode="HTML",
            )
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"Report {message_id_to_ban} action taken by @{button_pressed_by}: User (<code>{author_id}</code>) banned and their messages deleted where applicable.",
                parse_mode="HTML",
            )
            if forwarded_message_data[4] and (forwarded_message_data[4] != 0):
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"<code>{author_id}</code>:@{forwarded_message_data[4]} (2536)",
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )
            banned_users_dict[author_id] = forwarded_message_data[4]
            if forwarded_message_data[4] in active_user_checks_dict:
                active_user_checks_dict.pop(forwarded_message_data[4], None)
                LOGGER.info(
                    "\033[91m%s removed from active_user_checks_dict and stored to banned_users_dict during handle_ban by admin: %s\033[0m",
                    forwarded_message_data[4],
                    active_user_checks_dict,
                )
            LOGGER.info(
                "%s Message %s action taken by @%s: User @%s banned and their messages deleted where applicable.",
                author_id,
                message_id_to_ban,
                button_pressed_by,
                (
                    forwarded_message_data[4]
                    if forwarded_message_data[4] != 0
                    else "!UNDEFINED!"
                ),
            )

        except utils.exceptions.MessageCantBeDeleted as e:
            LOGGER.error("Error in handle_ban function: %s", e)
            await callback_query.message.reply(f"Error in handle_ban function: {e}")

    @DP.callback_query_handler(lambda c: c.data.startswith("reset_ban_"))
    async def reset_ban(callback_query: CallbackQuery):
        """Function to reset the ban button."""
        *_, report_id_to_ban = callback_query.data.split("_")

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
            "%s Report %s button ACTION CANCELLED by @%s !!!",
            admin_id,
            report_id_to_ban,
            button_pressed_by,
        )

        await BOT.send_message(
            ADMIN_GROUP_ID,
            f"Button ACTION CANCELLED by @{button_pressed_by}: Report WAS NOT PROCESSED!!! "
            f"Report them again if needed or use <code>/ban {report_id_to_ban}</code> command.",
            message_thread_id=callback_query.message.message_thread_id,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await BOT.send_message(
            TECHNOLOG_GROUP_ID,
            f"CANCEL button pressed by @{button_pressed_by}. "
            f"Button ACTION CANCELLED: Report WAS NOT PROCESSED. "
            f"Report them again if needed or use <code>/ban {report_id_to_ban}</code> command.",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    @DP.message_handler(
        is_channel_message,
        content_types=ALLOWED_CONTENT_TYPES,
    )
    async def store_recent_messages(message: types.Message):
        """Function to store recent messages in the database."""
        # XXX

        # create unified message link
        message_link = construct_message_link(
            [message.chat.id, message.message_id, message.chat.username]
        )
        lols_link = f"https://t.me/lolsbotcatcherbot?start={message.from_user.id}"

        # Create the inline keyboard
        inline_kb = InlineKeyboardMarkup()

        # Add buttons to the keyboard, each in a new row
        inline_kb.add(InlineKeyboardButton("View Original Message", url=message_link))
        inline_kb.add(InlineKeyboardButton("Check LOLS Data", url=lols_link))

        # Buttons in one line
        # inline_kb = InlineKeyboardMarkup().add(
        #     InlineKeyboardButton("View Original Message", url=message_link),
        #     InlineKeyboardButton("Check lols data", url=lols_link),
        # )

        # check if message is from user from active_user_checks_dict or banned_users_dict set
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
        elif message.from_user.id in active_user_checks_dict:
            # Ensure active_user_checks_dict[message.from_user.id] is a dictionary
            if not isinstance(active_user_checks_dict.get(message.from_user.id), dict):
                # Initialize with the username if it exists, otherwise with "!UNDEFINED!"
                active_user_checks_dict[message.from_user.id] = {
                    "username": (
                        "@" + message.from_user.username
                        if message.from_user.username
                        else "!UNDEFINED!"
                    )
                }

            # Store the message link in the active_user_checks_dict
            message_key = f"{message.chat.id}_{message.message_id}"
            active_user_checks_dict[message.from_user.id][message_key] = message_link

            # Create an inline keyboard with a link
            LOGGER.warning(
                "\033[47m\033[34m%s:%s is in active_user_checks_dict, check the message %s in the chat %s (%s).\033[0m Suspicious message link: %s",
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
            # Log resulting dict
            LOGGER.info(
                "%s:%s suspicious messages dict: %s",
                message.from_user.id,
                (
                    message.from_user.username
                    if message.from_user.username
                    else "!UNDEFINED!"
                ),
                active_user_checks_dict[message.from_user.id],
            )
            # Forward suspicious message to the technolog originals thread
            await BOT.forward_message(
                TECHNOLOG_GROUP_ID,
                message.chat.id,
                message.message_id,
                TECHNO_ORIGINALS,
                True,
            )
            # Send a new message with the inline keyboard link to the technolog originals
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"<code>{message_link}</code>\nClick the button below to view the suspicious message:",
                reply_markup=inline_kb,
                parse_mode="HTML",
                message_thread_id=TECHNO_ORIGINALS,
            )
            # Send warning to the Admin group with link to the message
            # await BOT.send_message(
            #     ADMIN_GROUP_ID,
            #     f"WARNING! User {message.from_user.id} suspicious activity detected.",
            #     reply_markup=inline_kb,
            #     # message_thread_id=1,  # # main thread (#REPORTS)
            # )
        elif message.from_user.id in banned_users_dict:
            LOGGER.warning(
                "\033[41m\033[37m%s is in banned_users_dict, DELETING the message %s in the chat %s (%s)\033[0m",
                message.from_user.id,
                message.message_id,
                message.chat.title,
                message.chat.id,
            )
            # Forwarding banned user message to technolog originals
            await BOT.forward_message(
                ADMIN_GROUP_ID,
                message.chat.id,
                message.message_id,
                ADMIN_AUTOBAN,
                True,
            )
            await BOT.send_message(
                ADMIN_GROUP_ID,
                "Click buttons below for more information:",
                reply_markup=inline_kb,
                message_thread_id=ADMIN_AUTOBAN,
            )
            # Delete message from banned user
            await BOT.delete_message(message.chat.id, message.message_id)
            # return
        try:
            # Log the full message object for debugging
            # or/and forward the message to the technolog group
            # if (
            #     message.chat.id == -1001461337235 or message.chat.id == -1001527478834
            # ):  # mevrikiy or beautymauritius
            #     # temporal horse fighting
            #     await BOT.forward_message(
            #         TECHNOLOG_GROUP_ID,
            #         message.chat.id,
            #         message.message_id,
            #         message_thread_id=TECHNO_ORIGINALS,
            #     )
            #     LOGGER.info(
            #         "Message ID: %s Forwarded from chat: %s",
            #         message.message_id,
            #         message.chat.title,
            #     )
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

            # NOTE hash JSON to make signature
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
            # HACK remove afer sandboxing

            # check if sender is an admin in the channel or admin group and skip the message
            if await is_admin(message.from_user.id, message.chat.id) or await is_admin(
                message.from_user.id, ADMIN_GROUP_ID
            ):
                message_link = construct_message_link(
                    [message.chat.id, message.message_id, message.chat.username]
                )
                LOGGER.debug(
                    "\033[95m%s:@%s is admin, skipping the message %s in the chat %s.\033[0m Message link: %s",
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

            # Check if the message is from chat in settings
            if (
                message.chat.id not in CHANNEL_IDS
                and message.chat.id != ADMIN_GROUP_ID
                and message.chat.id != TECHNOLOG_GROUP_ID
            ):
                # LOGGER.debug(
                #     "message chat id: %s not in CHANNEL_IDS: %s ADMIN_GROUP_ID: %s TECHNOLOG_GROUP_ID: %s",
                #     message.chat.id,
                #     CHANNEL_IDS,
                #     ADMIN_GROUP_ID,
                #     TECHNOLOG_GROUP_ID,
                # )

                LOGGER.debug(
                    "\033[93m%s is not in the allowed chat, skipping the message %s in the chat %s (%s) and leaving it...\033[0m",
                    message.from_user.id,
                    message.message_id,
                    message.chat.title,
                    message.chat.id,
                )
                # XXX await BOT.leave_chat(message.chat.id)
                return

            CURSOR.execute(
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
            CONN.commit()
            # logger.info(f"Stored recent message: {message}")

            # search for the user join chat event date using user_id in the DB
            user_join_chat_date_str = CURSOR.execute(
                "SELECT received_date FROM recent_messages WHERE user_id = ? AND new_chat_member = 1",
                (message.from_user.id,),
            ).fetchone()
            # if there is no such data assume user joined the chat 3 years ago in seconds
            user_join_chat_date_str = (
                user_join_chat_date_str[0]
                if user_join_chat_date_str
                else "2020-01-01 00:00:00"  # datetime(2020, 1, 1, 0, 0, 0)
            )
            # LOGGER.info(
            #     "USER JOINED: ",
            #     user_join_chat_date_str,
            # )

            # Convert the string to a datetime object
            user_join_chat_date = datetime.strptime(
                user_join_chat_date_str, "%Y-%m-%d %H:%M:%S"
            )

            # flag true if user joined the chat more than 3 days ago
            user_is_old = (message.date - user_join_chat_date).total_seconds() > 259200
            user_is_1week_old = (
                message.date - user_join_chat_date
            ).total_seconds() < 604805  # ONE week and 5 seconds
            # user_is_1day_old = (
            #     message.date - user_join_chat_date
            # ).total_seconds() < 86400  # 1 days and 5 seconds
            user_is_1hr_old = (
                message.date - user_join_chat_date
            ).total_seconds() < 3600
            user_is_10sec_old = (
                message.date - user_join_chat_date
            ).total_seconds() < 10

            # check if the message is a spam by checking the entities
            entity_spam_trigger = has_spam_entities(SPAM_TRIGGERS, message)

            # XXX if user was in lols but before it was kicked it posted a message eventually
            # we can check it in runtime banned user list
            if message.from_user.id in banned_users_dict:
                the_reason = f"{message.from_user.id} is banned before sending a message, but squizzed due to latency..."
                latency_message_link = construct_message_link(
                    [
                        message.chat.id,
                        message.message_id,
                        message.chat.username,
                    ]
                )
                LOGGER.info(
                    "%s:%s latency message link: %s",
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
            elif (
                user_is_1week_old
            ):  # do lols check if user less than 48hr old sending a message
                time_passed = message.date - user_join_chat_date
                human_readable_time = str(time_passed)
                LOGGER.info(
                    "%s sent message and joined the chat %s %s ago",
                    message.from_id,
                    message.chat.title,
                    human_readable_time,
                )
                if message.chat.username:
                    message_link = construct_message_link(
                        [message.chat.id, message.message_id, message.chat.username]
                    )
                LOGGER.info(
                    "%s message link: %s",
                    message.from_id,
                    message_link,
                )
                the_reason = f"\033[91m{message.from_id} identified as a spammer when sending a message during the first WEEK after registration. Telefragged in {human_readable_time}...\033[0m"
                await check_n_ban(message, the_reason)

                # At the point where you want to print the traceback
                # snapshot = tracemalloc.take_snapshot()
                # top_stats = snapshot.statistics('lineno')

                # print("[ Top 10 ]")
                # for stat in top_stats[:10]:
                #     print(stat)

                return

            elif (
                message.forward_from_chat.type if message.forward_from_chat else None
            ) == types.ChatType.CHANNEL:
                # or (message.forward_origin.type if message.forward_origin else None) == types.ChatType.CHANNEL:
                # check if it is forward from channel
                # check for allowed channels for forwards
                if message.forward_from_chat.id not in ALLOWED_FORWARD_CHANNEL_IDS:
                    # this is possibly a spam
                    the_reason = (
                        f"{message.from_id} forwarded message from unknown channel"
                    )
                    if await check_n_ban(message, the_reason):
                        return
                    else:
                        LOGGER.info(
                            "\033[93m%s possibly forwarded a spam from unknown channel in chat %s\033[0m",
                            message.from_user.id,
                            message.chat.title,
                        )
                        await take_heuristic_action(message, the_reason)

            elif has_custom_emoji_spam(
                message
            ):  # check if the message contains spammy custom emojis
                the_reason = (
                    f"{message.from_id} message contains 5 or more spammy custom emojis"
                )

                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "\033[93m%s possibly sent a spam with 5+ spammy custom emojis in chat %s\033[0m",
                        message.from_user.id,
                        message.chat.title,
                    )
                    await take_heuristic_action(message, the_reason)

            elif check_message_for_sentences(message, PREDETERMINED_SENTENCES, LOGGER):
                the_reason = f"{message.from_id} message contains spammy sentences"
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "\033[93m%s possibly sent a spam with spammy sentences in chat %s\033[0m",
                        message.from_user.id,
                        message.chat.title,
                    )
                    await take_heuristic_action(message, the_reason)

            elif check_message_for_capital_letters(
                message
            ) and check_message_for_emojis(message):
                the_reason = f"{message.from_id} message contains 5+ spammy capital letters and 5+ spammy regular emojis"
                if check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "\033[93m%s possibly sent a spam with 5+ spammy capital letters and 5+ spammy regular emojis in chat %s\033[0m",
                        message.from_user.id,
                        message.chat.title,
                    )
                    await take_heuristic_action(message, the_reason)

            elif not user_is_old:
                # check if the message is sent less then 10 seconds after joining the chat
                if user_is_10sec_old:
                    # this is possibly a bot
                    the_reason = f"{message.from_id} message is sent less then 10 seconds after joining the chat"
                    if await check_n_ban(message, the_reason):
                        return
                    else:
                        LOGGER.info(
                            "%s is possibly a bot typing histerically...",
                            message.from_id,
                        )
                        await take_heuristic_action(message, the_reason)
                # check if the message is sent less then 1 hour after joining the chat
                elif user_is_1hr_old and entity_spam_trigger:
                    # this is possibly a spam
                    the_reason = (
                        f"{message.from_id} message sent less then 1 hour after joining the chat and have "
                        + entity_spam_trigger
                        + " inside"
                    )
                    if check_n_ban(message, the_reason):
                        return
                    else:
                        LOGGER.info(
                            "%s possibly sent a spam with (%s) links or other entities in less than 1 hour after joining the chat",
                            message.from_user.id,
                            entity_spam_trigger,
                        )
                        await take_heuristic_action(message, the_reason)

            elif message.via_bot:
                # check if the message is sent via inline bot comand
                the_reason = f"{message.from_id} message sent via inline bot"
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "%s possibly sent a spam via inline bot", message.from_id
                    )
                    await take_heuristic_action(message, the_reason)

            elif message_sent_during_night(message):  # disabled for now only logging
                # await BOT.set_message_reaction(message, "🌙")
                # NOTE switch to aiogram 3.13.1 or higher
                the_reason = f"{message.from_id} message sent during the night"
                # LOGGER.info(
                #     "%s message sent during the night: %s", message.from_id, message
                # )
                # start the perform_checks coroutine
                # get the admin group members
                # admin_group_members = await fetch_admin_group_members()
                # LOGGER.debug(
                #     "%s Admin ids fetched successfully: %s",
                #     message.from_id,
                #     admin_group_members,
                # )
                if await check_n_ban(message, the_reason):
                    return
                elif message.from_id not in active_user_checks_dict:
                    # check if the user is not in the active_user_checks_dict already
                    active_user_checks_dict[message.from_id] = (
                        message.from_user.username
                    )
                    # start the perform_checks coroutine
                    # TODO need to delete the message if user is spammer
                    message_to_delete = message.chat.id, message.message_id
                    # FIXME remove -100 from public group id?
                    LOGGER.info(
                        "%s Nightwatch Message to delete: %s",
                        message.from_id,
                        message_to_delete,
                    )
                    asyncio.create_task(
                        perform_checks(
                            message_to_delete=message_to_delete,
                            event_record=f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: {message.from_id:<10} night message in {'@' + message.chat.username + ': ' if message.chat.username else ''}{message.chat.title:<30}",
                            user_id=message.from_id,
                            inout_logmessage=f"{message.from_id} message sent during the night, in {message.chat.title}, checking user activity...",
                            user_name=(
                                message.from_user.username
                                if message.from_user.username
                                else "!UNDEFINED!"
                            ),
                        ),
                        name=str(message.from_id),
                    )

            # elif check_message_for_capital_letters(message):
            #     the_reason = "Message contains 5+ spammy capital letters"
            #     await take_heuristic_action(message, the_reason)

            # elif check_message_for_emojis(message):
            #     the_reason = "Message contains 5+ spammy regular emojis"
            #     await take_heuristic_action(message, the_reason)

        # If other user/admin or bot deletes message earlier than this bot we got an error
        except utils.exceptions.MessageIdInvalid as e:
            LOGGER.error(
                "Error storing/deleting recent %s message, %s - someone deleted it already?",
                message.message_id,
                e,
            )

    @DP.message_handler(commands=["ban"], chat_id=ADMIN_GROUP_ID)
    # NOTE: Manual typing command ban - useful if ban were postponed
    async def ban(message: types.Message):
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
                "Original chat ID: %s, Original message ID: %s, Forwarded message data: %s, Original message timestamp: %s",
                original_chat_id,
                original_message_id,
                forwarded_message_data,
                original_message_timestamp,
            )

            author_id = eval(forwarded_message_data)[3]
            LOGGER.debug("Author ID retrieved for original message: %s", author_id)
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"Author ID retrieved for original message: {author_id}",
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
                if len(active_user_checks_dict) > 5:
                    LOGGER.info(
                        "\033[91m%s removed from active_user_checks_dict during ban by admin: %s... %d totally\033[0m",
                        author_id,
                        list(active_user_checks_dict.items())[:3],  # First 2 elements
                        len(active_user_checks_dict),  # Number of elements left
                    )
                else:
                    LOGGER.info(
                        "\033[91m%s removed from active_user_checks_dict during ban by admin: %s\033[0m",
                        author_id,
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
                        "User %s banned and their messages deleted from chat %s (%s).",
                        author_id,
                        CHANNEL_DICT[chat_id],
                        chat_id,
                    )
                    # await BOT.send_message(
                    #     TECHNOLOG_GROUP_ID,
                    #     f"User {author_id} banned and their messages deleted from chat {channels_dict[chat_id]} ({chat_id}).",
                    # )
                except Exception as inner_e:
                    LOGGER.error(
                        "Failed to ban and delete messages in chat %s (%s). Error: %s",
                        CHANNEL_DICT[chat_id],
                        chat_id,
                        inner_e,
                    )
                    await BOT.send_message(
                        TECHNOLOG_GROUP_ID,
                        f"Failed to ban and delete messages in chat {CHANNEL_DICT[chat_id]} ({chat_id}). Error: {inner_e}",
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
                except Exception as inner_e:
                    LOGGER.error(
                        "Failed to delete message %s in chat %s (%s). Error: %s",
                        message_id,
                        CHANNEL_DICT[chat_id],
                        chat_id,
                        inner_e,
                    )
                    # await BOT.send_message(
                    #     TECHNOLOG_GROUP_ID,
                    #     f"Failed to delete message {message_id} in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}",
                    # )
            LOGGER.debug(
                "\033[91m%s banned and their messages deleted where applicable.\033[0m",
                author_id,
            )
            await message.reply(
                f"Action taken: User (<code>{author_id}</code>) banned and their messages deleted where applicable.",
                parse_mode="HTML",
            )

        except Exception as e:
            LOGGER.error("Error in ban function: %s", e)
            await message.reply(f"Error: {e}")

    @DP.message_handler(commands=["check"], chat_id=ADMIN_GROUP_ID)
    async def check_user(message: types.Message):
        """Function to start lols_cas check 3hrs corutine check the user for spam."""
        try:
            command_args = message.text.split()
            # LOGGER.debug("Command arguments received: %s", command_args)

            if len(command_args) < 2:
                raise ValueError("Please provide the user ID to check.")

            user_id = int(command_args[1])
            LOGGER.debug(
                "%d:!UNDEFINED! - User ID to check, requested by admin %d",
                user_id,
                message.from_user.id,
            )

            if user_id in active_user_checks_dict:
                await message.reply(
                    f"User {active_user_checks_dict[user_id]} is already being checked."
                )
                return
            else:
                active_user_checks_dict[user_id] = "!UNDEFINED!"

            # start the perform_checks coroutine
            asyncio.create_task(
                perform_checks(
                    event_record=f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: {user_id:<10} 👀 manual check requested by admin {message.from_user.id}",
                    user_id=user_id,
                    inout_logmessage=f"{user_id} manual check requested, checking user activity requested by admin {message.from_id}...",
                    user_name=active_user_checks_dict[user_id],
                ),
                name=str(user_id),
            )

            await message.reply(
                f"User {user_id} 3hrs monitoring activity check started."
            )
        except ValueError as ve:
            await message.reply(str(ve))
        except Exception as e:
            LOGGER.error("Error in check_user: %s", e)
            await message.reply("An error occurred while trying to check the user.")

    @DP.message_handler(commands=["delmsg"], chat_id=ADMIN_GROUP_ID)
    async def delete_message(message: types.Message):
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
            chat_id, message_id = extract_chat_id_and_message_id_from_link(message_link)
            LOGGER.debug("Chat ID: %s, Message ID: %d", chat_id, message_id)

            # reply to the message # TODO confirm deletion
            # await message.reply('Are you sure you want to delete the message?')

            if not chat_id or not message_id:
                raise ValueError("Invalid message link provided.")

            try:
                await BOT.delete_message(chat_id=chat_id, message_id=message_id)
                LOGGER.info(
                    "Message %d deleted from chat %s by admin request",
                    message_id,
                    chat_id,
                )
                await message.reply(
                    f"Message {message_id} deleted from chat {chat_id}."
                )
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"{message_link} Message {message_id} deleted from chat {chat_id} by admin <code>{admin_id}</code> request.",
                    parse_mode="HTML",
                )
                await BOT.send_message(
                    ADMIN_GROUP_ID,
                    f"{message_link} Message {message_id} deleted from chat {chat_id} by admin <code>{admin_id}</code> request.",
                    parse_mode="HTML",
                    message_thread_id=ADMIN_MANBAN,
                )

            except utils.exceptions.ChatNotFound as e:
                LOGGER.error(
                    "Failed to delete message %d in chat %s. Error: %s",
                    message_id,
                    chat_id,
                    e,
                )
                await message.reply(
                    f"Failed to delete message {message_id} in chat {chat_id}. Error: {e}"
                )

        except ValueError as ve:
            await message.reply(str(ve))
        except Exception as e:
            LOGGER.error("Error in delete_message: %s", e)
            await message.reply("An error occurred while trying to delete the message.")

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
        except Exception as e:  # XXX too general exception!
            LOGGER.error("Error in unban_user: %s", e)
            await message.reply("An error occurred while trying to unban the user.")

    @DP.message_handler(
        is_valid_message,
        content_types=ALLOWED_CONTENT_TYPES,
    )  # exclude admins and technolog group, exclude join/left messages
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

            # LOGGER.debug("Received message %s", message)
            LOGGER.debug("-----------DEBUG INFO-----------")
            LOGGER.debug("From ID: %s", message.from_user.id)
            LOGGER.debug("From username: %s", message.from_user.username)
            LOGGER.debug("From first name: %s", message.from_user.first_name)

            LOGGER.debug("Message ID: %s", message.message_id)
            LOGGER.debug("Message from chat title: %s", message.chat.title)
            LOGGER.debug("Message Chat ID: %s", message.chat.id)
            LOGGER.debug("-----------DEBUG INFO-----------")

            user_id = message.from_user.id

            user_firstname = message.from_user.first_name

            if message.from_user.last_name:
                user_lastname = message.from_user.last_name
            else:
                user_lastname = ""

            user_full_name = html.escape(user_firstname + user_lastname)
            # user_full_name = f"{user_full_name} (<code>{user_id}</code>)"

            if message.from_user.username:
                user_name = message.from_user.username
            else:
                user_name = user_full_name

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
                disable_web_page_preview=True,
            )

            admin_message = await BOT.forward_message(
                ADMIN_USER_ID, message.chat.id, message.message_id
            )

            # Store the mapping of unhandled message to admin's message
            # XXX move it to DB
            unhandled_messages[admin_message.message_id] = [
                message.chat.id,
                message.message_id,
                message.from_user.first_name,
            ]

            return

        except Exception as e:
            LOGGER.error("Error in log_all_unhandled_messages function: %s", e)
            await message.reply(f"Error: {e}")

    async def simulate_admin_reply(
        original_message_chat_id, original_message_chat_reply_id, response_text
    ):
        """Simulate an admin reply with the given response text."""
        await BOT.send_message(
            original_message_chat_id,
            response_text,
            reply_to_message_id=original_message_chat_reply_id,
        )

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

    @DP.message_handler(
        is_admin_user_message,
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
            LOGGER.error("Error in handle_admin_reply function: %s", e)
            await message.reply(f"Error: {e}")

    @DP.message_handler(
        content_types=[
            types.ContentType.NEW_CHAT_MEMBERS,
            types.ContentType.LEFT_CHAT_MEMBER,
        ]
    )
    async def user_changed_message(message: types.Message):
        """Function to handle users joining or leaving the chat."""

        # handle user join/left events
        # with message.new_chat_members and message.left_chat_member
        # for chats with small amount of members

        # LOGGER.info("Users changed", message.new_chat_members, message.left_chat_member)

        LOGGER.info(
            "%s changed in user_changed_message function: %s --> %s, deleting system message...",
            message.from_id,
            getattr(message, "left_chat_member", ""),
            getattr(message, "new_chat_members", ""),
        )

        # remove system message about user join/left where applicable
        await BOT.delete_message(message_id=message.message_id, chat_id=message.chat.id)

    # scheduler to run the log_lists function daily at 04:00
    @aiocron.crontab("0 4 * * *")
    async def scheduled_log():
        """Function to schedule the log_lists function to run daily at 00:00."""
        await log_lists()

    # TODO reply to individual messages by bot in the monitored groups or make posts
    # TODO hash all banned spam messages and check if the signature of new message is same as spam to produce autoreport
    # TODO if user banned - analyze message and caption scrap for links or channel/user names to check in the other messages
    # TODO fix message_forward_date to be the same as the message date in functions get_spammer_details and store_recent_messages
    # TODO check profile picture date, if today - check for lols for 2 days
    # TODO more attention to the messages from users with IDs > 8 000 000 000
    # TODO edit message update check - check if user edited his message
    # TODO check if user changed his name
    # TODO check photos date and DC location of the joined profile - warn admins if it's just uploaded
    # TODO check if user changed his name after joining the chat when he sends a message
    # TODO scheduler_dict = {}: Implement scheduler to manage chat closure at night for example
    # TODO switch to aiogram 3.13.1 or higher
    # TODO fix database spammer store and find indexes, instead of date
    # XXX search and delete user messages if banned by admin and timely checks
    # XXX use active checks list and banned users list to store recent messages links during runtime to delete it if user is banned FSM?

    # Uncomment this to get the chat ID of a group or channel
    # @dp.message_handler(commands=["getid"])
    # async def cmd_getid(message: types.Message):
    #     await message.answer(f"This chat's ID is: {message.chat.id}")

    executor.start_polling(
        DP,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        allowed_updates=ALLOWED_UPDATES,
    )

    # Close SQLite connection
    CONN.close()
