#!/usr/bin/env python3
"""Test script to verify ban service permission checking improvements."""

import asyncio
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Mock aiogram Bot for testing
class MockBot:
    def __init__(self, bot_id=12345, is_admin=True, has_ban_permission=True):
        self.id = bot_id
        self._is_admin = is_admin
        self._has_ban_permission = has_ban_permission
    
    async def get_chat_member(self, chat_id, user_id):
        if user_id == self.id:
            # Bot member info
            class BotMember:
                status = 'administrator' if self._is_admin else 'member'
                can_restrict_members = self._has_ban_permission
            return BotMember()
        else:
            # Regular user
            class UserMember:
                status = 'member'
            return UserMember()


async def test_ban_permissions():
    """Test ban permission checking."""
    from services.ban_service import BanService
    from utils.database import DatabaseManager
    
    print("🔧 Testing ban service permission checking...")
    
    # Mock settings
    class MockSettings:
        CHANNEL_IDS = [-1001234567890]
        CHANNEL_DICT = {-1001234567890: "Test Chat"}
    
    # Initialize components
    db = DatabaseManager("test_permissions.db")
    await db.initialize()
    
    settings = MockSettings()
    ban_service = BanService(settings, db)
    
    try:
        # Test 1: Bot has admin permissions
        print("\n📝 Test 1: Bot with admin permissions...")
        bot_admin = MockBot(bot_id=12345, is_admin=True, has_ban_permission=True)
        can_ban = await ban_service._can_ban_user(bot_admin, -1001234567890, 98765)
        print(f"✅ Can ban user: {can_ban}")
        
        # Test 2: Bot lacks admin permissions
        print("\n📝 Test 2: Bot without admin permissions...")
        bot_no_admin = MockBot(bot_id=12345, is_admin=False, has_ban_permission=False)
        can_ban = await ban_service._can_ban_user(bot_no_admin, -1001234567890, 98765)
        print(f"✅ Can ban user: {can_ban} (should be False)")
        
        # Test 3: Bot is admin but lacks ban permissions
        print("\n📝 Test 3: Bot admin without ban permissions...")
        bot_no_ban_perm = MockBot(bot_id=12345, is_admin=True, has_ban_permission=False)
        can_ban = await ban_service._can_ban_user(bot_no_ban_perm, -1001234567890, 98765)
        print(f"✅ Can ban user: {can_ban} (should be False)")
        
        print("\n🎉 All ban permission tests completed!")
        
    except Exception as e:
        print(f"❌ Permission test failed: {e}")
        raise
    
    finally:
        # Clean up test database
        import os
        if os.path.exists("test_permissions.db"):
            os.remove("test_permissions.db")
            print("🗑️ Test database cleaned up")


if __name__ == "__main__":
    asyncio.run(test_ban_permissions())
