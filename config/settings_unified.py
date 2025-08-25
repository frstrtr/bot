"""Unified configuration management for aiogram 3.x bot.

This file consolidates all settings in one place to eliminate confusion
and ensure all environment variables are properly loaded.
"""

import os
from pathlib import Path
from functools import lru_cache
from typing import List, Dict, Any, Optional


class Settings:
    """Unified settings class that loads from .env file and environment variables."""
    
    def __init__(self):
        """Initialize settings from environment and .env file."""
        
        # Load .env file if it exists
        env_file = Path(".env")
        env_vars = {}
        
        if env_file.exists():
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        env_vars[key.strip()] = value.strip()
        
        # Helper function to get value from .env or environment
        def get_env(key: str, default: str = '') -> str:
            return env_vars.get(key, os.getenv(key, default))
        
        def get_env_int(key: str, default: int = 0) -> int:
            value = get_env(key, str(default))
            try:
                return int(value) if value else default
            except ValueError:
                return default
        
        # ===== ESSENTIAL BOT CONFIGURATION =====
        self.BOT_TOKEN = get_env('BOT_TOKEN')
        self.BOT_NAME = get_env('BOT_NAME', 'Dr. Alfred Lanning')
        self.BOT_USER_ID = get_env_int('BOT_USER_ID')
        
        # ===== DATABASE CONFIGURATION =====
        self.DATABASE_URL = get_env('DATABASE_URL', 'aiogram3_messages.db')
        
        # ===== ADMIN CONFIGURATION =====
        # Single admin ID (for backwards compatibility)
        self.ADMIN_ID = get_env_int('ADMIN_ID')
        
        # Multiple admin user IDs (comma-separated list)
        admin_ids_str = get_env('ADMIN_USER_IDS')
        self.ADMIN_USER_IDS = self._parse_int_list(admin_ids_str)
        
        # ===== GROUP IDS (WHERE BOT OPERATES) =====
        self.ADMIN_GROUP_ID = get_env_int('ADMIN_GROUP_ID')
        self.TECHNOLOG_GROUP_ID = get_env_int('TECHNOLOG_GROUP_ID')
        self.LOG_GROUP_ID = get_env_int('LOG_GROUP_ID', self.ADMIN_GROUP_ID)
        
        # ===== THREAD IDS FOR FORUM-STYLE GROUPS =====
        # Admin group threads
        self.ADMIN_AUTOREPORTS = get_env_int('ADMIN_AUTOREPORTS', 1)
        self.ADMIN_AUTOBAN = get_env_int('ADMIN_AUTOBAN', 1)
        self.ADMIN_MANBAN = get_env_int('ADMIN_MANBAN', 1)
        self.ADMIN_SUSPICIOUS = get_env_int('ADMIN_SUSPICIOUS', 1)
        
        # Technolog group threads
        self.TECHNO_LOGGING = get_env_int('TECHNO_LOGGING', 1)
        self.TECHNO_ORIGINALS = get_env_int('TECHNO_ORIGINALS', 1)
        self.TECHNO_UNHANDLED = get_env_int('TECHNO_UNHANDLED', 1)
        self.TECHNO_RESTART = get_env_int('TECHNO_RESTART', 1)
        self.TECHNO_INOUT = get_env_int('TECHNO_INOUT', 1)
        self.TECHNO_NAMES = get_env_int('TECHNO_NAMES', 1)
        self.TECHNO_ADMIN = get_env_int('TECHNO_ADMIN', 1)
        
        # ===== MONITORED CHANNELS =====
        # Channel IDs (comma-separated list of channel IDs to monitor)
        channel_ids_str = get_env('CHANNEL_IDS')
        self.CHANNEL_IDS = self._parse_int_list(channel_ids_str)
        
        # Channel names (comma-separated list, must match CHANNEL_IDS order)
        channel_names_str = get_env('CHANNEL_NAMES')
        self.CHANNEL_NAMES = self._parse_string_list(channel_names_str)
        
        # ===== ALLOWED FORWARD CHANNELS =====
        # Channels whose forwarded messages bypass spam detection
        forward_channels_str = get_env('ALLOWED_FORWARD_CHANNELS')
        self.ALLOWED_FORWARD_CHANNELS = self._parse_int_list(forward_channels_str)
        
        # Forward channel names (must match ALLOWED_FORWARD_CHANNELS order)
        forward_names_str = get_env('ALLOWED_FORWARD_CHANNEL_NAMES')
        self.ALLOWED_FORWARD_CHANNEL_NAMES = self._parse_string_list(forward_names_str)
        
        # ===== SPAM DETECTION CONFIGURATION =====
        # Spam detection triggers
        spam_triggers_str = get_env('SPAM_TRIGGERS', 'url,email,phone_number,hashtag,mention,text_link')
        self.SPAM_TRIGGERS = self._parse_string_list(spam_triggers_str)
        
        # Spam check intervals (in seconds)
        intervals_str = get_env('SPAM_CHECK_INTERVALS', '65,185,305,605,1205,1805,3605,7205,10805')
        self.SPAM_CHECK_INTERVALS = self._parse_int_list(intervals_str)
        
        # Spam dictionary file
        self.SPAM_DICT_FILE = get_env('SPAM_DICT_FILE', 'spam_dict.txt')
        
        # ===== API CONFIGURATION =====
        # External API endpoints
        self.LOCAL_SPAM_API_URL = get_env('LOCAL_SPAM_API_URL', 'http://127.0.0.1:8081')
        self.CAS_API_URL = get_env('CAS_API_URL', 'https://api.cas.chat')
        self.LOLS_API_URL = get_env('LOLS_API_URL', 'https://api.lols.bot')
        
        # ===== RATE LIMITING & TIMEOUTS =====
        self.API_TIMEOUT = get_env_int('API_TIMEOUT', 10)
        self.RATE_LIMIT_CALLS = get_env_int('RATE_LIMIT_CALLS', 30)
        self.RATE_LIMIT_PERIOD = get_env_int('RATE_LIMIT_PERIOD', 60)
        self.MAX_MESSAGE_LENGTH = get_env_int('MAX_MESSAGE_LENGTH', 4096)
        
        # ===== WEBHOOK CONFIGURATION (OPTIONAL) =====
        self.WEBHOOK_URL = get_env('WEBHOOK_URL') or None
        self.WEBHOOK_PORT = get_env_int('WEBHOOK_PORT', 8000)
        self.WEBHOOK_SECRET = get_env('WEBHOOK_SECRET') or None
        
        # ===== LOGGING =====
        self.LOG_LEVEL = get_env('LOG_LEVEL', 'INFO')
    
    @property
    def CHANNEL_DICT(self) -> Dict[int, str]:
        """Create a mapping of channel IDs to names."""
        if len(self.CHANNEL_IDS) == len(self.CHANNEL_NAMES):
            return dict(zip(self.CHANNEL_IDS, self.CHANNEL_NAMES))
        return {}
    
    def _parse_int_list(self, value: str) -> List[int]:
        """Parse comma-separated string into list of integers."""
        if not value or not value.strip():
            return []
        try:
            return [int(x.strip()) for x in value.split(',') if x.strip()]
        except ValueError:
            return []
    
    def _parse_string_list(self, value: str) -> List[str]:
        """Parse comma-separated string into list of strings."""
        if not value or not value.strip():
            return []
        return [x.strip() for x in value.split(',') if x.strip()]
    
    def validate_required_fields(self) -> None:
        """Validate that all required fields are set."""
        required_fields = {
            'BOT_TOKEN': self.BOT_TOKEN,
            'BOT_USER_ID': self.BOT_USER_ID,
            'ADMIN_GROUP_ID': self.ADMIN_GROUP_ID,
            'TECHNOLOG_GROUP_ID': self.TECHNOLOG_GROUP_ID,
        }
        
        missing_fields = [
            field for field, value in required_fields.items() 
            if not value or (isinstance(value, int) and value == 0)
        ]
        
        if missing_fields:
            raise ValueError(f"Missing required configuration: {', '.join(missing_fields)}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return {
            key: getattr(self, key)
            for key in dir(self)
            if not key.startswith('_') and not callable(getattr(self, key))
        }
    
    def summary(self) -> str:
        """Return a summary of loaded configuration."""
        return f"""Configuration Summary:
Bot: {self.BOT_NAME} (ID: {self.BOT_USER_ID})
Admin Group: {self.ADMIN_GROUP_ID}
Technolog Group: {self.TECHNOLOG_GROUP_ID}
Monitored Channels: {len(self.CHANNEL_IDS)}
API Endpoints: Local, CAS, LOLS
Database: {self.DATABASE_URL}
Log Level: {self.LOG_LEVEL}"""


