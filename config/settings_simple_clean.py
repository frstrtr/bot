"""Simple configuration management for aiogram 3.x bot."""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional


class Settings:
    """Simple settings class that loads from .env file."""
    
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
        
        # Bot settings
        self.BOT_TOKEN = env_vars.get('BOT_TOKEN', os.getenv('BOT_TOKEN', ''))
        self.BOT_NAME = env_vars.get('BOT_NAME', os.getenv('BOT_NAME', 'Modern Bot'))
        self.BOT_USER_ID = int(env_vars.get('BOT_USER_ID', os.getenv('BOT_USER_ID', '0')))
        
        # Database
        self.DATABASE_URL = env_vars.get('DATABASE_URL', os.getenv('DATABASE_URL', 'sqlite:///messages.db'))
        
        # Group IDs (where bot operates)
        self.ADMIN_GROUP_ID = int(env_vars.get('ADMIN_GROUP_ID', os.getenv('ADMIN_GROUP_ID', '0')))
        self.TECHNOLOG_GROUP_ID = int(env_vars.get('TECHNOLOG_GROUP_ID', os.getenv('TECHNOLOG_GROUP_ID', '0')))
        self.LOG_GROUP_ID = int(env_vars.get('LOG_GROUP_ID', os.getenv('LOG_GROUP_ID', str(self.ADMIN_GROUP_ID))))
        
        # Admin users (comma-separated list of user IDs)
        admin_ids_str = env_vars.get('ADMIN_USER_IDS', os.getenv('ADMIN_USER_IDS', ''))
        self.ADMIN_USER_IDS = self._parse_int_list(admin_ids_str)
        
        # Monitored channels (comma-separated list of channel IDs)
        channel_ids_str = env_vars.get('CHANNEL_IDS', os.getenv('CHANNEL_IDS', ''))
        self.CHANNEL_IDS = self._parse_int_list(channel_ids_str)
        
        # Channel names (comma-separated list, must match CHANNEL_IDS order)
        channel_names_str = env_vars.get('CHANNEL_NAMES', os.getenv('CHANNEL_NAMES', ''))
        self.CHANNEL_NAMES = self._parse_string_list(channel_names_str)
        
        # Allowed forward channels (messages from these channels bypass spam detection)
        forward_channels_str = env_vars.get('ALLOWED_FORWARD_CHANNELS', os.getenv('ALLOWED_FORWARD_CHANNELS', ''))
        self.ALLOWED_FORWARD_CHANNELS = self._parse_int_list(forward_channels_str)
        
        # Forward channel names (must match ALLOWED_FORWARD_CHANNELS order)
        forward_names_str = env_vars.get('ALLOWED_FORWARD_CHANNEL_NAMES', os.getenv('ALLOWED_FORWARD_CHANNEL_NAMES', ''))
        self.ALLOWED_FORWARD_CHANNEL_NAMES = self._parse_string_list(forward_names_str)
        
        # Spam detection triggers
        spam_triggers_str = env_vars.get('SPAM_TRIGGERS', os.getenv('SPAM_TRIGGERS', 'url,email,phone_number'))
        self.SPAM_TRIGGERS = self._parse_string_list(spam_triggers_str)
        
        # Thread IDs for different message types
        self.ADMIN_AUTOREPORTS = int(env_vars.get('ADMIN_AUTOREPORTS', os.getenv('ADMIN_AUTOREPORTS', '1')))
        self.ADMIN_AUTOBAN = int(env_vars.get('ADMIN_AUTOBAN', os.getenv('ADMIN_AUTOBAN', '1')))
        self.ADMIN_MANBAN = int(env_vars.get('ADMIN_MANBAN', os.getenv('ADMIN_MANBAN', '1')))
        self.ADMIN_SUSPICIOUS = int(env_vars.get('ADMIN_SUSPICIOUS', os.getenv('ADMIN_SUSPICIOUS', '1')))
        self.TECHNO_LOGGING = int(env_vars.get('TECHNO_LOGGING', os.getenv('TECHNO_LOGGING', '1')))
        self.TECHNO_ORIGINALS = int(env_vars.get('TECHNO_ORIGINALS', os.getenv('TECHNO_ORIGINALS', '1')))
        self.TECHNO_UNHANDLED = int(env_vars.get('TECHNO_UNHANDLED', os.getenv('TECHNO_UNHANDLED', '1')))
        self.TECHNO_RESTART = int(env_vars.get('TECHNO_RESTART', os.getenv('TECHNO_RESTART', '1')))
        self.TECHNO_INOUT = int(env_vars.get('TECHNO_INOUT', os.getenv('TECHNO_INOUT', '1')))
        self.TECHNO_NAMES = int(env_vars.get('TECHNO_NAMES', os.getenv('TECHNO_NAMES', '1')))
        self.TECHNO_ADMIN = int(env_vars.get('TECHNO_ADMIN', os.getenv('TECHNO_ADMIN', '1')))
        
        # Logging
        self.LOG_LEVEL = env_vars.get('LOG_LEVEL', os.getenv('LOG_LEVEL', 'INFO'))
        
        # API settings
        self.LOCAL_SPAM_API_URL = env_vars.get('LOCAL_SPAM_API_URL', os.getenv('LOCAL_SPAM_API_URL', 'http://127.0.0.1:8081'))
        self.CAS_API_URL = env_vars.get('CAS_API_URL', os.getenv('CAS_API_URL', 'https://api.cas.chat'))
        self.LOLS_API_URL = env_vars.get('LOLS_API_URL', os.getenv('LOLS_API_URL', 'https://api.lols.bot'))
        
        # Rate limiting
        self.API_TIMEOUT = int(env_vars.get('API_TIMEOUT', os.getenv('API_TIMEOUT', '10')))
        self.RATE_LIMIT_CALLS = int(env_vars.get('RATE_LIMIT_CALLS', os.getenv('RATE_LIMIT_CALLS', '30')))
        self.RATE_LIMIT_PERIOD = int(env_vars.get('RATE_LIMIT_PERIOD', os.getenv('RATE_LIMIT_PERIOD', '60')))
    
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return {
            key: getattr(self, key)
            for key in dir(self)
            if not key.startswith('_') and not callable(getattr(self, key))
        }


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance (singleton pattern)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


