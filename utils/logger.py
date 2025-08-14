"""Modern structured logging utilities."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter."""
    
    def __init__(self, include_extra: bool = True):
        super().__init__()
        self.include_extra = include_extra
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON."""
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields if enabled
        if self.include_extra:
            # Add custom fields from extra parameter
            for key, value in record.__dict__.items():
                if key not in {
                    'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                    'filename', 'module', 'lineno', 'funcName', 'created',
                    'msecs', 'relativeCreated', 'thread', 'threadName',
                    'processName', 'process', 'getMessage', 'exc_info',
                    'exc_text', 'stack_info'
                }:
                    try:
                        # Ensure value is JSON serializable
                        json.dumps(value)
                        log_data[key] = value
                    except (TypeError, ValueError):
                        log_data[key] = str(value)
        
        return json.dumps(log_data, ensure_ascii=False)


class TelegramLogHandler(logging.Handler):
    """Log handler that sends critical errors to Telegram."""
    
    def __init__(self, bot_token: str, chat_id: int, level: int = logging.ERROR):
        super().__init__(level)
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._last_send = {}
        self._rate_limit = 60  # seconds between duplicate messages
    
    def emit(self, record: logging.LogRecord) -> None:
        """Send log record to Telegram."""
        try:
            message = self.format(record)
            
            # Rate limiting for duplicate messages
            message_hash = hash(message)
            now = datetime.now().timestamp()
            
            if (message_hash in self._last_send and 
                now - self._last_send[message_hash] < self._rate_limit):
                return
            
            self._last_send[message_hash] = now
            
            # Send to Telegram (would need async implementation in real usage)
            # This is a placeholder for the actual implementation
            print(f"[TELEGRAM LOG] {message}")
            
        except Exception:
            self.handleError(record)


def setup_logger(
    name: str,
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    console_output: bool = True,
    structured: bool = True,
    telegram_bot_token: Optional[str] = None,
    telegram_chat_id: Optional[int] = None
) -> logging.Logger:
    """Setup logger with multiple handlers."""
    
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Formatters
    if structured:
        formatter = StructuredFormatter()
        console_formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        )
    
    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # Telegram handler for critical errors
    if telegram_bot_token and telegram_chat_id:
        telegram_handler = TelegramLogHandler(
            telegram_bot_token, 
            telegram_chat_id,
            level=logging.ERROR
        )
        telegram_handler.setFormatter(formatter)
        logger.addHandler(telegram_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """Get logger instance with standard configuration."""
    return logging.getLogger(name)


class BotLogger:
    """Central logger for the bot with context management."""
    
    def __init__(self, settings):
        self.settings = settings
        self._loggers: Dict[str, logging.Logger] = {}
        self._setup_root_logger()
    
    def _setup_root_logger(self) -> None:
        """Setup root logger configuration."""
        self.root_logger = setup_logger(
            name="bancop_bot",
            level=self.settings.LOG_LEVEL,
            log_file="logs/bot.log",
            structured=True,
            telegram_bot_token=getattr(self.settings, 'BOT_TOKEN', None),
            telegram_chat_id=getattr(self.settings, 'LOG_GROUP_ID', None)
        )
    
    def get_logger(self, name: str) -> logging.Logger:
        """Get or create logger for specific component."""
        if name not in self._loggers:
            full_name = f"bancop_bot.{name}"
            self._loggers[name] = logging.getLogger(full_name)
        return self._loggers[name]
    
    def log_user_action(
        self,
        user_id: int,
        action: str,
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log user action with structured data."""
        logger = self.get_logger("user_actions")
        
        log_data = {
            "user_id": user_id,
            "action": action,
            "chat_id": chat_id,
            "message_id": message_id,
            **(extra_data or {})
        }
        
        logger.info(f"User action: {action}", extra=log_data)
    
    def log_spam_detection(
        self,
        user_id: int,
        chat_id: int,
        message_id: int,
        spam_type: str,
        confidence: float,
        content_hash: Optional[str] = None
    ) -> None:
        """Log spam detection event."""
        logger = self.get_logger("spam_detection")
        
        log_data = {
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": message_id,
            "spam_type": spam_type,
            "confidence": confidence,
            "content_hash": content_hash
        }
        
        logger.warning(f"Spam detected: {spam_type}", extra=log_data)
    
    def log_ban_action(
        self,
        user_id: int,
        banned_by: int,
        reason: str,
        chat_id: Optional[int] = None,
        duration: Optional[str] = None
    ) -> None:
        """Log ban action."""
        logger = self.get_logger("ban_actions")
        
        log_data = {
            "user_id": user_id,
            "banned_by": banned_by,
            "reason": reason,
            "chat_id": chat_id,
            "duration": duration
        }
        
        logger.warning(f"User banned: {reason}", extra=log_data)
    
    def log_api_call(
        self,
        api_name: str,
        method: str,
        response_time: float,
        status_code: Optional[int] = None,
        error: Optional[str] = None
    ) -> None:
        """Log external API call."""
        logger = self.get_logger("api_calls")
        
        log_data = {
            "api_name": api_name,
            "method": method,
            "response_time": response_time,
            "status_code": status_code,
            "error": error
        }
        
        if error:
            logger.error(f"API call failed: {api_name}", extra=log_data)
        else:
            logger.info(f"API call: {api_name}", extra=log_data)
    
    def log_performance(
        self,
        operation: str,
        duration: float,
        success: bool = True,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Log performance metrics."""
        logger = self.get_logger("performance")
        
        log_data = {
            "operation": operation,
            "duration": duration,
            "success": success,
            **(details or {})
        }
        
        level = logging.INFO if success else logging.WARNING
        logger.log(level, f"Operation: {operation}", extra=log_data)


# Global logger instance
bot_logger: Optional[BotLogger] = None


def initialize_logger(settings) -> BotLogger:
    """Initialize global logger instance."""
    global bot_logger
    bot_logger = BotLogger(settings)
    return bot_logger


def get_bot_logger() -> BotLogger:
    """Get global bot logger instance."""
    if bot_logger is None:
        raise RuntimeError("Logger not initialized. Call initialize_logger() first.")
    return bot_logger


# Legacy logging compatibility
def legacy_log(message: str, level: str = "INFO") -> None:
    """Legacy logging function for compatibility."""
    logger = get_logger("legacy")
    level_num = getattr(logging, level.upper(), logging.INFO)
    logger.log(level_num, message)


# Context manager for timed operations
class LoggedOperation:
    """Context manager for logging timed operations."""
    
    def __init__(self, operation_name: str, logger_name: str = "operations"):
        self.operation_name = operation_name
        self.logger = get_logger(logger_name)
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.info(f"Starting operation: {self.operation_name}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self.start_time).total_seconds()
        
        if exc_type is None:
            self.logger.info(
                f"Completed operation: {self.operation_name}",
                extra={"duration": duration, "success": True}
            )
        else:
            self.logger.error(
                f"Failed operation: {self.operation_name}",
                extra={"duration": duration, "success": False, "error": str(exc_val)}
            )


# Utility functions
def log_function_call(func):
    """Decorator to log function calls."""
    import functools
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        
        try:
            logger.debug(f"Calling {func.__name__}")
            result = func(*args, **kwargs)
            logger.debug(f"Completed {func.__name__}")
            return result
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {e}")
            raise
    
    return wrapper


def log_async_function_call(func):
    """Decorator to log async function calls."""
    import functools
    
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        
        try:
            logger.debug(f"Calling async {func.__name__}")
            result = await func(*args, **kwargs)
            logger.debug(f"Completed async {func.__name__}")
            return result
        except Exception as e:
            logger.error(f"Error in async {func.__name__}: {e}")
            raise
    
    return wrapper
