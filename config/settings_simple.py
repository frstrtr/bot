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
        self.DATABASE_URL = env_vars.get('DATABASE_URL', os.getenv('DATABASE_URL', 'messages.db'))
        
        # Group IDs
        self.ADMIN_GROUP_ID = int(env_vars.get('ADMIN_GROUP_ID', os.getenv('ADMIN_GROUP_ID', '0')))
        self.TECHNOLOG_GROUP_ID = int(env_vars.get('TECHNOLOG_GROUP_ID', os.getenv('TECHNOLOG_GROUP_ID', '0')))
        self.LOG_GROUP_ID = int(env_vars.get('LOG_GROUP_ID', os.getenv('LOG_GROUP_ID', '0')))
        
        # Thread IDs
        self.ADMIN_AUTOBAN = int(env_vars.get('ADMIN_AUTOBAN', os.getenv('ADMIN_AUTOBAN', '0')))
        self.ADMIN_MANBAN = int(env_vars.get('ADMIN_MANBAN', os.getenv('ADMIN_MANBAN', '0')))
        self.ADMIN_SUSPICIOUS = int(env_vars.get('ADMIN_SUSPICIOUS', os.getenv('ADMIN_SUSPICIOUS', '0')))
        self.ADMIN_AUTOREPORTS = int(env_vars.get('ADMIN_AUTOREPORTS', os.getenv('ADMIN_AUTOREPORTS', '0')))
        self.TECHNO_RESTART = int(env_vars.get('TECHNO_RESTART', os.getenv('TECHNO_RESTART', '0')))
        self.TECHNO_INOUT = int(env_vars.get('TECHNO_INOUT', os.getenv('TECHNO_INOUT', '0')))
        self.TECHNO_NAMES = int(env_vars.get('TECHNO_NAMES', os.getenv('TECHNO_NAMES', '0')))
        self.TECHNO_ADMIN = int(env_vars.get('TECHNO_ADMIN', os.getenv('TECHNO_ADMIN', '0')))
        self.TECHNO_LOGGING = int(env_vars.get('TECHNO_LOGGING', os.getenv('TECHNO_LOGGING', '0')))
        self.TECHNO_ORIGINALS = int(env_vars.get('TECHNO_ORIGINALS', os.getenv('TECHNO_ORIGINALS', '0')))
        self.TECHNO_UNHANDLED = int(env_vars.get('TECHNO_UNHANDLED', os.getenv('TECHNO_UNHANDLED', '0')))
        
        # Admin users
        admin_users_str = env_vars.get('ADMIN_USER_IDS', os.getenv('ADMIN_USER_IDS', ''))
        self.ADMIN_USER_IDS = self._parse_int_list(admin_users_str)
        
        # Monitored channels
        channel_ids_str = env_vars.get('CHANNEL_IDS', os.getenv('CHANNEL_IDS', ''))
        self.CHANNEL_IDS = self._parse_int_list(channel_ids_str)
        
        channel_names_str = env_vars.get('CHANNEL_NAMES', os.getenv('CHANNEL_NAMES', ''))
        self.CHANNEL_NAMES = self._parse_string_list(channel_names_str)
        
        # Allowed forward channels
        allowed_forward_str = env_vars.get('ALLOWED_FORWARD_CHANNELS', os.getenv('ALLOWED_FORWARD_CHANNELS', ''))
        self.ALLOWED_FORWARD_CHANNELS = self._parse_int_list(allowed_forward_str)
        
        allowed_forward_names_str = env_vars.get('ALLOWED_FORWARD_CHANNEL_NAMES', os.getenv('ALLOWED_FORWARD_CHANNEL_NAMES', ''))
        self.ALLOWED_FORWARD_CHANNEL_NAMES = self._parse_string_list(allowed_forward_names_str)
        
        # Spam detection
        spam_triggers_str = env_vars.get('SPAM_TRIGGERS', os.getenv('SPAM_TRIGGERS', 'url,text_link,email,phone_number'))
        self.SPAM_TRIGGERS = self._parse_string_list(spam_triggers_str)
        
        # API endpoints
        self.LOCAL_SPAM_API_URL = env_vars.get('LOCAL_SPAM_API_URL', os.getenv('LOCAL_SPAM_API_URL', 'http://127.0.0.1:8081'))
        self.LOLS_API_URL = env_vars.get('LOLS_API_URL', os.getenv('LOLS_API_URL', 'https://api.lols.bot'))
        self.CAS_API_URL = env_vars.get('CAS_API_URL', os.getenv('CAS_API_URL', 'https://api.cas.chat'))
        
        # Timeouts and limits
        self.API_TIMEOUT = int(env_vars.get('API_TIMEOUT', os.getenv('API_TIMEOUT', '10')))
        self.MAX_MESSAGE_LENGTH = int(env_vars.get('MAX_MESSAGE_LENGTH', os.getenv('MAX_MESSAGE_LENGTH', '4096')))
        self.RATE_LIMIT_CALLS = int(env_vars.get('RATE_LIMIT_CALLS', os.getenv('RATE_LIMIT_CALLS', '30')))
        self.RATE_LIMIT_PERIOD = int(env_vars.get('RATE_LIMIT_PERIOD', os.getenv('RATE_LIMIT_PERIOD', '60')))
        
        # Webhook settings
        self.WEBHOOK_URL = env_vars.get('WEBHOOK_URL', os.getenv('WEBHOOK_URL'))
        self.WEBHOOK_PORT = int(env_vars.get('WEBHOOK_PORT', os.getenv('WEBHOOK_PORT', '8000')))
        self.WEBHOOK_SECRET = env_vars.get('WEBHOOK_SECRET', os.getenv('WEBHOOK_SECRET'))
        
        # File paths
        self.SPAM_DICT_FILE = env_vars.get('SPAM_DICT_FILE', os.getenv('SPAM_DICT_FILE', 'spam_dict.txt'))
        self.LOG_LEVEL = env_vars.get('LOG_LEVEL', os.getenv('LOG_LEVEL', 'INFO'))
        
        # Monitoring intervals
        intervals_str = env_vars.get('SPAM_CHECK_INTERVALS', os.getenv('SPAM_CHECK_INTERVALS', '65,185,305,605,1205,1805,3605,7205,10805'))
        self.SPAM_CHECK_INTERVALS = self._parse_int_list(intervals_str)
        
        # Validate required settings
        self._validate()
    
    def _parse_int_list(self, value: str) -> List[int]:
        """Parse comma-separated integers."""
        if not value:
            return []
        
        try:
            return [int(x.strip()) for x in value.split(',') if x.strip()]
        except ValueError:
            return []
    
    def _parse_string_list(self, value: str) -> List[str]:
        """Parse comma-separated strings."""
        if not value:
            return []
        
        return [x.strip() for x in value.split(',') if x.strip()]
    
    def _validate(self):
        """Validate required settings."""
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required. Please set it in .env file or environment variable.")
        
        if not self.BOT_TOKEN.count(':') == 1:
            raise ValueError("BOT_TOKEN format is invalid. Should be like: 123456789:ABCDEF...")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert settings to dictionary."""
        return {
            key: value for key, value in self.__dict__.items()
            if not key.startswith('_')
        }


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Reload settings from configuration."""
    global _settings
    _settings = Settings()
    return _settings


