"""Modern database utilities with async support."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple, Union

import aiosqlite
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class DatabaseRecord(BaseModel):
    """Base model for database records."""
    
    class Config:
        arbitrary_types_allowed = True


class SpamRecord(DatabaseRecord):
    """Spam detection record."""
    user_id: int
    message_id: int
    chat_id: int
    detected_at: datetime
    spam_type: str
    confidence: float
    content_hash: Optional[str] = None


class BanRecord(DatabaseRecord):
    """Ban record."""
    user_id: int
    banned_by: int
    banned_at: datetime
    reason: str
    is_active: bool = True
    expires_at: Optional[datetime] = None


class ReportRecord(DatabaseRecord):
    """Report record."""
    report_id: str
    user_id: int
    reported_by: int
    chat_id: int
    message_id: int
    created_at: datetime
    status: str  # 'pending', 'approved', 'rejected'
    reason: str


class UserRecord(DatabaseRecord):
    """User activity record."""
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    last_seen: datetime
    message_count: int = 0
    spam_score: float = 0.0
    is_monitored: bool = False


class DatabaseManager:
    """Async database manager with connection pooling."""
    
    def __init__(self, database_url: str = "messages.db"):
        self.database_url = database_url
        self._connection_pool: Dict[int, aiosqlite.Connection] = {}
        self._lock = asyncio.Lock()
        
    async def initialize(self) -> None:
        """Initialize database with required tables."""
        async with self.get_connection() as conn:
            await self._create_tables(conn)
            logger.info("Database initialized successfully")
    
    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[aiosqlite.Connection, None]:
        """Get database connection with automatic cleanup."""
        conn = None
        try:
            conn = await aiosqlite.connect(self.database_url)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                await conn.close()
    
    async def _create_tables(self, conn: aiosqlite.Connection) -> None:
        """Create database tables if they don't exist."""
        
        # Users table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                message_count INTEGER DEFAULT 0,
                spam_score REAL DEFAULT 0.0,
                is_monitored BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Messages table (existing structure compatibility)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                user_id INTEGER,
                chat_id INTEGER,
                date TIMESTAMP,
                text TEXT,
                entities TEXT,
                forward_from_user_id INTEGER,
                forward_from_chat_id INTEGER,
                forward_from_message_id INTEGER,
                reply_to_message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        
        # Spam detection table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS spam_detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message_id INTEGER,
                chat_id INTEGER,
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                spam_type TEXT NOT NULL,
                confidence REAL DEFAULT 0.0,
                content_hash TEXT,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        """)
        
        # Bans table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                banned_by INTEGER,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reason TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                expires_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (banned_by) REFERENCES users (user_id)
            )
        """)
        
        # Reports table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT UNIQUE NOT NULL,
                user_id INTEGER,
                reported_by INTEGER,
                chat_id INTEGER,
                message_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending',
                reason TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (user_id),
                FOREIGN KEY (reported_by) REFERENCES users (user_id)
            )
        """)
        
        # Indexes for performance
        await conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages (user_id);
            CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages (chat_id);
            CREATE INDEX IF NOT EXISTS idx_messages_date ON messages (date);
            CREATE INDEX IF NOT EXISTS idx_spam_user_id ON spam_detections (user_id);
            CREATE INDEX IF NOT EXISTS idx_spam_detected_at ON spam_detections (detected_at);
            CREATE INDEX IF NOT EXISTS idx_bans_user_id ON bans (user_id);
            CREATE INDEX IF NOT EXISTS idx_bans_is_active ON bans (is_active);
            CREATE INDEX IF NOT EXISTS idx_reports_status ON reports (status);
            CREATE INDEX IF NOT EXISTS idx_reports_report_id ON reports (report_id);
        """)
        
        await conn.commit()
    
    # User operations
    async def upsert_user(self, user_record: UserRecord) -> None:
        """Insert or update user record."""
        async with self.get_connection() as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO users 
                (user_id, username, first_name, last_name, last_seen, message_count, spam_score, is_monitored)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_record.user_id,
                user_record.username,
                user_record.first_name,
                user_record.last_name,
                user_record.last_seen,
                user_record.message_count,
                user_record.spam_score,
                user_record.is_monitored
            ))
            await conn.commit()
    
    async def get_user(self, user_id: int) -> Optional[UserRecord]:
        """Get user by ID."""
        async with self.get_connection() as conn:
            cursor = await conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return UserRecord(**dict(row))
            return None
    
    async def update_user_activity(self, user_id: int) -> None:
        """Update user's last seen and increment message count."""
        async with self.get_connection() as conn:
            await conn.execute("""
                INSERT INTO users (user_id, last_seen, message_count) 
                VALUES (?, CURRENT_TIMESTAMP, 1)
                ON CONFLICT(user_id) DO UPDATE SET
                    last_seen = CURRENT_TIMESTAMP,
                    message_count = message_count + 1
            """, (user_id,))
            await conn.commit()
    
    # Message operations
    async def store_message(
        self,
        message_id: int,
        user_id: int,
        chat_id: int,
        date: datetime,
        text: Optional[str] = None,
        entities: Optional[str] = None,
        forward_from_user_id: Optional[int] = None,
        forward_from_chat_id: Optional[int] = None,
        forward_from_message_id: Optional[int] = None,
        reply_to_message_id: Optional[int] = None
    ) -> None:
        """Store message in database."""
        async with self.get_connection() as conn:
            await conn.execute("""
                INSERT OR IGNORE INTO messages 
                (message_id, user_id, chat_id, date, text, entities, 
                 forward_from_user_id, forward_from_chat_id, forward_from_message_id, reply_to_message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_id, user_id, chat_id, date, text, entities,
                forward_from_user_id, forward_from_chat_id, forward_from_message_id, reply_to_message_id
            ))
            await conn.commit()
    
    async def get_user_messages(
        self, 
        user_id: int, 
        limit: int = 100,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get user's recent messages."""
        async with self.get_connection() as conn:
            query = "SELECT * FROM messages WHERE user_id = ?"
            params = [user_id]
            
            if since:
                query += " AND date > ?"
                params.append(since)
            
            query += " ORDER BY date DESC LIMIT ?"
            params.append(limit)
            
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    # Alias for compatibility with migrated legacy logic
    async def fetch_user_messages(
        self,
        user_id: int,
        limit: int = 500,
        since: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Compatibility wrapper to fetch user messages (delegates to get_user_messages)."""
        return await self.get_user_messages(user_id=user_id, limit=limit, since=since)
    
    # Spam operations
    async def record_spam_detection(self, spam_record: SpamRecord) -> None:
        """Record spam detection."""
        async with self.get_connection() as conn:
            await conn.execute("""
                INSERT INTO spam_detections 
                (user_id, message_id, chat_id, detected_at, spam_type, confidence, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                spam_record.user_id,
                spam_record.message_id,
                spam_record.chat_id,
                spam_record.detected_at,
                spam_record.spam_type,
                spam_record.confidence,
                spam_record.content_hash
            ))
            await conn.commit()
    
    async def get_spam_history(
        self, 
        user_id: int, 
        hours: int = 24
    ) -> List[SpamRecord]:
        """Get user's spam detection history."""
        since = datetime.now() - timedelta(hours=hours)
        
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                SELECT * FROM spam_detections 
                WHERE user_id = ? AND detected_at > ?
                ORDER BY detected_at DESC
            """, (user_id, since))
            
            rows = await cursor.fetchall()
            return [SpamRecord(**dict(row)) for row in rows]
    
    # Ban operations
    async def record_ban(self, ban_record: BanRecord) -> None:
        """Record user ban."""
        async with self.get_connection() as conn:
            await conn.execute("""
                INSERT INTO bans 
                (user_id, banned_by, banned_at, reason, is_active, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                ban_record.user_id,
                ban_record.banned_by,
                ban_record.banned_at,
                ban_record.reason,
                ban_record.is_active,
                ban_record.expires_at
            ))
            await conn.commit()
    
    async def is_user_banned(self, user_id: int) -> bool:
        """Check if user is currently banned."""
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                SELECT 1 FROM bans 
                WHERE user_id = ? AND is_active = TRUE 
                AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            """, (user_id,))
            
            return await cursor.fetchone() is not None
    
    # Report operations
    async def store_report(self, report_record: ReportRecord) -> None:
        """Store user report."""
        async with self.get_connection() as conn:
            await conn.execute("""
                INSERT OR REPLACE INTO reports 
                (report_id, user_id, reported_by, chat_id, message_id, created_at, status, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                report_record.report_id,
                report_record.user_id,
                report_record.reported_by,
                report_record.chat_id,
                report_record.message_id,
                report_record.created_at,
                report_record.status,
                report_record.reason
            ))
            await conn.commit()
    
    async def get_pending_reports(self) -> List[ReportRecord]:
        """Get all pending reports."""
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                SELECT * FROM reports 
                WHERE status = 'pending'
                ORDER BY created_at ASC
            """)
            
            rows = await cursor.fetchall()
            return [ReportRecord(**dict(row)) for row in rows]
    
    async def update_report_status(self, report_id: str, status: str) -> None:
        """Update report status."""
        async with self.get_connection() as conn:
            await conn.execute("""
                UPDATE reports SET status = ? WHERE report_id = ?
            """, (status, report_id))
            await conn.commit()
    
    # Statistics and cleanup
    async def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics."""
        async with self.get_connection() as conn:
            stats = {}
            
            # User count
            cursor = await conn.execute("SELECT COUNT(*) FROM users")
            stats["total_users"] = (await cursor.fetchone())[0]
            
            # Message count
            cursor = await conn.execute("SELECT COUNT(*) FROM messages")
            stats["total_messages"] = (await cursor.fetchone())[0]
            
            # Spam detections (last 24h)
            since = datetime.now() - timedelta(hours=24)
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM spam_detections WHERE detected_at > ?", 
                (since,)
            )
            stats["spam_24h"] = (await cursor.fetchone())[0]
            
            # Active bans
            cursor = await conn.execute("""
                SELECT COUNT(*) FROM bans 
                WHERE is_active = TRUE 
                AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            """)
            stats["active_bans"] = (await cursor.fetchone())[0]
            
            # Pending reports
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM reports WHERE status = 'pending'"
            )
            stats["pending_reports"] = (await cursor.fetchone())[0]
            
            return stats
    
    async def cleanup_old_data(self, days: int = 30) -> None:
        """Clean up old data to manage database size."""
        cutoff = datetime.now() - timedelta(days=days)
        
        async with self.get_connection() as conn:
            # Clean old messages
            await conn.execute(
                "DELETE FROM messages WHERE date < ?", (cutoff,)
            )
            
            # Clean old spam detections
            await conn.execute(
                "DELETE FROM spam_detections WHERE detected_at < ?", (cutoff,)
            )
            
            # Clean expired bans
            await conn.execute("""
                UPDATE bans SET is_active = FALSE 
                WHERE expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP
            """)
            
            await conn.commit()
            logger.info(f"Cleaned up data older than {days} days")


# Global database instance
db_manager: Optional[DatabaseManager] = None


def get_database() -> DatabaseManager:
    """Get global database manager instance."""
    global db_manager
    if db_manager is None:
        from config.settings import get_settings
        settings = get_settings()
        db_manager = DatabaseManager(settings.DATABASE_URL)
    return db_manager


async def initialize_database() -> None:
    """Initialize database for the application."""
    db = get_database()
    await db.initialize()


# Legacy compatibility functions
async def legacy_execute_query(query: str, params: Tuple = ()) -> List[Dict[str, Any]]:
    """Execute legacy SQL query for compatibility."""
    db = get_database()
    async with db.get_connection() as conn:
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def legacy_execute_update(query: str, params: Tuple = ()) -> None:
    """Execute legacy SQL update for compatibility."""
    db = get_database()
    async with db.get_connection() as conn:
        await conn.execute(query, params)
        await conn.commit()
