#!/usr/bin/env python3
"""
Modern Telegram bot using aiogram 3.x with structured architecture.
This is a complete rewrite using the latest aiogram features.
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
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
    DATABASE_AVAILABLE = True
except ImportError:
    print("⚠️  utils.database not available, using fallback")
    DATABASE_AVAILABLE = False
    
    class DatabaseManager:
        def __init__(self, *args, **kwargs): pass
        async def initialize(self): pass
        async def update_user_activity(self, user_id): pass
        async def store_message(self, *args, **kwargs): pass
    
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
        
        # Global dictionaries for tracking users (from aiogram 2.x compatibility)
        self.active_user_checks_dict = {}
        self.banned_users_dict = {}
        
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
        
        @self.dp.callback_query(lambda c: c.data.startswith(("suspiciousglobalban_", "suspiciousban_", "suspiciousdelmsg_", "confirmdelmsg_", "canceldelmsg_", "confirmban_", "cancelban_", "confirmglobalban_", "cancelglobalban_")))
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
                await message.answer("❌ Usage: /unban &lt;user_id&gt;")
                return
            
            try:
                user_id = int(args[0])
            except ValueError:
                await message.answer("❌ Invalid user ID.")
                return
            
            if self.ban_service:
                result = await self.ban_service.unban_user(
                    bot=self.bot,
                    user_id=user_id,
                    chat_id=message.chat.id,
                    unbanned_by=message.from_user.id
                )
                
                if result.success:
                    await message.answer(f"✅ User {user_id} has been unbanned.")
                else:
                    await message.answer(f"❌ Failed to unban user: {result.error_message}")
            else:
                await message.answer("❌ Ban service not available.")
                
        except Exception as e:
            self.logger.error(f"Error in unban command: {e}")
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
        return user_id == self.ADMIN_USER_ID
    
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
            message_link = f"https://t.me/c/{str(susp_chat_id)[4:]}/{susp_message_id}"
            lols_link = self.build_lols_url(susp_user_id)
            
            # Create inline keyboard with links
            kb = InlineKeyboardBuilder()
            kb.row(InlineKeyboardButton(text="🔗 View Original Message 🔗", url=message_link))
            kb.row(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))
            
            callback_answer = None
            
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
                        
                    # Global ban user
                    if self.ban_service:
                        await self.ban_service.ban_user_globally(susp_user_id, susp_user_name, f"Suspicious activity - Admin decision by @{admin_username}")
                    
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
            message_link = f"https://t.me/c/{str(chat_id)[4:]}/{message_id}"
            kb.row(InlineKeyboardButton(text="🔗 View Original Message", url=message_link))
            
            # Spam check link
            lols_link = self.build_lols_url(user_id)
            kb.row(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_link))
            
            # Action buttons
            kb.row(
                InlineKeyboardButton(text="🚫 Ban User", callback_data=f"suspiciousban_{chat_id}_{report_id}_{user_id}"),
                InlineKeyboardButton(text="🌐 Global Ban", callback_data=f"suspiciousglobalban_{chat_id}_{report_id}_{user_id}")
            )
            kb.row(
                InlineKeyboardButton(text="🗑️ Delete Message", callback_data=f"suspiciousdelmsg_{chat_id}_{report_id}_{user_id}")
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
                    is_spam = lols or is_spammer or cas > 0
                    
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
        return f"https://t.me/oLolsBot?start={user_id}"
    
    def make_lols_kb(self, user_id: int) -> InlineKeyboardMarkup:
        """Create a one-button keyboard with the LOLS check link."""
        lols_url = self.build_lols_url(user_id)
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="ℹ️ Check Spam Data ℹ️", url=lols_url))
        return kb.as_markup()
    
    async def check_and_autoban(self, user_id: int, reason: str = "Automated ban", **kwargs) -> bool:
        """Check user and automatically ban if conditions are met."""
        try:
            # Check if user is in banned list
            if user_id in self.banned_users_dict:
                self.logger.debug(f"User {user_id} already banned")
                return True
            
            # Perform spam check
            is_spam = await self.spam_check(user_id)
            
            if is_spam:
                # Auto-ban the user
                if self.ban_service:
                    ban_result = await self.ban_service.ban_user(
                        user_id=user_id,
                        reason=reason,
                        admin_id=0  # System auto-ban
                    )
                    
                    if ban_result.success:
                        self.banned_users_dict[user_id] = f"AUTO_BAN_{reason}"
                        self.logger.info(f"Auto-banned user {user_id}: {reason}")
                        return True
                    else:
                        self.logger.error(f"Failed to auto-ban user {user_id}: {ban_result.error_message}")
                        return False
            
            return False
        except Exception as e:
            self.logger.error(f"Error in check_and_autoban for user {user_id}: {e}")
            return False
    
    async def perform_checks(self, user_id: int, user_name: str = "!UNDEFINED!", event_record: str = "", inout_logmessage: str = ""):
        """Perform 3-hour monitoring checks on a user."""
        try:
            self.logger.info(f"Starting 3-hour monitoring for user {user_id}")
            
            # Add user to active checks if not already there
            if user_id not in self.active_user_checks_dict:
                self.active_user_checks_dict[user_id] = {
                    "username": user_name,
                    "start_time": asyncio.get_event_loop().time(),
                    "event_record": event_record
                }
            
            # Wait for 3 hours (or shorter for testing)
            monitoring_duration = 3 * 60 * 60  # 3 hours in seconds
            await asyncio.sleep(monitoring_duration)
            
            # After 3 hours, perform final check
            if user_id in self.active_user_checks_dict:
                final_check = await self.check_and_autoban(user_id, "3hr monitoring completed")
                
                if not final_check:
                    # User is clean, remove from monitoring
                    del self.active_user_checks_dict[user_id]
                    self.logger.info(f"User {user_id} monitoring completed - user is clean")
                else:
                    self.logger.info(f"User {user_id} monitoring completed - user was banned")
            
        except asyncio.CancelledError:
            self.logger.info(f"Monitoring cancelled for user {user_id}")
            if user_id in self.active_user_checks_dict:
                del self.active_user_checks_dict[user_id]
        except Exception as e:
            self.logger.error(f"Error in perform_checks for user {user_id}: {e}")
            if user_id in self.active_user_checks_dict:
                del self.active_user_checks_dict[user_id]
    
    async def log_lists(self):
        """Log active checks and banned users, then clean up daily data."""
        try:
            self.logger.info(f"Daily log: {len(self.banned_users_dict)} banned users, {len(self.active_user_checks_dict)} active checks")
            
            # Save data to files
            from datetime import datetime, timedelta
            import os
            
            today = (datetime.now() - timedelta(days=1)).strftime("%d-%m-%Y")
            
            # Ensure directories exist
            os.makedirs("inout", exist_ok=True)
            os.makedirs("daily_spam", exist_ok=True)
            
            # Save banned users to file
            filename = f"inout/banned_users_{today}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                for user_id, user_name in self.banned_users_dict.items():
                    f.write(f"{user_id}: {user_name}\n")
            
            # Clear banned users dict for new day
            self.banned_users_dict.clear()
            
            self.logger.info(f"Daily cleanup completed, banned users saved to {filename}")
            
        except Exception as e:
            self.logger.error(f"Error in log_lists: {e}")
    
    def setup_scheduled_tasks(self):
        """Setup daily scheduled tasks."""
        if AIOCRON_AVAILABLE:
            # Schedule daily log cleanup at 4 AM Mauritius time
            @aiocron.crontab("0 4 * * *", tz=ZoneInfo("Indian/Mauritius"))
            async def scheduled_log():
                await self.log_lists()
            
            self.logger.info("✅ Scheduled tasks setup completed")
        else:
            self.logger.warning("⚠️  Scheduled tasks disabled - aiocron not available")
    
    def _is_forwarded_from_unknown_channel(self, message: Message) -> bool:
        """Check if message is forwarded from an unknown channel."""
        if not message.forward_origin:
            return False
        
        # Check if it's forwarded from a channel
        if hasattr(message.forward_origin, 'chat') and message.forward_origin.chat:
            channel_id = message.forward_origin.chat.id
            # Check if channel is not in allowed forward channels
            allowed_channels = getattr(self.settings, 'ALLOWED_FORWARD_CHANNELS', [])
            return channel_id not in allowed_channels
        
        return False
    
    def _is_in_monitored_channel(self, message: Message) -> bool:
        """Check if message is in a monitored channel."""
        if not message.chat:
            return False
        
        monitored_channels = getattr(self.settings, 'CHANNEL_IDS', [])
        return message.chat.id in monitored_channels
    
    def _is_valid_message(self, message: Message) -> bool:
        """Check if message is valid for unhandled message processing."""
        if not message.chat or not message.from_user:
            return False
        
        # Exclude admin groups, technolog group, admin user, and managed channels
        excluded_ids = [
            self.admin_group_id,
            self.technolog_group_id, 
            self.ADMIN_USER_ID
        ] + getattr(self.settings, 'CHANNEL_IDS', [])
        
        return (
            message.chat.id not in excluded_ids and
            not message.forward_origin and  # Not forwarded
            not message.from_user.is_bot     # Not from bot
        )
    
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
                
                # Check if user is already banned
                if user_id in self.banned_users_dict:
                    try:
                        await message.delete()
                        self.logger.info(f"Deleted message from banned user {user_id}")
                    except Exception as e:
                        self.logger.error(f"Failed to delete message from banned user: {e}")
                    return
                
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
                                asyncio.create_task(
                                    self.perform_checks(
                                        user_id=user_id,
                                        user_name=message.from_user.username or "!UNDEFINED!",
                                        event_record=f"Suspicious message detected: {spam_result.spam_type}"
                                    ),
                                    name=f"monitor_{user_id}"
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
            
            # Notify admin group
            if hasattr(self.settings, 'ADMIN_GROUP_ID') and self.settings.ADMIN_GROUP_ID:
                try:
                    await self.bot.send_message(
                        self.settings.ADMIN_GROUP_ID,
                        f"🤖 <b>Bot Started</b>\n\n"
                        f"Name: {bot_info.first_name}\n"
                        f"Username: @{bot_info.username}\n"
                        f"Version: aiogram 3.x\n"
                        f"Time: {asyncio.get_event_loop().time()}"
                    )
                except Exception as e:
                    self.logger.warning(f"Could not notify admin group: {e}")
            
            yield
            
        finally:
            # Shutdown
            self.logger.info("🛑 Bot shutting down...")
            
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
