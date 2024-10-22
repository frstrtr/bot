# database.py

"""
This module handles database operations for storing and retrieving spammer data.
"""

import sqlite3
import logging

LOGGER = logging.getLogger(__name__)

DATABASE_FILE = "spammers.db"

def initialize_database():
    """Initialize the database and create tables if they don't exist."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS spammers (
            user_id TEXT PRIMARY KEY,
            lols_bot_data TEXT,
            cas_chat_data TEXT,
            p2p_data TEXT
        )
    ''')
    conn.commit()
    conn.close()
    LOGGER.info("Database initialized")

def store_spammer_data(user_id, lols_bot_data, cas_chat_data, p2p_data):
    """Store spammer data in the database."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO spammers (user_id, lols_bot_data, cas_chat_data, p2p_data)
        VALUES (?, ?, ?, ?)
    ''', (user_id, lols_bot_data, cas_chat_data, p2p_data))
    conn.commit()
    conn.close()
    LOGGER.info("Stored spammer data for user_id: %s", user_id)

def retrieve_spammer_data(user_id):
    """Retrieve spammer data from the database."""
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT lols_bot_data, cas_chat_data, p2p_data FROM spammers WHERE user_id = ?
    ''', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        lols_bot_data, cas_chat_data, p2p_data = row
        return {
            "lols_bot_data": lols_bot_data,
            "cas_chat_data": cas_chat_data,
            "p2p_data": p2p_data
        }
    else:
        return None