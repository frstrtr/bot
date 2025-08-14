#!/usr/bin/env python3
"""
Simple Bot Launcher - Launch your modern aiogram 3.x bot
Usage: python run_bot.py [--help]
"""

import sys
import signal
from pathlib import Path


def check_requirements():
    """Check if we have what we need."""
    try:
        import aiogram
        version = aiogram.__version__
        if not version.startswith('3.'):
            print(f"❌ Wrong aiogram version: {version}")
            print("   Please install aiogram 3.x:")
            print("   pip install -r requirements_modern.txt")
            return False
        
        print(f"✅ aiogram {version} ready")
        return True
    except ImportError:
        print("❌ aiogram not found")
        print("   Please install dependencies:")
        print("   pip install -r requirements_modern.txt")
        return False


def check_config():
    """Check if configuration is valid."""
    try:
        from config.settings_simple import Settings
        config = Settings()
        print(f"✅ Configuration loaded: {config.BOT_NAME}")
        return True
    except (ImportError, FileNotFoundError, ValueError, AttributeError) as e:
        print(f"❌ Configuration error: {e}")
        print("   Please check your .env file")
        return False


def signal_handler(_signum, _frame):
    """Handle Ctrl+C gracefully."""
    print("\n🛑 Shutting down bot...")
    sys.exit(0)


def main():
    """Main launcher."""
    # Setup signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    print("🤖 Modern Telegram Bot Launcher")
    print("=" * 40)
    print(f"🐍 Python {sys.version.split()[0]}")
    print("=" * 40)
    
    # Check if we're in the right directory
    if not Path("main_aiogram3.py").exists():
        print("❌ main_aiogram3.py not found")
        print("   Make sure you're in the bot directory")
        sys.exit(1)
    
    # Check requirements
    if not check_requirements():
        sys.exit(1)
    
    # Check configuration
    if not check_config():
        sys.exit(1)
    
    # Show help if requested
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h']:
        print("\n📚 Available commands:")
        print("  python run_bot.py           - Start the bot")
        print("  python run_bot.py --help    - Show this help")
        print("\n📁 Important files:")
        print("  main_aiogram3.py           - Modern aiogram 3.x bot")
        print("  .env                       - Configuration")
        print("  requirements_modern.txt    - Dependencies")
        print("\n🛠️  Development commands:")
        print("  python config/settings_simple.py test    - Test config")
        print("  python main_aiogram3.py                  - Direct start")
        return
    
    # Launch the bot
    print("\n🚀 Starting modern aiogram 3.x bot...")
    print("📝 Press Ctrl+C to stop")
    print("-" * 40)
    
    try:
        # Import and run the bot
        import asyncio
        from main_aiogram3 import main as run_bot
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n👋 Bot stopped")
    except (ImportError, RuntimeError) as e:
        print(f"\n❌ Error starting bot: {e}")
        print("Check the logs above for more details")
        sys.exit(1)


if __name__ == "__main__":
    main()
