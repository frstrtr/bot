"""Message validation utilities for bot handlers."""

from __future__ import annotations

from typing import List, Optional
from aiogram.types import Message
import logging

logger = logging.getLogger(__name__)


class MessageValidator:
    """Handles message validation and filtering logic."""
    
    def __init__(self, channel_ids: List[int] = None, allowed_forward_channels: List[int] = None):
        self.channel_ids = channel_ids or []
        self.allowed_forward_channels = allowed_forward_channels or []
    
    def is_forwarded_from_unknown_channel(self, message: Message) -> bool:
        """Check if message is forwarded from an unknown channel."""
        try:
            # Check if it's a forwarded message
            if not (message.forward_origin or message.forward_from_chat or message.forward_from):
                return False
            
            # Check forward origin (aiogram 3.x)
            if hasattr(message, 'forward_origin') and message.forward_origin:
                if hasattr(message.forward_origin, 'chat') and message.forward_origin.chat:
                    forward_chat_id = message.forward_origin.chat.id
                    return forward_chat_id not in self.allowed_forward_channels
            
            # Check legacy forward attributes
            if message.forward_from_chat:
                forward_chat_id = message.forward_from_chat.id
                return forward_chat_id not in self.allowed_forward_channels
            
            # If forwarded from user (not channel), consider it unknown
            if message.forward_from:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking forwarded message: {e}")
            return False
    
    def is_in_monitored_channel(self, message: Message) -> bool:
        """Check if message is in a monitored channel."""
        try:
            return message.chat.id in self.channel_ids
        except Exception as e:
            logger.error(f"Error checking monitored channel: {e}")
            return False
    
    def is_valid_message(self, message: Message) -> bool:
        """Check if message is valid for processing."""
        try:
            # Basic validation
            if not message or not message.from_user:
                return False
            
            # Skip bot messages
            if message.from_user.is_bot:
                return False
            
            # Skip service messages
            if (hasattr(message, 'new_chat_members') and message.new_chat_members) or \
               (hasattr(message, 'left_chat_member') and message.left_chat_member):
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating message: {e}")
            return False
    
    def is_admin_user_message(self, message: Message, admin_user_ids: List[int]) -> bool:
        """Check if message is from an admin user."""
        try:
            if not message or not message.from_user:
                return False
            
            return message.from_user.id in admin_user_ids
            
        except Exception as e:
            logger.error(f"Error checking admin user: {e}")
            return False
    
    def is_reply_to_admin_group(self, message: Message, admin_group_id: int) -> bool:
        """Check if message is a reply in the admin group."""
        try:
            return (message.chat.id == admin_group_id and 
                    message.reply_to_message is not None)
        except Exception as e:
            logger.error(f"Error checking admin group reply: {e}")
            return False


# Convenience functions for backward compatibility
def is_forwarded_from_unknown_channel(message: Message, allowed_forward_channels: List[int] = None) -> bool:
    """Check if message is forwarded from an unknown channel."""
    validator = MessageValidator(allowed_forward_channels=allowed_forward_channels or [])
    return validator.is_forwarded_from_unknown_channel(message)


def is_in_monitored_channel(message: Message, channel_ids: List[int] = None) -> bool:
    """Check if message is in a monitored channel."""
    validator = MessageValidator(channel_ids=channel_ids or [])
    return validator.is_in_monitored_channel(message)


def is_valid_message(message: Message) -> bool:
    """Check if message is valid for processing."""
    validator = MessageValidator()
    return validator.is_valid_message(message)


def is_admin_user_message(message: Message, admin_user_ids: List[int] = None) -> bool:
    """Check if message is from an admin user."""
    validator = MessageValidator()
    return validator.is_admin_user_message(message, admin_user_ids or [])
