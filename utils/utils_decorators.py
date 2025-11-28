from aiogram import types

from utils.utils_config import (
    ADMIN_GROUP_ID,
    TECHNOLOG_GROUP_ID,
    ADMIN_USER_ID,
    CHANNEL_IDS,
    BOT_USERID,
    SUPERADMIN_GROUP_ID,
)


def is_valid_message(
    message: types.Message,
) -> bool:
    """Check if the message is not from admin groups, technolog group, admin user, superadmin group, or BOT managed channels, and is not forwarded."""
    excluded_chats = [ADMIN_GROUP_ID, TECHNOLOG_GROUP_ID, ADMIN_USER_ID] + CHANNEL_IDS
    if SUPERADMIN_GROUP_ID:
        excluded_chats.append(SUPERADMIN_GROUP_ID)
    return (
        message.chat.id not in excluded_chats
        and message.forward_from_chat is None
    )


def is_not_bot_action(update: types.ChatMemberUpdated) -> bool:
    """Check if the update is not from the bot itself."""
    return update.from_user.id != BOT_USERID


def is_forwarded_from_unknown_channel_message(
    message: types.Message,
) -> bool:
    """Function to check if the message is a forwarded message from someone or FOREIGN channel.
    Message is not from the BOT managed channels.
    Message is not from ADMIN group.
    Message is not from TECHNOLOG group.
    """
    return (
        message.forward_date is not None
        and message.chat.id not in CHANNEL_IDS
        and message.chat.id != ADMIN_GROUP_ID
        and message.chat.id != TECHNOLOG_GROUP_ID
    )


def is_in_monitored_channel(message: types.Message) -> bool:
    """Check if the message is from one of the specified channels."""
    return (
        message.chat.id in CHANNEL_IDS
        and message.chat.id != ADMIN_GROUP_ID
        and message.chat.id != TECHNOLOG_GROUP_ID
    )


def is_admin_user_message(message: types.Message) -> bool:
    """Check if the message is from the admin user and not forwarded."""
    return message.from_user.id == ADMIN_USER_ID and message.forward_date is None
