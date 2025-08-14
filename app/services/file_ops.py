"""File persistence helpers for active checks and banned users."""
from datetime import datetime
import os, ast, asyncio
from app.state import active_user_checks_dict, banned_users_dict
from utils.utils_config import LOGGER

ACTIVE_CHECKS_FILE = "active_user_checks.txt"
BANNED_USERS_FILE = "banned_users.txt"

async def load_banned_users():
    if not os.path.exists(BANNED_USERS_FILE):
        return
    with open(BANNED_USERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if ":" not in line:
                continue
            uid_str, name_repr = line.strip().split(":", 1)
            try:
                user_id = int(uid_str)
            except ValueError:
                continue
            try:
                name = ast.literal_eval(name_repr)
            except Exception:
                name = name_repr
            banned_users_dict[user_id] = name
    LOGGER.info("Loaded %d banned users from file", len(banned_users_dict))

async def load_active_user_checks(start_check_cb):
    if not os.path.exists(ACTIVE_CHECKS_FILE):
        return
    with open(ACTIVE_CHECKS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if ":" not in line:
                continue
            uid_str, payload = line.strip().split(":", 1)
            try:
                user_id = int(uid_str)
            except ValueError:
                continue
            try:
                value = ast.literal_eval(payload) if payload.startswith("{") else payload
            except Exception:
                value = payload
            active_user_checks_dict[user_id] = value
            await asyncio.sleep(1)
            await start_check_cb(user_id, value)
    LOGGER.info("Loaded %d active checks from file", len(active_user_checks_dict))

async def persist_shutdown_state():
    if active_user_checks_dict:
        with open(ACTIVE_CHECKS_FILE, "w", encoding="utf-8") as f:
            for uid, val in active_user_checks_dict.items():
                f.write(f"{uid}:{repr(val)}\n")
    else:
        open(ACTIVE_CHECKS_FILE, "w", encoding="utf-8").close()
    if banned_users_dict:
        mode = "a" if os.path.exists(BANNED_USERS_FILE) else "w"
        with open(BANNED_USERS_FILE, mode, encoding="utf-8") as f:
            for uid, val in banned_users_dict.items():
                f.write(f"{uid}:{repr(val)}\n")
