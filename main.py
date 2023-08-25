import datetime
import sqlite3
from aiogram import Bot, Dispatcher, types
import xml.etree.ElementTree as ET
import logging


# Setting up SQLite Database
conn = sqlite3.connect("messages.db")
cursor = conn.cursor()


# Modified the table to include forward_date, received_date


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

# If adding the forwarded_message_data column for the first time, uncomment below
# cursor.execute("ALTER TABLE recent_messages ADD COLUMN forwarded_message_data INTEGER")
# conn.commit()

# Add this for the forward_date as well if running the script for the first time after the changes
# cursor.execute("ALTER TABLE recent_messages ADD COLUMN forward_date INTEGER")
# conn.commit()


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
        SELECT chat_id, message_id, chat_username, user_id
        FROM recent_messages 
        WHERE user_first_name = :sender_first_name AND received_date = :message_forward_date
        """
    params = {
        "sender_first_name": sender_first_name,
        "message_forward_date": message_forward_date,
    }

    result = cursor.execute(query, params).fetchone()

    logger.debug(
        f"get_chat_and_message_id_by_sender_name_and_date result for sender: {sender_first_name} {sender_last_name}, date: {message_forward_date}: {result}"
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

#Extract group names from XML
CHANNEL_NAMES = [group.find("name").text for group in channels_root.findall("group")]

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
LOG_GROUP_ID = int(log_group)  # Ensure this is an integer
TECHNO_LOG_GROUP_ID = int(techno_log_group)  # Ensure this is an integer

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


@dp.message_handler(lambda message: message.forward_date is not None and message.chat.id == LOG_GROUP_ID)
async def handle_forwarded_reports(message: types.Message):
    # logger.debug(f"Received forwarded message {message}")
    # Fetch original user information from the recent messages database
    # (author_id, username, first_name, last_name, post_date, origin_chat_id, origin_message_id)

    sender_full_name  = message.forward_sender_name and message.forward_sender_name.split(" ");
    found_message_data = get_chat_and_message_id_by_sender_name_and_date(
        (sender_full_name and sender_full_name[0])
        or message.forward_from.first_name,
        (sender_full_name and len(sender_full_name) > 1 and sender_full_name[1])
        or "",
        message.forward_date,
    )
    logger.debug(f"Message data: {found_message_data}")

    if not found_message_data:
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

    # Log the information with the link
    log_info = (
        f"Date-Time: {message.date}\n"  # Using message.date here
        f"Forwarded from user: {message.forward_sender_name or message.forward_from.first_name}\n"
        f"Reported by user: {message.from_user.username or 'Unknown'}\n"
        f"[Link to the reported message]({message_link})\n"
        f"Use /ban {new_message_id} to take action."
    )
    await bot.send_message(LOG_GROUP_ID, log_info, parse_mode="Markdown")

    # Send a thank you note to the user
    await message.answer("Thank you for the report. We will investigate it.")


@dp.message_handler(lambda message: message.chat.id in CHANNEL_IDS)
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


@dp.message_handler(commands=["ban"], chat_id=LOG_GROUP_ID)
async def ban(message: types.Message):
    try:
        # logger.debug("ban triggered.")

        command_args = message.text.split()
        logger.debug(f"Command arguments received: {command_args}")

        if len(command_args) < 2:
            raise ValueError("Please provide the message ID of the report.")

        report_msg_id = int(command_args[1])
        logger.debug(f"Report message ID parsed: {report_msg_id}")

        # TODO: Fetch original chat_id and message_id using the forwarded_message_data
        cursor.execute(
            "SELECT chat_id, message_id, forwarded_message_data FROM recent_messages WHERE message_id = ?",
            (report_msg_id,),
        )
        result = cursor.fetchone()
        logger.debug(
            f"Database query result for forwarded_message_data {report_msg_id}: {result}"
        )

        if not result:
            await message.reply("Error: Report not found in database.")
            return

        original_chat_id, original_message_id, forwarded_message_data = result
        logger.debug(
            f"Original chat ID: {original_chat_id}, Original message ID: {original_message_id}"
        )

        author_id = eval(forwarded_message_data)[3]
        logger.debug(f"Author ID retrieved for original message: {author_id}")

        if not author_id:
            await message.reply(
                "Could not retrieve the author's user ID from the report."
            )
            return

        # Attempting to ban user from channels
        for chat_id in CHANNEL_IDS:
            logger.debug(f"Attempting to ban user {author_id} from chat {chat_id}")

            try:
                await bot.ban_chat_member(
                    chat_id=chat_id,
                    user_id=author_id,
                    until_date=None,
                    revoke_messages=True,
                )
                logger.debug(
                    f"User {author_id} banned and their messages deleted from chat {chat_id}."
                )
            except Exception as inner_e:
                logger.error(
                    f"Failed to ban and delete messages in chat {chat_id}. Error: {inner_e}"
                )
                await bot.send_message(
                    TECHNO_LOG_GROUP_ID,
                    f"Failed to ban and delete messages in chat {chat_id}. Error: {inner_e}",
                )
        # select all messages from the user in the chat
        query = """
            SELECT chat_id, message_id
            FROM recent_messages 
            WHERE user_id = :author_id
            """
        params = {"author_id": author_id}
        result = cursor.execute(query, params).fetchall()
        # delete them one by one
        for chat_id, message_id in result:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                logger.debug(
                    f"Message {message_id} deleted from chat {chat_id} for user {author_id}."
                )
            except Exception as inner_e:
                logger.error(
                    f"Failed to delete message {message_id} in chat {chat_id}. Error: {inner_e}"
                )
                await bot.send_message(
                    TECHNO_LOG_GROUP_ID,
                    f"Failed to delete message {message_id} in chat {chat_id}. Error: {inner_e}",
                )

        await message.reply(
            "Action taken: User banned and their messages deleted where applicable."
        )

    except Exception as e:
        logger.error(f"Error in ban function: {e}")
        await message.reply(f"Error: {e}")


if __name__ == "__main__":
    from aiogram import executor

    # Locale test
    print('Locale test: ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮËйцукенгшщзхъфывапролджэячсмитьбюё')

    # Add this section right after setting up your logger or at the start of your main execution:
    current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_log_message = f"\nBot started at {current_time}\n{'-' * 20}\n"
    logger.info(start_log_message)

    executor.start_polling(dp, skip_updates=True)

    # Close SQLite connection
    conn.close()
