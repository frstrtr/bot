from datetime import datetime
import sqlite3
import xml.etree.ElementTree as ET
import logging
import json
import subprocess
import time
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# from aiogram.types import Message
from aiogram.utils.exceptions import (
    MessageToDeleteNotFound,
    # MessageCantBeDeleted,
    RetryAfter,
)

# define automated spam detection message.entities type triggers
SPAM_TRIGGERS = (
    "url",
    "email",
    "phone_number",
    "hashtag",
    "mention",
    "text_link",
    "mention_name",
    "cashtag",
    "bot_command",
)

MAX_TELEGRAM_MESSAGE_LENGTH = 4096

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

# If adding new column for the first time, uncomment below
# cursor.execute("ALTER TABLE recent_messages ADD COLUMN new_chat_member BOOL")
# conn.commit()
# cursor.execute("ALTER TABLE recent_messages ADD COLUMN left_chat_member BOOL")
# conn.commit()


# Custom filter function to exclude specific content types and groups for the message handler
def custom_filter(message: types.Message):
    """Function to filter messages based on the chat ID and content type."""
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

    logger.debug(
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

    logger.debug(
        "Result for sender: %s : %s %s, date: %s, from chat title: %s\nResult: %s",
        spammer_id,
        spammer_first_name,
        spammer_last_name,
        message_forward_date,
        forward_from_chat_title,
        result,
    )

    return result


# logging.basicConfig(level=logging.DEBUG) # To debug the bot itself (e.g., to see the messages it receives)
logger = logging.getLogger(
    __name__
)  # To debug the script (e.g., to see if the XML is loaded correctly)
logger.setLevel(
    logging.DEBUG
)  # To debug the script (e.g., to see if the XML is loaded correctly)

# Create handlers
file_handler = logging.FileHandler("bancop_bot.log")  # For writing logs to a file
stream_handler = logging.StreamHandler()  # For writing logs to the console

# Create formatters and add them to handlers
FROMAT_STR = "%(message)s"  # Excludes timestamp, logger's name, and log level
formatter = logging.Formatter(FROMAT_STR)
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

# Add handlers to the logger
logger.addHandler(file_handler)
logger.addHandler(stream_handler)


# Load the XML
config_XML = ET.parse("config.xml")
config_XML_root = config_XML.getroot()

channels_XML = ET.parse("groups.xml")
channels_root = channels_XML.getroot()

# Extract group IDs from XML
CHANNEL_IDS = [int(group.find("id").text) for group in channels_root.findall("group")]

# Extract group names from XML
CHANNEL_NAMES = [group.find("name").text for group in channels_root.findall("group")]

# add channels to dict for logging
channels_dict = {}
# scheduler_dict = {} TODO: Implement scheduler to manage chat closure at night for example

for group in channels_root.findall("group"):
    channel_id = int(group.find("id").text)
    channel_name = group.find("name").text
    channels_dict[channel_id] = channel_name

#     # Attempt to extract the schedule, if present
#     schedule = group.find('schedule')
#     if schedule is not None and schedule.get('trigger') == "1":
#         start_time = schedule.find('start').text
#         end_time = schedule.find('end').text
#         scheduler_dict[channel_id] = {'start': start_time, 'end': end_time}


# Get config data
bot_token = config_XML_root.find("bot_token").text
bot_name = config_XML_root.find("bot_name").text
log_group = config_XML_root.find("log_group").text
log_group_name = config_XML_root.find("log_group_name").text
techno_log_group = config_XML_root.find("techno_log_group").text
techno_log_group_name = config_XML_root.find("techno_log_group_name").text

API_TOKEN = bot_token
ADMIN_GROUP_ID = int(log_group)  # Ensure this is an integer
TECHNOLOG_GROUP_ID = int(techno_log_group)  # Ensure this is an integer

# TODO: move to XML credentials files
TECHNO_LOGGING = 1  #           LOGGING
TECHNO_ORIGINALS = 21541  #     ORIGINALS
TECHNO_UNHANDLED = 21525  #     UNHANDLED
TECHNO_RESTART = 21596  #       RESTART
TECHNO_INOUT = 27448  #          INOUT

# TODO: move to XML credentials files
ALLOWED_FORWARD_CHANNELS = (
    {"id": -1001843786479, "name": "whales_mauritius"},
    {"id": -1001359927097, "name": "elena_mauritius"},
    {"id": -1001900619969, "name": "mavrikikit"},
)

ALLOWED_FORWARD_CHANNEL_IDS = {d["id"] for d in ALLOWED_FORWARD_CHANNELS}


print("Using bot: " + bot_name)
print("Using log group: " + log_group_name + ", id:" + log_group)
print("Using techno log group: " + techno_log_group_name + ", id: " + techno_log_group)
channel_info = [f"{name}({id_})" for name, id_ in zip(CHANNEL_NAMES, CHANNEL_IDS)]
print("Monitoring chats: " + ", ".join(channel_info))
print("\n")
print(
    "Excluding autoreport when forwarded from chats: @"
    + " @".join([d["name"] for d in ALLOWED_FORWARD_CHANNELS])
)
print("\n")


bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)


