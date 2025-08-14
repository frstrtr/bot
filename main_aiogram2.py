"""Modern Telegram bot with aiogram 2.x compatibility and structured architecture."""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, Optional

# aiogram 2.x imports
from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import exceptions

# Project imports - create empty __init__.py files first
sys.path.append(str(Path(__file__).parent))

# Try to import our modules, with fallbacks for missing ones
try:
    from config.settings import get_settings, Settings
except ImportError:
    print("Warning: config.settings not found, using fallback configuration")
    class Settings:
        BOT_TOKEN = ""
        LOG_LEVEL = "INFO"
        DATABASE_URL = "messages.db"
    
    def get_settings():
        return Settings()

try:
    from utils.database import DatabaseManager, initialize_database
except ImportError:
    print("Warning: utils.database not found, using fallback database")
    class DatabaseManager:
        def __init__(self, *args, **kwargs): pass
        async def initialize(self): pass
    
    async def initialize_database(): pass

try:
    from utils.logger import initialize_logger, get_bot_logger
except ImportError:
    print("Warning: utils.logger not found, using fallback logging")
    def initialize_logger(settings): 
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger()
    
    def get_bot_logger(): 
        return logging.getLogger()

try:
    from services.spam_service import SpamService
except ImportError:
    print("Warning: services.spam_service not found, using fallback")
    class SpamService:
        def __init__(self, *args, **kwargs): pass
        async def initialize(self): pass
        async def close(self): pass

try:
    from services.ban_service import BanService
except ImportError:
    print("Warning: services.ban_service not found, using fallback")
    class BanService:
        def __init__(self, *args, **kwargs): pass
        async def initialize(self): pass


class BotStates(StatesGroup):
    """FSM states for bot interactions."""
    waiting_for_report_reason = State()
    waiting_for_ban_reason = State()
    waiting_for_admin_command = State()


