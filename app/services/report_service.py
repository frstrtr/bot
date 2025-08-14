"""Report handling (forwarded spam reports) extracted from main."""
from __future__ import annotations
from datetime import datetime
import json, html, sqlite3, ast
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from utils.utils_config import (
    BOT, ADMIN_AUTOREPORTS, TECHNOLOG_GROUP_ID, ADMIN_GROUP_ID,
    MAX_TELEGRAM_MESSAGE_LENGTH, TECHNO_NAMES, LOGGER, CHANNEL_IDS, CHANNEL_DICT
)
from utils.utils import (
    safe_send_message, format_spam_report, construct_message_link,
    make_lols_kb, extract_spammer_info, get_channel_name_by_id
)
from app.state import banned_users_dict, active_user_checks_dict
from main import save_report_file, get_spammer_details  # reuse existing without duplicating now

async def submit_autoreport(message: types.Message, reason: str):
    reported_spam = "ADM" + format_spam_report(message)[3:]
    await save_report_file("daily_spam_", reported_spam)
    try:
        techn_cp = await BOT.forward_message(TECHNOLOG_GROUP_ID, message.chat.id, message.message_id)
    except Exception:
        return
    message_as_json = json.dumps(message.to_python(), indent=4, ensure_ascii=False)
    if len(message_as_json) > MAX_TELEGRAM_MESSAGE_LENGTH - 3:
        message_as_json = message_as_json[: MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
    await safe_send_message(BOT, TECHNOLOG_GROUP_ID, message_as_json, LOGGER)
    await safe_send_message(BOT, TECHNOLOG_GROUP_ID, "Please investigate this message.", LOGGER)
    # Minimal subset (full original logic remains in main until fully migrated)
    # TODO finalize extraction of handle_autoreports
    return techn_cp
