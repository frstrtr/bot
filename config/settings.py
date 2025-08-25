"""Modern configuration management using Pydantic settings."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Dict, Any, Optional, Union

try:
    from pydantic import BaseModel, Field, field_validator
    try:
        from pydantic_settings import BaseSettings, SettingsSourceCallable, SettingsConfigDict
    except ImportError:
        # Fallback for older pydantic versions where BaseSettings is in pydantic
        from pydantic import BaseSettings
        from typing import Callable, Any
        SettingsSourceCallable = Callable[[], dict[str, Any]]
        # Define a fallback SettingsConfigDict
        SettingsConfigDict = dict
    PYDANTIC_AVAILABLE = True
except ImportError:
    try:
        # Fallback for older pydantic versions where BaseSettings is in pydantic
        from pydantic import BaseSettings, Field, validator, field_validator
        # Define SettingsSourceCallable fallback
        from typing import Callable, Any
        SettingsSourceCallable = Callable[[], dict[str, Any]]
        SettingsConfigDict = dict
        PYDANTIC_AVAILABLE = True
    except ImportError:
        # Ultimate fallback when pydantic is not available
        PYDANTIC_AVAILABLE = False
        class BaseSettings:
            def __init__(self, **kwargs):
                for key, value in kwargs.items():
                    setattr(self, key, value)
        
        def Field(default=None, **kwargs):
            return default
        
        def field_validator(*args, **kwargs):
            def decorator(func):
                return func
            return decorator
        
        # Fallback type for SettingsSourceCallable
        from typing import Callable, Any
        SettingsSourceCallable = Callable[[], dict[str, Any]]


class Settings(BaseSettings):
    """Application settings with validation."""
    
    # Bot settings
    BOT_TOKEN: str = Field(..., env="BOT_TOKEN")
    BOT_NAME: str = Field("SpamDetectorBot", env="BOT_NAME")
    BOT_USER_ID: str = Field(..., env="BOT_USER_ID")
    
    # Database
    DATABASE_URL: str = Field("sqlite:///bot.db", env="DATABASE_URL")
    
    # Telegram settings
    ADMIN_GROUP_ID: int = Field(..., env="ADMIN_GROUP_ID")
    TECHNOLOG_GROUP_ID: int = Field(..., env="TECHNOLOG_GROUP_ID")
    LOG_GROUP_ID: int = Field(..., env="LOG_GROUP_ID")
    
    # Thread IDs
    ADMIN_AUTOBAN: int = Field(..., env="ADMIN_AUTOBAN")
    ADMIN_MANBAN: int = Field(..., env="ADMIN_MANBAN") 
    ADMIN_SUSPICIOUS: int = Field(..., env="ADMIN_SUSPICIOUS")
    ADMIN_AUTOREPORTS: int = Field(..., env="ADMIN_AUTOREPORTS")
    TECHNO_RESTART: int = Field(..., env="TECHNO_RESTART")
    TECHNO_INOUT: int = Field(..., env="TECHNO_INOUT")
    TECHNO_NAMES: int = Field(..., env="TECHNO_NAMES")
    TECHNO_ADMIN: int = Field(..., env="TECHNO_ADMIN")
    TECHNO_LOGGING: int = Field(..., env="TECHNO_LOGGING")
    TECHNO_ORIGINALS: int = Field(..., env="TECHNO_ORIGINALS")
    TECHNO_UNHANDLED: int = Field(..., env="TECHNO_UNHANDLED")
    
    # Monitored channels  
    CHANNEL_IDS: str = Field(default="", env="CHANNEL_IDS")
    CHANNEL_NAMES: str = Field(default="", env="CHANNEL_NAMES")
    
    # Spam detection
    SPAM_TRIGGERS: Union[str, List[str]] = Field(
        default_factory=lambda: ["url", "text_link", "email", "phone_number"],
        env="SPAM_TRIGGERS"
    )
    
    # Allowed forward channels
    ALLOWED_FORWARD_CHANNELS: Union[str, List[int]] = Field(default_factory=list, env="ALLOWED_FORWARD_CHANNELS")
    ALLOWED_FORWARD_CHANNEL_NAMES: Union[str, List[str]] = Field(default_factory=list, env="ALLOWED_FORWARD_CHANNEL_NAMES")
    
    # External APIs
    LOCAL_SPAM_API_URL: str = Field("http://127.0.0.1:8081", env="LOCAL_SPAM_API_URL")
    LOLS_API_URL: str = Field("https://api.lols.bot", env="LOLS_API_URL")
    CAS_API_URL: str = Field("https://api.cas.chat", env="CAS_API_URL")
    
    # Timeouts and limits
    API_TIMEOUT: int = Field(10, env="API_TIMEOUT")
    MAX_MESSAGE_LENGTH: int = Field(4096, env="MAX_MESSAGE_LENGTH")
    RATE_LIMIT_CALLS: int = Field(30, env="RATE_LIMIT_CALLS")
    RATE_LIMIT_PERIOD: int = Field(60, env="RATE_LIMIT_PERIOD")
    
    # Webhook settings (optional)
    WEBHOOK_URL: str | None = Field(None, env="WEBHOOK_URL")
    WEBHOOK_PORT: int = Field(8000, env="WEBHOOK_PORT")
    WEBHOOK_SECRET: str | None = Field(None, env="WEBHOOK_SECRET")
    
    # Monitoring intervals (in seconds)
    SPAM_CHECK_INTERVALS: Union[str, List[int]] = Field(
        default_factory=lambda: [65, 185, 305, 605, 1205, 1805, 3605, 7205, 10805],
        env="SPAM_CHECK_INTERVALS"
    )
    
    # File paths
    SPAM_DICT_FILE: str = Field("spam_dict.txt", env="SPAM_DICT_FILE")
    LOG_LEVEL: str = Field("INFO", env="LOG_LEVEL")
    
    # Admin user IDs
    ADMIN_USER_IDS: Union[str, List[int]] = Field(default_factory=list, env="ADMIN_USER_IDS")
    
    # Channel dictionary for ID->name mapping (computed property)
    @property
    def CHANNEL_DICT(self) -> Dict[int, str]:
        """Create a mapping of channel IDs to names."""
        channel_ids = self.CHANNEL_IDS or []
        channel_names = self.CHANNEL_NAMES or []
        if len(channel_ids) == len(channel_names):
            return dict(zip(channel_ids, channel_names))
        return {}
    
    @field_validator("CHANNEL_IDS", mode="before")
    @classmethod
    def parse_channel_ids(cls, v):
        """Parse channel IDs from string or keep as list."""
        if isinstance(v, str) and v.strip():
            result = [int(x.strip()) for x in v.split(",") if x.strip()]
            return result
        return v if v is not None else []

    @field_validator("CHANNEL_NAMES", mode="before")
    @classmethod
    def parse_channel_names(cls, v):
        """Parse channel names from string or keep as list."""
        if isinstance(v, str) and v.strip():
            return [x.strip() for x in v.split(",") if x.strip()]
        return v if v is not None else []
    
    @field_validator("SPAM_TRIGGERS", mode="before")
    @classmethod
    def parse_spam_triggers(cls, v):
        """Parse spam triggers from string or keep as list."""
        if isinstance(v, str) and v.strip():
            return [x.strip() for x in v.split(",") if x.strip()]
        return v if v is not None else ["url", "text_link", "email", "phone_number"]
    
    @field_validator("SPAM_CHECK_INTERVALS", mode="before")
    @classmethod
    def parse_spam_intervals(cls, v):
        """Parse spam check intervals from string or keep as list."""
        if isinstance(v, str) and v.strip():
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v if v is not None else [65, 185, 305, 605, 1205, 1805, 3605, 7205, 10805]
    
    @field_validator("ADMIN_USER_IDS", mode="before")
    @classmethod
    def parse_admin_user_ids(cls, v):
        """Parse admin user IDs from string or keep as list.""" 
        if isinstance(v, str) and v.strip():
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v if v is not None else []

    @field_validator("ALLOWED_FORWARD_CHANNELS", mode="before")
    @classmethod
    def parse_allowed_forward_channels(cls, v):
        """Parse allowed forward channels from string or keep as list."""
        if isinstance(v, str) and v.strip():
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v if v is not None else []

    @field_validator("ALLOWED_FORWARD_CHANNEL_NAMES", mode="before")
    @classmethod
    def parse_allowed_forward_channel_names(cls, v):
        """Parse allowed forward channel names from string or keep as list."""
        if isinstance(v, str) and v.strip():
            return [x.strip() for x in v.split(",") if x.strip()]
        return v if v is not None else []

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8", 
        "case_sensitive": False,  # Allow case insensitive env var matching
        "extra": "allow",  # Allow extra fields to avoid validation errors
    }
@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    # Load environment variables manually to ensure they're processed
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    # Create settings instance
    settings = Settings()
    
    # Manually apply environment variable parsing for fields that need it
    # This ensures the field validators are bypassed and we get the correct values
    
    # Parse CHANNEL_IDS
    channel_ids_str = os.getenv('CHANNEL_IDS', '')
    if channel_ids_str.strip():
        settings.CHANNEL_IDS = [int(x.strip()) for x in channel_ids_str.split(',') if x.strip()]
    
    # Parse CHANNEL_NAMES  
    channel_names_str = os.getenv('CHANNEL_NAMES', '')
    if channel_names_str.strip():
        settings.CHANNEL_NAMES = [x.strip() for x in channel_names_str.split(',') if x.strip()]
    
    # Parse ALLOWED_FORWARD_CHANNELS
    allowed_channels_str = os.getenv('ALLOWED_FORWARD_CHANNELS', '')
    if allowed_channels_str.strip():
        settings.ALLOWED_FORWARD_CHANNELS = [int(x.strip()) for x in allowed_channels_str.split(',') if x.strip()]
    
    # Parse ALLOWED_FORWARD_CHANNEL_NAMES
    allowed_names_str = os.getenv('ALLOWED_FORWARD_CHANNEL_NAMES', '')
    if allowed_names_str.strip():
        settings.ALLOWED_FORWARD_CHANNEL_NAMES = [x.strip() for x in allowed_names_str.split(',') if x.strip()]
    
    # Parse ADMIN_USER_IDS
    admin_ids_str = os.getenv('ADMIN_USER_IDS', '')
    if admin_ids_str.strip():
        settings.ADMIN_USER_IDS = [int(x.strip()) for x in admin_ids_str.split(',') if x.strip()]
    
    # Parse SPAM_TRIGGERS
    spam_triggers_str = os.getenv('SPAM_TRIGGERS', '')
    if spam_triggers_str.strip():
        settings.SPAM_TRIGGERS = [x.strip() for x in spam_triggers_str.split(',') if x.strip()]
    
    # Parse SPAM_CHECK_INTERVALS
    intervals_str = os.getenv('SPAM_CHECK_INTERVALS', '')
    if intervals_str.strip():
        settings.SPAM_CHECK_INTERVALS = [int(x.strip()) for x in intervals_str.split(',') if x.strip()]
    
    return settings


# Legacy compatibility layer for existing code
def load_legacy_config() -> Dict[str, Any]:
    """Load configuration from legacy XML format for migration."""
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
    
    # Extract channels
    channels_element = root.find("channels")
    if channels_element is not None:
        channel_ids = []
        channel_names = []
        for channel in channels_element.findall("channel"):
            channel_ids.append(int(channel.get("id", "0")))
            channel_names.append(channel.get("name", ""))
        config["CHANNEL_IDS"] = channel_ids
        config["CHANNEL_NAMES"] = channel_names
    
    # Extract thread IDs
    threads_element = root.find("threads")
    if threads_element is not None:
        for thread in threads_element:
            key = f"{thread.tag.upper()}"
            config[key] = int(thread.get("id", "0"))
    
    return config


def migrate_legacy_to_env() -> None:
    """Migrate legacy XML config to .env file."""
    try:
        legacy_config = load_legacy_config()
        
        env_lines = []
        for key, value in legacy_config.items():
            if isinstance(value, list):
                value = ",".join(str(v) for v in value)
            env_lines.append(f"{key}={value}")
        
        with open(".env", "w") as f:
            f.write("\n".join(env_lines))
        
        print("✅ Legacy configuration migrated to .env file")
        
    except Exception as e:
        print(f"❌ Failed to migrate legacy config: {e}")


if __name__ == "__main__":
    # CLI for migration
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "migrate":
        migrate_legacy_to_env()
    else:
        # Test configuration loading
        settings = get_settings()
        print("✅ Configuration loaded successfully")
        print(f"Bot name: {settings.BOT_NAME}")
        print(f"Monitoring {len(settings.CHANNEL_IDS)} channels")