class ModernTelegramBot:
    """Modern structured Telegram bot using aiogram 2.x."""
    
    def __init__(self):
        """Initialize the bot with modern architecture."""
        
        # Load configuration
        self.settings = get_settings()
        
        # Validate required settings
        if not self.settings.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        
        # Initialize logging
        self.logger = initialize_logger(self.settings)
        
        # Initialize bot and dispatcher
        self.bot = Bot(token=self.settings.BOT_TOKEN)
        self.storage = MemoryStorage()
        self.dp = Dispatcher(self.bot, storage=self.storage)
        
        # Initialize services
        self.db_manager: Optional[DatabaseManager] = None
        self.spam_service: Optional[SpamService] = None
        self.ban_service: Optional[BanService] = None
        
        # Statistics
        self.stats = {
            'messages_processed': 0,
            'spam_detected': 0,
            'users_banned': 0,
            'startup_time': None
        }
    
    async def setup_services(self) -> None:
        """Initialize all services."""
        try:
            # Database
            self.db_manager = DatabaseManager(self.settings.DATABASE_URL)
            await self.db_manager.initialize()
            
            # Spam service
            self.spam_service = SpamService(self.settings, self.db_manager)
            await self.spam_service.initialize()
            
            # Ban service
            self.ban_service = BanService(self.settings, self.db_manager)
            await self.ban_service.initialize()
            
            self.logger.info("All services initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize services: {e}")
            raise
    
    def setup_handlers(self) -> None:
        """Register all message handlers."""
        
        # Admin commands
        @self.dp.message_handler(Command(['start', 'help']), state='*')
        async def cmd_help(message: types.Message, state: FSMContext):
            """Help command handler."""
            await self._handle_help_command(message, state)
        
        @self.dp.message_handler(Command(['ban']), state='*')
        async def cmd_ban(message: types.Message, state: FSMContext):
            """Ban command handler."""
            await self._handle_ban_command(message, state)
        
        @self.dp.message_handler(Command(['unban']), state='*')
        async def cmd_unban(message: types.Message, state: FSMContext):
            """Unban command handler."""
            await self._handle_unban_command(message, state)
        
        @self.dp.message_handler(Command(['stats']), state='*')
        async def cmd_stats(message: types.Message):
            """Statistics command handler."""
            await self._handle_stats_command(message)
        
        # Chat member updates
        @self.dp.chat_member_handler()
        async def chat_member_update(update: types.ChatMemberUpdated):
            """Handle chat member updates."""
            await self._handle_chat_member_update(update)
        
        # Regular messages
        @self.dp.message_handler(content_types=['text', 'photo', 'video', 'document', 'sticker'])
        async def process_message(message: types.Message):
            """Process all incoming messages."""
            await self._handle_message(message)
        
        # Callback queries
        @self.dp.callback_query_handler(state='*')
        async def process_callback(callback_query: types.CallbackQuery, state: FSMContext):
            """Process callback queries."""
            await self._handle_callback_query(callback_query, state)
        
        self.logger.info("Message handlers registered")
    
    async def _handle_help_command(self, message: types.Message, state: FSMContext) -> None:
        """Handle help command."""
        help_text = (
            "🤖 *Modern Spam Detection Bot*\n\n"
            "📋 *Available Commands:*\n"
            "/help - Show this help message\n"
            "/ban - Ban a user (reply to message)\n"
            "/unban - Unban a user\n"
            "/stats - Show bot statistics\n\n"
            "🛡️ *Features:*\n"
            "• Automatic spam detection\n"
            "• User monitoring\n"
            "• Admin notifications\n"
            "• Comprehensive logging"
        )
        
        try:
            await message.reply(help_text, parse_mode='Markdown')
        except exceptions.TelegramAPIError as e:
            self.logger.error(f"Error sending help message: {e}")
    
    async def _handle_ban_command(self, message: types.Message, state: FSMContext) -> None:
        """Handle ban command."""
        try:
            # Check if user is admin (simplified check)
            if not await self._is_user_admin(message.from_user.id, message.chat.id):
                await message.reply("❌ You don't have permission to ban users.")
                return
            
            if message.reply_to_message:
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
                        await message.reply(f"✅ User {target_user.full_name} has been banned.")
                        self.stats['users_banned'] += 1
                    else:
                        await message.reply(f"❌ Failed to ban user: {result.error_message}")
                else:
                    await message.reply("❌ Ban service not available.")
            else:
                await message.reply("❌ Please reply to a message to ban the user.")
                
        except Exception as e:
            self.logger.error(f"Error in ban command: {e}")
            await message.reply("❌ An error occurred while processing the ban command.")
    
    async def _handle_unban_command(self, message: types.Message, state: FSMContext) -> None:
        """Handle unban command."""
        try:
            if not await self._is_user_admin(message.from_user.id, message.chat.id):
                await message.reply("❌ You don't have permission to unban users.")
                return
            
            # Parse user ID from command
            args = message.get_args().split()
            if not args:
                await message.reply("❌ Please provide a user ID: /unban <user_id>")
                return
            
            try:
                user_id = int(args[0])
            except ValueError:
                await message.reply("❌ Invalid user ID.")
                return
            
            if self.ban_service:
                result = await self.ban_service.unban_user(
                    bot=self.bot,
                    user_id=user_id,
                    chat_id=message.chat.id,
                    unbanned_by=message.from_user.id
                )
                
                if result.success:
                    await message.reply(f"✅ User {user_id} has been unbanned.")
                else:
                    await message.reply(f"❌ Failed to unban user: {result.error_message}")
            else:
                await message.reply("❌ Ban service not available.")
                
        except Exception as e:
            self.logger.error(f"Error in unban command: {e}")
            await message.reply("❌ An error occurred while processing the unban command.")
    
    async def _handle_stats_command(self, message: types.Message) -> None:
        """Handle statistics command."""
        try:
            stats_text = (
                "📊 *Bot Statistics*\n\n"
                f"📨 Messages processed: {self.stats['messages_processed']}\n"
                f"🚫 Spam detected: {self.stats['spam_detected']}\n"
                f"🔨 Users banned: {self.stats['users_banned']}\n"
            )
            
            if self.stats['startup_time']:
                uptime = asyncio.get_event_loop().time() - self.stats['startup_time']
                hours, remainder = divmod(uptime, 3600)
                minutes, seconds = divmod(remainder, 60)
                stats_text += f"⏰ Uptime: {int(hours)}h {int(minutes)}m {int(seconds)}s\n"
            
            await message.reply(stats_text, parse_mode='Markdown')
            
        except Exception as e:
            self.logger.error(f"Error in stats command: {e}")
            await message.reply("❌ An error occurred while getting statistics.")
    
    async def _handle_chat_member_update(self, update: types.ChatMemberUpdated) -> None:
        """Handle chat member updates (joins, leaves, etc.)."""
        try:
            if update.new_chat_member.status == 'member' and update.old_chat_member.status == 'left':
                # User joined
                user = update.new_chat_member.user
                self.logger.info(f"User {user.id} ({user.full_name}) joined chat {update.chat.id}")
                
                # Check if user should be auto-banned
                if self.ban_service:
                    result = await self.ban_service.check_auto_ban_conditions(
                        bot=self.bot,
                        user_id=user.id,
                        chat_id=update.chat.id
                    )
                    
                    if result and result.success:
                        self.logger.info(f"Auto-banned user {user.id} upon joining")
            
        except Exception as e:
            self.logger.error(f"Error handling chat member update: {e}")
    
    async def _handle_message(self, message: types.Message) -> None:
        """Handle regular messages."""
        try:
            self.stats['messages_processed'] += 1
            
            # Update user activity in database
            if self.db_manager:
                await self.db_manager.update_user_activity(message.from_user.id)
            
            # Check for spam
            if self.spam_service:
                spam_result = await self.spam_service.analyze_message(message)
                
                if spam_result.is_spam:
                    self.stats['spam_detected'] += 1
                    
                    # Delete the message
                    try:
                        await message.delete()
                    except exceptions.MessageCantBeDeleted:
                        pass
                    
                    # Auto-ban if confidence is high
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
            
        except Exception as e:
            self.logger.error(f"Error handling message: {e}")
    
    async def _handle_callback_query(self, callback_query: types.CallbackQuery, state: FSMContext) -> None:
        """Handle callback queries."""
        try:
            await callback_query.answer()
            
            data = callback_query.data
            if data.startswith('ban_'):
                # Handle ban callback
                user_id = int(data.split('_')[1])
                # Implement ban logic here
                pass
            elif data.startswith('report_'):
                # Handle report callback
                report_id = data.split('_')[1]
                # Implement report logic here
                pass
            
        except Exception as e:
            self.logger.error(f"Error handling callback query: {e}")
    
    async def _is_user_admin(self, user_id: int, chat_id: int) -> bool:
        """Check if user is admin in the chat."""
        try:
            member = await self.bot.get_chat_member(chat_id, user_id)
            return member.status in ['administrator', 'creator']
        except exceptions.TelegramAPIError:
            return False
    
    async def on_startup(self, dp: Dispatcher) -> None:
        """Execute on bot startup."""
        try:
            self.stats['startup_time'] = asyncio.get_event_loop().time()
            
            await self.setup_services()
            
            # Get bot info
            bot_info = await self.bot.get_me()
            self.logger.info(f"Bot started: @{bot_info.username}")
            
            # Notify admins (if configured)
            admin_group_id = getattr(self.settings, 'ADMIN_GROUP_ID', None)
            if admin_group_id:
                try:
                    await self.bot.send_message(
                        admin_group_id,
                        f"🤖 Bot started successfully!\n"
                        f"Name: {bot_info.first_name}\n"
                        f"Username: @{bot_info.username}"
                    )
                except exceptions.TelegramAPIError as e:
                    self.logger.warning(f"Could not notify admins: {e}")
            
        except Exception as e:
            self.logger.error(f"Error during startup: {e}")
            raise
    
    async def on_shutdown(self, dp: Dispatcher) -> None:
        """Execute on bot shutdown."""
        try:
            self.logger.info("Bot shutting down...")
            
            # Close services
            if self.spam_service:
                await self.spam_service.close()
            
            # Close database connections
            if self.db_manager:
                # Database manager would have a close method in real implementation
                pass
            
            # Close bot session
            await self.bot.close()
            
            self.logger.info("Bot shutdown complete")
            
        except Exception as e:
            self.logger.error(f"Error during shutdown: {e}")
    
    def run_polling(self) -> None:
        """Run the bot using polling."""
        try:
            self.setup_handlers()
            
            self.logger.info("Starting bot with polling...")
            
            executor.start_polling(
                dispatcher=self.dp,
                on_startup=self.on_startup,
                on_shutdown=self.on_shutdown,
                skip_updates=True
            )
            
        except KeyboardInterrupt:
            self.logger.info("Bot stopped by user")
        except Exception as e:
            self.logger.error(f"Error running bot: {e}")
            raise


def main():
    """Main entry point."""
    try:
        bot = ModernTelegramBot()
        bot.run_polling()
        
    except KeyboardInterrupt:
        print("\nBot stopped by user")
    except Exception as e:
        print(f"Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
