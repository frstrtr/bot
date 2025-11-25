"""Yet Another Telegram Bot for Spammers Detection and Reporting"""

# Force process timezone to Indian/Mauritius as early as possible
import os as _os

_os.environ.setdefault("TZ", "Indian/Mauritius")
try:
    import time as _time

    _time.tzset()  # Ensure the process picks up TZ on Unix
except Exception:
    pass

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
import re
import ast  # evaluate dictionaries safely

import aiocron
from zoneinfo import ZoneInfo

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
    Unauthorized,
    MessageNotModified,
    InvalidQueryID,
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
    report_spam_from_message,
    split_list,
    extract_username,
    make_lols_kb,
    build_lols_url,
    safe_get_chat_name_username,
    get_forwarded_states,
    set_forwarded_state,
    get_forwarded_state,
    safe_send_message,
    normalize_username,
)

# Track usernames already posted to TECHNO_NAMES to avoid duplicates in runtime
POSTED_USERNAMES = set()  # stores normalized usernames without '@'
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
        uid_fmt = f"{user_id:<10}"
        uname = username or "!UNDEFINED!"
        chat_repr = f"{chat_title or ''}({chat_id})" if chat_id else str(chat_id)
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
                o = ("@" + o) if o else "@!UNDEFINED!"
                n = ("@" + n) if n else "@!UNDEFINED!"
            diff_parts.append(f"{label}='{o}'→'{n}'")
        photo_marker = " P" if photo_changed else ""
        record = f"{ts}: {uid_fmt} PC[{context}{photo_marker}] @{uname:<20} in {chat_repr:<40} changes: {', '.join(diff_parts)}\n"
        await save_report_file("inout_", "pc" + record)
        LOGGER.info(record.rstrip())
    except Exception as _e:  # silent failure should not break main flow
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
    TECHNO_ORIGINALS,
    TECHNO_UNHANDLED,
    ADMIN_AUTOBAN,
    ADMIN_MANBAN,
    ADMIN_SUSPICIOUS,
    TECHNO_RESTART,
    TECHNO_IN,
    TECHNO_OUT,
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
) -> tuple[bool, str, str]:
    """ban chat sender chat for Rogue channels"""
    ban_rogue_chat_everywhere_error = None

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
            # LOGGER.debug("%s  CHANNEL successfully banned in %s", rogue_chat_id, chat_id)
            await asyncio.sleep(1)  # pause 1 sec

            # May be None if the chat has no username
            # LOGGER.debug(
            #     "Banned %s @%s(<code>%s</code>) in chat %s",
            #     rogue_chat_name,
            #     rogue_chat_username,
            #     rogue_chat_id,
            #     chat_id,
            # )
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

    if ban_rogue_chat_everywhere_error:
        LOGGER.error(
            "Failed to ban rogue channel %s @%s(%s): %s",
            rogue_chat_name,
            rogue_chat_username,
            rogue_chat_id,
            ban_rogue_chat_everywhere_error,
        )
        return False, rogue_chat_name, rogue_chat_username
    else:
        LOGGER.info(
            "%s @%s(%s)  CHANNEL successfully banned where it was possible",
            rogue_chat_name,
            rogue_chat_username,
            rogue_chat_id,
        )
        banned_users_dict[rogue_chat_id] = rogue_chat_username
        return True, rogue_chat_name, rogue_chat_username


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
        except BadRequest as e:  # if user were Deleted Account while unbanning
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

    # TODO: Remove rogue chat from the p2p server report list?
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
                # Persist dicts as repr for round-trip; loader already supports dict/string
                if isinstance(_uname, dict):
                    file.write(f"{_id}:{repr(_uname)}\n")
                else:
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
        f"❌ <b>Use <code>/ban {report_id}</code></b> to take action.\n"
    )

    admin_ban_banner = (
        f"💡 Reaction time: {message_report_date - message_timestamp}\n"
        f"💔 {reason}\n"
        f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
        f"ℹ️ <a href='{technnolog_spamMessage_copy_link}'>Technolog copy</a>\n"
        f"❌ <b>Use <code>/ban {report_id}</code></b> to take action.\n"
    )

    # construct lols check link button
    inline_kb = make_lols_kb(user_id)
    # Send the banner to the technolog group
    await safe_send_message(
        BOT,
        TECHNOLOG_GROUP_ID,
        log_info,
        LOGGER,
        parse_mode="HTML",
        reply_markup=inline_kb,
    )

    # Keyboard ban/cancel/confirm buttons
    keyboard = InlineKeyboardMarkup()
    # Consolidated actions button (expands to Ban / Global Ban / Delete on click)
    actions_btn = InlineKeyboardButton(
        "⚙️ Actions (Ban / Delete) ⚙️",
        callback_data=f"suspiciousactions_{message.chat.id}_{report_id}_{spammer_id}",
    )
    keyboard.add(actions_btn)
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
    admin_group_banner_autoreport_message = await safe_send_message(
        BOT,
        ADMIN_GROUP_ID,
        admin_ban_banner,
        LOGGER,
        reply_markup=keyboard,
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
        except BadRequest as e:  # if user were Deleted Account while banning
            fail_count += 1
            chat_name = get_channel_name_by_id(channel_dict, chat_id)
            LOGGER.error(
                "%s - error banning in chat %s (%s): %s. Deleted ACCOUNT or no BOT in CHAT? (Successfully banned: %d)",
                user_id,
                chat_name,
                chat_id,
                e,
                success_count,
            )
            await asyncio.sleep(1)
            # XXX remove user_id check coroutine and from monitoring list?
            continue
        except Exception as e:  # Catch any other exceptions
            fail_count += 1
            chat_name = get_channel_name_by_id(channel_dict, chat_id)
            LOGGER.error(
                "%s - unexpected error banning in chat %s (%s): %s",
                user_id,
                chat_name,
                chat_id,
                e,
            )
            await asyncio.sleep(1)
            continue

    total_count = len(channel_ids)
    # RED color for the log
    LOGGER.info(
        "\033[91m%s:@%s identified as a SPAMMER, banned from %d/%d chats.\033[0m",
        user_id,
        user_name if user_name else "!UNDEFINED!",
        success_count,
        total_count,
    )

    return success_count, fail_count, total_count


async def autoban(_id, user_name="!UNDEFINED!"):
    """Function to ban a user from all chats using lols's data.
    id: int: The ID of the user to ban."""

    if _id in active_user_checks_dict:
        banned_users_dict[_id] = active_user_checks_dict.pop(
            _id, None
        )  # add and remove the user to the banned_users_dict

        # remove user from all known chats first
        success_count, fail_count, total_count = await ban_user_from_all_chats(
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
        success_count, fail_count, total_count = await ban_user_from_all_chats(
            _id, user_name, CHANNEL_IDS, CHANNEL_DICT
        )

        last_3_users = list(banned_users_dict.items())[-3:]  # Last 3 elements
        last_3_users_str = ", ".join([f"{uid}: {uname}" for uid, uname in last_3_users])
        LOGGER.info(
            "\033[91m%s:@%s added to banned_users_dict during lols_autoban: %s... %d totally\033[0m",
            _id,
            user_name if user_name else "!UNDEFINED!",
            last_3_users_str,  # Last 3 elements
            len(banned_users_dict),  # Number of elements left
        )

    # Normalize username for logging / notification (may be dict with nested baseline)
    def _extract_username(u):
        if isinstance(u, dict):
            # Direct 'username' key first
            val = u.get("username")
            if val:
                return str(val).strip()
            # Check possible nested 'baseline' structure
            baseline = u.get("baseline")
            if isinstance(baseline, dict):
                val = baseline.get("username") or baseline.get("user_name")
                if val:
                    return str(val).strip()
            # Fallback: nothing usable
            return ""
        # Primitive / string cases
        return str(u or "").strip()

    norm_username = _extract_username(user_name).lstrip("@")
    if not norm_username:
        norm_username = "!UNDEFINED!"

    # Only send if we have something (we still show !UNDEFINED! explicitly per requirement)
    # If username is undefined, skip sending this line (requested behavior change)
    if norm_username == "!UNDEFINED!":
        LOGGER.debug(
            "%s username undefined; skipping TECHNO_NAMES notification line", _id
        )
        return
    await safe_send_message(
        BOT,
        TECHNOLOG_GROUP_ID,
        f"<code>{_id}</code> @{norm_username} (1156)",
        LOGGER,
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
                reply_markup=inline_kb,
            )
            event_record = (
                event_record.replace("member", "kicked", 1).split(" by ")[0]
                + " by Хранитель Порядков\n"
            )
            await save_report_file("inout_", "cbk" + event_record)
        elif "manual check requested" in inout_logmessage:
            # XXX it was /check id command
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
                reply_markup=inline_kb,
            )
            _norm_username_990 = normalize_username(user_name)
            if _norm_username_990:
                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code> @{_norm_username_990} (990)",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )
            else:
                LOGGER.debug(
                    "%s username undefined; skipping 990 notification line", user_id
                )
            event_record = (
                event_record.replace("member", "kicked", 1).split(" by ")[0]
                + " by Хранитель Порядков\n"
            )
            await save_report_file("inout_", "cbm" + event_record)
        else:  # done by bot but not yet detected by lols_cas XXX
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
                reply_markup=inline_kb,
            )
            _norm_username = normalize_username(user_name)
            if _norm_username:
                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code> @{_norm_username} (1526)",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )
            else:
                LOGGER.debug(
                    "%s username undefined; skipping 1526 notification line", user_id
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

        # perform_checks(user_id, user_name)
        # TODO Add perform-checks coroutine!!!
        # TODO check again if it is marked as SPAMMER already

        # LOGGER.debug("inout_logmessage: %s", inout_logmessage)
        # LOGGER.debug("event_record: %s", event_record)
        # user is not spammer but kicked or restricted by admin
        # TODO log admin name getting it from inout_logmessage
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
            f"User is not now in the SPAM database\nbut kicked/restricted by Admin or other BOT.\n"
            + inout_logmessage,
            LOGGER,
            message_thread_id=ADMIN_MANBAN,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )
        if user_name and user_name != "!UNDEFINED!":
            _norm_username_1054 = normalize_username(user_name)
            if _norm_username_1054:
                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"<code>{user_id}</code> @{_norm_username_1054} (1054)",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=TECHNO_NAMES,
                )
            else:
                LOGGER.debug(
                    "%s username undefined; skipping 1054 notification line", user_id
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
        # Create keyboard with both LOLS check and Actions button
        inline_kb = InlineKeyboardMarkup()
        inline_kb.add(
            InlineKeyboardButton(
                "ℹ️ Check Spam Data ℹ️",
                url=f"https://t.me/oLolsBot?start={message.from_user.id}",
            )
        )
        # Add Actions button for manual review/unban
        report_id = (
            int(str(message.chat.id)[4:] + str(message.message_id))
            if message.chat.id < 0
            else int(str(message.chat.id) + str(message.message_id))
        )
        inline_kb.add(
            InlineKeyboardButton(
                "⚙️ Actions (Unban / Review) ⚙️",
                callback_data=f"suspiciousactions_{message.chat.id}_{report_id}_{message.from_user.id}",
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
        admin_autoban_banner = await safe_send_message(
            BOT,
            ADMIN_GROUP_ID,
            f"Alert! 🚨 User @{message.from_user.username if message.from_user.username else '!UNDEFINED!'}:(<code>{message.from_user.id}</code>) has been caught red-handed spamming in <a href='{chat_link}'>{chat_link_name}</a>! Telefragged in {time_passed}...",
            LOGGER,
            message_thread_id=ADMIN_AUTOBAN,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )

        # Store the autoban state for Actions button to work
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
            21605,  # 6 hr
            43205,  # 12 hr
            86405,  # 1 day
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
                "%s%s:%s %02dmin check lols_cas_spam: %s\033[0m IDs to check left: %s",
                color_code,
                user_id,
                format_username_for_log(user_name),
                sleep_time // 60,
                lols_spam,
                len(active_user_checks_dict),
            )

            # getting message to delete link if it is in the checks dict
            # XXX what if there is more than one message link?
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

                        try:
                            _member = await BOT.get_chat_member(_chat_id, user_id)
                            _user = getattr(_member, "user", None) or _member
                            cur_first = getattr(_user, "first_name", "") or ""
                            cur_last = getattr(_user, "last_name", "") or ""
                            cur_username = getattr(_user, "username", "") or ""
                        except Exception as _e:
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
                        except Exception as _e:
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
                        if cur_username != baseline.get("username", ""):
                            changed.append("username")
                        if baseline.get("photo_count", 0) == 0 and cur_photo_count > 0:
                            changed.append("profile photo")

                        if changed:
                            chat_username = _chat_info.get("username")
                            chat_title = _chat_info.get("title") or ""
                            universal_chatlink = (
                                f'<a href="https://t.me/{chat_username}">{html.escape(chat_title)}</a>'
                                if chat_username
                                else f"<a href=\"https://t.me/c/{str(_chat_id)[4:] if str(_chat_id).startswith('-100') else _chat_id}\">{html.escape(chat_title)}</a>"
                            )
                            _ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                            kb = make_lols_kb(user_id)
                            _report_id = int(datetime.now().timestamp())
                            _chat_id_for_gban = baseline.get("chat", {}).get("id")
                            # Consolidated actions menu (expands to Ban / Global Ban / Delete)
                            kb.add(
                                InlineKeyboardButton(
                                    "⚙️ Actions (Ban / Delete) ⚙️",
                                    callback_data=f"suspiciousactions_{_chat_id_for_gban}_{_report_id}_{user_id}",
                                )
                            )

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
                                    joined_dt = datetime.strptime(
                                        joined_at_raw, "%Y-%m-%d %H:%M:%S"
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
                                except Exception:
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
                                reply_markup=kb,
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
            # remove user from active checks dict as LEGIT / cleanup baseline
            try:
                del active_user_checks_dict[user_id]
            except Exception:
                active_user_checks_dict.pop(user_id, None)
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
        except Exception:
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
            except Exception as e:
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
                except BadRequest as e:
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
                except BadRequest as e:
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
            by_user = f"by {by_userfirstname} {by_userlastname} @{by_username} (<code>{update.from_user.id}</code>)\n"

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
            f"{escaped_inout_userfirstname} {escaped_inout_userlastname} "
            f"@{inout_username} (<code>{inout_userid}</code>)\n"
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

        inoout_thread = None # initialize
        # Add buttons for the user actions only if the user is not a spammer
        if lols_spam is not True:
            inline_kb.add(
                InlineKeyboardButton(
                    "🚫 Ban User", callback_data=f"banuser_{inout_userid}"
                )
            )
            inout_thread = TECHNO_IN
        else:
            inout_thread = TECHNO_OUT

        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP,
            inout_logmessage,
            LOGGER,
            message_thread_id=inout_thread,
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
                # Only capture baseline on join (is_member True) to compare later on leave
                if "is_member" in locals() and is_member:
                    try:
                        photos = await BOT.get_user_profile_photos(
                            inout_userid, limit=1
                        )
                        _photo_count = (
                            getattr(photos, "total_count", 0) if photos else 0
                        )
                    except Exception as _e:
                        _photo_count = 0
                        LOGGER.debug(
                            "%s:@%s unable to fetch initial photo count: %s",
                            inout_userid,
                            inout_username,
                            _e,
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
                    except Exception as _e:
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
                    if cur_username != _baseline.get("username", ""):
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
                        _link = (
                            f'<a href="https://t.me/{_cuser}">{html.escape(_ctitle)}</a>'
                            if _cuser
                            else f"<a href=\"https://t.me/c/{str(_cid)[4:] if str(_cid).startswith('-100') else _cid}\">{html.escape(_ctitle)}</a>"
                        )
                        _ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                        _kb = make_lols_kb(inout_userid)
                        _rid = int(datetime.now().timestamp())
                        # Consolidated actions button (expands to ban/global/delete options)
                        _kb.add(
                            InlineKeyboardButton(
                                "⚙️ Actions (Ban / Delete) ⚙️",
                                callback_data=f"suspiciousactions_{update.chat.id}_{_rid}_{inout_userid}",
                            )
                        )
                        # Elapsed time since join if available
                        joined_at_raw = _baseline.get("joined_at")
                        elapsed_line = ""
                        if joined_at_raw:
                            try:
                                _jdt = datetime.strptime(
                                    joined_at_raw, "%Y-%m-%d %H:%M:%S"
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
                            except Exception:
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
                            reply_markup=_kb,
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
                        "%s:@%s joined and left %s in 30 seconds or less",
                        inout_userid,
                        inout_username,
                        inout_chattitle,
                    )
                    # ban user from all chats
                    success_count, fail_count, total_count = (
                        await ban_user_from_all_chats(
                            inout_userid, inout_username, CHANNEL_IDS, CHANNEL_DICT
                        )
                    )
                    lols_url = build_lols_url(inout_userid)
                    inline_kb = InlineKeyboardMarkup().add(
                        InlineKeyboardButton("Check user profile", url=lols_url)
                    )
                    joinleft_timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                    await safe_send_message(
                        BOT,
                        ADMIN_GROUP_ID,
                        f"{escaped_inout_userfirstname} {escaped_inout_userlastname} @{inout_username} (<code>{inout_userid}</code>) joined and left {universal_chatlink} in 30 seconds or less. Telefragged at {joinleft_timestamp}...",
                        LOGGER,
                        message_thread_id=ADMIN_AUTOBAN,
                        parse_mode="HTML",
                        reply_markup=inline_kb,
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
                except Exception as _e:
                    LOGGER.debug(
                        "%s:@%s failed to remove baseline/watch entry on leave: %s",
                        inout_userid,
                        inout_username,
                        _e,
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
            reply_markup=inline_kb,
        )

        # Keyboard ban/cancel/confirm buttons
        keyboard = InlineKeyboardMarkup()
        # Consolidated actions button (expands to Ban / Global Ban / Delete on click)
        actions_btn = InlineKeyboardButton(
            "⚙️ Actions (Ban / Delete) ⚙️",
            callback_data=f"suspiciousactions_{message.chat.id}_{report_id}_{user_id}",
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

                # XXX return admin personal report banner message object
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

        except BadRequest as e:
            LOGGER.error("Error while sending the banner to the admin group: %s", e)
            await message.answer(
                "Error while sending the banner to the admin group. Please check the logs."
            )

    @DP.callback_query_handler(
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

        keyboard = InlineKeyboardMarkup(row_width=2)
        # MODIFIED: Pass spammer_user_id_str and report_id_to_ban_str, and rename callback prefixes
        confirm_btn = InlineKeyboardButton(
            "🟢 Confirm",
            callback_data=f"doban_{spammer_user_id_str}_{report_id_to_ban_str}",
        )
        cancel_btn = InlineKeyboardButton(
            "🔴 Cancel",
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
                reply_markup=keyboard,
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
                except Exception as _e:
                    LOGGER.debug(
                        "Editing related banners during confirmation failed: %s", _e
                    )

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

    @DP.callback_query_handler(
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
                success_count, fail_count, total_count = await ban_user_from_all_chats(
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
                    f"Ad-hoc ban executed by @{button_pressed_by}: User (<code>{author_id}</code>) banned across monitored chats.",
                    LOGGER,
                    parse_mode="HTML",
                    reply_markup=lols_check_kb,
                    message_thread_id=callback_query.message.message_thread_id,
                )
                return

            original_spam_message: types.Message = forwarded_report_state.get(
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

            # XXX fixed find safe solution to get the author_id from the forwarded_message_data
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
            user_name = forwarded_message_data[4] or "!UNDEFINED!"
            bot_info_message = (
                f"Attempting to delete all messages <b>({spam_messages_count})</b> from @{user_name} (<code>{author_id}</code>)\n"
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
                    message_link = construct_message_link(
                        [channel_id, message_id, None]
                    )
                    chat_link = f"https://t.me/c/{str(channel_id)[4:]}/"
                    bot_chatlink_message = (
                        f"Attempting to delete message <code>{message_id}</code>\n"
                        f"in chat <a href='{chat_link}'>{CHANNEL_DICT[channel_id]}</a> (<code>{channel_id}</code>)\n"
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
                        await safe_send_message(
                            BOT,
                            TECHNOLOG_GROUP_ID,
                            f"Bot is not an admin in chat {CHANNEL_DICT[channel_id]} ({channel_id}). Error: {inner_e}",
                            LOGGER,
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
                    await safe_send_message(
                        BOT,
                        TECHNOLOG_GROUP_ID,
                        f"Failed to ban and delete messages in chat {CHANNEL_DICT[channel_id]} ({channel_id}). Error: {inner_e}",
                        LOGGER,
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

            lols_check_kb = make_lols_kb(author_id)
            await safe_send_message(
                BOT,
                ADMIN_GROUP_ID,
                f"Report <code>{report_id_to_ban}</code> action taken by @{button_pressed_by}: User @{user_name} (<code>{author_id}</code>) banned and their messages deleted where applicable.\n{chan_ban_msg}",
                LOGGER,
                message_thread_id=callback_query.message.message_thread_id,
                parse_mode="HTML",
                reply_markup=lols_check_kb,
            )
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                f"Report <code>{report_id_to_ban}</code> action taken by @{button_pressed_by}: User @{user_name} (<code>{author_id}</code>) banned and their messages deleted where applicable.\n{chan_ban_msg}",
                LOGGER,
                parse_mode="HTML",
                reply_markup=lols_check_kb,
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

        except MessageCantBeDeleted as e:
            LOGGER.error("Error in handle_ban function: %s", e)
            await callback_query.message.reply(f"Error in handle_ban function: {e}")

        # report spam to the P2P spamcheck server
        await report_spam_2p2p(author_id, LOGGER)

        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP_ID,
            f"{author_id}:@{user_name} reported to P2P spamcheck server.",
            LOGGER,
            parse_mode="HTML",
            disable_web_page_preview=True,
            message_thread_id=TECHNO_ADMIN,
        )

    @DP.callback_query_handler(
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
            "\033[95m%s Report %s button ACTION CANCELLED by @%s !!! (User ID for LOLS: %s)\033[0m",
            admin_id,
            original_report_id_str,  # Log the original report identifier
            button_pressed_by,
            actual_user_id,
        )

        # FIXED BUG: Use actual_user_id for the LOLS bot link
        inline_kb = make_lols_kb(actual_user_id)
        await safe_send_message(
            BOT,
            ADMIN_GROUP_ID,
            f"Button ACTION CANCELLED by @{button_pressed_by}: Report WAS NOT PROCESSED!!! "
            f"Report them again if needed or use <code>/ban {original_report_id_str}</code> command.",
            LOGGER,
            message_thread_id=callback_query.message.message_thread_id,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )
        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP_ID,
            f"CANCEL button pressed by @{button_pressed_by}. "
            f"Button ACTION CANCELLED: Report WAS NOT PROCESSED. "
            f"Report them again if needed or use <code>/ban {original_report_id_str}</code> command.",
            LOGGER,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=inline_kb,
        )

    @DP.callback_query_handler(lambda c: c.data.startswith("banuser_"))
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
            display_name = f"{first_name} {last_name}".strip() or username
        except:
            username = "!UNDEFINED!"
            display_name = "Unknown User"

        keyboard = InlineKeyboardMarkup(row_width=2)
        confirm_btn = InlineKeyboardButton(
            "✅ Yes, Ban", callback_data=f"confirmbanuser_{user_id_str}"
        )
        cancel_btn = InlineKeyboardButton(
            "❌ No, Cancel", callback_data=f"cancelbanuser_{user_id_str}"
        )
        keyboard.add(confirm_btn, cancel_btn)

        # Edit the message to show confirmation
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=keyboard,
        )

        # Send confirmation message
        # await callback_query.answer(
        #     f"Confirm ban for {display_name} (@{username})?", show_alert=True
        # )

    @DP.callback_query_handler(lambda c: c.data.startswith("confirmbanuser_"))
    async def handle_user_inout_ban(callback_query: CallbackQuery):
        """Function to ban the user from all chats."""
        # Parse user_id from callback data
        parts = callback_query.data.split("_")
        user_id_str = parts[1]
        user_id = int(user_id_str)

        button_pressed_by = callback_query.from_user.username or "!UNDEFINED!"
        admin_id = callback_query.from_user.id

        # Create response message
        lols_check_and_banned_kb = make_lols_kb(user_id)
        api_url = f"https://api.lols.bot/account?id={user_id}"
        lols_check_and_banned_kb.add(
            InlineKeyboardButton("💀💀💀 B.A.N.N.E.D. 💀💀💀", url=api_url)
        )

        # Remove buttons
        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=lols_check_and_banned_kb,
        )

        try:
            # Get user info
            try:
                user_info = await BOT.get_chat(user_id)
                username = user_info.username or "!UNDEFINED!"
                first_name = user_info.first_name or ""
                last_name = user_info.last_name or ""
            except:
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
            success_count, fail_count, total_count = await ban_user_from_all_chats(
                user_id, username, CHANNEL_IDS, CHANNEL_DICT
            )

            # Add to banned users dict
            banned_users_dict[user_id] = username

            # Create event record
            event_record = (
                f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "
                f"{user_id:<10} "
                f"❌  @{username} {first_name} {last_name}            "
                f" member          --> kicked          in "
                f"ALL_CHATS                          by @{button_pressed_by}\n"
            )
            await save_report_file("inout_", "mbn" + event_record)

            # Report to spam servers
            await report_spam_2p2p(user_id, LOGGER)

            ban_message = (
                f"Manual ban completed by @{button_pressed_by}:\n"
                f"User @{username} ({first_name} {last_name}) <code>{user_id}</code> "
                f"banned from all monitored chats and reported to spam servers."
            )

            # Send to technolog group
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                ban_message,
                LOGGER,
                parse_mode="HTML",
                reply_markup=lols_check_and_banned_kb,
                message_thread_id=TECHNO_ADMIN,
            )

            # Send to admin group
            await safe_send_message(
                BOT,
                ADMIN_GROUP_ID,
                ban_message,
                LOGGER,
                parse_mode="HTML",
                reply_markup=lols_check_and_banned_kb,
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

        except Exception as e:
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

    @DP.callback_query_handler(lambda c: c.data.startswith("cancelbanuser_"))
    async def cancel_user_ban(callback_query: CallbackQuery):
        """Function to cancel the ban and restore original buttons."""
        # Parse user_id from callback data
        parts = callback_query.data.split("_")
        user_id_str = parts[1]
        user_id = int(user_id_str)

        # Restore original buttons
        lols_url = f"https://t.me/oLolsBot?start={user_id}"
        inline_kb = InlineKeyboardMarkup()
        inline_kb.add(InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_url))
        inline_kb.add(
            InlineKeyboardButton("🚫 Ban User", callback_data=f"banuser_{user_id_str}")
        )

        await BOT.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=inline_kb,
        )

        await callback_query.answer("Ban cancelled.", show_alert=False)

    @DP.callback_query_handler(lambda c: c.data.startswith("banchannelconfirm_"))
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
        confirm_kb = InlineKeyboardMarkup()
        confirm_kb.row(
            InlineKeyboardButton(
                "✅ Confirm Ban",
                callback_data=f"banchannelexecute_{channel_id}_{source_chat_id}",
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=f"banchannelcancel_{channel_id}_{source_chat_id}",
            ),
        )

        # Update message with confirmation buttons (no popup alert)
        try:
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=confirm_kb,
            )
        except (MessageNotModified, InvalidQueryID, BadRequest) as e:
            LOGGER.debug("Could not update buttons: %s", e)

    @DP.callback_query_handler(lambda c: c.data.startswith("banchannelexecute_"))
    async def ban_channel_execute(callback_query: CallbackQuery):
        """Function to execute the channel ban."""
        # Parse channel_id from callback data
        parts = callback_query.data.split("_")
        channel_id = int(parts[1])
        source_chat_id = int(parts[2])

        admin_username = callback_query.from_user.username or "!NoName!"
        admin_id = callback_query.from_user.id

        # Answer callback immediately to prevent timeout (no popup alert)
        try:
            await callback_query.answer()
        except Exception as answer_error:
            # Query might be too old, but continue with ban anyway
            LOGGER.debug("Could not answer callback query: %s", answer_error)

        try:
            # Ban channel from all monitored chats
            success, channel_name, channel_username = await ban_rogue_chat_everywhere(
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
                result_message = (
                    f"✅ Channel {channel_name} {channel_username} "
                    f"(<code>{channel_id}</code>) banned from all monitored chats "
                    f"by admin @{admin_username} (<code>{admin_id}</code>)"
                )
                LOGGER.info(
                    "Channel %s %s (%s) banned by admin @%s(%s)",
                    channel_name,
                    channel_username,
                    channel_id,
                    admin_username,
                    admin_id,
                )
            else:
                result_message = (
                    f"⚠️ Channel {channel_name} {channel_username} "
                    f"(<code>{channel_id}</code>) ban failed or partially completed. "
                    f"Check logs for details."
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

        except Exception as e:
            LOGGER.error("Failed to execute channel ban for %s: %s", channel_id, e)

    @DP.callback_query_handler(lambda c: c.data.startswith("banchannelcancel_"))
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
        channel_ban_kb = InlineKeyboardMarkup()
        channel_ban_kb.add(
            InlineKeyboardButton(
                "🚫 Ban Channel",
                callback_data=f"banchannelconfirm_{channel_id}_{source_chat_id}",
            )
        )

        try:
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=channel_ban_kb,
            )
        except (MessageNotModified, InvalidQueryID, BadRequest) as e:
            LOGGER.debug("Could not restore buttons: %s", e)

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

                # DELETE CHANNEL message immediately after forwarding
                try:
                    await BOT.delete_message(message.chat.id, message.message_id)
                    LOGGER.info(
                        "🔴 CHANNEL MESSAGE deleted: %s (%s) from chat %s - message forwarded to admins",
                        message.sender_chat.title or "Unknown",
                        message.sender_chat.id,
                        message.chat.title,
                    )
                except Exception as del_error:
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
                # Create keyboard with Ban Channel button
                channel_ban_kb = InlineKeyboardMarkup()
                channel_ban_kb.add(
                    InlineKeyboardButton(
                        "🚫 Ban Channel",
                        callback_data=f"banchannelconfirm_{message.sender_chat.id}_{message.chat.id}",
                    )
                )

                channel_info = f"<b>⚠️ CHANNEL MESSAGE DETECTED</b>\n\n"
                channel_info += (
                    f"<b>Channel:</b> {message.sender_chat.title or 'Unknown'}\n"
                )
                if message.sender_chat.username:
                    channel_info += (
                        f"<b>Username:</b> @{message.sender_chat.username}\n"
                    )
                channel_info += (
                    f"<b>Channel ID:</b> <code>{message.sender_chat.id}</code>\n"
                )
                channel_info += f"<b>Posted in:</b> {message.chat.title}\n"
                channel_info += f"<b>Status:</b> ❌ Deleted from chat"

                await safe_send_message(
                    BOT,
                    TECHNOLOG_GROUP_ID,
                    f"{channel_info}\n\nMessage link (deleted): <a href='{message_link}'>Click here</a>",
                    LOGGER,
                    parse_mode="HTML",
                    message_thread_id=TECHNO_ORIGINALS,
                    disable_notification=True,
                    reply_markup=channel_ban_kb,
                )
            except MessageIdInvalid as e:
                LOGGER.error(
                    "🔴 CHANNEL MESSAGE: Message ID %s is invalid or was deleted in chat %s (%s): %s",
                    message.message_id,
                    message.chat.title,
                    message.chat.id,
                    e,
                )
            except MessageToForwardNotFound as e:
                LOGGER.error("🔴 CHANNEL MESSAGE: Already deleted: %s", e)
            except MessageCantBeForwarded as e:
                LOGGER.error("🔴 CHANNEL MESSAGE: Can't be forwarded: %s", e)
            except BadRequest as e:
                LOGGER.error("🔴 CHANNEL MESSAGE: Processing error: %s", e)
                # return XXX do not stop processing
            try:
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
            except MessageToDeleteNotFound as e:
                LOGGER.error("🔴 CHANNEL MESSAGE: Already deleted! %s", e)

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
                    except Exception as _e:
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
                    if new_usern != old_usern:
                        changed.append("username")
                        diffs.append(
                            f"username: @{old_usern or '!UNDEFINED!'} -> @{new_usern or '!UNDEFINED!'}"
                        )
                    if old_pcnt == 0 and new_pcnt > 0:
                        changed.append("profile photo")
                        diffs.append("profile photo: none -> set")

                    if changed:
                        # Forward the triggering message
                        try:
                            await message.forward(
                                ADMIN_GROUP_ID,
                                ADMIN_SUSPICIOUS,
                                disable_notification=True,
                            )
                        except Exception as _e:
                            LOGGER.debug(
                                "%s:@%s forward to admin/suspicious failed: %s",
                                _uid,
                                new_usern or "!UNDEFINED!",
                                _e,
                            )

                        kb = make_lols_kb(_uid)
                        _report_id = int(datetime.now().timestamp())
                        kb.add(
                            InlineKeyboardButton(
                                "⚙️ Actions (Ban / Delete) ⚙️",
                                callback_data=f"suspiciousactions_{message.chat.id}_{_report_id}_{_uid}",
                            )
                        )

                        _ts = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                        chat_title_safe = html.escape(message.chat.title)
                        chat_link_html = (
                            f"<a href='https://t.me/{message.chat.username}'>{chat_title_safe}</a>"
                            if message.chat.username
                            else (
                                f"<a href='https://t.me/c/{str(message.chat.id)[4:]}'>{chat_title_safe}</a>"
                                if str(message.chat.id).startswith("-100")
                                else chat_title_safe
                            )
                        )

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
                                _jdt = datetime.strptime(
                                    joined_at_raw, "%Y-%m-%d %H:%M:%S"
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
                            except Exception:
                                elapsed_line = f"\nJoined at: {joined_at_raw}"

                        message_text = (
                            "Suspicious profile change detected while under watch.\n"
                            f"In chat: {chat_link_html}\n"
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
                            reply_markup=kb,
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
        except Exception as _e:
            LOGGER.debug("Immediate profile-change check failed: %s", _e)

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
                message_thread_id=ADMIN_AUTOBAN,
                disable_notification=True,
            )

            # report ids of sender_chat, forward_from and forward_from_chat as SPAM to p2p server
            await report_spam_from_message(message, LOGGER, TELEGRAM_CHANNEL_BOT_ID)
            LOGGER.warning(logger_text)

            # delete message immidiately
            await BOT.delete_message(message.chat.id, message.message_id)

            # Send info to ADMIN_AUTOBAN
            chat_title_safe = html.escape(message.chat.title)
            if message.chat.username:
                chat_link_html = f"<a href='https://t.me/{message.chat.username}'>{chat_title_safe} (@{message.chat.username})</a>"
            elif str(message.chat.id).startswith(
                "-100"
            ):  # For supergroups and channels
                chat_link_html = f"<a href='https://t.me/c/{str(message.chat.id)[4:]}'>{chat_title_safe}</a>"
            else:  # Fallback for other chat types (e.g., basic groups, though less common for this bot's scope)
                chat_link_html = f"{chat_title_safe}"  # Just the title, as direct links can be unreliable

            admin_notification_text = (
                f"Deleted message: <code>{message_link}</code>\n"
                f"{html.escape(message.from_user.first_name)}{f' {html.escape(message.from_user.last_name)}' if message.from_user.last_name else ''} "
                f"@{message.from_user.username if message.from_user.username else '!UNDEFINED!'} (<code>{message.from_user.id}</code>)\n"
                f"In chat: {chat_link_html} (<code>{message.chat.id}</code>)"
            )
            await safe_send_message(
                BOT,
                ADMIN_GROUP_ID,
                admin_notification_text,
                LOGGER,
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
                    escaped_chat_title_for_link = html.escape(
                        message.chat.title, quote=True
                    )
                    escaped_chat_title_for_display = html.escape(
                        message.chat.title
                    )  # Used when no link is formed

                    if message.chat.username:
                        banned_in_chat_link_html = f'<a href="https://t.me/{message.chat.username}">{escaped_chat_title_for_link}</a>'
                    elif str(message.chat.id).startswith("-100"):
                        chat_id_suffix = str(message.chat.id)[4:]
                        banned_in_chat_link_html = f'<a href="https://t.me/c/{chat_id_suffix}">{escaped_chat_title_for_link}</a>'
                    else:
                        banned_in_chat_link_html = escaped_chat_title_for_display
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
                success_count, fail_count, total_count = await ban_user_from_all_chats(
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
                    f"(<code>{message.from_id}</code>) sent message less then 1 hour after joining the chat and have "
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
                        # Build clickable chat link (public @username or internal /c/ link) with safe fallback
                        _chat_title_safe = html.escape(message.chat.title)
                        if message.chat.username:
                            _chat_link_html = f"<a href='https://t.me/{message.chat.username}'>{_chat_title_safe}</a>"
                        elif str(message.chat.id).startswith("-100"):
                            _chat_link_html = f"<a href='https://t.me/c/{str(message.chat.id)[4:]}'>{_chat_title_safe}</a>"
                        else:
                            _chat_link_html = (
                                f"<b>{_chat_title_safe}</b>"  # non-linkable
                            )

                        await safe_send_message(
                            BOT,
                            ADMIN_GROUP_ID,
                            f"WARNING! User @{message.from_user.username if message.from_user.username else 'UNDEFINED'} (<code>{message.from_user.id}</code>) sent a SUSPICIOUS message in {_chat_link_html} after {human_readable_time}. Please check it out!",
                            LOGGER,
                            message_thread_id=ADMIN_SUSPICIOUS,
                            reply_markup=inline_kb,
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
                "phones": [],
                "hashtags": [],
                "cashtags": [],
                "bot_commands": [],
                "emails": [],
            }

            # Helper function to extract text from entity
            def extract_entity_text(text, entity):
                """Extract text from message entity."""
                offset = entity.get("offset", 0)
                length = entity.get("length", 0)
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
                    entity_type = entity.get("type")
                    if entity_type in ["url", "text_link"]:
                        has_suspicious_content = True
                        # Extract URL from text_link or visible url
                        if entity_type == "text_link":
                            url = entity.get("url", "")
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
                    elif entity_type == "text_mention":
                        # Direct mention of user by ID (users without username)
                        has_suspicious_content = True
                        user = entity.get("user")
                        if user:
                            user_id = user.get("id")
                            user_name = user.get("username")
                            first_name = user.get("first_name", "")
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
                    entity_type = entity.get("type")
                    if entity_type in ["url", "text_link"]:
                        has_suspicious_content = True
                        # Extract URL from text_link or visible url
                        if entity_type == "text_link":
                            url = entity.get("url", "")
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
                        user = entity.get("user")
                        if user:
                            user_id = user.get("id")
                            user_name = user.get("username")
                            first_name = user.get("first_name", "")
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

            # If suspicious content detected, forward to ADMIN_SUSPICIOUS thread
            if has_suspicious_content:
                try:
                    # Forward the message to suspicious thread
                    await message.forward(
                        ADMIN_GROUP_ID,
                        ADMIN_SUSPICIOUS,
                        disable_notification=True,
                    )

                    # Build clickable chat link
                    _chat_title_safe = html.escape(message.chat.title)
                    if message.chat.username:
                        _chat_link_html = f"<a href='https://t.me/{message.chat.username}'>{_chat_title_safe}</a>"
                    elif str(message.chat.id).startswith("-100"):
                        _chat_link_html = f"<a href='https://t.me/c/{str(message.chat.id)[4:]}'>{_chat_title_safe}</a>"
                    else:
                        _chat_link_html = f"<b>{_chat_title_safe}</b>"

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
                                    button_text,
                                    url=mention_lols_link,
                                )
                            )

                    # Build detailed content list with length limiting
                    content_details = []
                    max_items_per_type = 10  # Limit items to prevent message overflow

                    if suspicious_items["links"]:
                        links_count = len(suspicious_items["links"])
                        content_details.append(f"<b>🔗 Links ({links_count}):</b>")
                        for i, link in enumerate(
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
                        for i, mention in enumerate(
                            suspicious_items["mentions"][:max_items_per_type]
                        ):
                            content_details.append(
                                f"  • <code>{html.escape(mention)}</code>"
                            )
                        if mentions_count > max_items_per_type:
                            content_details.append(
                                f"  ... and {mentions_count - max_items_per_type} more"
                            )

                    if suspicious_items["phones"]:
                        phones_count = len(suspicious_items["phones"])
                        content_details.append(
                            f"<b>📞 Phone Numbers ({phones_count}):</b>"
                        )
                        for i, phone in enumerate(
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
                        for i, hashtag in enumerate(
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
                        for i, cashtag in enumerate(
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
                        for i, bot_cmd in enumerate(
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
                        for i, email in enumerate(
                            suspicious_items["emails"][:max_items_per_type]
                        ):
                            content_details.append(
                                f"  • <code>{html.escape(email)}</code>"
                            )
                        if emails_count > max_items_per_type:
                            content_details.append(
                                f"  ... and {emails_count - max_items_per_type} more"
                            )

                    content_report = "\n".join(content_details)

                    # Build the full message
                    full_message = (
                        f"⚠️ <b>Suspicious Content Detected</b>\n"
                        f"From: @{message.from_user.username if message.from_user.username else 'UNDEFINED'} "
                        f"(<code>{message.from_user.id}</code>)\n"
                        f"Chat: {_chat_link_html}\n\n"
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
                            f"Chat: {_chat_link_html}\n\n"
                            f"{content_report}"
                        )

                    await safe_send_message(
                        BOT,
                        ADMIN_GROUP_ID,
                        full_message,
                        LOGGER,
                        message_thread_id=ADMIN_SUSPICIOUS,
                        reply_markup=inline_kb,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                except Exception as e:
                    LOGGER.error("Error forwarding suspicious content message: %s", e)

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
                except Exception as inner_e:
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
                except Exception as inner_e:
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
            lols_check_kb = InlineKeyboardMarkup().add(
                InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_url)
            )

            await message.reply(
                f"Action taken: User @{user_name} (<code>{author_id}</code>) banned and their messages deleted where applicable.",
                parse_mode="HTML",
                reply_markup=lols_check_kb,
            )

        except (sqlite3.Error, ValueError, TypeError) as e:
            LOGGER.error("Error in ban function: %s", e)
            await message.reply(f"Error: {e}")

        # report spammer to P2P spam checker server
        await report_spam_2p2p(author_id, LOGGER)
        user_name = (
            forwarded_message_data[4]
            if forwarded_message_data[4] not in [0, "0", None]
            else "!UNDEFINED!"
        )
        lols_check_kb = make_lols_kb(author_id)
        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP_ID,
            f"{author_id}:@{user_name} reported to P2P spamcheck server.",
            LOGGER,
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

            except ChatNotFound as e:
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
                except BadRequest as e:
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
        await log_lists(message.chat.id, message.message_thread_id)

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

            # Mark user as legit in database
            admin_id = message.from_user.id
            admin_username = message.from_user.username or "!NoAdminName!"
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
        except Exception as e:  # XXX too general exception!
            LOGGER.error("Error in unban_user: %s", e)
            await message.reply("An error occurred while trying to unban the user.")

    @DP.callback_query_handler(lambda c: c.data.startswith("stopchecks_"))
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
                f"Invalid callback data for stop_checks: {callback_query.data}, Error: {e}"
            )
            await callback_query.answer(
                "Invalid data format for stop_checks.", show_alert=True
            )
            return

        button_pressed_by = callback_query.from_user.username or "!NoAdminName!"
        admin_id = callback_query.from_user.id

        user_name_data = active_user_checks_dict.get(user_id_legit)
        user_name = "!UNDEFINED!"
        if isinstance(user_name_data, dict):
            user_name = str(user_name_data.get("username", "!UNDEFINED!")).lstrip("@")
        elif isinstance(user_name_data, str):
            user_name = (
                user_name_data.lstrip("@")
                if user_name_data != "None"
                else "!UNDEFINED!"
            )

        message_link = construct_message_link([orig_chat_id, orig_message_id, None])
        lols_link = f"https://t.me/oLolsBot?start={user_id_legit}"

        inline_kb = InlineKeyboardMarkup()
        inline_kb.add(
            InlineKeyboardButton("🔗 View Original Message 🔗", url=message_link)
        )
        inline_kb.add(InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_link))

        try:
            await BOT.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=inline_kb,
            )
        except Exception as e_edit:
            LOGGER.error(
                f"Error editing message markup in stop_checks for user {user_id_legit}: {e_edit}"
            )

        LOGGER.info(
            "\033[95m%s:@%s Identified as a legit user by admin %s:@%s!!! Future checks cancelled...\033[0m",
            user_id_legit,
            user_name,
            admin_id,
            button_pressed_by,
        )

        common_message_text = (
            f"Future checks for @{user_name} (<code>{user_id_legit}</code>) cancelled by Admin @{button_pressed_by}. "
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
        except Exception as e_send:
            LOGGER.error(
                f"Error sending notification messages in stop_checks for user {user_id_legit}: {e_send}"
            )

        if user_id_legit in active_user_checks_dict:
            del active_user_checks_dict[user_id_legit]
            task_cancelled = False
            for task in asyncio.all_tasks():
                if task.get_name() == str(user_id_legit):
                    task.cancel()
                    task_cancelled = True
                    LOGGER.info(
                        f"Watchdog task for user {user_id_legit} (@{user_name}) cancelled by admin {admin_id}."
                    )
                    break
            if not task_cancelled:
                LOGGER.warning(
                    f"Watchdog task for user {user_id_legit} (@{user_name}) not found for cancellation, though user was in active_user_checks_dict."
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
                f"{user_id_legit} (@{user_name}) Recorded/Updated legitimization status in DB, linked to original context {orig_chat_id}/{orig_message_id}."
            )
        except Exception as e_db:
            LOGGER.error(f"{user_id_legit}: {e_db} Error updating DB in stop_checks")

        await callback_query.answer(
            "Checks stopped. User marked as legit.", show_alert=False
        )

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
            await safe_send_message(
                BOT,
                ADMIN_USER_ID,
                _reply_message,
                LOGGER,
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
        await safe_send_message(
            BOT,
            original_message_chat_id,
            response_text,
            LOGGER,
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

        except Exception as e:
            LOGGER.error("Error in process_callback function: %s", e)

        # Acknowledge the callback query
        await callback_query.answer()

    @DP.callback_query_handler(
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
            message_link = construct_message_link([susp_chat_id, susp_message_id, None])
            lols_link = f"https://t.me/oLolsBot?start={susp_user_id}"
            collapsed_kb = InlineKeyboardMarkup()
            collapsed_kb.add(
                InlineKeyboardButton("🔗 View Original Message 🔗", url=message_link)
            )
            collapsed_kb.add(InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_link))
            collapsed_kb.add(
                InlineKeyboardButton(
                    "⚙️ Actions (Ban / Delete) ⚙️",
                    callback_data=f"suspiciousactions_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                )
            )
            try:
                await BOT.edit_message_reply_markup(
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.message_id,
                    reply_markup=collapsed_kb,
                )
            except Exception as e:  # noqa
                LOGGER.debug("Failed to collapse suspicious actions menu: %s", e)
            await callback_query.answer("Menu closed.")
            return

        # If the consolidated actions button was pressed, expand available actions and return
        if action_prefix == "suspiciousactions":
            susp_user_id = int(susp_user_id_str)
            susp_message_id = int(susp_message_id_str)
            susp_chat_id = int(susp_chat_id_str)
            message_link = construct_message_link([susp_chat_id, susp_message_id, None])
            lols_link = f"https://t.me/oLolsBot?start={susp_user_id}"
            expand_kb = InlineKeyboardMarkup()
            expand_kb.add(
                InlineKeyboardButton("🔗 View Original Message 🔗", url=message_link)
            )
            expand_kb.add(InlineKeyboardButton("ℹ️ Check Spam Data ℹ️", url=lols_link))
            expand_kb.add(
                InlineKeyboardButton(
                    "🌐 Global Ban",
                    callback_data=f"suspiciousglobalban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
                InlineKeyboardButton(
                    "🚫 Ban User",
                    callback_data=f"suspiciousban_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                ),
            )
            expand_kb.add(
                InlineKeyboardButton(
                    "🗑 Delete Msg",
                    callback_data=f"suspiciousdelmsg_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                )
            )
            # Global cancel button to revert view
            expand_kb.add(
                InlineKeyboardButton(
                    "🔙 Cancel / Close",
                    callback_data=f"suspiciouscancel_{susp_chat_id}_{susp_message_id}_{susp_user_id}",
                )
            )
            try:
                await BOT.edit_message_reply_markup(
                    chat_id=callback_query.message.chat.id,
                    message_id=callback_query.message.message_id,
                    reply_markup=expand_kb,
                )
            except Exception as e:  # noqa
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
            LOGGER.error(f"Unknown prefix in handle_suspicious_sender: {action_prefix}")
            await callback_query.answer(
                "Internal error processing action.", show_alert=True
            )
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
                        except Exception as _e_del:
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
                                        except Exception as _e_del2:
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
                    except Exception as _e_active_extra:
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
                except Exception as _e_bulk:
                    LOGGER.error(
                        "Error bulk-deleting messages for global ban user %s:@%s: %s",
                        susp_user_id,
                        susp_user_name,
                        _e_bulk,
                    )
                # Ban user from all monitored chats
                success_count, fail_count, total_count = await ban_user_from_all_chats(
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
            except BadRequest as e:
                LOGGER.error("Suspicious user not found: %s", e)
                callback_answer = "User not found in chat."
            # report spammer to the P2P spam check server
            await report_spam_2p2p(susp_user_id, LOGGER)
            await safe_send_message(
                BOT,
                TECHNOLOG_GROUP_ID,
                f"{susp_user_id}:@{susp_user_name} reported to P2P spamcheck server.",
                LOGGER,
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
                if len(str(susp_message_id)) < 13 and susp_message_id < 4_000_000_000:
                    await BOT.delete_message(susp_chat_id, susp_message_id)
                else:
                    LOGGER.debug(
                        "Skip delete_message for synthetic suspicious message_id=%s chat_id=%s",
                        susp_message_id,
                        susp_chat_id,
                    )
                # Delete all messages from this user in THIS chat only
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
                        except Exception as _e_del:
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
                                        except Exception as _e_del2:
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
                    except Exception as _e_active_local:
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
                except Exception as _e_bulk:
                    LOGGER.error(
                        "Error deleting messages for local ban user %s:@%s in chat %s: %s",
                        susp_user_id,
                        susp_user_name,
                        susp_chat_id,
                        _e_bulk,
                    )
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
            except BadRequest as e:
                LOGGER.error("Suspicious user not found: %s", e)
                callback_answer = "User not found in chat."
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
            f"Suspicious user @{susp_user_name} (<code>{susp_user_id}</code>) "
            f"Message origin: <a href='{message_link}'>{message_link}</a>\n"
            f"Action done by Admin @{admin_username}"
        )

        await safe_send_message(
            BOT,
            callback_query.message.chat.id,
            bot_reply_action_message,
            LOGGER,
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
