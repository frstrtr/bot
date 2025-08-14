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