if __name__ == "__main__":
    # CLI for testing and configuration display
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "test":
            # Test configuration loading
            try:
                settings = get_settings()
                print("✅ Configuration loaded successfully")
                print(f"Bot name: {settings.BOT_NAME}")
                print(f"Bot token: {'***' + settings.BOT_TOKEN[-10:] if settings.BOT_TOKEN else 'NOT SET'}")
                print(f"Admin group: {settings.ADMIN_GROUP_ID}")
                print(f"Admin users: {settings.ADMIN_USER_IDS}")
                print(f"Monitoring {len(settings.CHANNEL_IDS)} channels")
                
                if settings.CHANNEL_IDS:
                    print("\n📋 Monitored Channels:")
                    for i, (channel_id, name) in enumerate(zip(settings.CHANNEL_IDS, settings.CHANNEL_NAMES)):
                        print(f"  {i+1}. {name} ({channel_id})")
                
                if hasattr(settings, 'ALLOWED_FORWARD_CHANNELS') and settings.ALLOWED_FORWARD_CHANNELS:
                    print(f"\n✅ Allowed Forward Channels ({len(settings.ALLOWED_FORWARD_CHANNELS)}):")
                    print("   (Messages forwarded from these channels bypass anti-spam)")
                    for i, (channel_id, name) in enumerate(zip(settings.ALLOWED_FORWARD_CHANNELS, settings.ALLOWED_FORWARD_CHANNEL_NAMES)):
                        print(f"  {i+1}. {name} ({channel_id})")
                
                if hasattr(settings, 'SPAM_TRIGGERS') and settings.SPAM_TRIGGERS:
                    print(f"\n🛡️  Spam Triggers ({len(settings.SPAM_TRIGGERS)}):")
                    print(f"  {', '.join(settings.SPAM_TRIGGERS)}")
            except Exception as e:
                print(f"❌ Configuration error: {e}")
        elif sys.argv[1] == "show":
            # Show current configuration
            settings = get_settings()
            config_dict = settings.to_dict()
            for key, value in sorted(config_dict.items()):
                if 'TOKEN' in key or 'SECRET' in key:
                    value = "***HIDDEN***"
                print(f"{key}: {value}")
    else:
        print("Usage: python config/settings.py [test|show]")
        print("  test    - Test configuration loading") 
        print("  show    - Show current configuration")
