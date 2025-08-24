"""Data persistence utilities for bot state management."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class DataPersistence:
    """Handles saving and loading of bot persistent data."""
    
    def __init__(self, base_dir: str = "."):
        self.base_dir = Path(base_dir)
        self.banned_users_file = "aiogram3_banned_users.txt"
        self.active_checks_file = "aiogram3_active_user_checks.txt"
        self.inout_dir = "aiogram3_inout"
        self.daily_spam_dir = "aiogram3_daily_spam"
    
    async def save_banned_users(self, banned_users_dict: Dict[int, str]) -> None:
        """Save banned users dictionary to file."""
        try:
            file_path = self.base_dir / self.banned_users_file
            with open(file_path, 'w', encoding='utf-8') as f:
                for user_id, username in banned_users_dict.items():
                    f.write(f"{user_id}:{repr(username)}\n")
            
            logger.info(f"💾 Saved {len(banned_users_dict)} banned users to {self.banned_users_file}")
            
        except Exception as e:
            logger.error(f"Error saving banned users: {e}")
    
    async def load_banned_users(self) -> Dict[int, str]:
        """Load banned users dictionary from file."""
        banned_users_dict = {}
        
        try:
            file_path = self.base_dir / self.banned_users_file
            if not file_path.exists():
                logger.info(f"Banned users file {self.banned_users_file} not found, starting with empty dict")
                return banned_users_dict
            
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if line and ':' in line:
                        try:
                            user_id_str, username_repr = line.split(':', 1)
                            user_id = int(user_id_str)
                            # Safely evaluate the repr string
                            username = eval(username_repr) if username_repr else "!UNDEFINED!"
                            banned_users_dict[user_id] = username
                        except (ValueError, SyntaxError) as e:
                            logger.warning(f"Invalid line {line_num} in banned users file: {line} - {e}")
            
            logger.info(f"Banned users dict ({len(banned_users_dict)}) loaded from file")
            return banned_users_dict
            
        except Exception as e:
            logger.error(f"Error loading banned users: {e}")
            return banned_users_dict
    
    async def save_active_user_checks(self, active_user_checks_dict: Dict[int, Any]) -> None:
        """Save active user checks dictionary to file."""
        try:
            file_path = self.base_dir / self.active_checks_file
            with open(file_path, 'w', encoding='utf-8') as f:
                for user_id, user_data in active_user_checks_dict.items():
                    if isinstance(user_data, dict):
                        f.write(f"{user_id}:{json.dumps(user_data)}\n")
                    else:
                        # Legacy format - just username string
                        f.write(f"{user_id}:{user_data}\n")
            
            logger.info(f"💾 Saved {len(active_user_checks_dict)} active user checks to {self.active_checks_file}")
            
        except Exception as e:
            logger.error(f"Error saving active user checks: {e}")
    
    async def load_active_user_checks(self) -> Dict[int, Any]:
        """Load active user checks dictionary from file."""
        active_checks_dict = {}
        
        try:
            file_path = self.base_dir / self.active_checks_file
            if not file_path.exists():
                logger.info(f"Active user checks file {self.active_checks_file} not found, starting with empty dict")
                return active_checks_dict
            
            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if line and ':' in line:
                        try:
                            user_id_str, user_data_str = line.split(':', 1)
                            user_id = int(user_id_str)
                            
                            # Try to parse as JSON first (new format)
                            try:
                                user_data = json.loads(user_data_str)
                            except json.JSONDecodeError:
                                # Legacy format - just username string
                                user_data = user_data_str
                            
                            active_checks_dict[user_id] = user_data
                        except ValueError as e:
                            logger.warning(f"Invalid line {line_num} in active checks file: {line} - {e}")
            
            logger.info(f"Active user checks dict ({len(active_checks_dict)}) loaded from file")
            return active_checks_dict
            
        except Exception as e:
            logger.error(f"Error loading active user checks: {e}")
            return active_checks_dict
    
    async def save_report_file(self, file_type: str, data: str) -> bool:
        """Save data to daily report file."""
        try:
            today = datetime.now().strftime("%d-%m-%Y")
            
            # Determine directory based on file type
            if file_type.startswith('daily_spam_'):
                directory = self.base_dir / self.daily_spam_dir
            else:
                directory = self.base_dir / self.inout_dir
            
            # Create directory if it doesn't exist
            directory.mkdir(exist_ok=True)
            
            # Create filename
            filename = f"{file_type}{today}.txt"
            file_path = directory / filename
            
            # Append data to file
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(data + '\n')
            
            logger.debug(f"📝 Saved report to {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving report file: {e}")
            return False
    
    async def daily_cleanup(self) -> None:
        """Perform daily cleanup of old files."""
        try:
            today = datetime.now().strftime("%d-%m-%Y")
            
            # Archive current day's banned users
            banned_users_dict = await self.load_banned_users()
            if banned_users_dict:
                await self.save_report_file('banned_users_', 
                    '\n'.join(f"{uid}:{uname}" for uid, uname in banned_users_dict.items()))
            
            logger.info(f"✅ Daily cleanup completed for {today}")
            
        except Exception as e:
            logger.error(f"Error in daily cleanup: {e}")


# Convenience functions for backward compatibility
async def save_banned_users(banned_users_dict: Dict[int, str], base_dir: str = ".") -> None:
    """Save banned users dictionary to file."""
    persistence = DataPersistence(base_dir)
    await persistence.save_banned_users(banned_users_dict)


async def load_banned_users(base_dir: str = ".") -> Dict[int, str]:
    """Load banned users dictionary from file."""
    persistence = DataPersistence(base_dir)
    return await persistence.load_banned_users()


async def save_active_user_checks(active_checks_dict: Dict[int, Any], base_dir: str = ".") -> None:
    """Save active user checks dictionary to file."""
    persistence = DataPersistence(base_dir)
    await persistence.save_active_user_checks(active_checks_dict)


async def load_active_user_checks(base_dir: str = ".") -> Dict[int, Any]:
    """Load active user checks dictionary from file."""
    persistence = DataPersistence(base_dir)
    return await persistence.load_active_user_checks()


async def save_report_file(file_type: str, data: str, base_dir: str = ".") -> bool:
    """Save data to daily report file."""
    persistence = DataPersistence(base_dir)
    return await persistence.save_report_file(file_type, data)
