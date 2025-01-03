import xml.etree.ElementTree as ET
from aiogram import Bot, Dispatcher, types
import logging

# Initialize logger
LOGGER = logging.getLogger(__name__)

# Define global variables
CHANNEL_IDS = []
ADMIN_AUTOREPORTS = None
TECHNO_LOGGING = None
TECHNO_ORIGINALS = None
TECHNO_UNHANDLED = None
ADMIN_AUTOBAN = None
ADMIN_MANBAN = None
TECHNO_RESTART = None
TECHNO_INOUT = None
ADMIN_USER_ID = None
TECHNO_NAMES = None
CHANNEL_NAMES = []
SPAM_TRIGGERS = []
ALLOWED_FORWARD_CHANNELS = []
ADMIN_GROUP_ID = None
TECHNOLOG_GROUP_ID = None
ALLOWED_FORWARD_CHANNEL_IDS = set()
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
BOT_NAME = None
BOT_USERID = None
LOG_GROUP = None
LOG_GROUP_NAME = None
TECHNO_LOG_GROUP = None
TECHNO_LOG_GROUP_NAME = None
DP = None
BOT = None
ALLOWED_UPDATES = []
CHANNEL_DICT = {}
ALLOWED_CONTENT_TYPES = []
API_TOKEN = None  # Initialize API_TOKEN at the module level


def load_config():
    """Load configuration values from an XML file."""
    global CHANNEL_IDS, ADMIN_AUTOREPORTS, TECHNO_LOGGING, TECHNO_ORIGINALS, TECHNO_UNHANDLED
    global ADMIN_AUTOBAN, ADMIN_MANBAN, TECHNO_RESTART, TECHNO_INOUT, ADMIN_USER_ID, TECHNO_NAMES
    global CHANNEL_NAMES, SPAM_TRIGGERS
    global ALLOWED_FORWARD_CHANNELS, ADMIN_GROUP_ID, TECHNOLOG_GROUP_ID
    global ALLOWED_FORWARD_CHANNEL_IDS, MAX_TELEGRAM_MESSAGE_LENGTH
    global BOT_NAME, BOT_USERID, LOG_GROUP, LOG_GROUP_NAME, TECHNO_LOG_GROUP, TECHNO_LOG_GROUP_NAME
    global DP, BOT, LOGGER, ALLOWED_UPDATES, CHANNEL_DICT, ALLOWED_CONTENT_TYPES
    global API_TOKEN

    ALLOWED_CONTENT_TYPES = [
        types.ContentType.TEXT,
        types.ContentType.AUDIO,
        types.ContentType.DOCUMENT,
        types.ContentType.GAME,
        types.ContentType.PHOTO,
        types.ContentType.STICKER,
        types.ContentType.VIDEO,
        types.ContentType.VIDEO_NOTE,
        types.ContentType.VOICE,
        types.ContentType.CONTACT,
        types.ContentType.LOCATION,
        types.ContentType.VENUE,
        types.ContentType.POLL,
        types.ContentType.DICE,
        types.ContentType.INVOICE,
        types.ContentType.SUCCESSFUL_PAYMENT,
        types.ContentType.CONNECTED_WEBSITE,
        types.ContentType.MIGRATE_TO_CHAT_ID,
        types.ContentType.MIGRATE_FROM_CHAT_ID,
    ]

    try:
        # Load the XML
        config_XML = ET.parse("config.xml")
        config_XML_root = config_XML.getroot()

        channels_XML = ET.parse("groups.xml")
        channels_root = channels_XML.getroot()

        # Assign configuration values to variables
        ADMIN_AUTOREPORTS = int(config_XML_root.find("admin_autoreports").text)
        ADMIN_AUTOBAN = int(config_XML_root.find("admin_autoban").text)
        ADMIN_MANBAN = int(config_XML_root.find("admin_manban").text)
        TECHNO_LOGGING = int(config_XML_root.find("techno_logging").text)
        TECHNO_ORIGINALS = int(config_XML_root.find("techno_originals").text)
        TECHNO_UNHANDLED = int(config_XML_root.find("techno_unhandled").text)
        TECHNO_RESTART = int(config_XML_root.find("techno_restart").text)
        TECHNO_INOUT = int(config_XML_root.find("techno_inout").text)
        TECHNO_NAMES = int(config_XML_root.find("techno_names").text)

        ADMIN_USER_ID = int(config_XML_root.find("admin_id").text)
        CHANNEL_IDS = [
            int(group.find("id").text) for group in channels_root.findall("group")
        ]
        CHANNEL_NAMES = [
            group.find("name").text for group in channels_root.findall("group")
        ]

        # add channels to dict for logging
        CHANNEL_DICT = {}
        for group in channels_root.findall("group"):
            channel_id = int(group.find("id").text)
            channel_name = group.find("name").text
            CHANNEL_DICT[channel_id] = channel_name

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
        BOT_USERID = int(API_TOKEN.split(":")[0])
        LOG_GROUP = config_XML_root.find("log_group").text
        LOG_GROUP_NAME = config_XML_root.find("log_group_name").text
        TECHNO_LOG_GROUP = config_XML_root.find("techno_log_group").text
        TECHNO_LOG_GROUP_NAME = config_XML_root.find("techno_log_group_name").text

        BOT = Bot(token=API_TOKEN)
        DP = Dispatcher(BOT)
        ALLOWED_UPDATES = ["message", "chat_member", "callback_query"]

    except FileNotFoundError as e:
        LOGGER.error("\033[91mFile not found: %s\033[0m", e.filename)
    except ET.ParseError as e:
        LOGGER.error("\033[91mError parsing XML: %s\033[0m", e)


# Load configuration when the module is imported
load_config()
