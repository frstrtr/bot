from datetime import timedelta
from datetime import datetime
import argparse
import asyncio
import os
import random
import sqlite3
import json
import time
import html
import tracemalloc  # for memory usage debugging
import ast
import aiocron
import ast  # evaluate dictionaries safely

import aiohttp
from aiogram import Dispatcher, types

# import requests
# from PIL import Image
# from io import BytesIO
# from io import BytesIO
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ChatMemberStatus,
    # ChatActions,  # for banchan actions
)

from aiogram import executor

# from aiogram.types import Message
from aiogram.utils.exceptions import (
    MessageToDeleteNotFound,
    MessageCantBeDeleted,
    MessageCantBeForwarded,
    RetryAfter,
    BadRequest,
    ChatNotFound,
    MessageToForwardNotFound,
    MessageIdInvalid,
    ChatAdminRequired,
    # BotKicked,
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
    # get_spammer_details,  # Add this line
    store_message_to_db,
    db_init,
    create_inline_keyboard,
    check_user_legit,
    report_spam,
    report_spam_from_message,
)
from utils.utils_decorators import (
    is_not_bot_action,
    is_forwarded_from_unknown_channel_message,
    is_admin_user_message,
    is_in_monitored_channel,
    is_valid_message,
)

from utils.utils_config import (
    CHANNEL_IDS,
    ADMIN_AUTOREPORTS,
    # TECHNO_LOGGING,
    TECHNO_ADMIN,
    TECHNO_ORIGINALS,
    TECHNO_UNHANDLED,
    ADMIN_AUTOBAN,
    ADMIN_MANBAN,
    ADMIN_SUSPICIOUS,
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
    TECHNOLOG_GROUP,
    TECHNOLOG_GROUP_NAME,
    DP,
    BOT,
    LOGGER,
    ALLOWED_UPDATES,
    CHANNEL_DICT,
    ALLOWED_CONTENT_TYPES,
    TELEGRAM_CHANNEL_BOT_ID,
)

# Parse command line arguments
parser = argparse.ArgumentParser(
    description="Run the bot with specified logging level."
)
parser.add_argument(
    "--log-level",
    type=str,
    default="DEBUG",  # TODO for production
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

# Dictionary to store running tasks by user ID
running_watchdogs = {}

# Initialize the event
shutdown_event = asyncio.Event()

# Setting up SQLite Database
CONN = sqlite3.connect("messages.db")
CURSOR = CONN.cursor()
db_init(CURSOR, CONN)


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


async def submit_autoreport(message: types.Message, reason):
    """Function to take heuristically invoked action on the message."""

    LOGGER.info(
        # "%-10s : %s. Sending automated report to the admin group for review...",
        "%s. Sending automated report to the admin group for review...",
        # f"{message.from_id:10}",
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


async def on_startup(_dp: Dispatcher):
    """Function to handle the bot startup."""
    _commit_info = get_latest_commit_info(LOGGER)

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


async def ban_rogue_chat_everywhere(rogue_chat_id: int, chan_list: list) -> bool:
    """ban chat sender chat for Rogue channels"""
    ban_rogue_chat_everywhere_error = None

    for chat_id in chan_list:
        try:
            await BOT.ban_chat_sender_chat(chat_id, rogue_chat_id)
            # LOGGER.debug("%s  CHANNEL successfully banned in %s", rogue_chat_id, chat_id)
            await asyncio.sleep(1)  # pause 1 sec
        except BadRequest as e:  # if user were Deleted Account while banning
            # chat_name = get_channel_id_by_name(channel_dict, chat_id)
            LOGGER.error(
                "%s - error banning in chat (%s): %s. Deleted CHANNEL?",
                rogue_chat_id,
                chat_id,
                e,
            )
            ban_rogue_chat_everywhere_error = str(e) + f" in {chat_id}"
            continue

    # report rogue chat to the p2p server
    await report_spam(rogue_chat_id, LOGGER)
    await BOT.send_message(
        TECHNOLOG_GROUP_ID,
        f"{rogue_chat_id}:@!ROGUECHAT! reported to P2P spamcheck server.",
        parse_mode="HTML",
        disable_web_page_preview=True,
        message_thread_id=TECHNO_ADMIN,
    )

    if ban_rogue_chat_everywhere_error:
        return ban_rogue_chat_everywhere_error
    else:
        LOGGER.info(
            "%s  CHANNEL successfully banned where it was possible", rogue_chat_id
        )
        banned_users_dict[rogue_chat_id] = "!ROGUECHAT!"
        return True


async def unban_rogue_chat_everywhere(rogue_chat_id: int, chan_list: list) -> bool:
    """Unban chat sender chat for Rogue channels"""
    unban_rogue_chat_everywhere_error = None

    for chat_id in chan_list:
        try:
            await BOT.unban_chat_sender_chat(chat_id, rogue_chat_id)
            # LOGGER.debug("%s  CHANNEL successfully unbanned in %s", rogue_chat_id, chat_id)
            await asyncio.sleep(1)  # pause 1 sec
        except BadRequest as e:  # if user were Deleted Account while unbanning
            # chat_name = get_channel_id_by_name(channel_dict, chat_id)
            LOGGER.error(
                "%s - error unbanning in chat (%s): %s. Deleted CHANNEL?",
                rogue_chat_id,
                chat_id,
                e,
            )
            unban_rogue_chat_everywhere_error = str(e) + f" in {chat_id}"
            continue

    # TODO: Remove rogue chat from the p2p server report list?
    # await unreport_spam(rogue_chat_id, LOGGER)
    # await BOT.send_message(
    #     TECHNOLOG_GROUP_ID,
    #     f"{rogue_chat_id}:@!ROGUECHAT! removed from P2P spamcheck server.",
    #     parse_mode="HTML",
    #     disable_web_page_preview=True,
    #     message_thread_id=TECHNO_ADMIN,
    # )

    if unban_rogue_chat_everywhere_error:
        return unban_rogue_chat_everywhere_error
    else:
        LOGGER.info(
            "%s  CHANNEL successfully unbanned where it was possible", rogue_chat_id
        )
        if rogue_chat_id in banned_users_dict:
            del banned_users_dict[rogue_chat_id]
        return True


async def load_banned_users():
    """Coroutine to load banned users from file"""
    banned_users_filename = "banned_users.txt"

    if not os.path.exists(banned_users_filename):
        LOGGER.error("File not found: %s", banned_users_filename)
        return

    with open(banned_users_filename, "r", encoding="utf-8") as file:
        for line in file:
            user_id, user_name = (
                int(line.strip().split(":")[0]),
                line.strip().split(":")[1],
            )
            banned_users_dict[user_id] = user_name
        LOGGER.info(
            "\033[91mBanned users dict (%s) loaded from file: %s\033[0m",
            len(banned_users_dict),
            banned_users_dict,
        )


async def load_active_user_checks():
    """Coroutine to load checks non-blockingly from file"""
    active_checks_filename = "active_user_checks.txt"

    if not os.path.exists(active_checks_filename):
        LOGGER.error("File not found: %s", active_checks_filename)
        return

    with open(active_checks_filename, "r", encoding="utf-8") as file:
        for line in file:
            user_id = int(line.strip().split(":")[0])
            user_name = line.strip().split(":", 1)[1]
            try:
                # Attempt to parse user_name as a dictionary if it looks like a dict
                user_name = (
                    ast.literal_eval(user_name)
                    if user_name.startswith("{") and user_name.endswith("}")
                    else user_name
                )
            except (ValueError, SyntaxError):
                # If parsing fails, keep user_name as a string
                pass
            active_user_checks_dict[user_id] = user_name
            event_message = (
                f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "
                + str(user_id)
                + " ❌ \t\t\tbanned everywhere during initial checks on_startup"
            )
            # Start the check NON-BLOCKING
            if isinstance(user_name, dict):
                user_name = user_name.get("username", "!UNDEFINED!")
            else:
                user_name = user_name if user_name != "None" else "!UNDEFINED!"
            asyncio.create_task(
                perform_checks(
                    user_id=user_id,
                    user_name=user_name,
                    event_record=event_message,
                    inout_logmessage=f"(<code>{user_id}</code>) banned using data loaded on_startup event",
                )
            )
            LOGGER.info(
                "%s:@%s loaded from file & 3hr monitoring started ...",
                user_id,
                user_name if user_name != "None" else "!UNDEFINED!",
            )
            # Insert a 1-second interval between task creations
            await asyncio.sleep(1)
        LOGGER.info(
            "\033[93mActive users checks dict (%s) loaded from file: %s\033[0m",
            len(active_user_checks_dict),
            active_user_checks_dict,
        )


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


async def on_shutdown(_dp):
    """Function to handle the bot shutdown."""
    LOGGER.info(
        "\033[95mBot is shutting down... Performing final spammer check...\033[0m"
    )

    # Create a list to hold all tasks
    tasks = []

    # Iterate over active user checks and create a task for each check
    for _id, _uname in active_user_checks_dict.items():
        LOGGER.info(
            "%s:@%s shutdown check for spam...",
            _id,
            (
                _uname["username"]
                if isinstance(_uname, dict)
                else (_uname if _uname else "!UNDEFINED!")
            ),
        )

        # Create the task for the sequential coroutine without awaiting it immediately
        task = asyncio.create_task(
            sequential_shutdown_tasks(_id, _uname), name=str(_id) + "shutdown"
        )
        tasks.append(task)

    # try:
    # Run all tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # TODO add messages deletion if spammer detected and have messages posted

    # Process results and log any exceptions
    for task, result in zip(tasks, results):
        if isinstance(result, Exception):
            LOGGER.error("Task %s failed with exception: %s", task.get_name(), result)
        else:
            LOGGER.info("Task %s completed successfully.", task.get_name())
    # except Exception as e:
    #     LOGGER.error("Unexpected error during shutdown tasks: %s", e)

    # save all unbanned checks to temp file to restart checks after bot restart
    # Check if active_user_checks_dict is not empty
    if active_user_checks_dict:
        LOGGER.debug(
            "Saving active user checks to file...\n\033[93m%s\033[0m",
            active_user_checks_dict,
        )
        with open("active_user_checks.txt", "w", encoding="utf-8") as file:
            for _id, _uname in active_user_checks_dict.items():
                # XXX preserve messages to delete for next startup checks
                # if isinstance(_uname, dict) and "username" in _uname:
                #     _uname = _uname["username"]
                # LOGGER.debug(_uname)
                file.write(f"{_id}:{_uname}\n")
    else:
        # clear the file if no active checks
        with open("active_user_checks.txt", "w", encoding="utf-8") as file:
            file.write("")

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
                file.write(f"{_id}:{_uname}\n")
    elif banned_users_dict:
        with open(banned_users_filename, "w", encoding="utf-8") as file:
            for _id, _uname in banned_users_dict.items():
                file.write(f"{_id}:{_uname}\n")

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
        TECHNOLOG_GROUP,
        (
            "Runtime session shutdown stats:\n"
            f"Bot started at: {bot_start_time}\n"
            f"Current active user checks: {len(active_user_checks_dict)}\n"
            f"Spammers detected: {len(banned_users_dict)}\n"
        ),
        message_thread_id=TECHNO_RESTART,
    )
    LOGGER.info(
        "\033[93m\nRuntime session shutdown stats:\n"
        "Bot started at: %s\n"
        "Current active user checks: %d\n"
        "Spammers detected: %d\033[0m",
        bot_start_time,
        len(active_user_checks_dict),
        len(banned_users_dict),
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


async def handle_autoreports(
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
    try:  # if it was already removed earlier
        technnolog_spam_message_copy = await BOT.forward_message(
            TECHNOLOG_GROUP_ID, message.chat.id, message.message_id
        )
    except MessageToForwardNotFound:
        LOGGER.error(
            "%s:@%s Message to forward not found: %s",
            spammer_id,
            "!UNDEFINED!",
            message.message_id,
        )
        return

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
            message.from_id,
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
            message.forward_date if message.forward_date else None,
            received_date,
            str(found_message_data),
        ),
    )

    CONN.commit()

    message_link = f"https://t.me/c/{str(message.chat.id)[4:] if message.chat.id < 0 else str(message.chat.id)}/{str(message.message_id)}"

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
            "ℹ️ Check Spam Data ℹ️",
            url=f"https://t.me/oLolsBot?start={user_id}",
        )
    )
    # Send the banner to the technolog group
    await BOT.send_message(
        TECHNOLOG_GROUP_ID, log_info, parse_mode="HTML", reply_markup=inline_kb
    )

    # Keyboard ban/cancel/confirm buttons
    keyboard = InlineKeyboardMarkup()
    # MODIFIED: Pass spammer_id (user_id) and report_id, and rename callback prefix
    ban_btn = InlineKeyboardButton(
        "Ban", callback_data=f"confirmban_{spammer_id}_{report_id}"
    )
    keyboard.add(ban_btn)
    try:
        # Forward original message to the admin group
        await BOT.forward_message(
            ADMIN_GROUP_ID,
            found_message_data[0],  # from_chat_id
            found_message_data[1],  # message_id
            message_thread_id=ADMIN_AUTOREPORTS,
            disable_notification=True,
        )
    except MessageToForwardNotFound:
        if message:
            await message.forward(ADMIN_GROUP_ID, ADMIN_AUTOREPORTS)
        else:
            LOGGER.warning("%s autoreported message already DELETED?", spammer_id)
    # Show ban banner with buttons in the admin group to confirm or cancel the ban
    admin_group_banner_autoreport_message = await BOT.send_message(
        ADMIN_GROUP_ID,
        admin_ban_banner,
        reply_markup=keyboard,
        parse_mode="HTML",
        message_thread_id=ADMIN_AUTOREPORTS,
        disable_web_page_preview=True,
    )

    # Store the admin action banner message data
    # AUTOREPORT ALWAYS IN ADMIN_GROUP_ID so there is no ADMIN action banner message

    forwarded_report_state = DP.get("forwarded_reports_states")
    forwarded_report_state[report_id] = {}
    # Add the new state to the forwarded_reports_states dictionary
    forwarded_report_state[report_id] = {
        "original_forwarded_message": message,
        "admin_group_banner_message": admin_group_banner_autoreport_message,
        "action_banner_message": None,  # AUTOREPORT have no ADMIN ACTION
        "report_chat_id": message.chat.id,
    }
    DP["forwarded_reports_states"] = forwarded_report_state

    return