# Legacy compatibility functions
def load_legacy_config() -> Dict[str, Any]:
    """Load configuration from legacy XML format for migration."""
    import xml.etree.ElementTree as ET
    
    config_file = "config.xml"
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Configuration file {config_file} not found")
    
    tree = ET.parse(config_file)
    root = tree.getroot()
    
    config = {}
    
    # Map XML elements to environment variables
    xml_mappings = {
        'bot_token': 'BOT_TOKEN',
        'bot_name': 'BOT_NAME',
        'bot_userid': 'BOT_USER_ID',
        'log_group': 'ADMIN_GROUP_ID',
        'techno_log_group': 'TECHNOLOG_GROUP_ID',
        'admin_autoreports': 'ADMIN_AUTOREPORTS',
        'admin_autoban': 'ADMIN_AUTOBAN',
        'admin_manban': 'ADMIN_MANBAN',
        'admin_suspicious': 'ADMIN_SUSPICIOUS',
        'techno_logging': 'TECHNO_LOGGING',
        'techno_originals': 'TECHNO_ORIGINALS',
        'admin_id': 'ADMIN_USER_IDS'
    }
    
    # Extract values from XML
    for xml_key, env_key in xml_mappings.items():
        element = root.find(xml_key)
        if element is not None:
            config[env_key] = element.text or element.get('value', '')
    
    # Set LOG_GROUP_ID same as ADMIN_GROUP_ID if not specified
    if 'ADMIN_GROUP_ID' in config and 'LOG_GROUP_ID' not in config:
        config['LOG_GROUP_ID'] = config['ADMIN_GROUP_ID']
    
    return config


def migrate_legacy_to_env() -> None:
    """Migrate legacy XML config to .env file."""
    try:
        legacy_config = load_legacy_config()
        
        # Read existing .env if it exists
        env_file = Path(".env")
        existing_lines = []
        if env_file.exists():
            with open(env_file, 'r', encoding='utf-8') as f:
                existing_lines = f.readlines()
        
        # Update with legacy values
        env_lines = []
        env_lines.append("# Bot configuration migrated from XML\n")
        env_lines.append(f"# Generated on {Path(__file__).stat().st_mtime}\n\n")
        
        for key, value in legacy_config.items():
            env_lines.append(f"{key}={value}\n")
        
        # Add any additional lines from existing .env that weren't in XML
        for line in existing_lines:
            if line.strip() and not line.startswith('#') and '=' in line:
                key = line.split('=', 1)[0].strip()
                if key not in legacy_config:
                    env_lines.append(line)
        
        # Write updated .env
        with open(env_file, 'w', encoding='utf-8') as f:
            f.writelines(env_lines)
        
        print("✅ Legacy configuration migrated to .env file")
        
    except Exception as e:
        print(f"❌ Failed to migrate legacy config: {e}")


if __name__ == "__main__":
    # CLI for testing and migration
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "migrate":
            migrate_legacy_to_env()
        elif sys.argv[1] == "test":
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
        print("Usage: python config/settings.py [migrate|test|show]")
        print("  migrate - Migrate from XML to .env")
        print("  test    - Test configuration loading") 
        print("  show    - Show current configuration")
