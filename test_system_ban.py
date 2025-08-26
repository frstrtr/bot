#!/usr/bin/env python3
"""Test script to verify system ban (banned_by=0) foreign key fix."""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from utils.database import DatabaseManager, BanRecord


async def test_system_ban_fix():
    """Test system ban with banned_by=0."""
    print("🔧 Testing system ban foreign key constraint fix...")
    
    # Initialize database
    db = DatabaseManager("test_system_ban.db")
    await db.initialize()
    
    try:
        # Test system ban (banned_by=0)
        print("\n📝 Test: Recording system ban (banned_by=0)...")
        ban_record = BanRecord(
            user_id=888888888,  # User that doesn't exist
            banned_by=0,        # System ban
            banned_at=datetime.now(),
            reason="System auto-ban",
            is_active=True
        )
        
        await db.record_ban(ban_record)
        print("✅ System ban record created successfully!")
        
        # Verify the ban was recorded
        is_banned = await db.is_user_banned(888888888)
        print(f"✅ User 888888888 banned status: {is_banned}")
        
        print("\n🎉 System ban foreign key constraint test passed!")
        
    except Exception as e:
        print(f"❌ System ban test failed: {e}")
        raise
    
    finally:
        # Clean up test database
        import os
        if os.path.exists("test_system_ban.db"):
            os.remove("test_system_ban.db")
            print("🗑️ Test database cleaned up")


if __name__ == "__main__":
    asyncio.run(test_system_ban_fix())
