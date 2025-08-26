#!/usr/bin/env python3
"""Test enhanced ban service error handling."""

import asyncio
import logging
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.append('/home/user0/bot')

from services.ban_service import BanService
from utils.database import DatabaseManager
from config.settings import Settings
from aiogram.exceptions import TelegramBadRequest

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_enhanced_error_handling():
    """Test the enhanced error handling in ban service."""
    
    # Mock dependencies
    mock_db = AsyncMock(spec=DatabaseManager)
    mock_settings = MagicMock(spec=Settings)
    mock_settings.CHANNEL_DICT = {
        -1001234567890: "Test Chat",
        -1001234567891: "Another Chat"
    }
    
    # Create ban service
    ban_service = BanService(mock_db, mock_settings)
    
    # Mock bot
    mock_bot = AsyncMock()
    mock_bot.id = 12345
    
    # Test case 1: User not found (deleted account)
    print("🧪 Testing deleted account error handling...")
    
    # Mock bot permissions check (success)
    mock_bot_member = MagicMock()
    mock_bot_member.status = 'administrator'
    mock_bot_member.can_restrict_members = True
    mock_bot.get_chat_member.return_value = mock_bot_member
    
    # Mock user not found error
    mock_bot.get_chat_member.side_effect = [
        mock_bot_member,  # Bot permissions check
        TelegramBadRequest(method="get_chat_member", message="Bad Request: user not found")  # User check
    ]
    
    can_ban, error_msg = await ban_service._can_ban_user_detailed(mock_bot, -1001234567890, 5382692684)
    
    print(f"DEBUG: can_ban={can_ban}, error_msg='{error_msg}'")
    assert not can_ban
    assert "user not found" in error_msg.lower() or "deleted account" in error_msg.lower()
    print(f"✅ Deleted account error: {error_msg}")
    
    # Test case 2: Deactivated account
    print("\n🧪 Testing deactivated account error handling...")
    
    mock_bot.get_chat_member.side_effect = [
        mock_bot_member,  # Bot permissions check
        TelegramBadRequest(method="get_chat_member", message="Bad Request: user account is deactivated")
    ]
    
    can_ban, error_msg = await ban_service._can_ban_user_detailed(mock_bot, -1001234567890, 5665816296)
    
    assert not can_ban
    assert "deactivated" in error_msg.lower()
    print(f"✅ Deactivated account error: {error_msg}")
    
    # Test case 3: User is admin
    print("\n🧪 Testing admin user error handling...")
    
    mock_admin_member = MagicMock()
    mock_admin_member.status = 'administrator'
    
    mock_bot.get_chat_member.side_effect = [
        mock_bot_member,  # Bot permissions check
        mock_admin_member  # User is admin
    ]
    
    can_ban, error_msg = await ban_service._can_ban_user_detailed(mock_bot, -1001234567890, 6673508384)
    
    assert not can_ban
    assert "admin" in error_msg.lower()
    print(f"✅ Admin user error: {error_msg}")
    
    # Test case 4: Valid user (should succeed)
    print("\n🧪 Testing valid user...")
    
    mock_valid_member = MagicMock()
    mock_valid_member.status = 'member'
    
    mock_bot.get_chat_member.side_effect = [
        mock_bot_member,  # Bot permissions check
        mock_valid_member  # Valid user
    ]
    
    can_ban, error_msg = await ban_service._can_ban_user_detailed(mock_bot, -1001234567890, 999999999)
    
    assert can_ban
    assert error_msg is None
    print(f"✅ Valid user check passed")
    
    print("\n🎉 All enhanced error handling tests passed!")

if __name__ == "__main__":
    asyncio.run(test_enhanced_error_handling())
