"""UI utilities for creating keyboards and links."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


class UIBuilder:
    """Builds UI components like keyboards and links."""
    
    @staticmethod
    def build_lols_url(user_id: int) -> str:
        """Build LOLS bot deep link for a given user ID."""
        return f"https://t.me/lolsbotbot?start=u{user_id}"
    
    @staticmethod
    def make_lols_kb(user_id: int) -> InlineKeyboardMarkup:
        """Create inline keyboard with LOLS bot link."""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="🔍 Check in LOLS",
                url=UIBuilder.build_lols_url(user_id)
            )]
        ])
        return keyboard
    
    @staticmethod
    def make_ban_confirmation_keyboard(user_id: int) -> InlineKeyboardMarkup:
        """Create ban confirmation keyboard."""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Confirm Ban",
                    callback_data=f"confirmbanuser_{user_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Cancel",
                    callback_data=f"cancelbanuser_{user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Check in LOLS",
                    url=UIBuilder.build_lols_url(user_id)
                )
            ]
        ])
        return keyboard
    
    @staticmethod
    def make_user_action_keyboard(user_id: int) -> InlineKeyboardMarkup:
        """Create user action keyboard for suspicious users."""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚫 Ban User", 
                    callback_data=f"banuser_{user_id}"
                ),
                InlineKeyboardButton(
                    text="🛑 Stop Checks", 
                    callback_data=f"stopchecks_{user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Check in LOLS",
                    url=UIBuilder.build_lols_url(user_id)
                )
            ]
        ])
        return keyboard
    
    @staticmethod
    def make_suspicious_actions_keyboard(
        user_id: int, 
        chat_id: int, 
        message_id: int
    ) -> InlineKeyboardMarkup:
        """Create suspicious actions keyboard."""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚫 Ban", 
                    callback_data=f"suspiciousban_{user_id}_{chat_id}_{message_id}"
                ),
                InlineKeyboardButton(
                    text="🌍 Global Ban", 
                    callback_data=f"suspiciousglobalban_{user_id}_{chat_id}_{message_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🗑️ Delete Message", 
                    callback_data=f"suspiciousdelmsg_{user_id}_{chat_id}_{message_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Check in LOLS",
                    url=UIBuilder.build_lols_url(user_id)
                )
            ]
        ])
        return keyboard
    
    @staticmethod
    def format_user_mention(user_id: int, username: str = None, first_name: str = None) -> str:
        """Format a user mention with fallback options."""
        if username:
            return f"@{username}"
        elif first_name:
            return f"<a href='tg://user?id={user_id}'>{first_name}</a>"
        else:
            return f"<a href='tg://user?id={user_id}'>User {user_id}</a>"
    
    @staticmethod
    def create_message_link(chat_id: int, message_id: int, chat_username: str = None) -> str:
        """Create a link to a specific message."""
        if chat_username:
            return f"https://t.me/{chat_username}/{message_id}"
        else:
            # For private groups, use the format with removed -100 prefix
            chat_id_str = str(chat_id)
            if chat_id_str.startswith("-100"):
                chat_id_clean = chat_id_str[4:]  # Remove -100 prefix
                return f"https://t.me/c/{chat_id_clean}/{message_id}"
            else:
                return f"tg://openmessage?chat_id={chat_id}&message_id={message_id}"
    
    @staticmethod
    def create_message_link_from_message(message) -> str:
        """Create a link to a specific message from Message object."""
        if message.chat.username:
            return f"https://t.me/{message.chat.username}/{message.message_id}"
        else:
            # For private groups, use the format with removed -100 prefix
            chat_id_str = str(message.chat.id)
            if chat_id_str.startswith("-100"):
                chat_id_clean = chat_id_str[4:]  # Remove -100 prefix
                return f"https://t.me/c/{chat_id_clean}/{message.message_id}"
            else:
                return f"tg://openmessage?chat_id={message.chat.id}&message_id={message.message_id}"


# Convenience functions for backward compatibility
def build_lols_url(user_id: int) -> str:
    """Build LOLS bot deep link for a given user ID."""
    return UIBuilder.build_lols_url(user_id)


def make_lols_kb(user_id: int) -> InlineKeyboardMarkup:
    """Create inline keyboard with LOLS bot link."""
    return UIBuilder.make_lols_kb(user_id)


def make_ban_confirmation_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Create ban confirmation keyboard."""
    return UIBuilder.make_ban_confirmation_keyboard(user_id)


def make_user_action_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Create user action keyboard for suspicious users."""
    return UIBuilder.make_user_action_keyboard(user_id)


def format_user_mention(user_id: int, username: str = None, first_name: str = None) -> str:
    """Format a user mention with fallback options."""
    return UIBuilder.format_user_mention(user_id, username, first_name)


def create_message_link(chat_id: int, message_id: int, chat_username: str = None) -> str:
    """Create a link to a specific message."""
    return UIBuilder.create_message_link(chat_id, message_id, chat_username)


def create_message_link_from_message(message) -> str:
    """Create a link to a specific message from Message object."""
    return UIBuilder.create_message_link_from_message(message)
