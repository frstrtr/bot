"""Yet Another Telegram Bot for Spammers Detection and Reporting

Modernized for aiogram 3.x and Python 3.11+
Refactored from monolithic structure to service-oriented architecture.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

# Set timezone early
os.environ.setdefault("TZ", "Indian/Mauritius")
try:
    import time
    time.tzset()
except Exception:
    pass

# aiogram 3.x imports
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ChatMemberStatus,
    Update,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# Local imports
from config.settings import Settings, get_settings
from services.spam_service import SpamService
from services.report_service import ReportService
from services.ban_service import BanService
from services.monitoring_service import MonitoringService
from handlers import (
    setup_admin_handlers,
    setup_chat_member_handlers,
    setup_message_handlers,
    setup_callback_handlers,
)
from middleware.auth import AdminAuthMiddleware
from middleware.logging import LoggingMiddleware
from middleware.throttling import ThrottlingMiddleware
from utils.database import Database
from utils.logger import setup_logger


class BotStates(StatesGroup):
    """FSM states for bot interactions."""
    waiting_for_ban_reason = State()
    waiting_for_report_details = State()


class ModernTelegramBot:
    """Main bot application class."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = setup_logger(__name__)
        
        # Initialize bot with default properties
        default_properties = DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        )
        
        self.bot = Bot(
            token=settings.BOT_TOKEN,
            default=default_properties,
        )
        
        # Initialize dispatcher with FSM storage
        self.dp = Dispatcher(storage=MemoryStorage())
        
        # Initialize services
        self.db: Database | None = None
        self.spam_service: SpamService | None = None
        self.report_service: ReportService | None = None
        self.ban_service: BanService | None = None
        self.monitoring_service: MonitoringService | None = None
    
    async def setup_services(self) -> None:
        """Initialize all services."""
        self.db = Database(self.settings.DATABASE_URL)
        await self.db.connect()
        
        self.spam_service = SpamService(self.db, self.settings)
        self.report_service = ReportService(self.db, self.settings)
        self.ban_service = BanService(self.bot, self.db, self.settings)
        self.monitoring_service = MonitoringService(self.bot, self.db, self.settings)
    
    async def setup_middleware(self) -> None:
        """Setup middleware."""
        # Order matters for middleware
        self.dp.message.middleware(LoggingMiddleware())
        self.dp.callback_query.middleware(LoggingMiddleware())
        self.dp.chat_member.middleware(LoggingMiddleware())
        
        self.dp.message.middleware(ThrottlingMiddleware())
        self.dp.callback_query.middleware(ThrottlingMiddleware())
        
        # Admin-only middleware for admin commands
        self.dp.message.middleware(AdminAuthMiddleware(self.settings))
    
    async def setup_handlers(self) -> None:
        """Setup all handlers."""
        # Pass services to handler setup functions
        services = {
            'spam_service': self.spam_service,
            'report_service': self.report_service,
            'ban_service': self.ban_service,
            'monitoring_service': self.monitoring_service,
            'settings': self.settings,
        }
        
        setup_admin_handlers(self.dp, **services)
        setup_chat_member_handlers(self.dp, **services)
        setup_message_handlers(self.dp, **services)
        setup_callback_handlers(self.dp, **services)
    
    async def on_startup(self) -> None:
        """Startup hook."""
        self.logger.info("Bot starting up...")
        
        await self.setup_services()
        await self.setup_middleware()
        await self.setup_handlers()
        
        # Initialize monitoring tasks
        if self.monitoring_service:
            await self.monitoring_service.start_background_tasks()
        
        # Send startup notification
        bot_info = await self.bot.get_me()
        startup_message = (
            f"🤖 Bot <b>{bot_info.full_name}</b> started!\n"
            f"📅 Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"🆔 Bot ID: <code>{bot_info.id}</code>\n"
            f"🔧 aiogram version: 3.15.0\n"
            f"🐍 Python version: {sys.version.split()[0]}"
        )
        
        try:
            await self.bot.send_message(
                chat_id=self.settings.ADMIN_GROUP_ID,
                text=startup_message,
                message_thread_id=self.settings.TECHNO_RESTART,
            )
        except Exception as e:
            self.logger.warning(f"Failed to send startup message: {e}")
        
        self.logger.info("Bot startup completed")
    
    async def on_shutdown(self) -> None:
        """Shutdown hook."""
        self.logger.info("Bot shutting down...")
        
        # Stop monitoring tasks
        if self.monitoring_service:
            await self.monitoring_service.stop_background_tasks()
        
        # Send shutdown notification
        shutdown_message = (
            f"🔴 Bot shutting down at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        
        try:
            await self.bot.send_message(
                chat_id=self.settings.ADMIN_GROUP_ID,
                text=shutdown_message,
                message_thread_id=self.settings.TECHNO_RESTART,
            )
        except Exception as e:
            self.logger.warning(f"Failed to send shutdown message: {e}")
        
        # Close database connections
        if self.db:
            await self.db.disconnect()
        
        # Close bot session
        await self.bot.session.close()
        
        self.logger.info("Bot shutdown completed")
    
    async def start_polling(self) -> None:
        """Start polling mode."""
        await self.on_startup()
        
        try:
            await self.dp.start_polling(
                self.bot,
                allowed_updates=[
                    "message",
                    "callback_query", 
                    "chat_member",
                    "my_chat_member",
                ],
                skip_updates=True,
            )
        finally:
            await self.on_shutdown()
    
    async def start_webhook(self, webhook_url: str, port: int = 8000) -> None:
        """Start webhook mode."""
        await self.on_startup()
        
        try:
            # Setup webhook
            await self.bot.set_webhook(
                url=webhook_url,
                allowed_updates=[
                    "message",
                    "callback_query",
                    "chat_member", 
                    "my_chat_member",
                ],
            )
            
            # Create aiohttp application
            app = web.Application()
            handler = SimpleRequestHandler(dispatcher=self.dp, bot=self.bot)
            handler.register(app, path="/webhook")
            
            setup_application(app, self.dp, bot=self.bot)
            
            # Start server
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, "0.0.0.0", port)
            await site.start()
            
            self.logger.info(f"Webhook server started on port {port}")
            
            # Keep running
            await asyncio.Event().wait()
            
        finally:
            await self.on_shutdown()


async def main() -> None:
    """Main entry point."""
    # Load settings
    settings = get_settings()
    
    # Create and run bot
    bot = ModernTelegramBot(settings)
    
    if settings.WEBHOOK_URL:
        await bot.start_webhook(settings.WEBHOOK_URL, settings.WEBHOOK_PORT)
    else:
        await bot.start_polling()


if __name__ == "__main__":
    asyncio.run(main())
