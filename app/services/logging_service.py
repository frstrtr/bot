from utils.utils import safe_send_message
from utils.utils_config import TECHNOLOG_GROUP_ID, TECHNO_ADMIN, LOGGER

async def log_and_notify(bot, text: str, thread: int = TECHNO_ADMIN, parse_mode: str = "HTML"):
    await safe_send_message(bot, TECHNOLOG_GROUP_ID, text, LOGGER, message_thread_id=thread, parse_mode=parse_mode, disable_web_page_preview=True)

async def runtime_stat(bot, active_checks: int, banned: int, start_time: str):
    msg = (
        "Runtime session shutdown stats:\n"
        f"Bot started at: {start_time}\n"
        f"Current active user checks: {active_checks}\n"
        f"Spammers detected: {banned}\n"
    )
    await log_and_notify(bot, msg)