# Uncomment this to get the chat ID of a group or channel
# @dp.message_handler(commands=["getid"])
# async def cmd_getid(message: types.Message):
#     await message.answer(f"This chat's ID is: {message.chat.id}")


async def take_heuristic_action(message: types.Message, reason):
    """Function to take heuristically invoked action on the message."""

    logger.warning(
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


async def on_startup(dp: Dispatcher):
    """Function to handle the bot startup."""
    bot_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _commit_info = get_latest_commit_info()
    bot_start_message = (
        f"\nBot restarted at {bot_start_time}\n{'-' * 40}\n"
        f"Commit info: {_commit_info}\n"
        "Финальная битва между людьми и роботами...\n"
    )
    logger.info(bot_start_message)

    # TODO Leave chats which is not in settings file
    # await bot.leave_chat(-1002174154456)
    # await bot.leave_chat(-1001876523135) # @lalaland_classy

    # start message to the Technolog group
    await bot.send_message(
        TECHNOLOG_GROUP_ID, bot_start_message, message_thread_id=TECHNO_RESTART
    )


async def is_admin(reporter_user_id: int, admin_group_id_check: int) -> bool:
    """Function to check if the reporter is an admin in the Admin group."""
    chat_admins = await bot.get_chat_administrators(admin_group_id_check)
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
    logger.debug("############################################################")
    logger.debug("                                                            ")
    logger.debug("------------------------------------------------------------")
    logger.debug(f"Received forwarded message for the investigation: {message}")
    # Send a thank you note to the user we dont need it for the automated reports anymore
    # await message.answer("Thank you for the report. We will investigate it.")
    # Forward the message to the admin group
    technnolog_spamMessage_copy = await bot.forward_message(
        TECHNOLOG_GROUP_ID, message.chat.id, message.message_id
    )
    message_as_json = json.dumps(message.to_python(), indent=4, ensure_ascii=False)
    # Truncate and add an indicator that the message has been truncated
    if len(message_as_json) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
        message_as_json = message_as_json[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
    await bot.send_message(TECHNOLOG_GROUP_ID, message_as_json)
    await bot.send_message(TECHNOLOG_GROUP_ID, "Please investigate this message.")

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
            logger.debug(
                "The requested data associated with the Deleted Account has been retrieved. Please verify the accuracy of this information, as it cannot be guaranteed due to the account's deletion."
            )
            await message.answer(
                "The requested data associated with the Deleted Account has been retrieved. Please verify the accuracy of this information, as it cannot be guaranteed due to the account's deletion."
            )
        else:
            e = "Renamed Account or wrong chat?"
            logger.debug(
                "Could not retrieve the author's user ID. Please ensure you're reporting recent messages. %s",
                e,
            )
            await message.answer(
                f"Could not retrieve the author's user ID. Please ensure you're reporting recent messages. {e}"
            )

    if not found_message_data:  # Last resort. Give up.
        return

    logger.debug("Message data: %s", found_message_data)
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
    if found_message_data[2]:  # this is public chat
        message_link = f"https://t.me/{found_message_data[2]}/{found_message_data[1]}"
    else:  # this is private chat
        # Construct the message link with the modified chat ID
        message_link = f"https://t.me/c/{chat_id}/{found_message_data[1]}"

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
        username = "!_U_N_D_E_F_I_N_E_D_!"

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
    logger.debug("Report banner content:")
    logger.debug(log_info)

    admin_ban_banner = (
        f"💡 Reaction time: {message_report_date - message.date}\n"
        f"💔 Reported by automated spam detection system\n"
        f"💔 {reason}\n"
        f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
        f"ℹ️ <a href='{technnolog_spamMessage_copy_link}'>Technolog copy</a>\n"
        f"❌ <b>Use /ban {report_id}</b> to take action.\n"
    )

    # Send the banner to the technolog group
    await bot.send_message(TECHNOLOG_GROUP_ID, log_info, parse_mode="HTML")

    # Keyboard ban/cancel/confirm buttons
    keyboard = InlineKeyboardMarkup()
    ban_btn = InlineKeyboardButton("Ban", callback_data=f"confirm_ban_{report_id}")
    keyboard.add(ban_btn)

    # Show ban banner with buttons in the admin group to confirm or cancel the ban
    admin_group_banner_message = await bot.send_message(
        ADMIN_GROUP_ID, admin_ban_banner, reply_markup=keyboard, parse_mode="HTML"
    )

    # Construct link to the published banner and send it to the reporter
    private_chat_id = int(
        str(admin_group_banner_message.chat.id)[4:]
    )  # Remove -100 from the chat ID
    banner_link = (
        f"https://t.me/c/{private_chat_id}/{admin_group_banner_message.message_id}"
    )

    # Check if the reporter is an admin in the admin group:
    if await is_admin(message.from_user.id, ADMIN_GROUP_ID):
        # Send the banner link to the reporter
        await message.answer(f"Admin group banner link: {banner_link}")


@dp.message_handler(
    lambda message: message.forward_date is not None
    and message.chat.id not in CHANNEL_IDS
    and message.chat.id != ADMIN_GROUP_ID
    and message.chat.id != TECHNOLOG_GROUP_ID,
    content_types=types.ContentTypes.ANY,
)
async def handle_forwarded_reports(message: types.Message):
    """Function to handle forwarded messages."""
    logger.debug("############################################################")
    logger.debug("                                                            ")
    logger.debug("------------------------------------------------------------")
    logger.debug(f"Received forwarded message for the investigation: {message}")
    # Send a thank you note to the user
    await message.answer("Thank you for the report. We will investigate it.")
    # Forward the message to the admin group
    technnolog_spamMessage_copy = await bot.forward_message(
        TECHNOLOG_GROUP_ID, message.chat.id, message.message_id
    )
    message_as_json = json.dumps(message.to_python(), indent=4, ensure_ascii=False)
    # Truncate and add an indicator that the message has been truncated
    if len(message_as_json) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
        message_as_json = message_as_json[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
    await bot.send_message(TECHNOLOG_GROUP_ID, message_as_json)
    await bot.send_message(TECHNOLOG_GROUP_ID, "Please investigate this message.")

    # Get the username, first name, and last name of the user who forwarded the message and handle the cases where they're not available
    spammer_id, spammer_first_name, spammer_last_name = extract_spammer_info(message)
    forward_from_chat_title = (
        message.forward_from_chat.title if message.forward_from_chat else None
    )

    forward_from_username = (
        getattr(message.forward_from, "username", None)
        if message.forward_from
        else None
    )

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
            logger.debug(
                f"The requested data associated with the Deleted Account has been retrieved. Please verify the accuracy of this information, as it cannot be guaranteed due to the account's deletion."
            )
            await message.answer(
                f"The requested data associated with the Deleted Account has been retrieved. Please verify the accuracy of this information, as it cannot be guaranteed due to the account's deletion."
            )
        else:
            e = "Renamed Account or wrong chat?"
            logger.debug(
                f"Could not retrieve the author's user ID. Please ensure you're reporting recent messages. {e}"
            )
            await message.answer(
                f"Could not retrieve the author's user ID. Please ensure you're reporting recent messages. {e}"
            )

    if not found_message_data:  # Last resort. Give up.
        return
        # pass

    logger.debug(f"Message data: {found_message_data}")

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
        username = "!_U_N_D_E_F_I_N_E_D_!"

    # Initialize user_id and user_link with default values
    user_id = found_message_data[3]
    # user_id=5338846489

    # print('##########----------DEBUG----------##########')
    technolog_chat_id = int(
        str(technnolog_spamMessage_copy.chat.id)[4:]
    )  # Remove -100 from the chat ID
    technnolog_spamMessage_copy_link = (
        f"https://t.me/c/{technolog_chat_id}/{technnolog_spamMessage_copy.message_id}"
    )
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
        f"ℹ️ <a href='{technnolog_spamMessage_copy_link}'>Technolog copy</a>\n"
        f"ℹ️ <a href='https://t.me/lolsbotcatcherbot?start={user_id}'>Profile spam check (@lolsbotcatcherbot)</a>\n"
        f"❌ <b>Use /ban {report_id}</b> to take action.\n"
    )
    logger.debug("Report banner content:")
    logger.debug(log_info)

    admin_ban_banner = (
        f"💡 Reaction time: {message.date - message.forward_date}\n"
        f"💔 Reported by admin <a href='tg://user?id={message.from_user.id}'></a>"
        f"@{message.from_user.username or '!_U_N_D_E_F_I_N_E_D_!'}\n"
        f"ℹ️ <a href='{message_link}'>Link to the reported message</a>\n"
        f"ℹ️ <a href='{technnolog_spamMessage_copy_link}'>Technolog copy</a>\n"
        f"❌ <b>Use /ban {report_id}</b> to take action.\n"
    )

    # Send the banner to the technolog group
    await bot.send_message(TECHNOLOG_GROUP_ID, log_info, parse_mode="HTML")

    # Keyboard ban/cancel/confirm buttons
    keyboard = InlineKeyboardMarkup()
    ban_btn = InlineKeyboardButton("Ban", callback_data=f"confirm_ban_{report_id}")
    keyboard.add(ban_btn)

    # Show ban banner with buttons in the admin group to confirm or cancel the ban
    # And store published bunner message data to provide link to the reportee
    # admin_group_banner_message: Message = None # Type hinting
    admin_group_banner_message = await bot.send_message(
        ADMIN_GROUP_ID, admin_ban_banner, reply_markup=keyboard, parse_mode="HTML"
    )
    # await bot.send_message(
    #     ADMIN_GROUP_ID, log_info, reply_markup=keyboard, parse_mode="HTML"
    # )

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


@dp.callback_query_handler(lambda c: c.data.startswith("confirm_ban_"))
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

    await bot.edit_message_reply_markup(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard,
    )


@dp.callback_query_handler(lambda c: c.data.startswith("do_ban_"))
async def handle_ban(callback_query: CallbackQuery):
    """Function to ban the user and delete all known to bot messages."""

    # remove buttons from the admin group first
    await bot.edit_message_reply_markup(
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
            await callback_query.message.reply("Error: Report not found in database.")
            return

        (
            original_chat_id,
            report_id,
            forwarded_message_data,
            original_message_timestamp,
        ) = result

        logger.debug(
            f"Original chat ID: {original_chat_id}, Original message ID: {report_id}, Forwarded message data: {forwarded_message_data}, Original message timestamp: {original_message_timestamp}"
        )

        author_id = eval(forwarded_message_data)[3]
        logger.debug(f"Author ID retrieved for original message: {author_id}")
        await bot.send_message(
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
            logger.debug(
                f"Attempting to ban user {author_id} from chat {channels_dict[chat_id]} ({chat_id})"
            )

            try:
                await bot.ban_chat_member(
                    chat_id=chat_id,
                    user_id=author_id,
                    until_date=None,
                    revoke_messages=True,
                )
                logger.debug(
                    f"User {author_id} banned and their messages deleted from chat {channels_dict[chat_id]} ({chat_id})."
                )
            except Exception as inner_e:
                logger.error(
                    f"Failed to ban and delete messages in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}"
                )
                await bot.send_message(
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
                    await bot.delete_message(chat_id=chat_id, message_id=message_id)
                    logger.debug(
                        f"Message {message_id} deleted from chat {channels_dict[chat_id]} ({chat_id}) for user @{user_name} ({author_id})."
                    )
                    break  # break the loop if the message was deleted successfully
                except RetryAfter as e:
                    wait_time = e.timeout  # This gives you the time to wait in seconds
                    if (
                        attempt < retry_attempts - 1
                    ):  # Don't wait after the last attempt
                        logger.warning(
                            f"Rate limited. Waiting for {wait_time} seconds."
                        )
                        time.sleep(wait_time)
                except MessageToDeleteNotFound:
                    logger.warning(
                        f"Message {message_id} in chat {channels_dict[chat_id]} ({chat_id}) not found for deletion."
                    )
                    break  # No need to retry in this case
                # TODO manage the case when the bot is not an admin in the channel
                except Exception as inner_e:
                    logger.error(
                        f"Failed to delete message {message_id} in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}"
                    )
                    await bot.send_message(
                        TECHNOLOG_GROUP_ID,
                        f"Failed to delete message {message_id} in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}",
                    )
        logger.debug(
            f"User {author_id} banned and their messages deleted where applicable."
        )
        button_pressed_by = callback_query.from_user.username

        await bot.send_message(
            ADMIN_GROUP_ID,
            f"Report {message_id_to_ban} action taken by @{button_pressed_by}: User {author_id} banned and their messages deleted where applicable.",
        )
        await bot.send_message(
            TECHNOLOG_GROUP_ID,
            f"Report {message_id_to_ban} action taken by @{button_pressed_by}: User {author_id} banned and their messages deleted where applicable.",
        )

    except Exception as e:
        logger.error(f"Error in handle_ban function: {e}")
        await callback_query.message.reply(f"Error: {e}")


@dp.callback_query_handler(lambda c: c.data.startswith("reset_ban_"))
async def reset_ban(callback_query: CallbackQuery):
    """Function to reset the ban button."""
    *_, report_id_to_ban = callback_query.data.split("_")

    # remove buttons from the admin group
    await bot.edit_message_reply_markup(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
    )

    # DEBUG:
    button_pressed_by = callback_query.from_user.username
    # logger.debug("Button pressed by the admin: @%s", button_pressed_by)

    logger.info("Report %s button ACTION CANCELLED!!!", report_id_to_ban)

    await bot.send_message(
        ADMIN_GROUP_ID,
        f"Button ACTION CANCELLED by @{button_pressed_by}: Report {report_id_to_ban} WAS NOT PROCESSED!!! "
        f"Report them again if needed or use /ban {report_id_to_ban} command.",
    )
    await bot.send_message(
        TECHNOLOG_GROUP_ID,
        f"CANCEL button pressed by @{button_pressed_by}. "
        f"Button ACTION CANCELLED: Report {report_id_to_ban} WAS NOT PROCESSED. "
        f"Report them again if needed or use /ban {report_id_to_ban} command.",
    )


# check for users joining/leaving the chat
@dp.message_handler(
    content_types=[
        types.ContentType.NEW_CHAT_MEMBERS,
        types.ContentType.LEFT_CHAT_MEMBER,
    ]
)


# Check for spam indicator: 5 or more entities of type 'custom_emoji'
def has_custom_emoji_spam(message):
    """Function to check if a message contains spammy custom emojis."""
    message_dict = message.to_python()
    entities = message_dict.get("entities", [])
    custom_emoji_count = sum(
        1 for entity in entities if entity.get("type") == "custom_emoji"
    )
    return custom_emoji_count >= 5


async def user_joined_chat(message: types.Message):
    """Function to handle users joining or leaving the chat."""
    # print("Users changed", message.new_chat_members, message.left_chat_member)

    # TODO add logic to store join/left events in the database

    # Send user join/left details to the technolog group
    inout_userid = message.from_id
    inout_userfirstname = message.from_user.first_name
    inout_userlastname = message.from_user.last_name or ""  # optional
    inout_username = message.from_user.username or "!UNDEFINED!"  # optional
    inout_chatid = str(message.chat.id)[4:]
    inout_action = "JOINED" if message.new_chat_members else "LEFT"
    inout_chatname = message.chat.title
    inout_logmessage = (
        f"💡 <a href='tg://resolve?domain={inout_username}'>@{inout_username}</a> : "
        f"{inout_userfirstname} {inout_userlastname} {inout_action}\n"
        f"💡 <a href='https://t.me/c/{inout_chatid}'>{inout_chatname}</a>\n"  # https://t.me/c/1902317320/27448/27778
        f"💡 USER ID profile links:\n"
        f"   ├ℹ️ <a href='tg://user?id={inout_userid}'>USER ID based profile link</a>\n"
        f"   ├ℹ️ Plain text: tg://user?id={inout_userid}\n"
        f"   ├ℹ️ <a href='tg://openmessage?user_id={inout_userid}'>Android</a>\n"
        f"   └ℹ️ <a href='https://t.me/@id{inout_userid}'>IOS (Apple)</a>\n"
    )

    await bot.send_message(
        TECHNOLOG_GROUP_ID,
        inout_logmessage,
        parse_mode="HTML",
        message_thread_id=TECHNO_INOUT,
    )


@dp.message_handler(custom_filter, content_types=types.ContentTypes.ANY)
async def store_recent_messages(message: types.Message):
    """Function to store recent messages in the database."""
    try:
        # Log the full message object for debugging
        # Convert the Message object to a dictionary
        message_dict = message.to_python()
        formatted_message = json.dumps(
            message_dict, indent=4, ensure_ascii=False
        )  # Convert back to a JSON string with indentation and human-readable characters
        # logger.debug(
        #     "\nReceived message object:\n %s\n",
        #     formatted_message,
        # )
        await bot.send_message(
            TECHNOLOG_GROUP_ID, formatted_message, message_thread_id=TECHNO_ORIGINALS
        )

        # logger.debug(
        #     # f"Bot?: {message.from_user.is_bot}\n"
        #     # f"First Name?: {message.from_user.first_name}\n"
        #     # f"Username?: {message.from_user.username}\n"
        #     # f"Author signature?: {message.author_signature}\n"
        #     f"Forwarded from chat type?: {message.forward_from_chat.type=='channel'}\n"
        # )
        # TODO remove afer sandboxing

        # TODO move to the join/left event handler
        new_chat_member = len(message.new_chat_members) > 0
        left_chat_member = bool(getattr(message.left_chat_member, "id", False))

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
                new_chat_member,
                left_chat_member,
            ),
        )
        conn.commit()
        # logger.info(f"Stored recent message: {message}")

        # if new_chat_member or left_chat_member:
        #     # Send user join/left details to the technolog group
        #     inout_userid = message.from_id
        #     inout_userfirstname = message.from_user.first_name
        #     inout_userlastname = message.from_user.last_name or ""  # optional
        #     inout_username = message.from_user.username or "!UNDEFINED!"  # optional
        #     inout_chatid = str(message.chat.id)[4:]
        #     inout_action = "JOINED" if new_chat_member else "LEFT"
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

        #     await bot.send_message(
        #         TECHNOLOG_GROUP_ID,
        #         inout_logmessage,
        #         parse_mode="HTML",
        #         message_thread_id=TECHNO_INOUT,
        #     )

        # HEURISTICS
        # Join date and first message with links or forwards from somewhere
        # Join date and immediate message after joining
        # Keywords or sentences
        # Number of messages in a short period of time
        # Number of forwards in a short period of time
        # User reactions for the message

        # check if the message is a spam by checking the entities
        entity_spam_trigger = None
        for entity in message.entities:
            if entity["type"] in SPAM_TRIGGERS:
                # spam detected
                entity_spam_trigger = entity["type"]

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
        user_is_1hr_old = (message.date - user_join_chat_date).total_seconds() < 3600
        user_is_10sec_old = (message.date - user_join_chat_date).total_seconds() < 10
        # print("User is old: ", user_is_old)
        # print("User is 1hr old: ", user_is_1hr_old)
        # print("User is 10sec old: ", user_is_10sec_old)

        if not user_is_old and not (new_chat_member or left_chat_member):
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
            the_reason = "Message contains more than 5 spammy custom emojis"
            await take_heuristic_action(message, the_reason)

    # TODO Error storing recent message: 'NoneType' object has no attribute 'type' if it is a system message like group join or leave
    except Exception as e:
        logger.error(f"Error storing recent message: {e}")


# TODO: Remove this if the buttons works fine
@dp.message_handler(commands=["ban"], chat_id=ADMIN_GROUP_ID)
async def ban(message: types.Message):
    """Function to ban the user and delete all known to bot messages using '/ban reportID' text command."""
    try:
        # logger.debug("ban triggered.")

        command_args = message.text.split()
        logger.debug(f"Command arguments received: {command_args}")

        if len(command_args) < 2:
            raise ValueError("Please provide the message ID of the report.")

        report_msg_id = int(command_args[1])
        logger.debug(f"Report message ID parsed: {report_msg_id}")

        cursor.execute(
            "SELECT chat_id, message_id, forwarded_message_data, received_date FROM recent_messages WHERE message_id = ?",
            (report_msg_id,),
        )
        result = cursor.fetchone()
        logger.debug(
            f"Database query result for forwarded_message_data {report_msg_id}: {result}"
        )
        await bot.send_message(
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
        logger.debug(
            f"Original chat ID: {original_chat_id}, Original message ID: {original_message_id}, Forwarded message data: {forwarded_message_data}, Original message timestamp: {original_message_timestamp}"
        )

        author_id = eval(forwarded_message_data)[3]
        logger.debug(f"Author ID retrieved for original message: {author_id}")
        await bot.send_message(
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
            logger.debug(
                f"Attempting to ban user {author_id} from chat {channels_dict[chat_id]} ({chat_id})"
            )

            try:
                await bot.ban_chat_member(
                    chat_id=chat_id,
                    user_id=author_id,
                    until_date=None,
                    revoke_messages=True,
                )
                logger.debug(
                    f"User {author_id} banned and their messages deleted from chat {channels_dict[chat_id]} ({chat_id})."
                )
                await bot.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"User {author_id} banned and their messages deleted from chat {channels_dict[chat_id]} ({chat_id}).",
                )
            except Exception as inner_e:
                logger.error(
                    f"Failed to ban and delete messages in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}"
                )
                await bot.send_message(
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
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.debug(
                    f"Message {message_id} deleted from chat {channels_dict[chat_id]} ({chat_id}) for user @{user_name} ({author_id})."
                )
            except Exception as inner_e:
                logger.error(
                    f"Failed to delete message {message_id} in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}"
                )
                await bot.send_message(
                    TECHNOLOG_GROUP_ID,
                    f"Failed to delete message {message_id} in chat {channels_dict[chat_id]} ({chat_id}). Error: {inner_e}",
                )
        logger.debug(
            f"User {author_id} banned and their messages deleted where applicable."
        )
        await message.reply(
            "Action taken: User banned and their messages deleted where applicable."
        )

    except Exception as e:
        logger.error(f"Error in ban function: {e}")
        await message.reply(f"Error: {e}")


# Dedug function to check if the bot is running and have unhandled messages
# Uncomment to use
@dp.message_handler(
    lambda message: message.chat.id not in [ADMIN_GROUP_ID, TECHNOLOG_GROUP_ID],
    content_types=types.ContentTypes.ANY,
)  # exclude admin and technolog group
async def log_all_unhandled_messages(message: types.Message):
    """Function to log all unhandled messages to the technolog group."""
    try:
        logger.debug(f"Received UNHANDLED message object:\n{message}")
        await bot.send_message(
            TECHNOLOG_GROUP_ID,
            f"Received UNHANDLED message object:\n{message}",
            message_thread_id=TECHNO_UNHANDLED,
        )
        await message.forward(
            TECHNOLOG_GROUP_ID, message_thread_id=TECHNO_UNHANDLED
        )  # forward all unhandled messages to technolog group
        return
    except Exception as e:
        logger.error(f"Error in log_all_unhandled_messages function: {e}")
        await message.reply(f"Error: {e}")


# TODO if failed to delete message  since the message is not found - delete corresponding record in the table
# TODO if succeed to delete message also remove this record from the DB

if __name__ == "__main__":
    from aiogram import executor

    # commit_info = get_latest_commit_info()
    # if commit_info:
    #     logger.info("Bot starting with commit info:\n%s", commit_info)
    # else:
    #     logger.warning("Bot starting without git info.")

    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)

    # Close SQLite connection
    conn.close()