# Global settings instance cache
_settings: Optional[Settings] = None


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.validate_required_fields()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings from environment/file."""
    global _settings
    get_settings.cache_clear()
    _settings = None
    return get_settings()


# Legacy compatibility - keep the same interface
def load_legacy_config() -> Dict[str, Any]:
    """Load configuration from legacy XML format for migration (compatibility)."""
    import xml.etree.ElementTree as ET
    
    config_file = "config.xml"
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Configuration file {config_file} not found")
    
    tree = ET.parse(config_file)
    root = tree.getroot()
    
    config = {}
    
    # Extract bot settings
    bot_element = root.find("bot")
    if bot_element is not None:
        config["BOT_TOKEN"] = bot_element.get("token", "")
        config["BOT_NAME"] = bot_element.get("name", "SpamDetectorBot")
    
    # Extract groups
    groups_element = root.find("groups")
    if groups_element is not None:
        admin_group = groups_element.find("admin_group")
        if admin_group is not None:
            config["ADMIN_GROUP_ID"] = int(admin_group.get("id", "0"))
        
        techno_group = groups_element.find("technolog_group")
        if techno_group is not None:
            config["TECHNOLOG_GROUP_ID"] = int(techno_group.get("id", "0"))
        
        log_group = groups_element.find("log_group")
        if log_group is not None:
            config["LOG_GROUP_ID"] = int(log_group.get("id", "0"))
    
    return config


if __name__ == "__main__":
    # Test configuration loading
    try:
        settings = get_settings()
        print("✅ Configuration loaded successfully")
        print(settings.summary())
        
        # Show all loaded values for debugging
        print("\n=== All Configuration Values ===")
        for key, value in settings.to_dict().items():
            if 'TOKEN' in key and value:
                print(f"{key}: ✅ (hidden)")
            else:
                print(f"{key}: {value}")
                
    except Exception as e:
        print(f"❌ Configuration error: {e}")
