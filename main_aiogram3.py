#!/usr/bin/env python3
"""
Modern Telegram bot using aiogram 3.x with structured architecture.
This is a complete rewrite using the latest aiogram features.
"""

import asyncio
import logging
import sys
import html
import re
import time
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# Add aiocron for scheduled tasks
try:
    import aiocron
    from zoneinfo import ZoneInfo
    AIOCRON_AVAILABLE = True
except ImportError:
    print("⚠️  aiocron not available, scheduled tasks disabled")
    AIOCRON_AVAILABLE = False

# HTTP client for external APIs
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    print("⚠️  aiohttp not available, some features disabled")
    AIOHTTP_AVAILABLE = False

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# aiogram 3.x imports - with fallbacks for development
try:
    from aiogram import Bot, Dispatcher, BaseMiddleware
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode
    from aiogram.filters import Command, CommandStart
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.state import State, StatesGroup
    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.types import (
        Message, 
        CallbackQuery, 
        ChatMemberUpdated,
        InlineKeyboardButton,
        InlineKeyboardMarkup,
        Update,
        ErrorEvent
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    AIOGRAM_3_AVAILABLE = True
except ImportError as e:
    print(f"❌ aiogram 3.x not available: {e}")
    print("📦 Please install: pip install aiogram==3.15.0")
    sys.exit(1)

# Project imports with graceful fallbacks
try:
    from config.settings_simple import get_settings, Settings
    CONFIG_AVAILABLE = True
except ImportError:
    print("⚠️  config.settings_simple not available, using minimal config")
    CONFIG_AVAILABLE = False
    
    class Settings:
        BOT_TOKEN: str = ""
        LOG_LEVEL: str = "INFO"
        DATABASE_URL: str = "messages.db"
        ADMIN_GROUP_ID: int = 0
        TECHNOLOG_GROUP_ID: int = 0
    
    def get_settings():
        s = Settings()
        # Load from .env if available
        if Path(".env").exists():
            with open(".env") as f:
                for line in f:
                    if "=" in line and not line.startswith("#"):
                        key, value = line.strip().split("=", 1)
                        if hasattr(s, key):
                            try:
                                # Try to convert to appropriate type
                                if key.endswith("_ID") or key == "BOT_USER_ID":
                                    setattr(s, key, int(value))
                                else:
                                    setattr(s, key, value)
                            except ValueError:
                                setattr(s, key, value)
        return s

try:
    from utils.database import DatabaseManager, initialize_database
    from utils.utils import get_latest_commit_info
    from utils.persistence import DataPersistence
    from utils.message_validator import MessageValidator
    from utils.profile_manager import ProfileManager
    from utils.ui_builder import UIBuilder
    from utils.admin_manager import AdminManager
    DATABASE_AVAILABLE = True
except ImportError:
    print("⚠️  utils modules not available, using fallback")
    DATABASE_AVAILABLE = False
    
    class DatabaseManager:
        def __init__(self, *args, **kwargs): pass
        async def initialize(self): pass
        async def update_user_activity(self, user_id): pass
        async def store_message(self, *args, **kwargs): pass
    
    class DataPersistence:
        def __init__(self, *args, **kwargs): pass
        async def save_banned_users(self, *args): pass
        async def load_banned_users(self): return {}
        async def save_active_user_checks(self, *args): pass
        async def load_active_user_checks(self): return {}
        async def save_report_file(self, *args): return True
    
    class MessageValidator:
        def __init__(self, *args, **kwargs): pass
        def is_forwarded_from_unknown_channel(self, message): return False
        def is_in_monitored_channel(self, message): return False
        def is_valid_message(self, message): return True
        def is_admin_user_message(self, message, admin_ids): return False
    
    class ProfileManager:
        @staticmethod
        def make_profile_dict(*args, **kwargs): return {}
        @staticmethod
        def format_profile_field(*args, **kwargs): return ""
        @staticmethod
        def compare_profiles(*args, **kwargs): return False, ""
    
    class UIBuilder:
        @staticmethod
        def build_lols_url(user_id): return f"https://t.me/lolsbotbot?start=u{user_id}"
        @staticmethod
        def make_lols_kb(user_id): return InlineKeyboardMarkup(inline_keyboard=[])
        @staticmethod
        def make_ban_confirmation_keyboard(user_id): return InlineKeyboardMarkup(inline_keyboard=[])
    
    class AdminManager:
        def __init__(self, *args, **kwargs): pass
        def is_admin(self, user_id): return False
    
    async def initialize_database(): pass

try:
    from services.spam_service import SpamService, SpamDetectionResult
    SPAM_SERVICE_AVAILABLE = True
except ImportError:
    print("⚠️  services.spam_service not available, using fallback")
    SPAM_SERVICE_AVAILABLE = False
    
    class SpamDetectionResult:
        def __init__(self):
            self.is_spam = False
            self.confidence = 0.0
            self.spam_type = "none"
    
    class SpamService:
        def __init__(self, *args, **kwargs): pass
        async def initialize(self): pass
        async def close(self): pass
        async def analyze_message(self, message): return SpamDetectionResult()

try:
    from services.ban_service import BanService, BanResult
    BAN_SERVICE_AVAILABLE = True
except ImportError:
    print("⚠️  services.ban_service not available, using fallback")
    BAN_SERVICE_AVAILABLE = False
    
    class BanResult:
        def __init__(self, success=False, error_message="Service not available"):
            self.success = success
            self.error_message = error_message
    
    class BanService:
        def __init__(self, *args, **kwargs): pass
        async def initialize(self): pass
        async def ban_user(self, *args, **kwargs): return BanResult()
        async def unban_user(self, *args, **kwargs): return BanResult()
        async def check_auto_ban_conditions(self, *args, **kwargs): return None


# FSM States for aiogram 3.x
class BotStates(StatesGroup):
    waiting_for_report_reason = State()
    waiting_for_ban_reason = State()
    waiting_for_admin_command = State()


# Middleware for aiogram 3.x
class LoggingMiddleware(BaseMiddleware):
    """Middleware for logging all updates."""
    
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            logging.info(f"Message from {event.from_user.id}: {event.text[:50] if event.text else 'Non-text'}")
        elif isinstance(event, CallbackQuery):
            logging.info(f"Callback from {event.from_user.id}: {event.data}")
        
        return await handler(event, data)


class AdminMiddleware(BaseMiddleware):
    """Middleware to check admin permissions."""
    
    def __init__(self, admin_user_ids: list):
        self.admin_user_ids = admin_user_ids
    
    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.text and event.text.startswith('/'):
            # Check if command requires admin
            admin_commands = ['/ban', '/unban', '/stats', '/config']
            if any(event.text.startswith(cmd) for cmd in admin_commands):
                if event.from_user.id not in self.admin_user_ids:
                    await event.answer("❌ You don't have permission to use this command.")
                    return
        
        return await handler(event, data)


class ModernTelegramBot:
    """Modern Telegram bot using aiogram 3.x architecture."""
    
    def __init__(self):
        """Initialize the bot with aiogram 3.x patterns."""
        
        # Load settings
        self.settings = get_settings()
        
        # Validate configuration
        if not self.settings.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required in .env file")
        
        # Initialize utility modules
        self.persistence = DataPersistence() if DATABASE_AVAILABLE else DataPersistence()
        self.message_validator = MessageValidator(
            channel_ids=getattr(self.settings, 'CHANNEL_IDS', []),
            allowed_forward_channels=getattr(self.settings, 'ALLOWED_FORWARD_CHANNELS', [])
        ) if DATABASE_AVAILABLE else MessageValidator()
        self.admin_manager = AdminManager(
            admin_user_ids=getattr(self.settings, 'ADMIN_USER_IDS', [])
        ) if DATABASE_AVAILABLE else AdminManager()
        
        # Global dictionaries for tracking users (from aiogram 2.x compatibility)
        self.active_user_checks_dict = {}
        self.banned_users_dict = {}
        self.running_watchdogs = {}  # Track running monitoring tasks
        
        # Unhandled messages mapping (admin replies system)
        self.unhandled_messages = {}  # XXX: Should be moved to DB for persistence
        
        # Admin configuration
        self.admin_group_id = getattr(self.settings, 'ADMIN_GROUP_ID', None)
        self.technolog_group_id = getattr(self.settings, 'TECHNOLOG_GROUP_ID', None)
        
        # Configuration constants
        self.ADMIN_USER_ID = getattr(self.settings, 'ADMIN_ID', None)
        self.MAX_TELEGRAM_MESSAGE_LENGTH = 4096
        # Setup logging
        logging.basicConfig(
            level=getattr(logging, self.settings.LOG_LEVEL.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
        
        # Initialize bot with aiogram 3.x patterns
        self.bot = Bot(
            token=self.settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        
        # Initialize storage and dispatcher
        self.storage = MemoryStorage()
        self.dp = Dispatcher(storage=self.storage)
        
        # Services
        self.db_manager: Optional[DatabaseManager] = None
        self.spam_service: Optional[SpamService] = None
        self.ban_service: Optional[BanService] = None
        
        # Statistics
        self.stats = {
            'messages_processed': 0,
            'spam_detected': 0,
            'users_banned': 0,
            'start_time': None
        }
        
        # Setup middleware and handlers
        self._setup_middleware()
        self._register_handlers()
        
        # Setup scheduled tasks
        self.setup_scheduled_tasks()
    
    def _setup_middleware(self):
        """Setup middleware stack for aiogram 3.x."""
        
        # Logging middleware
        self.dp.message.middleware(LoggingMiddleware())
        self.dp.callback_query.middleware(LoggingMiddleware())
        
        # Admin middleware
        admin_ids = getattr(self.settings, 'ADMIN_USER_IDS', [])
        if isinstance(admin_ids, str):
            admin_ids = [int(x.strip()) for x in admin_ids.split(',') if x.strip()]
        elif isinstance(admin_ids, int):
            admin_ids = [admin_ids]
        
        if admin_ids:
            self.dp.message.middleware(AdminMiddleware(admin_ids))
    
    def _register_handlers(self):
        """Register message handlers using aiogram 3.x syntax."""
        
        # Start command
        @self.dp.message(CommandStart())
        async def cmd_start(message: Message):
            await self._handle_start_command(message)
        
        # Help command
        @self.dp.message(Command('help'))
        async def cmd_help(message: Message):
            await self._handle_help_command(message)
        
        # Admin commands
        @self.dp.message(Command('ban'))
        async def cmd_ban(message: Message, state: FSMContext):
            await self._handle_ban_command(message, state)
        
        @self.dp.message(Command('unban'))
        async def cmd_unban(message: Message, state: FSMContext):
            await self._handle_unban_command(message, state)
        
        @self.dp.message(Command('stats'))
        async def cmd_stats(message: Message):
            await self._handle_stats_command(message)
        
        # Missing admin commands from aiogram 2.x version
        @self.dp.message(Command('check'))
        async def cmd_check(message: Message):
            await self._handle_check_command(message)
        
        @self.dp.message(Command('loglists'))
        async def cmd_loglists(message: Message):
            await self._handle_loglists_command(message)
        
        @self.dp.message(Command('delmsg'))
        async def cmd_delmsg(message: Message):
            await self._handle_delmsg_command(message)
        
        @self.dp.message(Command('banchan'))
        async def cmd_banchan(message: Message):
            await self._handle_banchan_command(message)
        
        @self.dp.message(Command('unbanchan'))
        async def cmd_unbanchan(message: Message):
            await self._handle_unbanchan_command(message)
        
        # Message handlers for content processing
        @self.dp.message(lambda message: self._is_forwarded_from_unknown_channel(message))
        async def handle_forwarded_reports(message: Message):
            await self._handle_forwarded_message(message)
        
        # Monitor messages in tracked channels  
        @self.dp.message(lambda message: self._is_in_monitored_channel(message))
        async def store_recent_messages(message: Message):
            await self._handle_monitored_message(message)
        
        # Admin reply handler (must be before catch-all)
        @self.dp.message(lambda message: self._is_admin_user_message(message))
        async def handle_admin_reply(message: Message):
            await self._handle_admin_reply(message)
        
        # Catch-all handler for unhandled messages (must be last)
        @self.dp.message(lambda message: self._is_valid_message(message))
        async def log_all_unhandled_messages(message: Message):
            await self._handle_unhandled_message(message)
        
        # Chat member updates
        @self.dp.chat_member()
        async def chat_member_update(update: ChatMemberUpdated):
            await self._handle_chat_member_update(update)
        
        # Regular messages
        @self.dp.message()
        async def process_message(message: Message):
            await self._handle_message(message)
        
        # Callback queries
        @self.dp.callback_query()
        async def process_callback(callback_query: CallbackQuery, state: FSMContext):
            await self._handle_callback_query(callback_query, state)
        
        # Specific callback handlers for advanced functionality
        @self.dp.callback_query(lambda c: c.data.startswith("banuser_"))
        async def ask_ban_confirmation(callback_query: CallbackQuery):
            await self._handle_banuser_callback(callback_query)
        
        @self.dp.callback_query(lambda c: c.data.startswith("confirmbanuser_"))
        async def confirm_ban_user(callback_query: CallbackQuery):
            await self._handle_confirmban_callback(callback_query)
        
        @self.dp.callback_query(lambda c: c.data.startswith("cancelbanuser_"))
        async def cancel_ban_user(callback_query: CallbackQuery):
            await self._handle_cancelban_callback(callback_query)
        
        @self.dp.callback_query(lambda c: c.data.startswith("stopchecks_"))
        async def stop_user_checks(callback_query: CallbackQuery):
            await self._handle_stopchecks_callback(callback_query)
        @self.dp.callback_query(lambda c: c.data.startswith((
            "suspiciousactions_", "suspiciousglobalban_", "suspiciousban_", "suspiciousdelmsg_", 
            "confirmdelmsg_", "canceldelmsg_", "confirmban_", "cancelban_", "confirmglobalban_", "cancelglobalban_"
        )))
        async def handle_suspicious_callback(callback_query: CallbackQuery):
            await self._handle_suspicious_sender(callback_query)

        # Error handling
        @self.dp.error()
        async def error_handler(event: ErrorEvent):
            await self._handle_error(event)
        
        self.logger.info("✅ All handlers registered")
    
    async def setup_services(self):
        """Initialize all services."""
        try:
            # Database
            if DATABASE_AVAILABLE:
                self.db_manager = DatabaseManager(self.settings.DATABASE_URL)
                await self.db_manager.initialize()
                self.logger.info("✅ Database initialized")
            
            # Spam service
            if SPAM_SERVICE_AVAILABLE and self.db_manager:
                self.spam_service = SpamService(self.settings, self.db_manager)
                await self.spam_service.initialize()
                self.logger.info("✅ Spam service initialized")
            
            # Ban service
            if BAN_SERVICE_AVAILABLE and self.db_manager:
                self.ban_service = BanService(self.settings, self.db_manager)
                await self.ban_service.initialize()
                self.logger.info("✅ Ban service initialized")
            
            self.logger.info("🎉 All services initialized successfully")
            
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize services: {e}")
            raise
    
    # Handler implementations
    async def _handle_start_command(self, message: Message):
        """Handle /start command."""
        try:
            welcome_text = (
                "🤖 <b>Modern Spam Detection Bot</b>\n\n"
                "🚀 Running on aiogram 3.x\n"
                "🛡️ Advanced spam protection\n"
                "📊 Real-time monitoring\n\n"
                "Use /help for available commands."
            )
            
            await message.answer(welcome_text)
            
        except Exception as e:
            self.logger.error(f"Error in start command: {e}")
    
    async def _handle_help_command(self, message: Message):
        """Handle /help command."""
        try:
            help_text = (
                "📋 <b>Available Commands:</b>\n\n"
                "🔧 <b>General:</b>\n"
                "/start - Start the bot\n"
                "/help - Show this help\n"
                "/stats - Show statistics\n\n"
                "🛡️ <b>Moderation (Admin only):</b>\n"
                "/ban - Ban user (reply to message)\n"
                "/unban &lt;user_id&gt; - Unban user\n\n"
                "🤖 <b>Features:</b>\n"
                "• Automatic spam detection\n"
                "• Real-time user monitoring\n"
                "• Admin notifications\n"
                "• Comprehensive logging\n\n"
                "🚀 Powered by aiogram 3.x"
            )
            
            await message.answer(help_text)
            
        except Exception as e:
            self.logger.error(f"Error in help command: {e}")
    
    async def _handle_ban_command(self, message: Message, state: FSMContext):
        """Handle /ban command."""
        try:
            if not message.reply_to_message:
                await message.answer("❌ Please reply to a message to ban the user.")
                return
            
            target_user = message.reply_to_message.from_user
            
            if self.ban_service:
                result = await self.ban_service.ban_user(
                    bot=self.bot,
                    user_id=target_user.id,
                    chat_id=message.chat.id,
                    banned_by=message.from_user.id,
                    reason="Manual ban by admin"
                )
                
                if result.success:
                    await message.answer(f"✅ User {target_user.full_name} has been banned.")
                    self.stats['users_banned'] += 1
                else:
                    await message.answer(f"❌ Failed to ban user: {result.error_message}")
            else:
                await message.answer("❌ Ban service not available.")
                
        except Exception as e:
            self.logger.error(f"Error in ban command: {e}")
            await message.answer("❌ An error occurred while processing the ban command.")
    
    async def _handle_unban_command(self, message: Message, state: FSMContext):
        """Handle /unban command."""
        try:
            args = message.text.split()[1:] if message.text else []
            if not args:
                await message.answer("❌ Usage: /unban <user_id>")
                return
            
            try:
                user_id = int(args[0])
            except ValueError:
                await message.answer("❌ Invalid user ID.")
                return
            
            # Remove from banned and checks dicts
            if user_id in self.active_user_checks_dict:
                del self.active_user_checks_dict[user_id]
            if user_id in self.banned_users_dict:
                del self.banned_users_dict[user_id]
            
            # Cancel any running watchdog for this user
            await self.cancel_named_watchdog(f"monitor_{user_id}")
            
            # Unban from all channels
            unban_count = 0
            for channel_name in self.settings.CHANNEL_NAMES:
                channel_id = self.get_channel_id_by_name(channel_name)
                if channel_id:
                    try:
                        await self.bot.unban_chat_member(
                            chat_id=channel_id, 
                            user_id=user_id, 
                            only_if_banned=True
                        )
                        unban_count += 1
                        self.logger.info(f"Unbanned user {user_id} in channel {channel_name} (ID: {channel_id})")
                    except Exception as e:
                        self.logger.error(f"Failed to unban user {user_id} in channel {channel_name}: {e}")
            
            await message.answer(f"✅ User {user_id} has been unbanned from {unban_count} channels and removed from monitoring.")
                
        except Exception as e:
            self.logger.error(f"Error in unban command: {e}")
            await message.answer("❌ An error occurred while trying to unban the user.")
            await message.answer("❌ An error occurred while processing the unban command.")
    
    async def _handle_stats_command(self, message: Message):
        """Handle /stats command."""
        try:
            uptime = "Unknown"
            if self.stats['start_time']:
                uptime_seconds = asyncio.get_event_loop().time() - self.stats['start_time']
                hours, remainder = divmod(uptime_seconds, 3600)
                minutes, seconds = divmod(remainder, 60)
                uptime = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
            
            stats_text = (
                "📊 <b>Bot Statistics</b>\n\n"
                f"📨 Messages processed: <code>{self.stats['messages_processed']}</code>\n"
                f"🚫 Spam detected: <code>{self.stats['spam_detected']}</code>\n"
                f"🔨 Users banned: <code>{self.stats['users_banned']}</code>\n"
                f"⏰ Uptime: <code>{uptime}</code>\n\n"
                f"🚀 Running aiogram 3.x"
            )
            
            await message.answer(stats_text)
            
        except Exception as e:
            self.logger.error(f"Error in stats command: {e}")
            await message.answer("❌ An error occurred while getting statistics.")
    
    async def _handle_chat_member_update(self, update: ChatMemberUpdated):
        """Handle chat member updates."""
        try:
            if (update.new_chat_member.status == 'member' and 
                update.old_chat_member.status in ['left', 'kicked']):
                # User joined
                user = update.new_chat_member.user
                self.logger.info(f"User {user.id} ({user.full_name}) joined chat {update.chat.id}")
                
                # Check for auto-ban conditions
                if self.ban_service:
                    result = await self.ban_service.check_auto_ban_conditions(
                        bot=self.bot,
                        user_id=user.id,
                        chat_id=update.chat.id
                    )
                    
                    if result and result.success:
                        self.logger.info(f"Auto-banned user {user.id} upon joining")
                        self.stats['users_banned'] += 1
            
        except Exception as e:
            self.logger.error(f"Error handling chat member update: {e}")
    
    async def _handle_message(self, message: Message):
        """Handle regular messages."""
        try:
            self.stats['messages_processed'] += 1
            
            # Update user activity
            if self.db_manager:
                await self.db_manager.update_user_activity(message.from_user.id)
                
                # Store message
                await self.db_manager.store_message(
                    message_id=message.message_id,
                    user_id=message.from_user.id,
                    chat_id=message.chat.id,
                    date=message.date,
                    text=message.text or message.caption,
                    entities=str(message.entities) if message.entities else None
                )
            
            # Check for spam
            if self.spam_service:
                spam_result = await self.spam_service.analyze_message(message)
                
                if spam_result.is_spam:
                    self.stats['spam_detected'] += 1
                    
                    # Delete spam message
                    try:
                        await message.delete()
                        self.logger.info(f"Deleted spam message from user {message.from_user.id}")
                    except Exception as e:
                        self.logger.warning(f"Could not delete spam message: {e}")
                    
                    # Auto-ban for high confidence spam
                    if spam_result.confidence >= 0.9 and self.ban_service:
                        result = await self.ban_service.ban_user(
                            bot=self.bot,
                            user_id=message.from_user.id,
                            chat_id=message.chat.id,
                            banned_by=0,  # System ban
                            reason=f"Auto-ban: {spam_result.spam_type} (confidence: {spam_result.confidence:.2f})"
                        )
                        
                        if result.success:
                            self.stats['users_banned'] += 1
                            self.logger.info(f"Auto-banned user {message.from_user.id} for spam")
            
        except Exception as e:
            self.logger.error(f"Error handling message: {e}")
    
    async def _handle_callback_query(self, callback_query: CallbackQuery, state: FSMContext):
        """Handle callback queries."""
        try:
            await callback_query.answer()
            
            data = callback_query.data
            if data.startswith('ban_'):
                user_id = int(data.split('_')[1])
                # Handle ban approval
                pass
            elif data.startswith('report_'):
                report_id = data.split('_')[1]
                # Handle report processing
                pass
            
        except Exception as e:
            self.logger.error(f"Error handling callback query: {e}")
    
    async def _handle_check_command(self, message: Message):
        """Handle /check command - start 3hrs monitoring for user."""
        if not self._is_admin(message.from_user.id):
            await message.reply("❌ Admin access required")
            return
        
        try:
            command_args = message.text.split()
            if len(command_args) < 2:
                await message.reply("Please provide the user ID to check.\nUsage: /check <user_id>")
                return
            
            user_id = int(command_args[1])
            
            if user_id in self.active_user_checks_dict:
                user_data = self.active_user_checks_dict.get(user_id)
                display_name = user_data.get("username", "!UNDEFINED!") if isinstance(user_data, dict) else (user_data or "!UNDEFINED!")
                await message.reply(f"User <code>{display_name}</code> is already being checked.", parse_mode="HTML")
                return
            
            # Add user to checks
            self.active_user_checks_dict[user_id] = "!UNDEFINED!"
            
            # Start monitoring (simplified - the full implementation would start a coroutine)
            await message.reply(f"User {user_id} 3hrs monitoring activity check started.")
            self.logger.info(f"Manual check requested for user {user_id} by admin {message.from_user.id}")
            
        except ValueError:
            await message.reply("Invalid user ID. Please provide a numeric user ID.")
        except Exception as e:
            self.logger.error(f"Error in check command: {e}")
            await message.reply("An error occurred while starting the check.")
    
    async def _handle_loglists_command(self, message: Message):
        """Handle /loglists command - show active checks and banned users."""
        if not self._is_admin(message.from_user.id):
            await message.reply("❌ Admin access required")
            return
        
        try:
            active_count = len(self.active_user_checks_dict)
            banned_count = len(self.banned_users_dict)
            
            response = f"📊 <b>Bot Status</b>\n\n"
            response += f"🔍 <b>Active Checks:</b> {active_count}\n"
            response += f"🚫 <b>Banned Users:</b> {banned_count}\n\n"
            
            if self.active_user_checks_dict:
                response += "<b>Active User Checks:</b>\n"
                for user_id, user_name in list(self.active_user_checks_dict.items())[:10]:  # Limit to 10
                    display_name = user_name.get("username", "!UNDEFINED!") if isinstance(user_name, dict) else (user_name or "!UNDEFINED!")
                    response += f"• {user_id}: {display_name}\n"
                if len(self.active_user_checks_dict) > 10:
                    response += f"... and {len(self.active_user_checks_dict) - 10} more\n"
            
            if len(response) > self.MAX_TELEGRAM_MESSAGE_LENGTH:
                # Split into multiple messages if too long
                parts = [response[i:i+self.MAX_TELEGRAM_MESSAGE_LENGTH] for i in range(0, len(response), self.MAX_TELEGRAM_MESSAGE_LENGTH)]
                for part in parts:
                    await message.reply(part, parse_mode="HTML")
            else:
                await message.reply(response, parse_mode="HTML")
                
        except Exception as e:
            self.logger.error(f"Error in loglists command: {e}")
            await message.reply("An error occurred while fetching the lists.")
    
    async def _handle_delmsg_command(self, message: Message):
        """Handle /delmsg command - delete message by link."""
        if not self._is_admin(message.from_user.id):
            await message.reply("❌ Admin access required")
            return
        
        try:
            command_args = message.text.split()
            if len(command_args) < 2:
                await message.reply("Please provide the message link to delete.\nUsage: /delmsg <message_link>")
                return
            
            message_link = command_args[1]
            # This would need the implementation from the original bot to extract chat_id and message_id
            await message.reply(f"Message deletion functionality needs full implementation.\nLink: {message_link}")
            
        except Exception as e:
            self.logger.error(f"Error in delmsg command: {e}")
            await message.reply("An error occurred while deleting the message.")
    
    async def _handle_banchan_command(self, message: Message):
        """Handle /banchan command - ban channel by ID."""
        if not self._is_admin(message.from_user.id):
            await message.reply("❌ Admin access required")
            return
        
        try:
            command_args = message.text.split()
            if len(command_args) < 2:
                await message.reply("Please provide the channel ID to ban.\nUsage: /banchan <channel_id>")
                return
            
            channel_id = command_args[1].strip()
            if not channel_id.startswith("-100") or not channel_id[4:].isdigit():
                await message.reply("Invalid channel ID format. Please provide a valid channel ID.")
                return
            
            channel_id = int(channel_id)
            
            if channel_id in self.banned_users_dict:
                await message.reply(f"Channel {channel_id} already banned.")
                return
            
            # Add channel to banned list
            self.banned_users_dict[channel_id] = f"CHANNEL_BANNED_BY_ADMIN_{message.from_user.id}"
            await message.reply(f"Channel {channel_id} has been banned.")
            self.logger.info(f"Channel {channel_id} banned by admin {message.from_user.id}")
            
        except ValueError:
            await message.reply("Invalid channel ID. Please provide a numeric channel ID.")
        except Exception as e:
            self.logger.error(f"Error in banchan command: {e}")
            await message.reply("An error occurred while banning the channel.")
    
    async def _handle_unbanchan_command(self, message: Message):
        """Handle /unbanchan command - unban channel by ID."""
        if not self._is_admin(message.from_user.id):
            await message.reply("❌ Admin access required")
            return
        
        try:
            command_args = message.text.split()
            if len(command_args) < 2:
                await message.reply("Please provide the channel ID to unban.\nUsage: /unbanchan <channel_id>")
                return
            
            channel_id = int(command_args[1].strip())
            
            if channel_id not in self.banned_users_dict:
                await message.reply(f"Channel {channel_id} is not banned.")
                return
            
            # Remove channel from banned list
            del self.banned_users_dict[channel_id]
            await message.reply(f"Channel {channel_id} has been unbanned.")
            self.logger.info(f"Channel {channel_id} unbanned by admin {message.from_user.id}")
            
        except ValueError:
            await message.reply("Invalid channel ID. Please provide a numeric channel ID.")
        except Exception as e:
            self.logger.error(f"Error in unbanchan command: {e}")
            await message.reply("An error occurred while unbanning the channel.")
    
    def _is_admin(self, user_id: int) -> bool:
        """Check if user is admin."""
        return self.admin_manager.is_admin(user_id) or user_id == self.ADMIN_USER_ID
    
    async def _handle_banuser_callback(self, callback_query: CallbackQuery):
        """Handle banuser_* callbacks - ask for ban confirmation."""
        try:
            parts = callback_query.data.split("_")
            user_id = int(parts[1])
            
            # Get user info for display
            try:
                user_info = await self.bot.get_chat(user_id)
                username = user_info.username or "!UNDEFINED!"
                first_name = user_info.first_name or ""
                last_name = user_info.last_name or ""
                display_name = f"{first_name} {last_name}".strip() or username
            except:
                username = "!UNDEFINED!"
                display_name = "Unknown User"
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Yes, Ban", callback_data=f"confirmbanuser_{user_id}"),
                    InlineKeyboardButton(text="❌ No, Cancel", callback_data=f"cancelbanuser_{user_id}")
                ]
            ])
            
            await callback_query.message.edit_reply_markup(reply_markup=keyboard)
            await callback_query.answer(f"Confirm ban for {display_name}?")
            
        except Exception as e:
            self.logger.error(f"Error in banuser callback: {e}")
            await callback_query.answer("Error processing ban request")
    
    async def _handle_confirmban_callback(self, callback_query: CallbackQuery):
        """Handle confirmbanuser_* callbacks - execute the ban."""
        try:
            parts = callback_query.data.split("_")
            user_id = int(parts[1])
            
            # Use ban service to ban the user
            if self.ban_service:
                ban_result = await self.ban_service.ban_user(
                    user_id=user_id,
                    reason="Manual ban by admin",
                    admin_id=callback_query.from_user.id
                )
                
                if ban_result.success:
                    # Update banned users dict
                    self.banned_users_dict[user_id] = f"BANNED_BY_ADMIN_{callback_query.from_user.id}"
                    
                    # Remove keyboard and show ban confirmation
                    keyboard = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💀💀💀 B.A.N.N.E.D. 💀💀💀", url=f"https://api.lols.bot/account?id={user_id}")]
                    ])
                    
                    await callback_query.message.edit_reply_markup(reply_markup=keyboard)
                    await callback_query.answer("✅ User banned successfully!")
                    
                    self.logger.info(f"User {user_id} banned by admin {callback_query.from_user.id}")
                else:
                    await callback_query.answer(f"❌ Ban failed: {ban_result.error_message}")
            else:
                await callback_query.answer("❌ Ban service not available")
                
        except Exception as e:
            self.logger.error(f"Error in confirmban callback: {e}")
            await callback_query.answer("Error executing ban")
    
    async def _handle_cancelban_callback(self, callback_query: CallbackQuery):
        """Handle cancelbanuser_* callbacks - cancel the ban."""
        try:
            # Remove keyboard
            await callback_query.message.edit_reply_markup(reply_markup=None)
            await callback_query.answer("❌ Ban cancelled")
            
        except Exception as e:
            self.logger.error(f"Error in cancelban callback: {e}")
            await callback_query.answer("Error cancelling ban")
    
    async def _handle_stopchecks_callback(self, callback_query: CallbackQuery):
        """Handle stopchecks_* callbacks - stop user monitoring."""
        try:
            parts = callback_query.data.split("_")
            user_id = int(parts[1])
            
            # Remove user from active checks
            if user_id in self.active_user_checks_dict:
                user_data = self.active_user_checks_dict[user_id]
                del self.active_user_checks_dict[user_id]
                
                display_name = user_data.get("username", "!UNDEFINED!") if isinstance(user_data, dict) else (user_data or "!UNDEFINED!")
                
                # Remove keyboard
                await callback_query.message.edit_reply_markup(reply_markup=None)
                await callback_query.answer(f"✅ Stopped monitoring {display_name}")
                
                self.logger.info(f"Stopped monitoring user {user_id} by admin {callback_query.from_user.id}")
            else:
                await callback_query.answer("User not being monitored")
                
        except Exception as e:
            self.logger.error(f"Error in stopchecks callback: {e}")
            await callback_query.answer("Error stopping checks")
    
    async def _handle_suspicious_sender(self, callback_query: CallbackQuery):
        """Handle suspicious sender callback actions with confirmation flow."""
        try:
            data = callback_query.data
            parts = data.split("_")
            
            if len(parts) < 4:
                self.logger.error(f"Invalid callback data format: {data}")
                await callback_query.answer("Invalid action data.", show_alert=True)
                return
                
            action_prefix = parts[0]
            susp_chat_id = int(parts[1])
            susp_message_id = int(parts[2])
            susp_user_id = int(parts[3])
            
            # Determine action based on prefix
            action_map = {
                "suspiciousactions": "actions",
                "suspiciousglobalban": "globalban",
                "suspiciousban": "ban", 
                "suspiciousdelmsg": "delmsg",
                "confirmglobalban": "confirmglobalban",
                "cancelglobalban": "cancelglobalban",
                "confirmban": "confirmban",
                "cancelban": "cancelban",
                "confirmdelmsg": "confirmdelmsg",
                "canceldelmsg": "canceldelmsg"
            }
            
            action = action_map.get(action_prefix)
            if not action:
                self.logger.error(f"Unknown action prefix: {action_prefix}")
                await callback_query.answer("Unknown action.", show_alert=True)
                return
                
            # Get user and chat info
            susp_chat_title = self.settings.CHANNEL_DICT.get(susp_chat_id, "!UNKNOWN!")
            admin_id = callback_query.from_user.id
            admin_username = callback_query.from_user.username or "!NoName!"
            
            # Get user info from active checks
            user_info = self.active_user_checks_dict.get(susp_user_id, "!UNDEFINED!")
            if isinstance(user_info, dict):
                susp_user_name = str(user_info.get("username", "")).lstrip("@")
            else:
                susp_user_name = str(user_info)
                
            # Create message and spam check links
            message_link = self.ui_builder.create_message_link(susp_chat_id, susp_message_id)
            lols_link = self.build_lols_url(susp_user_id)
            
            # Create inline keyboard with links
            kb = InlineKeyboardBuilder()
            kb.row(InlineKeyboardButton(text="🔗 View Original Message 🔗", url=message_link))
            kb.row(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))
            
            callback_answer = None
            
            # Consolidated actions expansion
            if action == "actions":
                kb.row(
                    InlineKeyboardButton(text="🌐 Global Ban", callback_data=f"suspiciousglobalban_{susp_chat_id}_{susp_message_id}_{susp_user_id}"),
                    InlineKeyboardButton(text="🚫 Ban User", callback_data=f"suspiciousban_{susp_chat_id}_{susp_message_id}_{susp_user_id}")
                )
                kb.row(
                    InlineKeyboardButton(text="🗑 Delete Msg", callback_data=f"suspiciousdelmsg_{susp_chat_id}_{susp_message_id}_{susp_user_id}")
                )
                await callback_query.message.edit_reply_markup(reply_markup=kb.as_markup())
                await callback_query.answer()
                return

            # Handle confirmation flow actions
            if action in ["globalban", "ban", "delmsg"]:
                # Add confirmation buttons
                if action == "globalban":
                    kb.row(
                        InlineKeyboardButton(text="Confirm global ban", callback_data=f"confirmglobalban_{susp_chat_id}_{susp_message_id}_{susp_user_id}"),
                        InlineKeyboardButton(text="Cancel global ban", callback_data=f"cancelglobalban_{susp_chat_id}_{susp_message_id}_{susp_user_id}")
                    )
                elif action == "ban":
                    kb.row(
                        InlineKeyboardButton(text="Confirm ban", callback_data=f"confirmban_{susp_chat_id}_{susp_message_id}_{susp_user_id}"),
                        InlineKeyboardButton(text="Cancel ban", callback_data=f"cancelban_{susp_chat_id}_{susp_message_id}_{susp_user_id}")
                    )
                elif action == "delmsg":
                    kb.row(
                        InlineKeyboardButton(text="Confirm delmsg", callback_data=f"confirmdelmsg_{susp_chat_id}_{susp_message_id}_{susp_user_id}"),
                        InlineKeyboardButton(text="Cancel delmsg", callback_data=f"canceldelmsg_{susp_chat_id}_{susp_message_id}_{susp_user_id}")
                    )
                    
                # Update message with confirmation buttons
                await callback_query.message.edit_reply_markup(reply_markup=kb.as_markup())
                await callback_query.answer()
                return
                
            # Handle actual actions
            elif action == "confirmglobalban":
                try:
                    # Delete message if not synthetic
                    if len(str(susp_message_id)) < 13 and susp_message_id < 4_000_000_000:
                        await self.bot.delete_message(susp_chat_id, susp_message_id)
                    else:
                        self.logger.debug(f"Skip delete for synthetic message_id={susp_message_id} chat_id={susp_chat_id}")
                        
                    # Bulk delete all tracked messages for this user (DB + active tracking heuristics)
                    total_attempt = 0
                    total_deleted = 0
                    # If database manager supports fetching messages, implement placeholder logic
                    if hasattr(self, 'db_manager') and self.db_manager:
                        try:
                            # Expect a method or direct query; placeholder: self.db_manager.fetch_user_messages(user_id)
                            if hasattr(self.db_manager, 'fetch_user_messages'):
                                user_msgs = await self.db_manager.fetch_user_messages(susp_user_id)
                            else:
                                user_msgs = []  # Not implemented in modern DB layer
                            for rec in user_msgs:
                                try:
                                    chat_id_rec = rec.get('chat_id') if isinstance(rec, dict) else rec[0]
                                    msg_id_rec = rec.get('message_id') if isinstance(rec, dict) else rec[1]
                                    total_attempt += 1
                                    if len(str(msg_id_rec)) < 13 and msg_id_rec < 4_000_000_000:
                                        await self.bot.delete_message(chat_id_rec, msg_id_rec)
                                        total_deleted += 1
                                except Exception as _e_del:
                                    self.logger.debug(f"Unable to delete recorded message {rec}: {_e_del}")
                        except Exception as _e_db_fetch:
                            self.logger.debug(f"Skip DB bulk fetch for user {susp_user_id}: {_e_db_fetch}")
                    # Heuristic extra deletion from active checks dict
                    extra_attempt = 0
                    extra_deleted = 0
                    active_entry = self.active_user_checks_dict.get(susp_user_id)
                    if isinstance(active_entry, dict):
                        for _k, _v in active_entry.items():
                            if isinstance(_v, list):
                                for item in _v:
                                    chat_candidate = None
                                    msg_candidate = None
                                    if isinstance(item, tuple) and len(item) >= 2 and all(isinstance(x, int) for x in item[:2]):
                                        chat_candidate, msg_candidate = item[0], item[1]
                                    elif isinstance(item, int):
                                        chat_candidate, msg_candidate = susp_chat_id, item
                                    if chat_candidate is None or msg_candidate is None:
                                        continue
                                    extra_attempt += 1
                                    try:
                                        if len(str(msg_candidate)) < 13 and msg_candidate < 4_000_000_000:
                                            await self.bot.delete_message(chat_candidate, msg_candidate)
                                            extra_deleted += 1
                                    except Exception as _e_del2:
                                        self.logger.debug(f"Active-check extra delete fail {msg_candidate} in {chat_candidate}: {_e_del2}")
                    if total_attempt or extra_attempt:
                        self.logger.info(
                            f"Global ban cleanup for {susp_user_id}: attempts main={total_attempt} deleted={total_deleted} extra={extra_attempt}/{extra_deleted}"
                        )

                    # Global ban user
                    await self.ban_user_from_all_chats(susp_user_id, susp_user_name, f"Suspicious activity - Admin decision by @{admin_username}")
                    
                    self.logger.info(f"{susp_user_id}:@{susp_user_name} SUSPICIOUS banned globally by admin @{admin_username}({admin_id})")
                    callback_answer = "User banned globally and message deleted!"
                    
                    # Report to P2P spam server
                    await self.report_spam_2p2p(susp_user_id)
                        
                    # Cancel user checks
                    if susp_user_id in self.active_user_checks_dict:
                        del self.active_user_checks_dict[susp_user_id]
                        
                except Exception as e:
                    self.logger.error(f"Global ban failed: {e}")
                    callback_answer = "Failed to ban user globally."
                    
            elif action == "confirmban":
                try:
                    # Delete message if not synthetic 
                    if len(str(susp_message_id)) < 13 and susp_message_id < 4_000_000_000:
                        await self.bot.delete_message(susp_chat_id, susp_message_id)
                    else:
                        self.logger.debug(f"Skip delete for synthetic message_id={susp_message_id} chat_id={susp_chat_id}")
                        
                    # Local chat cleanup of tracked messages (if DB layer supports)
                    local_attempt = 0
                    local_deleted = 0
                    if hasattr(self, 'db_manager') and self.db_manager and hasattr(self.db_manager, 'fetch_user_messages'):
                        try:
                            user_msgs = await self.db_manager.fetch_user_messages(susp_user_id)
                            for rec in user_msgs:
                                try:
                                    chat_id_rec = rec.get('chat_id') if isinstance(rec, dict) else rec[0]
                                    msg_id_rec = rec.get('message_id') if isinstance(rec, dict) else rec[1]
                                    if chat_id_rec != susp_chat_id:
                                        continue
                                    local_attempt += 1
                                    if len(str(msg_id_rec)) < 13 and msg_id_rec < 4_000_000_000:
                                        await self.bot.delete_message(chat_id_rec, msg_id_rec)
                                        local_deleted += 1
                                except Exception as _e_del_loc:
                                    self.logger.debug(f"Local ban delete fail {rec}: {_e_del_loc}")
                        except Exception as _e_loc_db:
                            self.logger.debug(f"Skip local DB fetch for {susp_user_id}: {_e_loc_db}")
                    # Active user checks heuristic list for this chat
                    extra_attempt = 0
                    extra_deleted = 0
                    active_entry = self.active_user_checks_dict.get(susp_user_id)
                    if isinstance(active_entry, dict):
                        for _k, _v in active_entry.items():
                            if isinstance(_v, list):
                                for item in _v:
                                    msg_candidate = None
                                    if isinstance(item, tuple) and len(item) >= 2 and all(isinstance(x, int) for x in item[:2]):
                                        chat_candidate, msg_candidate = item[0], item[1]
                                        if chat_candidate != susp_chat_id:
                                            continue
                                    elif isinstance(item, int):
                                        msg_candidate = item
                                    else:
                                        continue
                                    extra_attempt += 1
                                    try:
                                        if len(str(msg_candidate)) < 13 and msg_candidate < 4_000_000_000:
                                            await self.bot.delete_message(susp_chat_id, msg_candidate)
                                            extra_deleted += 1
                                    except Exception as _e_del_loc2:
                                        self.logger.debug(f"Active local cleanup fail {msg_candidate}: {_e_del_loc2}")
                    if local_attempt or extra_attempt:
                        self.logger.info(
                            f"Local ban cleanup for {susp_user_id} chat {susp_chat_id}: main {local_attempt}/{local_deleted} extra {extra_attempt}/{extra_deleted}"
                        )

                    # Ban user in specific chat
                    await self.bot.ban_chat_member(chat_id=susp_chat_id, user_id=susp_user_id, revoke_messages=True)
                    
                    self.logger.info(f"{susp_user_id}:@{susp_user_name} SUSPICIOUS banned in chat {susp_chat_title} ({susp_chat_id}) by admin @{admin_username}({admin_id})")
                    callback_answer = "User banned in ONE chat and message deleted.\nForward message to bot to ban everywhere!"
                    
                except Exception as e:
                    self.logger.error(f"Ban failed: {e}")
                    callback_answer = "Failed to ban user."
                    
            elif action == "confirmdelmsg":
                try:
                    # Delete message if not synthetic
                    if len(str(susp_message_id)) < 13 and susp_message_id < 4_000_000_000:
                        await self.bot.delete_message(susp_chat_id, susp_message_id)
                        self.logger.info(f"{susp_user_id}:@{susp_user_name} SUSPICIOUS message {susp_message_id} deleted from chat ({susp_chat_id})")
                        callback_answer = "Suspicious message deleted.\nForward message to bot to ban user everywhere!"
                    else:
                        self.logger.debug(f"Skip delete for synthetic message_id={susp_message_id} chat_id={susp_chat_id} (delmsg)")
                        callback_answer = "Message was synthetic, no action taken."
                        
                except Exception as e:
                    self.logger.error(f"Delete message failed: {e}")
                    callback_answer = "Failed to delete message."
                    
            elif action in ["canceldelmsg", "cancelban", "cancelglobalban"]:
                self.logger.info(f"Action {action} cancelled by admin @{admin_username}({admin_id})")
                callback_answer = "Action cancelled."
                
            # Remove buttons and show final state
            await callback_query.message.edit_reply_markup(reply_markup=kb.as_markup())
            
            # Send callback response
            await callback_query.answer(callback_answer or "Action completed.", show_alert=True)
            
            # Send detailed response message
            response_msg = (
                f"{callback_answer}\n"
                f"Suspicious user @{susp_user_name} (<code>{susp_user_id}</code>)\n"
                f"Message origin: <a href='{message_link}'>{message_link}</a>\n"
                f"Action by Admin @{admin_username}"
            )
            
            await callback_query.message.answer(
                response_msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
            
        except Exception as e:
            self.logger.error(f"Error in suspicious sender handler: {e}")
            await callback_query.answer("Error processing action.", show_alert=True)
    
    async def _send_suspicious_message_report(self, message: Message, spam_result):
        """Send suspicious message report to ADMIN_SUSPICIOUS with action buttons."""
        try:
            if not self.admin_group_id:
                self.logger.warning("No admin group configured for suspicious reports")
                return
                
            user_id = message.from_user.id
            username = message.from_user.username or "!UNDEFINED!"
            chat_id = message.chat.id
            chat_title = message.chat.title or "!UNKNOWN!"
            message_id = message.message_id
            
            # Generate report ID
            import time
            report_id = int(time.time())
            
            # Create message text
            report_text = (
                f"🚨 <b>Suspicious Activity Detected</b>\n\n"
                f"👤 User: @{username} (<code>{user_id}</code>)\n"
                f"💬 Chat: {chat_title} (<code>{chat_id}</code>)\n"
                f"📊 Spam Type: {spam_result.spam_type}\n"
                f"🎯 Confidence: {spam_result.confidence:.2f}\n"
                f"📝 Message: {message.text[:200] if message.text else 'No text'}{'...' if message.text and len(message.text) > 200 else ''}\n\n"
                f"🔗 Original message in chat"
            )
            
            # Create action buttons
            kb = InlineKeyboardBuilder()
            
            # Message link
            message_link = self.ui_builder.create_message_link(chat_id, message_id)
            kb.row(InlineKeyboardButton(text="🔗 View Original Message", url=message_link))
            
            # Spam check link
            lols_link = self.build_lols_url(user_id)
            kb.row(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))
            
            # Consolidated actions button
            kb.row(
                InlineKeyboardButton(text="⚙️ Actions (Ban / Delete) ⚙️", callback_data=f"suspiciousactions_{chat_id}_{message_id}_{user_id}")
            )
            
            # Send to admin group with suspicious thread
            await self.bot.send_message(
                chat_id=self.admin_group_id,
                text=report_text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb.as_markup(),
                message_thread_id=self.settings.ADMIN_SUSPICIOUS,
                disable_web_page_preview=True
            )
            
            self.logger.info(f"Sent suspicious message report for user {user_id} to admin")
            
        except Exception as e:
            self.logger.error(f"Failed to send suspicious message report: {e}")
    
    async def spam_check(self, user_id: int) -> bool:
        """Check user against external spam databases (LoLs, CAS, local P2P)."""
        try:
            self.logger.debug(f"Checking user {user_id} against spam databases")
            
            if not AIOHTTP_AVAILABLE:
                self.logger.warning("aiohttp not available, spam check disabled")
                return False
            
            async with aiohttp.ClientSession() as session:
                lols = False
                cas = 0
                is_spammer = False

                async def check_local():
                    """Check local P2P spam server."""
                    try:
                        async with session.get(
                            f"{self.settings.LOCAL_SPAM_API_URL}/check?user_id={user_id}",
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                return data.get("is_spammer", False)
                    except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
                        self.logger.warning(f"Local endpoint check error: {e}")
                        return False

                async def check_lols():
                    """Check LoLs bot spam database."""
                    try:
                        async with session.get(
                            f"{self.settings.LOLS_API_URL}/account?id={user_id}",
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                return data.get("banned", False)
                    except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
                        self.logger.warning(f"LOLS endpoint check error: {e}")
                        return False

                async def check_cas():
                    """Check CAS (Combot Anti-Spam) database."""
                    try:
                        async with session.get(
                            f"{self.settings.CAS_API_URL}/check?user_id={user_id}",
                            timeout=aiohttp.ClientTimeout(total=10)
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if data.get("ok", False):
                                    return data["result"].get("offenses", 0)
                    except (aiohttp.ClientConnectorError, asyncio.TimeoutError) as e:
                        self.logger.warning(f"CAS endpoint check error: {e}")
                        return 0

                # Run all checks concurrently
                try:
                    results = await asyncio.gather(
                        check_local(), check_lols(), check_cas(), return_exceptions=True
                    )

                    is_spammer = results[0] if not isinstance(results[0], Exception) else False
                    lols = results[1] if not isinstance(results[1], Exception) else False
                    cas = results[2] if not isinstance(results[2], Exception) else 0

                    # User is spam if any service reports them
                    # Handle None values properly
                    cas_is_spam = cas is not None and cas > 0
                    is_spam = lols or is_spammer or cas_is_spam
                    
                    if is_spam:
                        self.logger.info(f"User {user_id} detected as spam: LoLs={lols}, Local={is_spammer}, CAS={cas}")
                    
                    return is_spam
                    
                except Exception as e:
                    self.logger.error(f"Unexpected error in spam checks: {e}")
                    return False
                    
        except Exception as e:
            self.logger.error(f"Error in spam_check for user {user_id}: {e}")
            return False
    
    async def report_spam_2p2p(self, spammer_id: int) -> bool:
        """Report spammer to local P2P spamcheck server."""
        try:
            if not AIOHTTP_AVAILABLE:
                self.logger.warning("aiohttp not available, cannot report to P2P server")
                return False
                
            url = f"{self.settings.LOCAL_SPAM_API_URL}/report_id?user_id={spammer_id}"
            async with aiohttp.ClientSession() as session:
                async with session.post(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        self.logger.info(f"{spammer_id} successfully reported to local P2P spamcheck server")
                        return True
                    else:
                        self.logger.warning(f"Failed to report {spammer_id} to P2P server: HTTP {response.status}")
                        return False
        except (aiohttp.ServerTimeoutError, aiohttp.ClientError) as e:
            self.logger.error(f"Error reporting spammer {spammer_id} to P2P server: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error reporting spammer {spammer_id}: {e}")
            return False
    
    def build_lols_url(self, user_id: int) -> str:
        """Return LOLS bot deep link for a given user id."""
        return self.ui_builder.build_lols_url(user_id)

    def make_lols_kb(self, user_id: int) -> InlineKeyboardMarkup:
        """Create a one-button keyboard with the LOLS check link."""
        return self.ui_builder.make_lols_kb(user_id)
    
    async def ban_user_from_all_chats(self, user_id: int, user_name: str = "!UNDEFINED!", reason: str = "Spam detected") -> bool:
        """Ban a user from all specified chats and log the results."""
        try:
            channel_ids = getattr(self.settings, 'CHANNEL_IDS', [])
            if not channel_ids:
                self.logger.warning("No channels configured for global ban")
                return False
                
            ban_count = 0
            for chat_id in channel_ids:
                try:
                    await self.bot.ban_chat_member(chat_id, user_id, revoke_messages=True)
                    ban_count += 1
                    self.logger.debug(f"Successfully banned user {user_id} in chat {chat_id}")
                except Exception as e:
                    chat_name = self.settings.CHANNEL_DICT.get(chat_id, "!UNKNOWN!")
                    self.logger.error(f"Error banning user {user_id} in chat {chat_name} ({chat_id}): {e}")
                    await asyncio.sleep(1)  # Rate limiting
                    continue

            if ban_count > 0:
                self.logger.info(f"🚫 {user_id}:@{user_name} banned from {ban_count}/{len(channel_ids)} chats - {reason}")
                return True
            else:
                self.logger.error(f"Failed to ban {user_id} from any chats")
                return False
                
        except Exception as e:
            self.logger.error(f"Error in ban_user_from_all_chats for user {user_id}: {e}")
            return False
    
    async def cancel_named_watchdog(self, user_id: int, user_name: str = "!UNDEFINED!", move_to_banned: bool = False) -> bool:
        """Cancel a running watchdog task for a given user ID."""
        try:
            if user_id in self.running_watchdogs:
                # Optionally move user from active checks to banned users
                if move_to_banned and user_id in self.active_user_checks_dict:
                    user_data = self.active_user_checks_dict.pop(user_id, None)
                    # Only add to banned if not already banned (avoid duplicates)
                    if user_id not in self.banned_users_dict:
                        self.banned_users_dict[user_id] = user_data
                        self.logger.info(f"✅ {user_id}:@{user_name} moved from active checks to banned users")
                    else:
                        self.logger.debug(f"ℹ️  {user_id}:@{user_name} already in banned users, not duplicating")
                
                # Cancel the task
                task = self.running_watchdogs.pop(user_id)
                task.cancel()
                
                try:
                    await task
                    self.logger.info(f"🛑 {user_id}:@{user_name} Watchdog disabled (Cancelled)")
                except asyncio.CancelledError:
                    self.logger.info(f"🛑 {user_id}:@{user_name} Watchdog cancellation confirmed")
                except Exception as e:
                    self.logger.error(f"Error during watchdog cancellation for {user_id}: {e}")
                
                return True
            else:
                self.logger.info(f"ℹ️  {user_id}:@{user_name} No running watchdog found to cancel")
                return False
                
        except Exception as e:
            self.logger.error(f"Error cancelling watchdog for user {user_id}: {e}")
            return False
    
    async def create_named_watchdog(self, coro, user_id: int, user_name: str = "!UNDEFINED!") -> bool:
        """Create or restart a watchdog task for user monitoring."""
        try:
            # Check if task already exists
            existing_task = self.running_watchdogs.get(user_id)
            if existing_task:
                self.logger.info(f"⚠️  {user_id}:@{user_name} Watchdog already exists. Restarting...")
                existing_task.cancel()
                try:
                    await existing_task
                except asyncio.CancelledError:
                    pass
            
            # Create new task
            task = asyncio.create_task(coro, name=f"watchdog_{user_id}")
            self.running_watchdogs[user_id] = task
            
            self.logger.info(f"🐕 {user_id}:@{user_name} Watchdog assigned")
            
            # Set up cleanup callback for watchdog task management
            def _task_done(t: asyncio.Task, _uid=user_id, _uname=user_name):
                try:
                    # Remove from running watchdogs registry
                    if self.running_watchdogs.get(_uid) is t:
                        self.running_watchdogs.pop(_uid, None)
                    
                    # Log task completion status
                    if t.cancelled():
                        self.logger.info(f"🛑 {_uid}:@{_uname} Watchdog task was cancelled (user monitoring persists)")
                    elif t.done() and not t.exception():
                        self.logger.info(f"✅ {_uid}:@{_uname} Watchdog task completed successfully")
                    else:
                        exc = t.exception()
                        if exc:
                            self.logger.error(f"❌ {_uid}:@{_uname} Watchdog task raised exception: {exc}")
                            # Only remove from active checks on exception
                            if _uid in self.active_user_checks_dict:
                                del self.active_user_checks_dict[_uid]
                                self.logger.info(f"�️ {_uid}:@{_uname} removed from active checks due to exception")
                except Exception as e:
                    self.logger.error(f"Error in watchdog cleanup for {_uid}: {e}")
            
            task.add_done_callback(_task_done)
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating watchdog for user {user_id}: {e}")
            return False
    
    async def autoban(self, user_id: int, user_name: str = "!UNDEFINED!", reason: str = "Automated spam detection", suppress_logging: bool = False) -> bool:
        """Function to automatically ban a user from all chats."""
        try:
            # Check if already banned
            if user_id in self.banned_users_dict:
                self.logger.debug(f"User {user_id} already banned")
                return True
            
            # Perform spam check first
            is_spam = await self.spam_check(user_id)
            if not is_spam:
                if not suppress_logging:
                    self.logger.info(f"User {user_id} passed spam check, not banning")
                return False
            
            # Ban from all chats
            ban_success = await self.ban_user_from_all_chats(user_id, user_name, reason)
            
            if ban_success:
                # Add to banned users
                self.banned_users_dict[user_id] = {
                    "username": user_name,
                    "reason": reason,
                    "timestamp": asyncio.get_event_loop().time()
                }
                
                # Remove from active checks
                if user_id in self.active_user_checks_dict:
                    del self.active_user_checks_dict[user_id]
                
                # Cancel watchdog if running
                await self.cancel_named_watchdog(user_id, user_name, move_to_banned=True)
                
                # Save banned users to persist the ban
                await self.save_banned_users()
                
                # Report to P2P
                await self.report_spam_2p2p(user_id)
                
                self.logger.info(f"🔨 {user_id}:@{user_name} AUTO-BANNED: {reason}")
                return True
            else:
                self.logger.error(f"Failed to autoban user {user_id}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error in autoban for user {user_id}: {e}")
            return False
    
    async def save_report_file(self, file_type: str, data: str) -> bool:
        """Create or append to daily report files."""
        try:
            from datetime import datetime
            import os
            
            # Get today's date
            today = datetime.now().strftime("%d-%m-%Y")
            filename = f"{file_type}{today}.txt"
            
            # Ensure directory exists
            if file_type.startswith("daily_spam_"):
                os.makedirs("aiogram3_daily_spam", exist_ok=True)
                filename = f"aiogram3_daily_spam/{filename}"
            elif file_type.startswith("inout_"):
                os.makedirs("aiogram3_inout", exist_ok=True)
                filename = f"aiogram3_inout/{filename}"
            
            # Write data to file
            with open(filename, "a", encoding="utf-8") as f:
                f.write(data + "\n")
            
            self.logger.debug(f"Saved report data to {filename}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error saving report file: {e}")
            return False
    
    async def log_profile_change(self, user_id: int, username: str, context: str, chat_id: int, chat_title: str, 
                                changed: list, old_values: dict, new_values: dict, photo_changed: bool = False) -> None:
        """Log profile changes for audit trail."""
        try:
            from datetime import datetime
            
            # Create timestamp
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Format user ID
            uid_fmt = f"{user_id:>12}"
            
            # Format username
            uname = username.lstrip("@") if username else "!UNDEFINED!"
            
            # Format chat representation
            chat_repr = f"{chat_title}({chat_id})" if chat_title else f"({chat_id})"
            
            # Build change details
            diff_parts = []
            mapping = {
                'first_name': ('first_name', 'FirstName'),
                'last_name': ('last_name', 'LastName'),
                'username': ('username', 'Username'),
                'photo_count': ('photo_count', 'PhotoCount')
            }
            
            for field in changed:
                key, label = mapping.get(field, (field, field))
                o = old_values.get(key, '')
                n = new_values.get(key, '')
                if key == 'username':
                    o = ('@' + o) if o else '@!UNDEFINED!'
                    n = ('@' + n) if n else '@!UNDEFINED!'
                diff_parts.append(f"{label}='{o}'→'{n}'")
            
            photo_marker = ' P' if photo_changed else ''
            record = f"{ts}: {uid_fmt} PC[{context}{photo_marker}] @{uname:<20} in {chat_repr:<40} changes: {', '.join(diff_parts)}\n"
            
            # Save to inout file
            await self.save_report_file('inout_', 'pc' + record.rstrip())
            self.logger.info(record.rstrip())
            
        except Exception as e:
            self.logger.debug(f'Failed to log profile change: {e}')
    
    def make_profile_dict(self, first_name: str = None, last_name: str = None, username: str = None, photo_count: int = None) -> dict:
        """Return a normalized profile snapshot dict used for logging diffs."""
        return self.profile_manager.make_profile_dict(first_name, last_name, username, photo_count)
    
    async def check_and_autoban(self, user_id: int, reason: str = "Automated ban", **kwargs) -> bool:
        """Check user and automatically ban if conditions are met."""
        try:
            # Use the new autoban function which includes spam checking
            return await self.autoban(user_id, kwargs.get('user_name', '!UNDEFINED!'), reason)
            
        except Exception as e:
            self.logger.error(f"Error in check_and_autoban for user {user_id}: {e}")
            return False
    
    async def submit_autoreport(self, report_chat: int, from_id: int, report_user_id: int, 
                               content: str, reason: str = None) -> bool:
        """Submit and log an autoreport."""
        try:
            from datetime import datetime
            
            # Log the autoreport
            timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            reason_str = f" ({reason})" if reason else ""
            ar_line = f"{timestamp} AutoReport{reason_str}: Chat={report_chat}, Reporter={from_id}, Target={report_user_id}, Content='{content}'"
            
            # Save to inout file
            await self.save_report_file('inout_', ar_line)
            self.logger.info(f"AutoReport{reason_str}: Reporter {from_id} → Target {report_user_id} in chat {report_chat}")
            
            # Process the content if it contains forwarded message investigation
            if "INVESTIGATE" in content.upper():
                await self.handle_autoreports(content, report_chat, from_id, report_user_id)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error submitting autoreport: {e}")
            return False
    
    async def handle_autoreports(self, content: str, chat_id: int, reporter_id: int, target_id: int) -> None:
        """Handle investigation of forwarded messages in autoreports."""
        try:
            # Look for patterns like "INVESTIGATE FORWARD FROM @username" or similar
            if "FORWARD" in content.upper() and "FROM" in content.upper():
                # Extract potential username or channel info
                import re
                patterns = [
                    r'FROM\s+@(\w+)',
                    r'FROM\s+(\w+)',
                    r'CHANNEL\s+@(\w+)',
                    r'USER\s+@(\w+)'
                ]
                
                found_entities = []
                for pattern in patterns:
                    matches = re.findall(pattern, content.upper())
                    found_entities.extend(matches)
                
                if found_entities:
                    entities_str = ", ".join(found_entities)
                    investigation_log = f"Investigation: Forward trace for user {target_id} → entities: {entities_str}"
                    await self.save_report_file('inout_', investigation_log)
                    self.logger.info(investigation_log)
                
                # If this looks like a spam forward, trigger additional checks
                spam_keywords = ["SPAM", "SCAM", "FLOOD", "ADVERTISING"]
                if any(keyword in content.upper() for keyword in spam_keywords):
                    await self.autoban(target_id, "Forwarded spam content investigation")
            
        except Exception as e:
            self.logger.error(f"Error handling autoreport investigation: {e}")
    
    async def save_active_user_checks(self) -> None:
        """Save active user checks to file for persistence across restarts."""
        await self.persistence.save_active_user_checks(self.active_user_checks_dict)

    async def save_banned_users(self) -> None:
        """Save banned users to file for persistence across restarts."""
        await self.persistence.save_banned_users(self.banned_users_dict)

    async def load_banned_users(self) -> None:
        """Load banned users from file."""
        self.banned_users_dict = await self.persistence.load_banned_users()
    
    async def load_active_user_checks(self) -> None:
        """Load active user checks from file and start monitoring."""
        self.active_user_checks_dict = await self.persistence.load_active_user_checks()
        
        # Start monitoring for each loaded user
        for user_id, user_data in self.active_user_checks_dict.items():
            # Extract username for logging
            if isinstance(user_data, dict):
                username = user_data.get("username", "!UNDEFINED!")
            else:
                username = user_data if user_data != "None" else "!UNDEFINED!"
            
            # Start monitoring with 1 second delay between tasks
            from datetime import datetime
            event_message = (
                f"{datetime.now().strftime('%H:%M:%S.%f')[:-3]}: "
                f"{user_id} ❌ \t\t\tbanned everywhere during initial checks on_startup"
            )
            
            # Start the check in watchdog system
            asyncio.create_task(
                self.perform_checks(
                    user_id=user_id,
                    user_name=username,
                    event_record=event_message,
                    inout_logmessage=f"(<code>{user_id}</code>) banned using data loaded on_startup event"
                )
            )
            
            self.logger.info(f"{user_id}:@{username} loaded from file & 24hr progressive monitoring started...")
            await asyncio.sleep(1)  # 1-second interval between task creations
    
    async def load_and_start_checks(self) -> None:
        """Load all data files and start monitoring."""
        try:
            self.logger.info("Loading banned users and active checks...")
            await self.load_banned_users()
            await self.load_active_user_checks()
            self.logger.info("All data loaded and monitoring started")
            
        except Exception as e:
            self.logger.error(f"Error in load_and_start_checks: {e}")
    
    async def perform_checks(self, user_id: int, user_name: str = "!UNDEFINED!", event_record: str = "", inout_logmessage: str = ""):
        """Perform progressive 24-hour monitoring checks on a user with watchdog system."""
        try:
            self.logger.info(f"🔍 Starting 24-hour progressive monitoring for user {user_id}:@{user_name}")
            
            # Add user to active checks if not already there
            if user_id not in self.active_user_checks_dict:
                self.active_user_checks_dict[user_id] = {
                    "username": user_name,
                    "start_time": asyncio.get_event_loop().time(),
                    "event_record": event_record,
                    "inout_logmessage": inout_logmessage,
                    "notified_profile_change": False,
                    "baseline": None  # Will be set if we have chat member info
                }
            
            # Progressive monitoring intervals (in seconds)
            # Original: 1min, 3min, 5min, 10min, 20min, 30min, 1hr, 2hr, 3hr, 6hr, 12hr, 24hr
            sleep_times = [
                65,      # 1 min
                185,     # 3 min  
                305,     # 5 min
                605,     # 10 min
                1205,    # 20 min
                1805,    # 30 min
                3605,    # 1 hr
                7205,    # 2 hr
                10805,   # 3 hr
                21605,   # 6 hr
                43205,   # 12 hr
                86405,   # 24 hr
            ]
            
            # Color mapping for spam check results
            color_map = {
                False: "🟢",  # Green for clean
                True: "🔴",   # Red for spam
                None: "🟡",   # Yellow for unknown
            }
            
            # Create monitoring coroutine
            async def monitoring_coro():
                message_to_delete = None
                
                for i, sleep_time in enumerate(sleep_times):
                    # Check if user still in monitoring (might have been banned elsewhere)
                    if user_id not in self.active_user_checks_dict:
                        self.logger.info(f"👤 {user_id}:@{user_name} no longer in active checks, stopping monitoring")
                        return
                    
                    # Sleep for the specified interval
                    await asyncio.sleep(sleep_time)
                    
                    # Perform spam check
                    is_spam = await self.spam_check(user_id)
                    
                    # Log the check with timing info
                    color_icon = color_map.get(is_spam, "🟡")
                    minutes = sleep_time // 60
                    remaining_checks = len(sleep_times) - i - 1
                    self.logger.info(f"{color_icon} {user_id}:@{user_name} {minutes:02d}min check spam: {is_spam} (checks left: {remaining_checks})")
                    
                    # Check for profile changes (if we have baseline data)
                    if user_id in self.active_user_checks_dict:
                        user_entry = self.active_user_checks_dict[user_id]
                        
                        if isinstance(user_entry, dict):
                            baseline = user_entry.get("baseline")
                            already_notified = user_entry.get("notified_profile_change", False)
                            
                            if baseline and not already_notified:
                                await self._check_profile_changes(user_id, user_name, user_entry, baseline)
                            
                            # Look for suspicious messages to track
                            suspicious_messages = {
                                k: v for k, v in user_entry.items()
                                if isinstance(k, str) and "_" in k and k not in ("username", "baseline", "notified_profile_change", "start_time", "event_record", "inout_logmessage")
                            }
                            
                            if suspicious_messages:
                                # Get the first suspicious message for deletion tracking
                                chat_id, message_id = next(iter(suspicious_messages)).split("_")
                                message_to_delete = [int(chat_id), int(message_id)]
                    
                    # Perform autoban check
                    if await self.autoban(user_id, user_name, f"Progressive check {minutes}min - {event_record}", suppress_logging=True):
                        self.logger.info(f"🔨 {user_id}:@{user_name} banned during {minutes}min progressive check")
                        return
                
                # If we reach here, user completed all 24-hour checks and is clean
                if user_id in self.active_user_checks_dict:
                    del self.active_user_checks_dict[user_id]
                    self.logger.info(f"✅ {user_id}:@{user_name} completed 24-hour monitoring - user is clean")
            
            # Create watchdog for this monitoring task
            await self.create_named_watchdog(monitoring_coro(), user_id, user_name)
            
        except asyncio.CancelledError:
            self.logger.info(f"🛑 Progressive monitoring cancelled for user {user_id}:@{user_name}")
            if user_id in self.active_user_checks_dict:
                # Move to banned users when cancelled
                self.banned_users_dict[user_id] = self.active_user_checks_dict.pop(user_id, None)
                self.logger.info(f"📝 {user_id}:@{user_name} moved to banned users during cancellation")
        except Exception as e:
            self.logger.error(f"Error in perform_checks for user {user_id}: {e}")
            if user_id in self.active_user_checks_dict:
                del self.active_user_checks_dict[user_id]
    
    async def _check_profile_changes(self, user_id: int, user_name: str, user_entry: dict, baseline: dict):
        """Check for profile changes during monitoring period."""
        try:
            chat_info = baseline.get("chat", {})
            chat_id = chat_info.get("id")
            
            if not chat_id:
                return
            
            # Get current profile data
            cur_first = baseline.get("first_name", "")
            cur_last = baseline.get("last_name", "")
            cur_username = baseline.get("username", "")
            cur_photo_count = baseline.get("photo_count", 0)
            
            try:
                # Get live chat member data
                member = await self.bot.get_chat_member(chat_id, user_id)
                user = member.user
                cur_first = user.first_name or ""
                cur_last = user.last_name or ""
                cur_username = user.username or ""
            except Exception as e:
                self.logger.debug(f"Unable to fetch chat member for {user_id}: {e}")
            
            try:
                # Get current photo count
                photos = await self.bot.get_user_profile_photos(user_id, limit=1)
                cur_photo_count = photos.total_count if photos else cur_photo_count
            except Exception as e:
                self.logger.debug(f"Unable to fetch photo count for {user_id}: {e}")
            
            # Detect changes
            changed = []
            if cur_first != baseline.get("first_name", ""):
                changed.append("first_name")
            if cur_last != baseline.get("last_name", ""):
                changed.append("last_name")
            if cur_username != baseline.get("username", ""):
                changed.append("username")
            if baseline.get("photo_count", 0) == 0 and cur_photo_count > 0:
                changed.append("profile_photo")
            
            if changed:
                await self._send_profile_change_report(user_id, user_name, chat_info, baseline, {
                    "first_name": cur_first,
                    "last_name": cur_last,
                    "username": cur_username,
                    "photo_count": cur_photo_count
                }, changed)
                
                # Mark as notified
                user_entry["notified_profile_change"] = True
                
        except Exception as e:
            self.logger.error(f"Error checking profile changes for {user_id}: {e}")
    
    async def _send_profile_change_report(self, user_id: int, user_name: str, chat_info: dict, 
                                        old_profile: dict, new_profile: dict, changed: list):
        """Send profile change report to admin."""
        try:
            from datetime import datetime
            import html
            
            if not self.admin_group_id:
                return
            
            chat_title = chat_info.get("title", "Unknown Chat")
            chat_username = chat_info.get("username")
            chat_id = chat_info.get("id")
            
            # Create chat link
            if chat_username:
                chat_link = f'<a href="https://t.me/{chat_username}">{html.escape(chat_title)}</a>'
            else:
                chat_link = f'<a href="https://t.me/c/{str(chat_id)[4:]}">{html.escape(chat_title)}</a>'
            
            # Format field changes
            def format_field(old_val, new_val, label, is_username=False):
                if is_username:
                    old_disp = f"@{old_val}" if old_val else "@!UNDEFINED!"
                    new_disp = f"@{new_val}" if new_val else "@!UNDEFINED!"
                else:
                    old_disp = html.escape(old_val) if old_val else "∅"
                    new_disp = html.escape(new_val) if new_val else "∅"
                
                if old_val != new_val:
                    return f"{label}: {old_disp} ➜ <b>{new_disp}</b>"
                return f"{label}: {new_disp}"
            
            field_lines = [
                format_field(old_profile.get("first_name", ""), new_profile.get("first_name", ""), "First name"),
                format_field(old_profile.get("last_name", ""), new_profile.get("last_name", ""), "Last name"),
                format_field(old_profile.get("username", ""), new_profile.get("username", ""), "Username", True),
                f"User ID: <code>{user_id}</code>"
            ]
            
            if "profile_photo" in changed:
                field_lines.append("Profile photo: none ➜ <b>set</b>")
            
            # Profile links
            profile_links = (
                f"🔗 <b>Profile links:</b>\n"
                f"   ├ <a href='tg://user?id={user_id}'>ID-based profile link</a>\n"
                f"   └ <a href='https://t.me/@id{user_id}'>Direct link</a>"
            )
            
            # Calculate elapsed time if available
            joined_at = old_profile.get("joined_at")
            elapsed_line = ""
            if joined_at:
                try:
                    if isinstance(joined_at, str):
                        joined_dt = datetime.strptime(joined_at, "%Y-%m-%d %H:%M:%S")
                    else:
                        joined_dt = joined_at
                    
                    delta = datetime.now() - joined_dt
                    days = delta.days
                    hours, rem = divmod(delta.seconds, 3600)
                    minutes, seconds = divmod(rem, 60)
                    
                    parts = []
                    if days: parts.append(f"{days}d")
                    if hours: parts.append(f"{hours}h")
                    if minutes and not days: parts.append(f"{minutes}m")
                    if seconds and not days and not hours: parts.append(f"{seconds}s")
                    
                    human_elapsed = " ".join(parts) or f"{seconds}s"
                    elapsed_line = f"\nJoined at: {joined_at} (elapsed: {human_elapsed})"
                except Exception:
                    elapsed_line = f"\nJoined at: {joined_at}"
            
            timestamp = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            
            message_text = (
                f"🚨 <b>Suspicious profile change detected</b> after joining {chat_link}.\n\n"
                + "\n".join(field_lines) + 
                f"\n\nChanges: <b>{', '.join(changed)}</b> at {timestamp}."
                + elapsed_line + "\n\n" + profile_links
            )
            
            # Create action buttons
            from aiogram.utils.keyboard import InlineKeyboardBuilder
            kb = InlineKeyboardBuilder()
            
            # Spam check link
            lols_link = self.build_lols_url(user_id)
            kb.row(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))
            
            # Action buttons
            report_id = int(datetime.now().timestamp())
            kb.row(InlineKeyboardButton(text="🚫 Ban User", callback_data=f"suspiciousban_{chat_id}_{report_id}_{user_id}"))
            kb.row(InlineKeyboardButton(text="🌐 Global Ban", callback_data=f"suspiciousglobalban_{chat_id}_{report_id}_{user_id}"))
            
            # Send to admin group
            await self.bot.send_message(
                chat_id=self.admin_group_id,
                text=message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb.as_markup(),
                message_thread_id=getattr(self.settings, 'ADMIN_SUSPICIOUS', None),
                disable_web_page_preview=True
            )
            
            # Log the profile change
            await self.log_profile_change(
                user_id=user_id,
                username=new_profile.get("username", ""),
                context='periodic',
                chat_id=chat_id,
                chat_title=chat_title,
                changed=changed,
                old_values=old_profile,
                new_values=new_profile,
                photo_changed=('profile_photo' in changed)
            )
            
            self.logger.info(f"📋 Sent profile change report for {user_id} to admin")
            
        except Exception as e:
            self.logger.error(f"Error sending profile change report for {user_id}: {e}")
    
    async def _store_suspicious_message(self, message: Message, user_id: int):
        """Store message from user being monitored for later tracking."""
        try:
            # Ensure user entry is a dict
            if not isinstance(self.active_user_checks_dict.get(user_id), dict):
                username = self.active_user_checks_dict.get(user_id, "!UNDEFINED!")
                self.active_user_checks_dict[user_id] = {
                    "username": username if username != "None" else "!UNDEFINED!"
                }
            
            # Create message key and link
            message_key = f"{message.chat.id}_{message.message_id}"
            
            # Create message link using UIBuilder
            message_link = self.ui_builder.create_message_link_from_message(message)
            
            # Store the message link in active_user_checks_dict
            self.active_user_checks_dict[user_id][message_key] = message_link
            
            # Log the suspicious message
            username = message.from_user.username or "!UNDEFINED!"
            self.logger.warning(
                f"🔍 {user_id}:@{username} sent monitored message {message.message_id} "
                f"in {message.chat.title} ({message.chat.id}). Link: {message_link}"
            )
            
            # Auto-save active checks to persist the message data
            await self.save_active_user_checks()
            
        except Exception as e:
            self.logger.error(f"Error storing suspicious message for user {user_id}: {e}")
    
    def is_user_or_source_banned(self, message: Message) -> tuple[bool, str]:
        """Check if user or forwarded source is banned. Returns (is_banned, reason)."""
        if not message.from_user:
            return False, ""
        
        user_id = message.from_user.id
        
        # Check if direct user is banned
        if user_id in self.banned_users_dict:
            return True, f"user {user_id} is banned"
        
        # Check forwarded from chat
        if message.forward_origin and hasattr(message.forward_origin, 'chat') and message.forward_origin.chat:
            forward_chat_id = message.forward_origin.chat.id
            if forward_chat_id in self.banned_users_dict:
                return True, f"forwarded from banned chat {forward_chat_id}"
        
        # Check forwarded from user
        elif message.forward_origin and hasattr(message.forward_origin, 'sender_user') and message.forward_origin.sender_user:
            forward_user_id = message.forward_origin.sender_user.id
            if forward_user_id in self.banned_users_dict:
                return True, f"forwarded from banned user {forward_user_id}"
        
        return False, ""

    async def log_lists(self):
        """Log active checks and banned users, then perform daily cleanup like aiogram2."""
        try:
            self.logger.info(f"Daily log: {len(self.banned_users_dict)} banned users, {len(self.active_user_checks_dict)} active checks")
            
            from datetime import datetime, timedelta
            import os
            import ast
            
            # Get yesterday's date 
            today = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")
            
            # Ensure directories exist
            os.makedirs("aiogram3_inout", exist_ok=True)
            os.makedirs("aiogram3_daily_spam", exist_ok=True)
            
            # Read current banned users from runtime file and merge with dict
            banned_users_filename = "aiogram3_banned_users.txt"
            if os.path.exists(banned_users_filename):
                with open(banned_users_filename, "r", encoding="utf-8") as file:
                    for line in file:
                        parts = line.strip().split(":", 1)
                        if len(parts) == 2:
                            user_id, user_name_repr = parts
                            try:
                                user_name = ast.literal_eval(user_name_repr.strip())
                            except (ValueError, SyntaxError):
                                user_name = user_name_repr.strip()  # Keep as string if not valid dict
                            self.banned_users_dict[int(user_id)] = user_name
                        else:
                            self.logger.warning(f"Skipping invalid line: {line}")
                
                # Remove the runtime file after reading
                os.remove(banned_users_filename)
                self.logger.info(f"Read and removed runtime banned users file: {len(self.banned_users_dict)} total users")
            
            # Save banned users to daily file with yesterday's date
            daily_banned_filename = f"aiogram3_inout/banned_users_{today}.txt"
            with open(daily_banned_filename, "w", encoding="utf-8") as file:
                for user_id, user_data in self.banned_users_dict.items():
                    file.write(f"{user_id}:{user_data}\n")
            
            # Move yesterday's files to appropriate folders
            self._move_old_files_to_folders()
            
            # Clear banned users dict for new day (fresh start)
            self.banned_users_dict.clear()
            
            self.logger.info(f"✅ Daily cleanup completed: banned users saved to {daily_banned_filename}")
            
        except Exception as e:
            self.logger.error(f"Error in log_lists: {e}")
    
    def _move_old_files_to_folders(self):
        """Move old daily files to their respective folders like aiogram2."""
        try:
            import os
            from datetime import datetime
            
            current_date = datetime.now().strftime("%d-%m-%Y")
            
            # Move old daily_spam files to aiogram3_daily_spam folder
            for file in os.listdir("."):
                if file.startswith("aiogram3_daily_spam_") and not file.endswith(f"{current_date}.txt"):
                    try:
                        os.rename(file, f"aiogram3_daily_spam/{file}")
                        self.logger.debug(f"Moved {file} to aiogram3_daily_spam/")
                    except Exception as e:
                        self.logger.error(f"Failed to move {file}: {e}")
            
            # Move old inout files to aiogram3_inout folder  
            for file in os.listdir("."):
                if file.startswith("aiogram3_inout_") and not file.endswith(f"{current_date}.txt"):
                    try:
                        os.rename(file, f"aiogram3_inout/{file}")
                        self.logger.debug(f"Moved {file} to aiogram3_inout/")
                    except Exception as e:
                        self.logger.error(f"Failed to move {file}: {e}")
                        
        except Exception as e:
            self.logger.error(f"Error moving old files: {e}")
    
    def setup_scheduled_tasks(self):
        """Setup daily scheduled tasks."""
        if AIOCRON_AVAILABLE:
            # Schedule daily log cleanup at 4 AM Mauritius time
            @aiocron.crontab("0 4 * * *", tz=ZoneInfo("Indian/Mauritius"))
            async def scheduled_log():
                await self.log_lists()
            
            # Schedule periodic save of active user checks every hour
            @aiocron.crontab("0 * * * *", tz=ZoneInfo("Indian/Mauritius"))
            async def scheduled_save():
                await self.save_active_user_checks()
                await self.save_banned_users()
            
            self.logger.info("✅ Scheduled tasks setup completed")
        else:
            self.logger.warning("⚠️  Scheduled tasks disabled - aiocron not available")
    
    def _is_forwarded_from_unknown_channel(self, message: Message) -> bool:
        """Check if message is forwarded from an unknown channel."""
        return self.message_validator.is_forwarded_from_unknown_channel(message, self.settings)
    
    def _is_in_monitored_channel(self, message: Message) -> bool:
        """Check if message is in a monitored channel."""
        return self.message_validator.is_in_monitored_channel(message, self.settings)
    
    def _is_valid_message(self, message: Message) -> bool:
        """Check if message is valid for unhandled message processing."""
        excluded_ids = [
            self.admin_group_id,
            self.technolog_group_id, 
            self.ADMIN_USER_ID
        ] + getattr(self.settings, 'CHANNEL_IDS', [])
        
        return self.message_validator.is_valid_message(message, excluded_ids)
    
    def _is_admin_user_message(self, message: Message) -> bool:
        """Check if message is from admin user and not forwarded."""
        return (
            message.from_user and
            message.from_user.id == self.ADMIN_USER_ID and
            not message.forward_origin
        )
    
    async def _handle_forwarded_message(self, message: Message):
        """Handle forwarded spam reports."""
        try:
            # Thank the user for the report
            await message.answer("Thank you for the report. We will investigate it.")
            
            # Forward to admin group if configured
            if self.technolog_group_id:
                try:
                    await self.bot.forward_message(
                        chat_id=self.technolog_group_id,
                        from_chat_id=message.chat.id,
                        message_id=message.message_id
                    )
                    
                    # Send investigation notice
                    await self.bot.send_message(
                        chat_id=self.technolog_group_id,
                        text="Please investigate this forwarded message."
                    )
                except Exception as e:
                    self.logger.error(f"Failed to forward message to admin group: {e}")
            
            self.logger.info(f"Processed forwarded spam report from user {message.from_user.id}")
            
        except Exception as e:
            self.logger.error(f"Error handling forwarded message: {e}")
    
    async def _handle_monitored_message(self, message: Message):
        """Handle messages in monitored channels."""
        try:
            # Store message if database is available
            if self.database_manager:
                await self.database_manager.store_message(
                    message_id=message.message_id,
                    chat_id=message.chat.id,
                    user_id=message.from_user.id if message.from_user else 0,
                    text=message.text or message.caption or "",
                    timestamp=message.date
                )
            
            # Check for spam if user is provided
            if message.from_user and not message.from_user.is_bot:
                user_id = message.from_user.id
                
                # Check if user or forwarded source is banned
                is_banned, ban_reason = self.is_user_or_source_banned(message)
                if is_banned:
                    try:
                        await message.delete()
                        self.logger.info(f"Deleted message from {user_id} - {ban_reason}")
                    except Exception as e:
                        self.logger.error(f"Failed to delete message: {e}")
                    return
                
                # If user is being monitored, store their message for tracking
                if user_id in self.active_user_checks_dict:
                    await self._store_suspicious_message(message, user_id)
                
                # Perform spam analysis
                if self.spam_service:
                    spam_result = await self.spam_service.analyze_message(message)
                    
                    if spam_result.is_spam:
                        # Auto-ban or start monitoring based on confidence
                        if spam_result.confidence > 0.8:
                            await self.check_and_autoban(user_id, f"High spam confidence: {spam_result.confidence}")
                        else:
                            # Send suspicious message to admin with action buttons
                            await self._send_suspicious_message_report(message, spam_result)
                            
                            # Start monitoring if not already being monitored
                            if user_id not in self.active_user_checks_dict:
                                await self.create_named_watchdog(
                                    self.perform_checks(
                                        user_id=user_id,
                                        user_name=message.from_user.username or "!UNDEFINED!",
                                        event_record=f"Suspicious message detected: {spam_result.spam_type}"
                                    ),
                                    user_id,
                                    message.from_user.username or "!UNDEFINED!"
                                )
            
        except Exception as e:
            self.logger.error(f"Error handling monitored message: {e}")
    
    async def _handle_unhandled_message(self, message: Message):
        """Handle unhandled messages by forwarding to admin."""
        try:
            # Convert message to JSON for technolog group
            import json
            message_dict = message.model_dump() if hasattr(message, 'model_dump') else message.dict()
            formatted_message = json.dumps(message_dict, indent=4, ensure_ascii=False)
            
            # Truncate if too long
            if len(formatted_message) > self.MAX_TELEGRAM_MESSAGE_LENGTH - 3:
                formatted_message = formatted_message[:self.MAX_TELEGRAM_MESSAGE_LENGTH - 3] + "..."
            
            # Only process group/supergroup/channel messages, not private chats
            if message.chat.type in ["group", "supergroup", "channel"]:
                # Forward to technolog group
                if self.technolog_group_id:
                    try:
                        await self.bot.forward_message(
                            chat_id=self.technolog_group_id,
                            from_chat_id=message.chat.id,
                            message_id=message.message_id
                        )
                        
                        # Send formatted message details
                        await self.bot.send_message(
                            chat_id=self.technolog_group_id,
                            text=formatted_message
                        )
                    except Exception as e:
                        self.logger.error(f"Failed to forward to technolog group: {e}")
                
                # Forward directly to admin user and store mapping
                if self.ADMIN_USER_ID:
                    try:
                        admin_message = await self.bot.forward_message(
                            chat_id=self.ADMIN_USER_ID,
                            from_chat_id=message.chat.id,
                            message_id=message.message_id
                        )
                        
                        # Store mapping for admin replies
                        self.unhandled_messages[admin_message.message_id] = [
                            message.chat.id,
                            message.message_id,
                            message.from_user.first_name or "Unknown"
                        ]
                        
                        self.logger.info(f"Forwarded unhandled message from {message.from_user.id} to admin")
                        
                    except Exception as e:
                        self.logger.error(f"Failed to forward to admin user: {e}")
            
            elif message.chat.type == "private" and message.text == "/start":
                # Easter egg for /start command in private chat
                await message.reply(
                    "Everything that follows is a result of what you see here.\n"
                    "I'm sorry. My responses are limited. You must ask the right questions."
                )
            
        except Exception as e:
            self.logger.error(f"Error handling unhandled message: {e}")
    
    async def _handle_admin_reply(self, message: Message):
        """Handle admin replies to unhandled messages."""
        try:
            # Check if this is a reply to an unhandled message
            if (message.reply_to_message and 
                message.reply_to_message.message_id in self.unhandled_messages):
                
                # Get original message info
                original_chat_id, original_message_id, original_sender_name = \
                    self.unhandled_messages[message.reply_to_message.message_id]
                
                # Prepare reply text
                reply_text = message.text
                if reply_text and (reply_text.startswith("/") or reply_text.startswith("\\")):
                    # Remove command prefix
                    reply_text = reply_text[1:]
                
                # Send reply back to original user
                try:
                    if reply_text:
                        await self.bot.send_message(
                            chat_id=original_chat_id,
                            text=reply_text,
                            reply_to_message_id=original_message_id
                        )
                        
                        self.logger.info(f"Admin replied to message from {original_sender_name}")
                        
                    # Optionally remove mapping after reply
                    # del self.unhandled_messages[message.reply_to_message.message_id]
                    
                except Exception as e:
                    self.logger.error(f"Failed to send admin reply: {e}")
                    await message.reply(f"Failed to send reply: {e}")
            
        except Exception as e:
            self.logger.error(f"Error handling admin reply: {e}")
            await message.reply(f"Error processing reply: {e}")
    
    async def _handle_error(self, event: ErrorEvent):
        """Handle errors in aiogram 3.x style."""
        self.logger.error(f"Error occurred: {event.exception}")
        return True
    
    @asynccontextmanager
    async def lifespan(self):
        """Async context manager for bot lifespan."""
        try:
            # Startup
            self.stats['start_time'] = asyncio.get_event_loop().time()
            await self.setup_services()
            
            # Get bot info
            bot_info = await self.bot.get_me()
            self.logger.info(f"🤖 Bot started: @{bot_info.username} (ID: {bot_info.id})")
            
            # Get current time and commit info for startup notification
            bot_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                commit_info = get_latest_commit_info(self.logger)
            except:
                commit_info = "Git info unavailable"
            
            # Create startup messages
            bot_start_log_message = (
                f"\033[95m\nBot restarted at {bot_start_time}\n{'-' * 40}\n"
                f"Commit info: {commit_info}\n"
                "Финальная битва между людьми и роботами...\033[0m\n"
            )
            bot_start_message = (
                f"Bot restarted at {bot_start_time}\n{'-' * 40}\n"
                f"```\n{commit_info}\n```\n"
                "Финальная битва между людьми и роботами..."
            )
            
            # Log startup info with colors
            self.logger.info(bot_start_log_message)
            
            # Notify technolog group in restart topic (like aiogram 2.x version)
            if hasattr(self.settings, 'TECHNOLOG_GROUP_ID') and self.settings.TECHNOLOG_GROUP_ID:
                try:
                    techno_restart_topic = getattr(self.settings, 'TECHNO_RESTART', None)
                    await self.bot.send_message(
                        self.settings.TECHNOLOG_GROUP_ID,
                        bot_start_message,
                        message_thread_id=techno_restart_topic,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    self.logger.warning(f"Could not notify technolog group: {e}")
            
            
            yield
            
        finally:
            # Shutdown
            self.logger.info("🛑 Bot shutting down...")
            
            # Get bot info for shutdown notification
            try:
                bot_info = await self.bot.get_me()
                bot_shutdown_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                # Notify technolog group about shutdown
                if hasattr(self.settings, 'TECHNOLOG_GROUP_ID') and self.settings.TECHNOLOG_GROUP_ID:
                    try:
                        techno_start_topic = getattr(self.settings, 'TECHNO_RESTART', None)  # Use restart topic for shutdown message
                        await self.bot.send_message(
                            self.settings.TECHNOLOG_GROUP_ID,
                            f"🔴 <b>Bot Shutdown</b>\n\n"
                            f"Name: {bot_info.first_name}\n"
                            f"Username: @{bot_info.username}\n"
                            f"Version: aiogram 3.x\n"
                            f"Time: {bot_shutdown_time}",
                            parse_mode="HTML",
                            message_thread_id=techno_start_topic
                        )
                    except Exception as e:
                        self.logger.warning(f"Could not notify technolog group with shutdown message: {e}")
            except Exception as e:
                self.logger.warning(f"Could not send shutdown notification: {e}")
            
            # Save active user checks and banned users before shutdown
            await self.save_active_user_checks()
            await self.save_banned_users()
            
            if self.spam_service:
                await self.spam_service.close()
            
            await self.bot.session.close()
            self.logger.info("✅ Bot shutdown complete")
    
    async def start_polling(self):
        """Start the bot with polling."""
        async with self.lifespan():
            self.logger.info("🚀 Starting polling...")
            await self.dp.start_polling(self.bot)
    
    async def start_webhook(self, webhook_url: str, port: int = 8000):
        """Start the bot with webhook."""
        if not AIOHTTP_AVAILABLE:
            self.logger.error("aiohttp not available, cannot start webhook")
            return
            
        from aiohttp import web
        
        async with self.lifespan():
            # Setup webhook
            await self.bot.set_webhook(webhook_url)
            
            # Create aiohttp app
            app = web.Application()
            
            # Setup aiogram webhook handler
            SimpleRequestHandler(
                dispatcher=self.dp,
                bot=self.bot
            ).register(app, path="/webhook")
            
            # Start server
            self.logger.info(f"🚀 Starting webhook on port {port}")
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, '0.0.0.0', port)
            await site.start()
            
            # Keep running
            try:
                await asyncio.Future()  # Run forever
            finally:
                await runner.cleanup()


async def main():
    """Main entry point."""
    try:
        bot = ModernTelegramBot()
        
        # Load data files and start monitoring
        await bot.load_and_start_checks()
        
        # Check if webhook URL is configured
        webhook_url = getattr(bot.settings, 'WEBHOOK_URL', None)
        webhook_port = getattr(bot.settings, 'WEBHOOK_PORT', 8000)
        
        if webhook_url:
            await bot.start_webhook(webhook_url, webhook_port)
        else:
            await bot.start_polling()
            
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    if not AIOGRAM_3_AVAILABLE:
        print("❌ aiogram 3.x is required. Please install:")
        print("pip install aiogram==3.15.0")
        sys.exit(1)
    
    # Run the bot
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
