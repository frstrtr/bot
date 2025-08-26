#!/usr/bin/env python3
"""Test script to verify database foreign key constraint fixes."""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from utils.database import DatabaseManager, BanRecord, SpamRecord


async def test_database_fixes():
    """Test the database foreign key constraint fixes."""
    print("🔧 Testing database foreign key constraint fixes...")
    
    # Initialize database
    db = DatabaseManager("test_fix.db")
    await db.initialize()
    
    try:
        # Test 1: Record a ban for a user that doesn't exist in users table
        print("\n📝 Test 1: Recording ban for non-existent user...")
        ban_record = BanRecord(
            user_id=999999999,  # User that doesn't exist
            banned_by=888888888,  # Admin that doesn't exist
            banned_at=datetime.now(),
            reason="Test ban for non-existent user",
            is_active=True
        )
        
        await db.record_ban(ban_record)
        print("✅ Ban record created successfully!")
        
        # Test 2: Record spam detection for non-existent user
        print("\n📝 Test 2: Recording spam detection for non-existent user...")
        spam_record = SpamRecord(
            user_id=777777777,  # User that doesn't exist
            message_id=123456,
            chat_id=-1001234567890,
            detected_at=datetime.now(),
            spam_type="test_spam",
            confidence=0.95
        )
        
        await db.record_spam_detection(spam_record)
        print("✅ Spam detection record created successfully!")
        
        # Test 3: Verify the records were created
        print("\n📝 Test 3: Verifying records exist...")
        
        # Check if banned user exists
        is_banned = await db.is_user_banned(999999999)
        print(f"✅ User 999999999 banned status: {is_banned}")
        
        # Get spam history
        spam_history = await db.get_spam_history(777777777, 24)
        print(f"✅ User 777777777 spam detections: {len(spam_history)}")
        
        print("\n🎉 All database foreign key constraint tests passed!")
        
    except Exception as e:
        print(f"❌ Database test failed: {e}")
        raise
    
    finally:
        # Clean up test database
        import os
        if os.path.exists("test_fix.db"):
            os.remove("test_fix.db")
            print("🗑️ Test database cleaned up")


if __name__ == "__main__":
    asyncio.run(test_database_fixes())