async def spam_check(user_id):
    """Function to check if a user is in the lols/cas/p2p/db spam list.
    var: user_id: int: The ID of the user to check."""
    # Check if the user is in the lols bot database
    # https://api.lols.bot/account?id=
    # https://api.cas.chat/check?user_id=
    # http://127.0.0.1:8081/check?user_id=
    # TODO implement prime_radiant local DB check
    async with aiohttp.ClientSession() as session:
        lols = False
        cas = 0
        is_spammer = False

        async def check_local():
            try:
                async with session.get(
                    f"http://127.0.0.1:8081/check?user_id={user_id}", timeout=10
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
    """

    for chat_id in channel_ids:
        try:
            await BOT.ban_chat_member(chat_id, user_id, revoke_messages=True)
            # LOGGER.debug("Successfully banned USER %s in %s", user_id, chat_id)
        except BadRequest as e:  # if user were Deleted Account while banning
            chat_name = get_channel_name_by_id(channel_dict, chat_id)
            LOGGER.error(
                "%s - error banning in chat %s (%s): %s. Deleted ACCOUNT or no BOT in CHAT?",
                user_id,
                chat_name,
                chat_id,
                e,
            )
            await asyncio.sleep(1)
            # XXX remove user_id check coroutine and from monitoring list?
            continue

    # RED color for the log
    LOGGER.info(
        "\033[91m%s:@%s identified as a SPAMMER, and has been banned from all chats.\033[0m",
        user_id,
        user_name if user_name else "!UNDEFINED!",
    )


async def autoban(_id, user_name="!UNDEFINED!"):
    """Function to ban a user from all chats using lols's data.
    id: int: The ID of the user to ban."""

    if _id in active_user_checks_dict:
        banned_users_dict[_id] = active_user_checks_dict.pop(
            _id, None
        )  # add and remove the user to the banned_users_dict

        # remove user from all known chats first
        await ban_user_from_all_chats(_id, user_name, CHANNEL_IDS, CHANNEL_DICT)

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
        await ban_user_from_all_chats(_id, user_name, CHANNEL_IDS, CHANNEL_DICT)

        last_3_users = list(banned_users_dict.items())[-3:]  # Last 3 elements
        last_3_users_str = ", ".join([f"{uid}: {uname}" for uid, uname in last_3_users])
        LOGGER.info(
            "\033[91m%s:@%s added to banned_users_dict during lols_autoban: %s... %d totally\033[0m",
            _id,
            user_name if user_name else "!UNDEFINED!",
            last_3_users_str,  # Last 3 elements
            len(banned_users_dict),  # Number of elements left
        )
    if user_name and user_name != "!UNDEFINED!":  # exclude noname users
        await BOT.send_message(
            TECHNOLOG_GROUP_ID,
            f"<code>{_id}</code>:@{user_name} (907)",
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

    lols_url = f"https://t.me/oLolsBot?start={user_id}"

    inline_kb = InlineKeyboardMarkup().add(
        InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_url)
    )

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

        if message_to_delete:
            LOGGER.debug("%s message to delete list (#CNAB)", message_to_delete)
            origin_chat_id = (
                int(f"-100{message_to_delete[0]}")
                if message_to_delete[0] > 0
                else message_to_delete[0]
            )
            try:
                await BOT.delete_message(origin_chat_id, message_to_delete[1])
            except ChatNotFound:
                LOGGER.error(
                    "%s:@%s Chat not found: %s",
                    user_id,
                    user_name,
                    message_to_delete[0],
                )
            except MessageToDeleteNotFound:
                LOGGER.error(
                    "%s:@%s Message to delete not found: %s",
                    user_id,
                    user_name,
                    message_to_delete[1],
                )

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
            if user_name and user_name != "!UNDEFINED!":
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code>:@{user_name} (990)",
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
            if user_name and user_name != "!UNDEFINED!":
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code>:@{user_name} (1013)",
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )
            else:
                user_name = "!UNDEFINED!"
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

        # perform_checks(user_id, user_name)
        # TODO Add perform-checks coroutine!!!
        # TODO check again if it is marked as SPAMMER already

        # LOGGER.debug("inout_logmessage: %s", inout_logmessage)
        # LOGGER.debug("event_record: %s", event_record)
        # user is not spammer but kicked or restricted by admin
        # TODO log admin name getting it from inout_logmessage
        admin_name = (
            inout_logmessage.split("by ", 1)[-1].split("\n", 1)[0]
            if "by " in inout_logmessage
            else "!UNDEFINED!"
        )
        LOGGER.info(
            "\033[95m%s:@%s kicked/restricted by %s, but is not now in the lols database.\033[0m",
            user_id,
            user_name,
            admin_name,
        )
        await BOT.send_message(
            ADMIN_GROUP_ID,
            f"User with ID: {user_id} is not now in the SPAM database but kicked/restricted by admin.\n"
            + inout_logmessage,
            message_thread_id=ADMIN_MANBAN,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )
        if user_name and user_name != "!UNDEFINED!":
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"<code>{user_id}</code>:@{user_name} (1054)",
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
        except MessageToForwardNotFound as e:
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
                "ℹ️ Check Spam Data ℹ️",
                url=f"https://t.me/oLolsBot?start={message.from_user.id}",
            )
        )
        chat_link = (
            f"https://t.me/{message.chat.username}"
            if message.chat.username
            else f"https://t.me/c/{message.chat.id}"
        )
        chat_link_name = (
            f"@{message.chat.username}:({message.chat.title})"
            if message.chat.username
            else message.chat.title
        )
        await BOT.send_message(
            ADMIN_GROUP_ID,
            f"Alert! 🚨 User @{message.from_user.username if message.from_user.username else '!UNDEFINED!'}:(<code>{message.from_user.id}</code>) has been caught red-handed spamming in <a href='{chat_link}'>{chat_link_name}</a>! Telefragged in {time_passed}...",
            message_thread_id=ADMIN_AUTOBAN,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )
        # log username to the username thread
        if message.from_user.username:
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"<code>{message.from_user.id}</code>:@{message.from_user.username} (1191)",
                parse_mode="HTML",
                message_thread_id=TECHNO_NAMES,
            )
        # remove spammer from all groups
        await autoban(message.from_user.id, message.from_user.username)
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

        # XXX message id invalid after the message is deleted? Or deleted by other bot?
        # TODO shift to delete_messages in aiogram 3.0
        try:
            await BOT.delete_message(message.chat.id, message.message_id)
        except MessageToDeleteNotFound:
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
            65,  # 1 min
            185,  # 3 min
            305,  # 5 min
            605,  # 10 min
            1205,  # 20 min
            1805,  # 30 min
            3605,  # 1 hr
            7205,  # 2 hr
            10805,  # 3 hr
        ]

        for sleep_time in sleep_times:

            if user_id not in active_user_checks_dict:  # if user banned somewhere else
                return

            await asyncio.sleep(sleep_time)
            lols_spam = await spam_check(user_id)

            # Get the color code based on the value of lols_spam
            color_code = color_map.get(
                lols_spam, "\033[93m"
            )  # Default to yellow if lols_spam is not in the map

            # Log the message with the appropriate color
            LOGGER.debug(
                "%s%s:@%s %02dmin check lols_cas_spam: %s\033[0m IDs to check left: %s",
                color_code,
                user_id,
                user_name if user_name else "!UNDEFINED!",
                sleep_time // 60,
                lols_spam,
                len(active_user_checks_dict),
            )

            # getting message to delete link if it is in the checks dict
            # XXX what if there is more than one message link?
            if user_id in active_user_checks_dict:
                if isinstance(active_user_checks_dict[user_id], dict):
                    suspicious_messages = {
                        k: v
                        for k, v in active_user_checks_dict[user_id].items()
                        if k
                        != "username"  # unpack message links only, leave username record
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
                # cancel cycle and cancel task if it is available
                # if user_id in running_watchdogs:
                #     running_watchdogs[user_id].cancel()
                # try:
                #     await running_watchdogs[user_id]
                # except asyncio.CancelledError:
                #     LOGGER.info(
                #         "%s:@%s Watchdog disabled.(Cancelled)",
                #         user_id,
                #         user_name,
                #     )
                #     # stop cycle
                #     break
                # except KeyError as e:
                #     LOGGER.info(
                #         "%s:@%s Watchdog disabled.(%s)",
                #         user_id,
                #         user_name,
                #         e,
                #     )
                #     # stop cycle
                #     break
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
            "\033[93m%s:@%s 3hrs spam checking cancelled. %s\033[0m",
            user_id,
            user_name,
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
            # banned_users_dict[user_id] = active_user_checks_dict.pop(user_id, None)
            del active_user_checks_dict[
                user_id
            ]  # remove user from active checks dict as LEGIT
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
    """Cancels a running watchdog task for a given user ID."""
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
        except Exception as e:
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


async def create_named_watchdog(coro, user_id, user_name="!UNDEFINED!"):
    """Check if a task for the same user_id is already running

    :param coro: The coroutine to run

    :param user_id: The user ID to use as the key in the running_watchdogs dictionary

    """
    if user_id in running_watchdogs:
        LOGGER.info(
            "\033[93m%s:@%s Watchdog is already set. Cancelling and restarting existing task.\033[0m",
            user_id,
            user_name,
        )
        # return  # Do nothing; a watchdog is already active.
        await running_watchdogs[
            user_id
        ]  # Await the existing task to prevent RuntimeWarning: coroutine was never awaited
        return

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


async def log_lists(msg_thread_id=TECHNO_ADMIN):
    """Function to log the banned users and active user checks lists.
    : params:: msg_thread_id : int Message Thread ID"""

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
            TECHNOLOG_GROUP_ID,
            f"Current user checks list: {len(active_user_checks_dict)}",
            message_thread_id=msg_thread_id,
            parse_mode="HTML",
        )
        # Send active user checks list in chunks
        for chunk in active_user_chunks:
            try:
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"Active user checks list:\n{chr(10).join(chunk)}",
                    message_thread_id=msg_thread_id,
                    parse_mode="HTML",
                )
            except BadRequest as e:
                LOGGER.error("Error sending active user checks chunk: %s", e)
        await BOT.send_message(
            TECHNOLOG_GROUP_ID,
            f"Current banned users list: {len(banned_users_dict)}",
            message_thread_id=msg_thread_id,
            parse_mode="HTML",
        )
        # Send banned users list in chunks
        for chunk in banned_user_chunks:
            try:
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"Banned users list:\n{chr(10).join(chunk)}",
                    message_thread_id=msg_thread_id,
                    parse_mode="HTML",
                )
            except BadRequest as e:
                LOGGER.error("Error sending banned users chunk: %s", e)
    except BadRequest as e:
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
    )  # XXX need to store in the DB to preserve it between sessions

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
        universal_chatlink = (
            f'<a href="https://t.me/{update.chat.username}">{update.chat.title}</a>'
            if update.chat.username
            else f'<a href="https://t.me/c/{str(update.chat.id)[4:] if str(update.chat.id).startswith("-100") else update.chat.id}">{update.chat.title}</a>'
        )
        # Get current date and time DD-MM-YY HH:MM
        greet_timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        # Construct the log message
        inout_logmessage = (
            f"<a href='tg://resolve?domain={inout_username}'>@{inout_username}</a> (<code>{inout_userid}</code>): "
            f"{escaped_inout_userfirstname} {escaped_inout_userlastname}\n"
            f"{'❌ -->' if lols_spam is True else '🟢 -->' if lols_spam is False else '❓ '}"
            f" {inout_status}\n"
            f"{by_user if by_user else ''}"
            f"💬 {universal_chatlink}\n"
            f"🕔 {greet_timestamp}\n"
            f"🔗 <b>profile links:</b>\n"
            f"   ├ <b><a href='tg://user?id={inout_userid}'>id based profile link</a></b>\n"
            f"   └ <a href='tg://openmessage?user_id={inout_userid}'>Android</a>, <a href='https://t.me/@id{inout_userid}'>IOS (Apple)</a>\n"
        )

        lols_url = f"https://t.me/oLolsBot?start={inout_userid}"
        inline_kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_url)
        )

        await BOT.send_message(
            TECHNOLOG_GROUP,
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
            "%s%s:@%s --> %s in %s%s",
            color,
            inout_userid,
            inout_username,
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
                    # XXX this is not MESSAGE.ID since UPDATE have no such property UNIX_TIMESTAMP
                    int(f"{int(getattr(update, 'date', datetime.now()).timestamp())}"),
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
                    time_diff <= 30
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
                    lols_url = f"https://t.me/oLolsBot?start={inout_userid}"
                    inline_kb = InlineKeyboardMarkup().add(
                        InlineKeyboardButton("Check user profile", url=lols_url)
                    )
                    joinleft_timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                    await BOT.send_message(
                        ADMIN_GROUP_ID,
                        f"(<code>{inout_userid}</code>) @{inout_username} {escaped_inout_userfirstname} {escaped_inout_userlastname} joined and left {universal_chatlink} in 30 seconds or less. Telefragged at {joinleft_timestamp}...",
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
                    "%s:@%s left and has no previous join/leave events or was already in lols/cas spam",
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
                "ℹ️ Check Spam Data ℹ️",
                url=f"https://t.me/oLolsBot?start={user_id}",
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
        # MODIFIED: Pass user_id (spammer's ID) and report_id, and rename callback prefix
        ban_btn = InlineKeyboardButton(
            "Ban", callback_data=f"confirmban_{user_id}_{report_id}"
        )
        keyboard.add(ban_btn)

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
                admin_group_banner_message = await BOT.send_message(
                    ADMIN_GROUP_ID,
                    admin_ban_banner,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
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

                # Store the admin action banner message data XXX
                forwarded_report_state = DP.get("forwarded_reports_states")
                forwarded_report_state[report_id] = {}
                # Add the new state to the forwarded_reports_states dictionary
                forwarded_report_state[report_id] = {
                    "original_forwarded_message": message,
                    "admin_group_banner_message": admin_group_banner_message,
                    "action_banner_message": admin_action_banner_message,
                    "report_chat_id": message.chat.id,
                }

                DP["forwarded_reports_states"] = forwarded_report_state

                # Construct link to the published banner and send it to the reporter
                private_chat_id = int(
                    str(admin_group_banner_message.chat.id)[4:]
                )  # Remove -100 from the chat ID
                banner_link = f"https://t.me/c/{private_chat_id}/{admin_group_banner_message.message_id}"
                # Send the banner link to the reporter-admin
                await message.answer(f"Admin group banner link: {banner_link}")

                # XXX return admin personal report banner message object
                return admin_action_banner_message

            else:  # send report to AUTOREPORT thread of the admin group if reported by non-admin user
                await BOT.forward_message(
                    ADMIN_GROUP_ID,
                    message.chat.id,
                    message.message_id,
                    message_thread_id=ADMIN_AUTOREPORTS,
                )
                admin_group_banner_message = await BOT.send_message(
                    ADMIN_GROUP_ID,
                    admin_ban_banner,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    message_thread_id=ADMIN_AUTOREPORTS,
                    disable_web_page_preview=True,
                )
                # store state
                # Store the admin action banner message data XXX
                # XXX
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
                #         reply_markup=keyboard,
                #         parse_mode="HTML",
                #         message_thread_id=ADMIN_AUTOREPORTS,
                #         disable_web_page_preview=True,
                #     )

                #     # Store the state
                #     await store_state(report_id, message, admin_group_banner_message, admin_action_banner_message)

                #     return admin_group_banner_message
                # XXX we need to lock
                forwarded_report_state = DP.get("forwarded_reports_states")
                forwarded_report_state[report_id] = {}
                # Add the new state to the forwarded_reports_states dictionary
                forwarded_report_state[report_id] = {
                    "original_forwarded_message": message,
                    "admin_group_banner_message": admin_group_banner_message,
                    "action_banner_message": admin_action_banner_message,  # BUG if report sent by non-admin user - there is no admin action banner message
                    "report_chat_id": message.chat.id,
                }

                DP["forwarded_reports_states"] = forwarded_report_state

                return admin_group_banner_message

        except BadRequest as e:
            LOGGER.error("Error while sending the banner to the admin group: %s", e)
            await message.answer(
                "Error while sending the banner to the admin group. Please check the logs."
            )

    @DP.callback_query_handler(lambda c: c.data.startswith("confirmban_"))  # MODIFIED: Renamed callback prefix
    async def ask_confirmation(callback_query: CallbackQuery):
        """Function to ask for confirmation before banning the user."""
        # MODIFIED: Parse user_id and report_id
        parts = callback_query.data.split("_")
        spammer_user_id_str = parts[1]
        report_id_to_ban_str = parts[2]

        # DEBUG:
        # logger.debug(f"Report {callback_query} confirmed for banning.")

        keyboard = InlineKeyboardMarkup(row_width=2)
        # MODIFIED: Pass spammer_user_id_str and report_id_to_ban_str, and rename callback prefixes
        confirm_btn = InlineKeyboardButton(
            "🟢 Confirm", callback_data=f"doban_{spammer_user_id_str}_{report_id_to_ban_str}"
        )
        cancel_btn = InlineKeyboardButton(
            "🔴 Cancel", callback_data=f"resetban_{spammer_user_id_str}_{report_id_to_ban_str}"
        )

        keyboard.add(confirm_btn, cancel_btn)

        # get report states
        forwarded_reports_states: dict = DP.get("forwarded_reports_states")
        forwarded_report_state: dict = forwarded_reports_states.get(report_id_to_ban_str)
        if forwarded_reports_states is None:
            LOGGER.warning("No states recorded!")
            # reply message and remove buttons
            return
        # """                forwarded_report_state[report_id] = {
        #             "original_forwarded_message": message,
        #             "admin_group_banner_message": admin_group_banner_message,
        #             "action_banner_message": admin_action_banner_message,
        #             "report_chat_id": message.chat.id,"""
        # unpack states for the report_id to ban
        # original_forwarded_message: types.Message = forwarded_report_state[
        #     "original_forwarded_message"
        # ]
        admin_group_banner_message: types.Message = forwarded_report_state[
            "admin_group_banner_message"
        ]
        action_banner_message: types.Message = forwarded_report_state[
            "action_banner_message"
        ]
        # report_chat_id: int = forwarded_report_state["report_chat_id"]
        # check received states for None

        # clear admin and personal banner states for this report
        del forwarded_report_state["action_banner_message"]
        del forwarded_report_state["admin_group_banner_message"]

        # update states for the designated report_id_to_ban
        forwarded_reports_states[report_id_to_ban_str] = forwarded_report_state

        # update DP states storage
        DP["forwarded_reports_states"] = forwarded_reports_states

        # Edit messages to remove buttons or messages
        # check where the callback_query was pressed
        # remove buttons and add Confirm/Cancel buttons in the same chat
        try:
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=keyboard,
            )

            if admin_group_banner_message:
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
                    return  # Action done in Admin group and this is AUTOREPORT or report from non-admin user do nothing
                else:  # report was actioned in the personal chat
                    # remove admin group banner buttons
                    await BOT.edit_message_reply_markup(
                        chat_id=ADMIN_GROUP_ID,
                        message_id=admin_group_banner_message.message_id,
                    )
                    return

        # FIXME exceptions type
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

    @DP.callback_query_handler(lambda c: c.data.startswith("doban_"))  # MODIFIED: Renamed callback prefix
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
            report_id_to_ban_str = parts[2]  # This is the original report_id (chat_id+message_id combo)

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
            forwarded_reports_states: dict = DP.get("forwarded_reports_states")
            forwarded_report_state: dict = forwarded_reports_states.get(
                report_id_to_ban
            )
            original_spam_message: types.Message = forwarded_report_state[
                "original_forwarded_message"
            ]
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
                        # MODIFIED: Use ast.literal_eval for safety
            author_id = ast.literal_eval(forwarded_message_data)[3]
            LOGGER.debug("%s author ID retrieved for original message", author_id)

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
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"Author ID (<code>{author_id}</code>) retrieved for original message.",
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
            spam_messages_count = len(result)
            bot_info_message = (
                f"Attempting to delete all messages <b>({spam_messages_count})</b> from <code>{author_id}</code>\n"
                f"reported by (@{original_spam_message.from_user.username if original_spam_message.from_user.username else '!UNDEFINED!'}):"
            )
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                bot_info_message,
                parse_mode="HTML",
                disable_web_page_preview=True,
                disable_notification=True,
                message_thread_id=TECHNO_ORIGINALS,
            )
            # Attempting to delete all messages one by one
            for channel_id, message_id, user_name in result:
                try:
                    message_link = construct_message_link(
                        [channel_id, message_id, None]
                    )
                    chat_link = f"https://t.me/c/{str(channel_id)[4:]}/"
                    bot_chatlink_message = (
                        f"Attempting to delete message <code>{message_id}</code>\n"
                        f"in chat <a href='{chat_link}'>{CHANNEL_DICT[channel_id]}</a> (<code>{channel_id}</code>)\n"
                        f"<a href='{message_link}'>{message_link}</a>"
                    )
                    await BOT.send_message(
                        TECHNOLOG_GROUP_ID,
                        bot_chatlink_message,
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
                # unpack user_name correctly XXX
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
                            e.timeout
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
                    except MessageToDeleteNotFound:
                        LOGGER.warning(
                            "%s:@%s Message %s in chat %s (%s) not found for deletion.",
                            author_id,
                            user_name,
                            message_id,
                            CHANNEL_DICT[channel_id],
                            channel_id,
                        )
                        break  # Cancel current attempt
                    except ChatAdminRequired as inner_e:
                        LOGGER.error(
                            "\033[91mBot is not an admin in chat %s (%s). Error: %s\033[0m",
                            CHANNEL_DICT[channel_id],
                            channel_id,
                            inner_e,
                        )
                        await BOT.send_message(
                            TECHNOLOG_GROUP_ID,
                            f"Bot is not an admin in chat {CHANNEL_DICT[channel_id]} ({channel_id}). Error: {inner_e}",
                        )
                        break  # Cancel current attempt
                    except MessageCantBeDeleted:
                        LOGGER.warning(
                            "%s:@%s Message %s in chat %s (%s) can't be deleted. Too old message?",
                            author_id,
                            user_name,
                            message_id,
                            CHANNEL_DICT[channel_id],
                            channel_id,
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
                except Exception as inner_e:
                    LOGGER.error(
                        "%s:@%s Failed to ban and delete messages in chat %s (%s). Error: %s",
                        author_id,
                        user_name,
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
                chan_ban_msg = f"<a href='https://t.me/c/{str(channel_id_to_ban)[4:]}'>Channel</a>:(<code>{channel_id_to_ban}</code>) also banned by AUTOREPORT#{report_id_to_ban}. "
            else:
                chan_ban_msg = ""

            # TODO add the timestamp of the button press and how much time passed since
            # button_timestamp = datetime.now()

            lols_url = f"https://t.me/oLolsBot?start={author_id}"
            lols_check_kb = InlineKeyboardMarkup().add(
                InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_url)
            )
            await BOT.send_message(
                ADMIN_GROUP_ID,
                f"Report {report_id_to_ban} action taken by @{button_pressed_by}: User (<code>{author_id}</code>) banned and their messages deleted where applicable.\n{chan_ban_msg}",
                message_thread_id=callback_query.message.message_thread_id,
                parse_mode="HTML",
                reply_markup=lols_check_kb,
            )
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"Report {report_id_to_ban} action taken by @{button_pressed_by}: User (<code>{author_id}</code>) banned and their messages deleted where applicable.\n{chan_ban_msg}",
                parse_mode="HTML",
                reply_markup=lols_check_kb,
            )
            if forwarded_message_data[4] not in [0, "0", None]:
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"<code>{author_id}</code>:@{forwarded_message_data[4]} (3088)",
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
                "\033[95m%s:@%s Report %s action taken by @%s: User @%s banned and their messages deleted where applicable.\033[0m",
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

        except MessageCantBeDeleted as e:
            LOGGER.error("Error in handle_ban function: %s", e)
            await callback_query.message.reply(f"Error in handle_ban function: {e}")

        # report spam to the P2P spamcheck server
        await report_spam(author_id, LOGGER)
        await BOT.send_message(
            TECHNOLOG_GROUP_ID,
            f"{author_id}:@{user_name} reported to P2P spamcheck server.",
            parse_mode="HTML",
            disable_web_page_preview=True,
            message_thread_id=TECHNO_ADMIN,
        )

    @DP.callback_query_handler(lambda c: c.data.startswith("resetban_"))  # MODIFIED: Renamed callback prefix
    async def reset_ban(callback_query: CallbackQuery):
        """Function to reset the ban button."""
        # MODIFIED: Parse actual_user_id and original_report_id from callback data
        parts = callback_query.data.split("_")
        actual_user_id_str = parts[1]  # The spammer's actual user ID
        original_report_id_str = parts[2]  # The original report_id (chat_id+message_id combo)

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
            "\033[95m%s Report %s button ACTION CANCELLED by @%s !!! (User ID for LOLS: %s)\033[0m",
            admin_id,
            original_report_id_str,  # Log the original report identifier
            button_pressed_by,
            actual_user_id,
        )

        # FIXED BUG: Use actual_user_id for the LOLS bot link
        lols_url = f"https://t.me/oLolsBot?start={actual_user_id}"
        inline_kb = InlineKeyboardMarkup().add(
            InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_url)
        )
        await BOT.send_message(
            ADMIN_GROUP_ID,
            f"Button ACTION CANCELLED by @{button_pressed_by}: Report WAS NOT PROCESSED!!! "
            # Use original_report_id_str for the /ban command hint
            f"Report them again if needed or use <code>/ban {original_report_id_str}</code> command.",
            message_thread_id=callback_query.message.message_thread_id,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )
        await BOT.send_message(
            TECHNOLOG_GROUP_ID,
            f"CANCEL button pressed by @{button_pressed_by}. "
            f"Button ACTION CANCELLED: Report WAS NOT PROCESSED. "
            # Use original_report_id_str for the /ban command hint
            f"Report them again if needed or use <code>/ban {original_report_id_str}</code> command.",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )

    @DP.message_handler(
        is_in_monitored_channel,
        content_types=ALLOWED_CONTENT_TYPES,
    )
    async def store_recent_messages(message: types.Message):
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
                message_link = construct_message_link(
                    [
                        message.chat.id,
                        message.message_id,
                        message.chat.username if message.chat.username else None,
                    ]
                )
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"From chat: {message.chat.title}\nMessage link: <a href='{message_link}'>Click here</a>",
                    parse_mode="HTML",
                    message_thread_id=TECHNO_ORIGINALS,
                    disable_notification=True,
                )
            except MessageIdInvalid as e:
                LOGGER.error(
                    "Message ID %s is invalid or the message was deleted in chat %s (%s): %s",
                    message.message_id,
                    message.chat.title,
                    message.chat.id,
                    e,
                )
            except MessageToForwardNotFound as e:
                LOGGER.error("Channel message already deleted: %s", e)
            except MessageCantBeForwarded as e:
                LOGGER.error("Channel message can't be forwarded: %s", e)
            except BadRequest as e:
                LOGGER.error("Channel message processing error: %s", e)
                # return XXX do not stop processing
            try:  # DELETE CHANNEL messages
                await BOT.delete_message(message.chat.id, message.message_id)
                # Convert the Message object to a dictionary
                message_dict = message.to_python()
                formatted_message = json.dumps(
                    message_dict, indent=4, ensure_ascii=False
                )  # Convert back to a JSON string with indentation and human-readable characters
                formatted_message_tlgrm: str = None
                if len(formatted_message) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
                    formatted_message_tlgrm = (
                        formatted_message[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
                    )
                LOGGER.debug(
                    "\nReceived CHANNEL message object:\n %s\n",
                    formatted_message,
                )
                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    (
                        formatted_message_tlgrm
                        if formatted_message_tlgrm
                        else formatted_message
                    ),
                    disable_web_page_preview=True,
                    message_thread_id=TECHNO_ADMIN,
                )
            except MessageToDeleteNotFound as e:
                LOGGER.error("Channel message already deleted! %s", e)

            return  # XXX STOP processing and do not store message in the DB

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
            return  # XXX stop processing and do not store message in the DB

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

        ### AUTOBAHN MESSAGE CHECKING ###
        # check if message is from user from active_user_checks_dict
        # and banned_users_dict set
        # XXX is that possible?
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
            await BOT.forward_message(
                ADMIN_GROUP_ID,
                message.chat.id,
                message.message_id,
                ADMIN_AUTOBAN,
                True,
            )

            # report ids of sender_chat, forward_from and forward_from_chat as SPAM to p2p server
            await report_spam_from_message(message, LOGGER, TELEGRAM_CHANNEL_BOT_ID)
            LOGGER.warning(logger_text)

            # delete message immidiately
            await BOT.delete_message(message.chat.id, message.message_id)

            # Send info to ADMIN_AUTOBAN
            await BOT.send_message(
                ADMIN_GROUP_ID,
                f"<code>{message_link}</code>\nby @{message.from_user.username if message.from_user.username else '!UNDEFINED!'}:(<code>{message.from_user.id}</code>)",
                # reply_markup=inline_kb, # Do not send keyboard since autobanned
                message_thread_id=ADMIN_AUTOBAN,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

            # check if message is forward from banned channel XXX
            rogue_chan_id = (
                # message.sender_chat.id
                # if message.sender_chat
                # else (
                message.forward_from_chat.id
                if message.forward_from_chat
                else None
                # )
            )
            if rogue_chan_id and (
                message.from_user.id in banned_users_dict
                or rogue_chan_id in banned_users_dict
                or await spam_check(message.from_user.id)
            ):
                try:
                    # ban spammer in all chats
                    ban_member_task = await check_and_autoban(
                        f"{message.from_user.id} CHANNELLED a SPAM message from ({rogue_chan_id})",
                        message.from_user.id,
                        f"{message.from_user.id} CHANNELLED a SPAM message from ({rogue_chan_id})",
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

                    admin_log_chan_data = (
                        f"Channel {message.sender_chat.title if message.sender_chat else (message.forward_from_chat.title if message.forward_from_chat else '!NO sender/forwarder chat TITLE!')} "
                        f"(<code>{message.sender_chat.id if message.sender_chat else (message.forward_from_chat.id if message.forward_from_chat else '!NO sender/forwarder chat ID!')}</code>):"
                        f"@{(message.sender_chat.username if message.sender_chat else (message.forward_from_chat.username if message.forward_from_chat else '!NONAME!'))} "
                        f"banned in chat {message.chat.title} (<code>{message.chat.id}</code>)"
                    )
                    log_chan_data = (
                        f"Channel {message.sender_chat.title if message.sender_chat else (message.forward_from_chat.title if message.forward_from_chat else '!NO sender/forwarder chat TITLE!')} "
                        f"({message.sender_chat.id if message.sender_chat else (message.forward_from_chat.id if message.forward_from_chat else '!NO sender/forwarder chat ID!')}):"
                        f"@{(message.sender_chat.username if message.sender_chat else (message.forward_from_chat.username if message.forward_from_chat else '!NONAME!'))} "
                        f"banned in chat {message.chat.title} ({message.chat.id})"
                    )
                    LOGGER.info(log_chan_data)
                    await BOT.send_message(
                        ADMIN_GROUP_ID,
                        admin_log_chan_data,
                        parse_mode="HTML",
                        message_thread_id=ADMIN_AUTOBAN,
                        disable_web_page_preview=True,
                        disable_notification=True,
                    )
                    return  # stop actions for this message forwarded from channel/chat and do not record to DB
                except BadRequest as e:
                    LOGGER.error(
                        "Error banning channel %s in chat %s: %s",
                        message.sender_chat,
                        message.chat.id,
                        e,
                    )
                    return  # stop processing further this message
            else:
                # LSS LATENCY squezzed spammer?
                LOGGER.debug(
                    "\033[91m%s:@%s banned and message %s deleted in chat %s (%s) @%s #LSS\033[0m",
                    message.from_user.id,
                    (
                        message.from_user.username
                        if message.from_user.username
                        else "!UNDEFINED!"
                    ),
                    message.message_id,
                    message.chat.title,
                    message.chat.id,
                    message.chat.username if message.chat.username else "NoName",
                )
                try:
                    await BOT.delete_message(message.chat.id, message.message_id)
                except MessageToDeleteNotFound as e:
                    LOGGER.error(
                        "\033[93m%s:@%s message %s to delete not found in chat %s (%s) @%s #LSS\033[0m:\n\t\t\t%s",
                        message.from_user.id,
                        (
                            message.from_user.username
                            if message.from_user.username
                            else "!UNDEFINED!"
                        ),
                        message.message_id,
                        message.chat.title,
                        message.chat.id,
                        message.chat.username if message.chat.username else "NoName",
                        e,
                    )
                await ban_user_from_all_chats(
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
                #     message.chat.id, message.from_id, revoke_messages=True
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
            # if there is no such data assume user joined the chat 3 years ago in seconds
            user_join_chat_date_str = (
                user_join_chat_date_str[0]
                if user_join_chat_date_str
                else "2020-01-01 00:00:00"  # datetime(2020, 1, 1, 0, 0, 0)
            )

            # Convert the string to a datetime object
            user_join_chat_date = datetime.strptime(
                user_join_chat_date_str, "%Y-%m-%d %H:%M:%S"
            )

            # flag true if user joined the chat more than 1 week ago
            user_is_old = (message.date - user_join_chat_date).total_seconds() > 604805
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
            user_flagged_legit = check_user_legit(CURSOR, message.from_id)

            # check if the message is a spam by checking the entities
            entity_spam_trigger = has_spam_entities(SPAM_TRIGGERS, message)

            # initialize the autoreport_sent flag
            autoreport_sent = False
            # check if the user is in the banned list
            # XXX if user was in lols but before it was kicked it posted a message eventually
            # we can check it in runtime banned user list
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
            if (
                message.is_forward()
                and message.forward_from
                and message.forward_from.id != message.from_user.id
            ):
                # this is possibly a spam
                the_reason = f"{message.from_id}:@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} forwarded message from unknown channel or user"
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
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
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
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            elif check_message_for_capital_letters(
                message
            ) and check_message_for_emojis(message):
                the_reason = f"{message.from_id} message contains 5+ spammy capital letters and 5+ spammy regular emojis"
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
                the_reason = f"{message.from_id} message is sent less then 10 seconds after joining the chat"
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "%s is possibly a bot typing histerically...",
                        message.from_id,
                    )
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            # check if the message is sent less then 1 hour after joining the chat
            elif user_is_1hr_old and entity_spam_trigger:
                # this is possibly a spam
                the_reason = (
                    f"{message.from_id} message sent less then 1 hour after joining the chat and have "
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
                the_reason = f"{message.from_id} message sent via inline bot"
                if await check_n_ban(message, the_reason):
                    return
                else:
                    LOGGER.info(
                        "%s possibly sent a spam via inline bot", message.from_id
                    )
                    if not autoreport_sent:
                        autoreport_sent = True
                        await submit_autoreport(message, the_reason)
                        return  # stop further actions for this message since user was banned before
            elif message_sent_during_night(message):  # disabled for now only logging
                # await BOT.set_message_reaction(message, "🌙")
                # NOTE switch to aiogram 3.13.1 or higher
                the_reason = f"{message.from_id} message {message.message_id} in chat {message.chat.title} sent during the night"
                if await check_n_ban(message, the_reason):
                    return
                elif message.from_id not in active_user_checks_dict:
                    active_user_checks_dict[message.from_id] = {
                        "username": (
                            message.from_user.username
                            if message.from_user.username
                            else "!UNDEFINED!"
                        )
                    }

                    # Store the message link in the active_user_checks_dict
                    message_key = f"{message.chat.id}_{message.message_id}"
                    active_user_checks_dict[message.from_id][message_key] = message_link

                    # start the perform_checks coroutine
                    # TODO need to delete the message if user is spammer
                    message_to_delete = message.chat.id, message.message_id
                    # FIXME remove -100 from public group id?
                    LOGGER.info(
                        "%s:@%s Nightwatch Message to delete: %s",
                        message.from_id,
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
                # if not autoreport_sent:
                #         autoreport_sent = True
                #         await submit_autoreport(message, the_reason)
            # elif check_message_for_capital_letters(message):
            #     the_reason = "Message contains 5+ spammy capital letters"
            #     await take_heuristic_action(message, the_reason)

            # elif check_message_for_emojis(message):
            #     the_reason = "Message contains 5+ spammy regular emojis"
            #     await take_heuristic_action(message, the_reason)

            # FINALLY:
            ### SUSPICIOUS MESSAGE CHECKING ###
            if (
                not autoreport_sent
                and message.from_user.id in active_user_checks_dict
                or not (user_is_old or user_flagged_legit)
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
                            message.from_id,
                            (
                                message.from_user.username
                                if message.from_user.username
                                else "!UNDEFINED!"
                            ),
                            message.chat.title,
                            human_readable_time,
                            message_link,
                        )
                    the_reason = f"\033[91m{message.from_id}:@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} identified as a spammer when sending a message during the first WEEK after registration. Telefragged in {human_readable_time}...\033[0m"
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
                        await message.forward(
                            ADMIN_GROUP_ID,
                            ADMIN_SUSPICIOUS,
                            disable_notification=True,
                        )
                        await BOT.send_message(
                            ADMIN_GROUP_ID,
                            f"WARNING! User @{message.from_user.username if message.from_user.username else 'UNDEFINED'} (<code>{message.from_user.id}</code>) sent a SUSPICIOUS message in <b>{message.chat.title}</b> after {human_readable_time}. Please check it out!",
                            message_thread_id=ADMIN_SUSPICIOUS,
                            reply_markup=inline_kb,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                        return
                else:
                    return

        # If other user/admin or bot deletes message earlier than this bot we got an error
        except MessageIdInvalid as e:
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
                "\033[93mOriginal chat ID: %s, Original message ID: %s,\n\t\t\tForwarded message data: %s,\n\t\t\tOriginal message timestamp: %s\033[0m",
                original_chat_id,
                original_message_id,
                forwarded_message_data,
                original_message_timestamp,
            )

            # MODIFIED: Use ast.literal_eval for safety
            author_id = ast.literal_eval(forwarded_message_data)[3]
            LOGGER.debug("%s author ID retrieved for original message", author_id)
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"Author ID (<code>{author_id}</code>) retrieved for original message.",
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

            lols_url = f"https://t.me/oLolsBot?start={author_id}"
            lols_check_kb = InlineKeyboardMarkup().add(
                InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_url)
            )

            await message.reply(
                f"Action taken: User (<code>{author_id}</code>) banned and their messages deleted where applicable.",
                parse_mode="HTML",
                reply_markup=lols_check_kb,
            )

        except (sqlite3.Error, ValueError, TypeError) as e:
            LOGGER.error("Error in ban function: %s", e)
            await message.reply(f"Error: {e}")

        # report spammer to P2P spam checker server
        await report_spam(author_id, LOGGER)
        user_name = (
            forwarded_message_data[4]
            if forwarded_message_data[4] not in [0, "0", None]
            else "!UNDEFINED!"
        )
        lols_url = f"https://t.me/oLolsBot?start={author_id}"
        lols_check_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="LOLS DATA",
                        url=lols_url,
                    )
                ]
            ]
        )
        await BOT.send_message(
            TECHNOLOG_GROUP_ID,
            f"{author_id}:@{user_name} reported to P2P spamcheck server.",  # XXX check user_name var
            parse_mode="HTML",
            disable_web_page_preview=True,
            message_thread_id=TECHNO_ADMIN,
            reply_markup=lols_check_kb,
        )

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
                await message.reply(
                    f"User <code>{active_user_checks_dict[user_id]}</code> is already being checked.",
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
                await message.forward(
                    TECHNOLOG_GROUP_ID,
                )
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

            except ChatNotFound as e:
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

    @DP.message_handler(commands=["banchan", "unbanchan"], chat_id=ADMIN_GROUP_ID)
    async def manage_channel(message: types.Message):
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
                    result = await ban_rogue_chat_everywhere(rogue_chan_id, CHANNEL_IDS)
                    if result is True:
                        LOGGER.info(
                            "\033[91mChannel (%s) banned where it is possible.\033[0m",
                            rogue_chan_id,
                        )
                        await message.reply(
                            f"Channel {rogue_chan_id} banned where it is possible."
                        )
                        await BOT.send_message(
                            TECHNOLOG_GROUP_ID,
                            f"Channel <code>{rogue_chan_id}</code> banned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            parse_mode="HTML",
                        )
                        await BOT.send_message(
                            ADMIN_GROUP_ID,
                            f"Channel <code>{rogue_chan_id}</code> banned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            parse_mode="HTML",
                            message_thread_id=ADMIN_MANBAN,
                        )
                    else:
                        await message.reply(
                            f"Banning channel {rogue_chan_id} generated error: {result}."
                        )
                except BadRequest as e:
                    LOGGER.error(
                        "Failed to ban channel %d. Error: %s", rogue_chan_id, e
                    )
            else:  # action == "unban"
                try:
                    result = await unban_rogue_chat_everywhere(
                        rogue_chan_id, CHANNEL_IDS
                    )
                    if result is True:
                        LOGGER.info(
                            "\033[91mChannel (%s) unbanned where it is possible.\033[0m",
                            rogue_chan_id,
                        )
                        await message.reply(
                            f"Channel {rogue_chan_id} unbanned where it is possible."
                        )
                        await BOT.send_message(
                            TECHNOLOG_GROUP_ID,
                            f"Channel <code>{rogue_chan_id}</code> unbanned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            parse_mode="HTML",
                        )
                        await BOT.send_message(
                            ADMIN_GROUP_ID,
                            f"Channel <code>{rogue_chan_id}</code> unbanned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
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
                        await message.reply(f"Channel {rogue_chan_id} unbanned.")
                        await BOT.send_message(
                            TECHNOLOG_GROUP_ID,
                            f"Channel <code>{rogue_chan_id}</code> unbanned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            parse_mode="HTML",
                        )
                        await BOT.send_message(
                            ADMIN_GROUP_ID,
                            f"Channel <code>{rogue_chan_id}</code> unbanned by admin {admin_name}(<code>{admin_id}</code>):@{admin_username} request.",
                            parse_mode="HTML",
                            message_thread_id=ADMIN_MANBAN,
                        )
                    else:
                        await message.reply(f"Channel {rogue_chan_id} was not banned.")
                except Exception as e:
                    LOGGER.error(
                        "Failed to unban channel %d. Error: %s", rogue_chan_id, e
                    )
                    await message.reply(
                        f"Failed to unban channel {rogue_chan_id}. Error: {e}"
                    )

        except ValueError as ve:
            await message.reply(str(ve))
            LOGGER.error("No channel ID provided!")

    @DP.message_handler(commands=["loglists"], chat_id=ADMIN_GROUP_ID)
    async def log_lists_handler(message: types.Message):
        """Function to log active checks and banned users dict."""
        await log_lists(message.message_thread_id)

    @DP.message_handler(commands=["unban"], chat_id=ADMIN_GROUP_ID)
    async def unban_user(message: types.Message):
        """Function to unban the user with userid in all channels listed in CHANNEL_NAMES."""
        try:
            command_args = message.text.split()
            LOGGER.debug("Command arguments received: %s", command_args)

            if len(command_args) < 2:
                raise ValueError("Please provide the user ID to unban.")

            user_id = int(command_args[1])
            LOGGER.debug("%d - User ID to unban", user_id)

            # remove from banned and checks dicts
            if user_id in active_user_checks_dict:
                del active_user_checks_dict[user_id]
            if user_id in banned_users_dict:
                del banned_users_dict[user_id]

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
            # Convert the Message object to a dictionary
            message_dict = message.to_python()
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
                # await BOT.send_message(
                #     TECHNOLOG_GROUP_ID,
                #     f"Received UNHANDLED message object:\n{message}",
                #     message_thread_id=TECHNO_UNHANDLED,
                # )
                await message.forward(
                    TECHNOLOG_GROUP_ID, message_thread_id=TECHNO_UNHANDLED
                )  # forward all unhandled messages to technolog group

                await BOT.send_message(
                    TECHNOLOG_GROUP_ID,
                    formatted_message,
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

    @DP.callback_query_handler(lambda c: c.data.startswith("stop_checks_"))
    async def stop_checks(callback_query: CallbackQuery):
        """Function to stop checks for the user."""
        try:
            # MODIFIED: Adjusted parsing for single-word prefix
            _prefix, user_id_legit_str, orig_chat_id_str, orig_message_id_str = callback_query.data.split("_")
            user_id_legit = int(user_id_legit_str)
            orig_chat_id = int(orig_chat_id_str)
            orig_message_id = int(orig_message_id_str)
        except ValueError as e:
            LOGGER.error("%s Invalid callback data: %s", e, callback_query.data)
            # await callback_query.answer("Invalid data format.")
            return

        button_pressed_by = callback_query.from_user.username
        admin_id = callback_query.from_user.id

        # Unpack user_name
        user_name_dict = active_user_checks_dict.get(user_id_legit, "!UNDEFINED!")
        # check if user_name_dict is a dict
        if isinstance(user_name_dict, dict):
            user_name = str(user_name_dict["username"]).lstrip("@")
        else:
            user_name = user_name_dict

        # # create unified message link
        message_link = construct_message_link([orig_chat_id, orig_message_id, None])
        lols_link = f"https://t.me/oLolsBot?start={user_id_legit}"

        # Create the inline keyboard
        inline_kb = InlineKeyboardMarkup()

        # # Add buttons to the keyboard, each in a new row
        inline_kb.add(
            InlineKeyboardButton("🔗 View Original Message 🔗", url=message_link)
        )
        inline_kb.add(InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_link))

        # remove buttons from the admin group
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=inline_kb,
        )

        # check if user already left active checks or button pressed after 3 hrs after report
        if user_id_legit not in active_user_checks_dict:
            LOGGER.error(
                "%s:@%s legitimized by %s(%s) not found in active_user_checks_dict",
                user_id_legit,
                user_name,
                button_pressed_by,
                admin_id,
            )
            await callback_query.answer("User not found in active checks.")
            return

        LOGGER.info(
            "\033[95m%s:@%s Identified as a legit user by admin %s:@%s!!! Future checks cancelled...\033[0m",
            user_id_legit,
            user_name,
            admin_id,
            button_pressed_by,
        )
        await asyncio.sleep(0.1)  # Add a small delay
        await BOT.send_message(
            callback_query.message.chat.id,
            f"Future checks for <code>{user_id_legit}</code> cancelled by @{button_pressed_by}!!! "
            f"Start checks them again if needed or use <code>/check {user_id_legit}</code> command.",
            message_thread_id=callback_query.message.message_thread_id,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await BOT.send_message(
            TECHNOLOG_GROUP_ID,
            f"Future checks for <code>{user_id_legit}</code> cancelled by @{button_pressed_by}. "
            f"Start checks them again if needed or use <code>/check {user_id_legit}</code> command.",
            parse_mode="HTML",
            message_thread_id=TECHNO_ADMIN,
            disable_web_page_preview=True,
        )
        # Removing user from active_user_checks dict and stop checks coroutines
        if user_id_legit in active_user_checks_dict:
            del active_user_checks_dict[user_id_legit]
            for task in asyncio.all_tasks():
                if task.get_name() == str(user_id_legit):
                    task.cancel()
        # else:
        # user is not in active checks but joined less than 1 week ago
        # store new record in the DB that future checks are cancelled
        # set new_chat_member and left_chat_member to 1
        # to indicate that checks were cancelled
        CURSOR.execute(
            """
            INSERT OR REPLACE INTO recent_messages
            (chat_id, message_id, user_id, user_name, received_date, new_chat_member, left_chat_member)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                callback_query.message.chat.id,
                callback_query.id,  # XXX not a message ID!!!
                user_id_legit,
                user_name,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                1,  # new_chat_member
                1,  # left_chat_member
            ),
        )
        CONN.commit()

        # Log that user checks are cancelled by admin
        if len(active_user_checks_dict) > 3:
            active_user_checks_dict_last3_list = list(active_user_checks_dict.items())[
                -3:
            ]
            active_user_checks_dict_last3_str = ", ".join(
                [f"{uid}: {uname}" for uid, uname in active_user_checks_dict_last3_list]
            )
            LOGGER.info(
                "\033[95m%s:@%s removed from active checks dict by admin %s:@%s:\n\t\t\t%s... %d left\033[0m",
                user_id_legit,
                user_name,
                admin_id,
                button_pressed_by,
                active_user_checks_dict_last3_str,  # Last 3 elements
                len(active_user_checks_dict),  # Number of elements left
            )
        else:
            LOGGER.info(
                "\033[95m%s:@%s removed from active checks dict by admin %s:@%s:\n\t\t\t%s\033[0m",
                user_id_legit,
                user_name,
                admin_id,
                button_pressed_by,
                active_user_checks_dict,
            )
        return

    @DP.callback_query_handler(
        # MODIFIED: Renamed callback prefixes and adjusted lambda
        lambda c: c.data.startswith("suspiciousglobalban_")
        or c.data.startswith("suspiciousban_")
        or c.data.startswith("suspiciousdelmsg_")
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
            LOGGER.error(f"Unknown prefix in handle_suspicious_sender: {action_prefix}")
            await callback_query.answer("Internal error processing action.", show_alert=True)
            return

        susp_chat_title = CHANNEL_DICT.get(susp_chat_id, "!UNKNOWN!")
        admin_id = callback_query.from_user.id
        admin_username = (
            callback_query.from_user.username
            if callback_query.from_user.username
            else "!NoName!"
        )
        callback_answer = None

        # Unpack user_name
        susp_user_name_dict = active_user_checks_dict.get(susp_user_id, "!UNDEFINED!")
        # check if user_name_dict is a dict
        if isinstance(susp_user_name_dict, dict):
            susp_user_name = str(susp_user_name_dict["username"]).lstrip("@")
        else:
            susp_user_name = susp_user_name_dict

        # create unified message link
        message_link = construct_message_link([susp_chat_id, susp_message_id, None])
        # create lols check link
        lols_link = f"https://t.me/oLolsBot?start={susp_user_id}"

        # Create the inline keyboard
        inline_kb = InlineKeyboardMarkup()

        # # Add buttons to the keyboard, each in a new row
        inline_kb.add(
            InlineKeyboardButton("🔗 View Original Message 🔗", url=message_link)
        )
        inline_kb.add(InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_link))

        if comand == "globalban":
            inline_kb.add(
                InlineKeyboardButton(
                    "Confirm global ban",
                    callback_data=f"confirmglobalban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
                InlineKeyboardButton(
                    "Cancel global ban",
                    callback_data=f"cancelglobalban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
            )
            # remove buttons from the admin group and add cancel/confirm buttons
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=inline_kb,
            )
            return
        elif comand == "ban":
            inline_kb.add(
                InlineKeyboardButton(
                    "Confirm ban",
                    callback_data=f"confirmban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
                InlineKeyboardButton(
                    "Cancel ban",
                    callback_data=f"cancelban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
            )
            # remove buttons from the admin group and add cancel/confirm buttons
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=inline_kb,
            )
            return
        elif comand == "delmsg":
            inline_kb.add(
                InlineKeyboardButton(
                    "Confirm delmsg",
                    callback_data=f"confirmdelmsg_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
                InlineKeyboardButton(
                    "Cancel delmsg",
                    callback_data=f"canceldelmsg_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
            )
            # remove buttons from the admin group and add cancel/confirm buttons
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=inline_kb,
            )
            return

        # remove buttons from the admin group
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=inline_kb,
        )

        if comand == "confirmglobalban":
            # ban user in all chats
            try:
                await BOT.delete_message(susp_chat_id, susp_message_id)
                await ban_user_from_all_chats(
                    susp_user_id,
                    susp_user_name,
                    CHANNEL_IDS,
                    CHANNEL_DICT,
                )
                LOGGER.info(
                    "%s:@%s SUSPICIOUS banned globally by admin @%s(%s)",
                    susp_user_id,
                    susp_user_name,
                    admin_username,
                    admin_id,
                )
                callback_answer = "User banned globally and the message were deleted!"
            except BadRequest as e:
                LOGGER.error("Suspicious user not found: %s", e)
                callback_answer = "User not found in chat."
            # report spammer to the P2P spam check server
            await report_spam(susp_user_id, LOGGER)
            await BOT.send_message(
                TECHNOLOG_GROUP_ID,
                f"{susp_user_id}:@{susp_user_name} reported to P2P spamcheck server.",
                parse_mode="HTML",
                disable_web_page_preview=True,
                message_thread_id=TECHNO_ADMIN,
            )
            # TODO add cancel_watchdog() for designated cases
            # cancel_named_watchdog()
            await cancel_named_watchdog(susp_user_id)

        elif comand == "confirmban":
            # ban user in chat
            try:
                await BOT.delete_message(susp_chat_id, susp_message_id)
                await BOT.ban_chat_member(
                    chat_id=susp_chat_id,
                    user_id=susp_user_id,
                    revoke_messages=True,
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
            except BadRequest as e:
                LOGGER.error("Suspicious user not found: %s", e)
                callback_answer = "User not found in chat."
        elif comand == "confirmdelmsg":
            callback_answer = "User suspicious message were deleted.\nForward message to the bot to ban user everywhere!"
            # delete suspicious message
            try:
                await BOT.delete_message(susp_chat_id, susp_message_id)
                LOGGER.info(
                    "%s:@%s SUSPICIOUS message %d were deleted from chat (%s)",
                    susp_user_id,
                    susp_user_name,
                    susp_message_id,
                    susp_chat_id,
                )
            except MessageToDeleteNotFound as e:
                LOGGER.error("Suspicious message to delete not found: %s", e)
                callback_answer = "Suspicious message to delete not found."
        elif comand in ["canceldelmsg", "cancelban", "cancelglobalban"]:
            LOGGER.info("Action cancelled by admin: @%s(%s)", admin_username, admin_id)
            callback_answer = "Action cancelled."

        await callback_query.answer(
            callback_answer,
            show_alert=True,
            cache_time=0,
        )

        bot_reply_action_message = (
            f"{callback_answer}\n"
            f"Suspicious user @{susp_user_name}:(<code>{susp_user_id}</code>) "
            f"<a href='{message_link}'>Message:{message_link}</a>\n"
            f"Action done by admin @{admin_username}"
        )

        await BOT.send_message(
            callback_query.message.chat.id,
            bot_reply_action_message,
            parse_mode="HTML",
            disable_web_page_preview=True,
            message_thread_id=callback_query.message.message_thread_id,
            # reply_to_message_id=callback_query.message.message_id,
        )

        return

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
            "%s:@%s changed in user_changed_message function:\n\t\t\t%s --> %s, deleting system message...",
            message.from_id,
            message.from_user.username if message.from_user.username else "!UNDEFINED!",
            getattr(message, "left_chat_member", ""),
            getattr(message, "new_chat_members", ""),
        )

        # remove system message about user join/left where applicable
        try:
            await BOT.delete_message(
                message_id=message.message_id, chat_id=message.chat.id
            )
        except MessageCantBeDeleted as e:
            LOGGER.error("Message can't be deleted: %s", e)
            await BOT.send_message(
                chat_id=message.chat.id,
                text="Sorry, I can't delete this message.",
                reply_to_message_id=message.message_id,
            )

    # scheduler to run the log_lists function daily at 04:00
    @aiocron.crontab("0 4 * * *")
    async def scheduled_log():
        """Function to schedule the log_lists function to run daily at 00:00."""
        await log_lists()
        # empty banned_users_dict
        banned_users_dict.clear()

    # FIXME double night message check in SRM
    # XXX remove user watchdog if banned when suspicious message detected
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
    # TODO sender_chat and forward_from_chat - add to banned database to find and check triple IDs user/senderChat/forwardChat and ban
    # TODO refactor move all temp storage to DB: messages, banned IDs, bot_unhandled, active_checks?
    # XXX search and delete user messages if banned by admin and timely checks
    # XXX use active checks list and banned users list to retrieve recent messages links during runtime to delete it if user is banned FSM?
    # XXX store nested dict when memorizing active user checks and banned users
    # XXX autoban rogue channels
    # XXX manage forwards from banned users as spam
    # XXX preserve banned channels list by storing it in the DB
    # XXX mark and check banned users in Database instead of file, leaving active checks intact as file (mark join and leave as 1 in database - to indicate banned)

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
