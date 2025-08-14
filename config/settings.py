"""Modern configuration management using Pydantic settings."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Dict, Any, Optional

try:
    from pydantic import BaseModel, Field, field_validator
    from pydantic_settings import BaseSettings
    PYDANTIC_AVAILABLE = True
except ImportError:
    try:
        # Fallback for older pydantic
        from pydantic import BaseSettings, Field, validator as field_validator
        PYDANTIC_AVAILABLE = True
    except ImportError:
        # Ultimate fallback
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


class Settings(BaseSettings):
    """Application settings with validation."""
    
    # Bot settings
    BOT_TOKEN: str = Field(..., env="BOT_TOKEN")
    BOT_NAME: str = Field("SpamDetectorBot", env="BOT_NAME")
    
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
    CHANNEL_IDS: List[int] = Field(default_factory=list, env="CHANNEL_IDS")
    CHANNEL_NAMES: List[str] = Field(default_factory=list, env="CHANNEL_NAMES")
    
    # Spam detection
    SPAM_TRIGGERS: List[str] = Field(
        default_factory=lambda: ["url", "text_link", "email", "phone_number"],
        env="SPAM_TRIGGERS"
    )
    
    # Allowed forward channels
    ALLOWED_FORWARD_CHANNELS: List[Dict[str, Any]] = Field(
        default_factory=list,
        env="ALLOWED_FORWARD_CHANNELS"
    )
    
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
    SPAM_CHECK_INTERVALS: List[int] = Field(
        default_factory=lambda: [65, 185, 305, 605, 1205, 1805, 3605, 7205, 10805],
        env="SPAM_CHECK_INTERVALS"
    )
    
    # File paths
    SPAM_DICT_FILE: str = Field("spam_dict.txt", env="SPAM_DICT_FILE")
    LOG_LEVEL: str = Field("INFO", env="LOG_LEVEL")
    
    # Admin user IDs
    ADMIN_USER_IDS: List[int] = Field(default_factory=list, env="ADMIN_USER_IDS")
    
    @validator("CHANNEL_IDS", pre=True)
    def parse_channel_ids(cls, v):
        """Parse channel IDs from string or keep as list."""
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v
    
    @validator("CHANNEL_NAMES", pre=True) 
    def parse_channel_names(cls, v):
        """Parse channel names from string or keep as list."""
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v
    
    @validator("SPAM_TRIGGERS", pre=True)
    def parse_spam_triggers(cls, v):
        """Parse spam triggers from string or keep as list."""
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v
    
    @validator("SPAM_CHECK_INTERVALS", pre=True)
    def parse_spam_intervals(cls, v):
        """Parse spam check intervals from string or keep as list."""
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v
    
    @validator("ADMIN_USER_IDS", pre=True)
    def parse_admin_user_ids(cls, v):
        """Parse admin user IDs from string or keep as list.""" 
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True
        
        @classmethod
        def customise_sources(
            cls,
            init_settings: SettingsSourceCallable,
            env_settings: SettingsSourceCallable,
            file_secret_settings: SettingsSourceCallable,
        ) -> tuple[SettingsSourceCallable, ...]:
            """Customize settings sources priority."""
            return (
                init_settings,
                env_settings,
                file_secret_settings,
            )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


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
