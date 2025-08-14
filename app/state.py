"""Shared runtime state containers for the bot.
Separated from main to allow service modules to import without circular dependencies.
"""
from typing import Dict, Any

# Active users under watch (user_id -> data dict / username)
active_user_checks_dict: Dict[int, Any] = {}
# Banned users (user/channel id -> username or metadata)
banned_users_dict: Dict[int, Any] = {}
# Running watchdog tasks (user_id -> asyncio.Task) (populated at runtime)
running_watchdogs: Dict[int, Any] = {}
