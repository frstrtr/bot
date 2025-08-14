"""Spam checking, banning, watchdog logic extracted from main."""
from __future__ import annotations
import asyncio, re, aiohttp
from datetime import datetime
from typing import Optional
from aiogram.types import InlineKeyboardMarkup
from app.state import active_user_checks_dict, banned_users_dict, running_watchdogs
from utils.utils_config import (
    CHANNEL_IDS, CHANNEL_DICT, BOT, LOGGER, BOT_USERID, ADMIN_GROUP_ID,
    ADMIN_AUTOBAN, ADMIN_MANBAN, ADMIN_SUSPICIOUS, TECHNOLOG_GROUP_ID,
    TECHNO_NAMES, TECHNO_ADMIN
)
from utils.utils import (
    safe_send_message, make_lols_kb, build_lols_url,
)
from app.services.logging_service import log_and_notify
from main import save_report_file  # reuse existing async util

# --- Core spam check (network) -------------------------------------------------
async def spam_check(user_id: int) -> Optional[bool]:
    async with aiohttp.ClientSession() as session:
        async def check_local():
            try:
                async with session.get(f"http://127.0.0.1:8081/check?user_id={user_id}", timeout=10) as r:
                    if r.status == 200:
                        data = await r.json(); return data.get("is_spammer", False)
            except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
                return False
        async def check_lols():
            try:
                async with session.get(f"https://api.lols.bot/account?id={user_id}", timeout=10) as r:
                    if r.status == 200:
                        data = await r.json(); return data.get("banned", False)
            except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
                return False
        async def check_cas():
            try:
                async with session.get(f"https://api.cas.chat/check?user_id={user_id}", timeout=10) as r:
                    if r.status == 200:
                        data = await r.json(); return data.get("result", {}).get("offenses", 0) if data.get("ok") else 0
            except (aiohttp.ClientConnectorError, asyncio.TimeoutError):
                return 0
        try:
            local, lols, cas = await asyncio.gather(check_local(), check_lols(), check_cas())
            return True if lols or local or (cas and cas > 0) else False
        except Exception as e:
            LOGGER.error("spam_check unexpected error: %s", e)
            return None

# --- Banning helpers -----------------------------------------------------------
async def ban_user_from_all_chats(user_id: int, user_name: str | None):
    uname = user_name or "!UNDEFINED!"
    for chat_id in CHANNEL_IDS:
        try:
            await BOT.ban_chat_member(chat_id, user_id, revoke_messages=True)
        except Exception as e:
            LOGGER.debug("ban all chats failure %s in %s", user_id, chat_id)
            await asyncio.sleep(0.05)
    banned_users_dict[user_id] = uname
    if uname and uname != "!UNDEFINED!":
        await safe_send_message(
            BOT, TECHNOLOG_GROUP_ID, f"<code>{user_id}</code>:@{uname} (svc)", LOGGER,
            parse_mode="HTML", message_thread_id=TECHNO_NAMES
        )

async def autoban(user_id: int, user_name: str | None):
    if user_id in active_user_checks_dict:
        banned_users_dict[user_id] = active_user_checks_dict.pop(user_id, None)
    else:
        banned_users_dict[user_id] = user_name or "!UNDEFINED!"
    await ban_user_from_all_chats(user_id, user_name)

# --- Watchdog / periodic perform checks ---------------------------------------
async def perform_checks(event_record: str, user_id: int, inout_logmessage: str, user_name: str):
    color_map = {False: "\033[92m", True: "\033[91m", None: "\033[93m"}
    sleep_times = [65,185,305,605,1205,1805,3605,7205,10805]
    try:
        for st in sleep_times:
            if user_id not in active_user_checks_dict:
                return
            await asyncio.sleep(st)
            lols_spam = await spam_check(user_id)
            LOGGER.debug("%s%s:@%s %02dmin check spam:%s left:%d\033[0m",
                         color_map.get(lols_spam, "\033[93m"), user_id, user_name or "!UNDEFINED!", st//60,
                         lols_spam, len(active_user_checks_dict))
            # TODO integrate check_and_autoban here via imported function once extracted
    except asyncio.CancelledError:
        LOGGER.info("%s:@%s perform_checks cancelled", user_id, user_name)
    finally:
        if user_id in active_user_checks_dict:
            active_user_checks_dict.pop(user_id, None)
            LOGGER.info("%s:@%s removed from active checks (perform_checks final)", user_id, user_name)

async def create_named_watchdog(coro, user_id: int, user_name: str):
    existing = running_watchdogs.get(user_id)
    task = asyncio.create_task(coro, name=str(user_id))
    running_watchdogs[user_id] = task
    if existing:
        try:
            existing.cancel()
        except Exception:
            pass
        async def _await_cancel(t):
            try: await t
            except asyncio.CancelledError: LOGGER.debug("prev watchdog %s cancelled", user_id)
        asyncio.create_task(_await_cancel(existing), name=f"cancel:{user_id}")
    def _done(t):
        if running_watchdogs.get(user_id) is t:
            running_watchdogs.pop(user_id, None)
    task.add_done_callback(_done)
    return task
