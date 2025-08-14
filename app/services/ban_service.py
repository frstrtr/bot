import asyncio
from utils.utils import safe_send_message
from utils.utils_config import TECHNOLOG_GROUP_ID, TECHNO_NAMES, CHANNEL_IDS, BOT, LOGGER

async def ban_user_everywhere(user_id: int, user_name: str | None):
    from main import banned_users_dict  # lazy import to avoid circular for now
    if user_name is None:
        user_name = "!UNDEFINED!"
    for chat_id in CHANNEL_IDS:
        try:
            await BOT.ban_chat_member(chat_id, user_id, revoke_messages=True)
        except RuntimeError as e:  # common network / loop issues
            LOGGER.debug("Ban in chat %s failed (runtime): %s", chat_id, e)
            await asyncio.sleep(0.2)
    banned_users_dict[user_id] = user_name
    if user_name and user_name != "!UNDEFINED!":
        await safe_send_message(
            BOT,
            TECHNOLOG_GROUP_ID,
            f"<code>{user_id}</code>:@{user_name} (ban_service)",
            LOGGER,
            parse_mode="HTML",
            message_thread_id=TECHNO_NAMES,
        )
