import datetime
import sqlite3
import xml.etree.ElementTree as ET
import logging
import json
from aiogram import Bot, Dispatcher, types

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
        PRIMARY KEY (chat_id, message_id)
    )
    """
)

conn.commit()


def get_chat_and_message_id_by_sender_name_and_date(
    sender_first_name, sender_last_name, message_forward_date
):
    """Function to get chat ID and message ID by sender name and date."""
    if not sender_last_name:
        sender_last_name = ""

    logger.debug(
        f"Getting chat ID and message ID for sender: {sender_first_name} {sender_last_name}, date: {message_forward_date}"
    )

    query = """
        SELECT chat_id, message_id, chat_username, user_id, user_name
        FROM recent_messages 
        WHERE user_first_name = :sender_first_name AND received_date = :message_forward_date
        """
    params = {
        "sender_first_name": sender_first_name,
        "message_forward_date": message_forward_date,
    }

    result = cursor.execute(query, params).fetchone()

    logger.debug(
        f"get_chat_and_message_id_by_sender_name_and_date result for sender: {sender_first_name} {sender_last_name}, date: {message_forward_date}\nResult: {result}"
    )

    return result


def get_author_info(
    chat_id,
    message_id,
    using_forwarded=False,
    message_forward_date=None,
    forward_sender_name=None,
):
    """Function to get user ID, username, first name, and last name."""

    logger.debug(
        f"Getting author info for Reporter: {chat_id}, report_id: {message_id}, using_forwarded: {using_forwarded}, message_forward_date: {message_forward_date}, forward_sender_name: {forward_sender_name}"
    )

    # Split the forward_sender_name to first and last name
    sender_first_name = forward_sender_name.split()[0] if forward_sender_name else None
    sender_last_name = (
        " ".join(forward_sender_name.split()[1:]) if forward_sender_name else None
    )

    # Initialize query and parameters
    query = ""
    params = {}

    if using_forwarded and message_forward_date and forward_sender_name:
        query = """
            SELECT user_id, user_name, user_first_name, user_last_name, received_date, chat_id, message_id, chat_username
            FROM recent_messages 
            WHERE received_date = :message_forward_date AND user_first_name = :sender_first_name AND user_last_name = :sender_last_name
            """
        params = {
            "message_forward_date": message_forward_date,
            "sender_first_name": sender_first_name,
            "sender_last_name": sender_last_name,
        }
    elif using_forwarded:
        query = """
            SELECT user_id, user_name, user_first_name, user_last_name, received_date
            FROM recent_messages WHERE received_date = :message_forward_date
            """
        params = {"message_forward_date": message_forward_date}
    else:
        query = """
            SELECT user_id, user_name, user_first_name, user_last_name
            FROM recent_messages WHERE chat_id = :chat_id AND message_id = :message_id
            """
        params = {"chat_id": chat_id, "message_id": message_id}

    result = cursor.execute(query, params).fetchone()

    # Additional checks
    if result and using_forwarded:
        recorded_full_name = f"{result[2] or ''} {result[3] or ''}".strip()
        if (
            recorded_full_name != forward_sender_name
            or datetime.datetime.strptime(result[4], "%Y-%m-%d %H:%M:%S")
            != message_forward_date
        ):
            return (None, None, None, None, None, None, None, None)

    logger.debug(
        f"get_author_info result for Reporter: {chat_id}, Report_ID: {message_id}: {result}"
    )

    # Return consistent 8 fields, filling with None as needed
    if not result:
        return (None, None, None, None, None, None, None, None)

    return result + (None,) * (8 - len(result))


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

# get info about chats where bot present


@dp.message_handler(
    lambda message: message.forward_date is not None
    and message.chat.id not in CHANNEL_IDS,
    content_types=types.ContentTypes.ANY,
)
async def handle_forwarded_reports(message: types.Message):
    logger.debug(f"Received forwarded message for the investigation: {message}")
    await bot.forward_message(TECHNOLOG_GROUP_ID, message.chat.id, message.message_id)
    message_as_json = json.dumps(message.to_python(), indent=4)
    # Truncate and add an indicator that the message has been truncated
    if len(message_as_json) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
        message_as_json = message_as_json[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
    await bot.send_message(TECHNOLOG_GROUP_ID, message_as_json)
    await bot.send_message(TECHNOLOG_GROUP_ID, "Please investigate this message.")

    sender_full_name = (
        message.forward_sender_name and message.forward_sender_name.split(" ")
    )
    found_message_data = get_chat_and_message_id_by_sender_name_and_date(
        (sender_full_name and sender_full_name[0]) or message.forward_from.first_name,
        (sender_full_name and len(sender_full_name) > 1 and sender_full_name[1]) or "",
        message.forward_date,
    )
    logger.debug(f"Message data: {found_message_data}")

    if not found_message_data:
        logger.debug(
            "Could not retrieve the author's user ID. Please ensure you're reporting recent messages."
        )
        await message.answer(
            "Could not retrieve the author's user ID. Please ensure you're reporting recent messages."
        )
        return

    # Save both the original message_id and the forwarded message's date
    received_date = message.date if message.date else None
    new_message_id = int(str(message.chat.id) + str(message.message_id))
    cursor.execute(
        """
        INSERT OR REPLACE INTO recent_messages 
        (chat_id, message_id, user_id, user_name, user_first_name, user_last_name, forward_date, received_date, forwarded_message_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.chat.id,
            new_message_id,
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
        first_name = ""
        last_name = ""

    # Get the username
    username = found_message_data[4]

    # Initialize user_id and user_link with default values
    user_id = found_message_data[3]

    # Log the information with the link
    log_info = (
        f"Report timestamp: {message.date}\n"  # Using message.date here
        f"Spam message timestamp: {message.forward_date}\n"  # Using received_date here
        f"Forwarded from @{username} : {message.forward_sender_name or first_name} {last_name}\n"
        f"[Spammer ID based link](tg://user?id={user_id})\n"
        f"Plain text spammer ID profile link: tg://user?id={user_id}\n"
        f"Spammer ID: {user_id}\n"
        f"Reported by admin @{message.from_user.username or 'UNKNOWN'}\n"
        f"[Link to the reported message]({message_link})\n"
        f"Use /ban {new_message_id} to take action."
    )

    await bot.send_message(ADMIN_GROUP_ID, log_info, parse_mode="Markdown")

    # Send a thank you note to the user
    await message.answer("Thank you for the report. We will investigate it.")


@dp.message_handler(
    lambda message: message.chat.id in CHANNEL_IDS, content_types=types.ContentTypes.ANY
)
async def store_recent_messages(message: types.Message):
    try:
        # Log the full message object for debugging
        # logger.debug(f"Received message object: {message}")

        cursor.execute(
            """
            INSERT OR REPLACE INTO recent_messages 
            (chat_id, chat_username, message_id, user_id, user_name, user_first_name, user_last_name, received_date) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.chat.id,
                message.chat.username,
                message.message_id,
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
                message.from_user.last_name,
                message.date,
            ),
        )
        conn.commit()

    except Exception as e:
        logger.error(f"Error storing recent message: {e}")


@dp.message_handler(commands=["ban"], chat_id=ADMIN_GROUP_ID)
async def ban(message: types.Message):
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
@dp.message_handler(content_types=types.ContentTypes.ANY)
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

    # Locale test
    print(
        "Console locale test: ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮËйцукенгшщзхъфывапролджэячсмитьбюё"
    )

    # Add this section right after setting up your logger or at the start of your main execution:
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_log_message = f"\nBot started at {current_time}\n{'-' * 40}\n"
    logger.info(start_log_message)

    executor.start_polling(dp, skip_updates=True)

    # Close SQLite connection
    conn.close()
