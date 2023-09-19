import datetime
import sqlite3
import xml.etree.ElementTree as ET
import logging
import json
import subprocess
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.utils.exceptions import (
    MessageToDeleteNotFound,
    # MessageCantBeDeleted,
    RetryAfter,
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
        received_date INTEGER,
        from_chat_title TEXT,
        PRIMARY KEY (chat_id, message_id)
    )
    """
)

conn.commit()

# If adding new column for the first time, uncomment below
# cursor.execute("ALTER TABLE recent_messages ADD COLUMN from_chat_title TEXT")
# conn.commit()


def get_latest_commit_info():
    """Function to get the latest commit info."""
    try:
        commit_info = (
            subprocess.check_output(["git", "show", "-s"]).decode("utf-8").strip()
        )
        return commit_info
    except Exception as e:
        print(f"Error getting git commit info: {e}")
        return None


def get_spammer_details(
    spammer_id,
    spammer_first_name,
    spammer_last_name,
    message_forward_date,
    forward_from_chat_title=None,
):
    """Function to get chat ID and message ID by sender name and date."""
    if not spammer_last_name:
        spammer_last_name = ""
    if not spammer_id:
        spammer_id = ""

    logger.debug(
        f"Getting chat ID and message ID for spammer: {spammer_id} : {spammer_first_name} {spammer_last_name}, date: {message_forward_date}, forwarded from chat title: {forward_from_chat_title}"
    )

    query = """
        SELECT chat_id, message_id, chat_username, user_id, user_name, user_first_name, user_last_name
        FROM recent_messages 
        WHERE (user_first_name = :sender_first_name AND received_date = :message_forward_date)
           OR (from_chat_title = :from_chat_title)
           OR (user_id = :user_id AND user_first_name = :sender_first_name AND user_last_name = :sender_last_name)
        ORDER BY received_date DESC
        LIMIT 1
        """
    params = {
        "sender_first_name": spammer_first_name,
        "sender_last_name": spammer_last_name,
        "message_forward_date": message_forward_date,
        "from_chat_title": forward_from_chat_title,
        "user_id": spammer_id,
    }

    result = cursor.execute(query, params).fetchone()
    if spammer_first_name == "":
        spammer_first_name = result[5]  # get spammer first name from db
        spammer_last_name = result[6]  # get spammer last name from db

    logger.debug(
        f"get_chat_and_message_id_by_sender_name_and_date result for sender: {spammer_id} : {spammer_first_name} {spammer_last_name}, date: {message_forward_date}, from chat title: {forward_from_chat_title}\nResult: {result}"
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
format_str = "%(message)s"  # Excludes timestamp, logger's name, and log level
formatter = logging.Formatter(format_str)
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
for group in channels_root.findall("group"):
    channel_id = int(group.find("id").text)
    channel_name = group.find("name").text
    channels_dict[channel_id] = channel_name

# Get config data
bot_token = config_XML_root.find("bot_token").text
bot_name = config_XML_root.find("bot_name").text
log_group = config_XML_root.find("log_group").text
log_group_name = config_XML_root.find("log_group_name").text
techno_log_group = config_XML_root.find("techno_log_group").text
techno_log_group_name = config_XML_root.find("techno_log_group_name").text

print("Using bot: " + bot_name)
print("Using log group: " + log_group_name + ", id:" + log_group)
print("Using techno log group: " + techno_log_group_name + ", id: " + techno_log_group)
print("Using channels: " + str(CHANNEL_NAMES))

API_TOKEN = bot_token
ADMIN_GROUP_ID = int(log_group)  # Ensure this is an integer
TECHNOLOG_GROUP_ID = int(techno_log_group)  # Ensure this is an integer

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)


# Uncomment this to get the chat ID of a group or channel
# @dp.message_handler(commands=["getid"])
# async def cmd_getid(message: types.Message):
#     await message.answer(f"This chat's ID is: {message.chat.id}")

recent_messages = (
    {}
)  # To store the recent messages in the format {chat_id: {message_id: user_id}}


@dp.message_handler(
    lambda message: message.forward_date is not None
    and message.chat.id not in CHANNEL_IDS
    and message.chat.id != ADMIN_GROUP_ID
    and message.chat.id != TECHNOLOG_GROUP_ID,
    content_types=types.ContentTypes.ANY,
)
async def handle_forwarded_reports(message: types.Message):
    """Function to handle forwarded messages."""
    logger.debug(f"Received forwarded message for the investigation: {message}")
    # Send a thank you note to the user
    await message.answer("Thank you for the report. We will investigate it.")
    # Forward the message to the admin group
    await bot.forward_message(TECHNOLOG_GROUP_ID, message.chat.id, message.message_id)
    message_as_json = json.dumps(message.to_python(), indent=4)
    # Truncate and add an indicator that the message has been truncated
    if len(message_as_json) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
        message_as_json = message_as_json[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
    await bot.send_message(TECHNOLOG_GROUP_ID, message_as_json)
    await bot.send_message(TECHNOLOG_GROUP_ID, "Please investigate this message.")

    # Get the username, first name, and last name of the user who forwarded the message and handle the cases where they're not available
    if message.forward_from:
        spammer_full_name = [message.forward_from.first_name]
        spammer_id = message.forward_from.id
        if hasattr(message.forward_from, "id") and message.forward_from.id:
            spammer_id = message.forward_from.id
        if (
            hasattr(message.forward_from, "last_name")
            and message.forward_from.last_name
        ):
            spammer_full_name.append(message.forward_from.last_name)
        else:
            spammer_full_name.append("")  # last name is not available
    else:
        spammer_full_name = (
            message.forward_sender_name and message.forward_sender_name.split(" ")
        )

    # Handle the case where the sender's name is not available
    spammer_last_name_part = ""
    spammer_first_name_part = ""
    if spammer_full_name and len(spammer_full_name) > 1:
        spammer_last_name_part = spammer_full_name[1]
        spammer_first_name_part = spammer_full_name[0]
    else:
        spammer_last_name_part = ""
        spammer_first_name_part = spammer_full_name[0]
    # Handle the case where the message is forwarded from a channel
    forward_from_chat_title = None
    if message.forward_from_chat:
        forward_from_chat_title = message.forward_from_chat.title
    # Get the chat ID and message ID of the original message
    try:
        found_message_data = get_spammer_details(
            spammer_id,
            spammer_first_name_part,
            spammer_last_name_part,
            message.forward_date,
            forward_from_chat_title,
        )
    except AttributeError as e:
        logger.error(f"An error occurred while fetching the message data: {e}")
        found_message_data = None

    logger.debug(f"Message data: {found_message_data}")

    if not found_message_data:
        # check if we have everything open
        # try:
        #     # try if everything is open
        #     pass
        #     # Save both the original message_id and the forwarded message's date
        #     # received_date = message.date if message.date else None
        #     # report_id = int(str(message.chat.id) + str(message.message_id))

        # except Exception as e:
        e = "TEST"
        logger.debug(
            f"Could not retrieve the author's user ID. Please ensure you're reporting recent messages. {e}"
        )
        await message.answer(
            f"Could not retrieve the author's user ID. Please ensure you're reporting recent messages. {e}"
        )
        return

    # Save both the original message_id and the forwarded message's date
    received_date = message.date if message.date else None
    report_id = int(str(message.chat.id) + str(message.message_id))
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
        username = "UNKNOWN"

    # Initialize user_id and user_link with default values
    user_id = found_message_data[3]

    # Log the information with the link
    log_info = (
        f"Report timestamp: {message.date}\n"
        f"Spam message timestamp: {message.forward_date}\n"
        f"Reaction time: {message.date - message.forward_date}\n"
        f"Forwarded from <a href='tg://resolve?domain={username}'>@{username}</a> : "
        f"{message.forward_sender_name or f'{first_name} {last_name}'}\n"
        f"<a href='tg://user?id={user_id}'>Spammer ID based profile link</a>\n"
        f"Plain text spammer ID profile link: tg://user?id={user_id}\n"
        f"Reported by admin <a href='tg://user?id={message.from_user.id}'>"
        f"@{message.from_user.username or 'UNKNOWN'}</a>\n"
        f"<a href='{message_link}'>Link to the reported message</a>\n"
        f"Use /ban <b>{report_id}</b> to take action.\n"
    )
    logger.debug("Report banner content:")
    logger.debug(log_info)

    await bot.send_message(TECHNOLOG_GROUP_ID, log_info, parse_mode="HTML")
    # show old banner in the admin group in case buttons test fails
    # await bot.send_message(ADMIN_GROUP_ID, log_info, parse_mode="HTML")

    # Keyboard ban/cancel/confirm buttons
    keyboard = InlineKeyboardMarkup()
    ban_btn = InlineKeyboardButton("Ban", callback_data=f"confirm_ban_{report_id}")
    keyboard.add(ban_btn)

    # Show ban banner with buttons in the admin group to confirm or cancel the ban
    await bot.send_message(
        ADMIN_GROUP_ID, log_info, reply_markup=keyboard, parse_mode="HTML"
    )


# TODO: Remove buttons and restart ban reporting process in case any button is pressed or any error occurs
@dp.callback_query_handler(lambda c: c.data.startswith("confirm_ban_"))
async def ask_confirmation(callback_query: CallbackQuery):
    """Function to ask for confirmation before banning the user."""
    *_, message_id_to_ban = callback_query.data.split("_")

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
                # logging is enough, no need to spam the group
                # await bot.send_message(
                #     TECHNOLOG_GROUP_ID,
                #     f"User {author_id} banned and their messages deleted from chat {channels_dict[chat_id]} ({chat_id}).",
                # )
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
                    # logging is enough, no need to spam the group
                    # await bot.send_message(
                    #     TECHNOLOG_GROUP_ID,
                    #     f"Message {message_id} in chat {channels_dict[chat_id]} ({chat_id}) not found for deletion.",
                    # )
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
        # await callback_query.answer(
        #     f"User banned! {message_id_to_ban}"
        # )  # TODO is it neccecary now?

        await bot.send_message(
            ADMIN_GROUP_ID,
            f"Report {message_id_to_ban} action taken: User {author_id} banned and their messages deleted where applicable.",
        )
        await bot.send_message(
            TECHNOLOG_GROUP_ID,
            f"Report {message_id_to_ban} action taken: User {author_id} banned and their messages deleted where applicable.",
        )

    except Exception as e:
        logger.error(f"Error in handle_ban function: {e}")
        await callback_query.message.reply(f"Error: {e}")


@dp.callback_query_handler(lambda c: c.data.startswith("reset_ban_"))
async def reset_ban(callback_query: CallbackQuery):
    """Function to reset the ban button."""
    *_, report_id_to_ban = callback_query.data.split("_")

    # TODO choose the right behaviour
    # reset to ban button
    # keyboard = InlineKeyboardMarkup()
    # ban_btn = InlineKeyboardButton(
    #     "Ban", callback_data=f"confirm_ban_{report_id_to_ban}"
    # )
    # keyboard.add(ban_btn)

    # await bot.edit_message_reply_markup(
    #     chat_id=callback_query.message.chat.id,
    #     message_id=callback_query.message.message_id,
    #     reply_markup=keyboard,
    # )

    # remove buttons from the admin group
    await bot.edit_message_reply_markup(
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
    )

    logger.info(f"Report {report_id_to_ban} button action canceled.")

    await bot.send_message(
        ADMIN_GROUP_ID,
        f"Button action canceled: Report {report_id_to_ban} was not processed. "
        f"Report them again if needed or use /ban {report_id_to_ban} command.",
    )
    await bot.send_message(
        TECHNOLOG_GROUP_ID,
        f"Cancel button pressed. "
        f"Button action canceled: Report {report_id_to_ban} was not processed. "
        f"Report them again if needed or use /ban {report_id_to_ban} command.",
    )


@dp.message_handler(
    lambda message: message.chat.id in CHANNEL_IDS, content_types=types.ContentTypes.ANY
)
async def store_recent_messages(message: types.Message):
    """Function to store recent messages in the database."""
    try:
        # Log the full message object for debugging
        # logger.debug(
        #     f"Received message object: {message}"
        # )  # TODO remove afer sandboxing

        cursor.execute(
            """
            INSERT OR REPLACE INTO recent_messages 
            (chat_id, chat_username, message_id, user_id, user_name, user_first_name, user_last_name, forward_date, received_date, from_chat_title) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                getattr(message, "date", None),
                getattr(message.forward_from_chat, "title", None),
            ),
        )
        conn.commit()
        # logger.info(f"Stored recent message: {message}")

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
    lambda message: message.chat.id != ADMIN_GROUP_ID,
    content_types=types.ContentTypes.ANY,
)  # exclude admin group
async def log_all_unhandled_messages(message: types.Message):
    try:
        logger.debug(f"Received UNHANDLED message object: {message}")
        return
    except Exception as e:
        logger.error(f"Error in log_all_unhandled_messages function: {e}")
        await message.reply(f"Error: {e}")


# TODO if failed to delete message  since the message is not found - delete corresponding record in the table
# TODO if succed to delete message also remove this record from the DB
if __name__ == "__main__":
    from aiogram import executor

    commit_info = get_latest_commit_info()
    if commit_info:
        logger.info(f"Bot starting with commit info:\n{commit_info}")
    else:
        logger.warning("Bot starting without git info.")

    # Add this section right after setting up your logger or at the start of your main execution:
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_log_message = f"\nBot started at {current_time}\n{'-' * 40}\n"
    logger.info(start_log_message)

    executor.start_polling(dp, skip_updates=True)

    # Close SQLite connection
    conn.close()
