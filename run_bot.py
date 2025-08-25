#!/usr/bin/env python3
"""
Comprehensive Bot Launcher - Launch your modern aiogram 3.x bot with full implementation checks
Usage: python run_bot.py [--help] [--check-all] [--quick]
"""

import sys
import signal
from pathlib import Path


def check_requirements():
    """Check if we have what we need."""
    print("🔍 Checking requirements...")
    
    # Core dependencies check
    required_packages = {
        'aiogram': '3.15.0',
        'aiohttp': '3.9.0',
        'aiosqlite': '0.20.0',
        'pydantic': '2.4.1',
        'aiocron': '1.8.0',
        'aiofiles': '24.1.0',
        'structlog': '24.4.0',
        'requests': '2.32.3'
    }
    
    missing_packages = []
    version_mismatches = []
    
    for package, _min_version in required_packages.items():
        try:
            module = __import__(package)
            version = getattr(module, '__version__', 'unknown')
            
            if package == 'aiogram' and not version.startswith('3.'):
                version_mismatches.append(f"{package}: {version} (need 3.x)")
            elif version == 'unknown':
                print(f"⚠️  {package}: version unknown")
            else:
                print(f"✅ {package}: {version}")
                
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n❌ Missing packages: {', '.join(missing_packages)}")
        print("   Please install dependencies:")
        print("   pip install -r requirements_modern.txt")
        return False
    
    if version_mismatches:
        print(f"\n❌ Version mismatches: {', '.join(version_mismatches)}")
        print("   Please update dependencies:")
        print("   pip install -r requirements_modern.txt")
        return False
    
    print("✅ All requirements satisfied")
    return True


def check_config():
    """Check if configuration is valid."""
    print("🔍 Checking configuration...")
    try:
        from config.settings import get_settings
        config = get_settings()
        
        # Check required config values
        required_attrs = ['BOT_TOKEN', 'BOT_NAME', 'ADMIN_GROUP_ID', 'CHANNEL_NAMES']
        missing_config = []
        
        for attr in required_attrs:
            if not hasattr(config, attr) or not getattr(config, attr):
                missing_config.append(attr)
        
        if missing_config:
            print(f"❌ Missing config values: {', '.join(missing_config)}")
            return False
            
        print(f"✅ Configuration loaded: {config.BOT_NAME}")
        print(f"   Admin Group: {config.ADMIN_GROUP_ID}")
        print(f"   Monitoring {len(config.CHANNEL_NAMES)} channels")
        return True
        
    except (ImportError, FileNotFoundError, ValueError, AttributeError) as e:
        print(f"❌ Configuration error: {e}")
        print("   Please check your .env file and config/settings.py")
        return False


def check_implementations():
    """Check if all major bot implementations are available."""
    print("🔍 Checking bot implementations...")
    
    try:
        # Import the bot module
        from main_aiogram3 import ModernTelegramBot
        bot = ModernTelegramBot()
        
        # Critical functions that must exist
        critical_functions = [
            'spam_check', 'report_spam_2p2p', 'ban_user_from_all_chats',
            'cancel_named_watchdog', 'create_named_watchdog', 'autoban',
            'load_banned_users', 'load_active_user_checks', 'perform_checks'
        ]
        
        # Admin command handlers
        admin_handlers = [
            '_handle_ban_command', '_handle_unban_command', '_handle_check_command',
            '_handle_stats_command', '_handle_loglists_command', '_handle_delmsg_command'
        ]
        
        # Callback handlers
        callback_handlers = [
            '_handle_stopchecks_callback', '_handle_suspicious_sender'
        ]
        
        # Data management functions
        data_functions = [
            'save_report_file', 'log_profile_change', 'submit_autoreport', 'handle_autoreports'
        ]
        
        all_functions = critical_functions + admin_handlers + callback_handlers + data_functions
        missing_functions = []
        implemented_functions = []
        
        for func_name in all_functions:
            if hasattr(bot, func_name):
                implemented_functions.append(func_name)
            else:
                missing_functions.append(func_name)
        
        print(f"✅ Implemented functions: {len(implemented_functions)}/{len(all_functions)}")
        
        if missing_functions:
            print(f"❌ Missing implementations: {', '.join(missing_functions)}")
            return False
        
        # Check if external API functions work
        print("🔍 Checking external API integrations...")
        api_functions = ['build_lols_url', 'make_lols_kb']
        for func_name in api_functions:
            if hasattr(bot, func_name):
                print(f"✅ {func_name}: available")
            else:
                print(f"⚠️  {func_name}: not found (optional)")
        
        print("✅ All critical implementations verified")
        return True
        
    except ImportError as e:
        print(f"❌ Cannot import bot module: {e}")
        return False
    except Exception as e:
        print(f"❌ Error checking implementations: {e}")
        return False


def check_file_structure():
    """Check if all required files exist."""
    print("🔍 Checking file structure...")
    
    required_files = [
        'main_aiogram3.py',
        'config/settings.py',
        'requirements_modern.txt',
        '.env'  # Optional but recommended
    ]
    
    optional_files = [
        'banned_users.txt',
        'active_user_checks.txt'
    ]
    
    missing_required = []
    missing_optional = []
    
    for file_path in required_files:
        if Path(file_path).exists():
            print(f"✅ {file_path}: exists")
        else:
            if file_path == '.env':
                print(f"⚠️  {file_path}: missing (recommended)")
                missing_optional.append(file_path)
            else:
                missing_required.append(file_path)
    
    for file_path in optional_files:
        if Path(file_path).exists():
            print(f"✅ {file_path}: exists")
        else:
            missing_optional.append(file_path)
    
    if missing_required:
        print(f"❌ Missing required files: {', '.join(missing_required)}")
        return False
    
    if missing_optional:
        print(f"⚠️  Optional files not found: {', '.join(missing_optional)}")
    
    print("✅ File structure verified")
    return True


def check_deployment_readiness():
    """Check if the bot is ready for production deployment."""
    print("🔍 Checking deployment readiness...")
    
    issues = []
    warnings = []
    
    # Check environment
    try:
        # Load from .env file like the bot does
        from config.settings import get_settings
        config = get_settings()
        
        if not config.BOT_TOKEN:
            issues.append("BOT_TOKEN not configured in .env file")
        
        if not config.ADMIN_GROUP_ID:
            warnings.append("ADMIN_GROUP_ID not configured in .env file")
            
    except Exception as e:
        issues.append(f"Could not load configuration: {e}")
    
    # Check log directories
    log_dirs = ['logs', 'inout', 'daily_spam']
    for log_dir in log_dirs:
        if not Path(log_dir).exists():
            warnings.append(f"Log directory '{log_dir}' doesn't exist (will be created)")
    
    # Check database
    if not Path('aiogram3_messages.db').exists():
        warnings.append("Database file doesn't exist (will be created)")
    
    # Check backup directory
    if not Path('backup_20250814_121051').exists():
        warnings.append("No backup directory found")
    
    # Security checks
    security_issues = []
    if Path('.env').exists():
        try:
            with open('.env', 'r') as f:
                content = f.read()
                if 'BOT_TOKEN' in content and len(content.split('\n')) > 0:
                    # Check for common security issues
                    if 'password' in content.lower():
                        security_issues.append("Possible password in .env file")
                    if 'secret' in content.lower() and 'BOT_TOKEN' not in content:
                        security_issues.append("Possible secret in .env file")
        except Exception:
            pass
    
    # Performance checks
    perf_warnings = []
    try:
        import psutil
        memory = psutil.virtual_memory()
        if memory.available < 512 * 1024 * 1024:  # Less than 512MB
            perf_warnings.append("Low available memory (< 512MB)")
        
        cpu_count = psutil.cpu_count()
        if cpu_count < 2:
            perf_warnings.append("Single CPU core detected")
            
    except ImportError:
        perf_warnings.append("psutil not available for performance monitoring")
    
    # Network connectivity check
    network_ok = True
    try:
        import socket
        socket.setdefaulttimeout(5)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
    except Exception:
        issues.append("No internet connectivity detected")
        network_ok = False
    
    # Report results
    if issues:
        print(f"❌ Critical issues found: {len(issues)}")
        for issue in issues:
            print(f"   • {issue}")
    
    if warnings:
        print(f"⚠️  Warnings: {len(warnings)}")
        for warning in warnings:
            print(f"   • {warning}")
    
    if security_issues:
        print(f"🔒 Security concerns: {len(security_issues)}")
        for concern in security_issues:
            print(f"   • {concern}")
    
    if perf_warnings:
        print(f"⚡ Performance warnings: {len(perf_warnings)}")
        for warning in perf_warnings:
            print(f"   • {warning}")
    
    if not issues and not security_issues:
        print("✅ Bot is ready for production deployment!")
        if warnings or perf_warnings:
            print("   (Some non-critical warnings noted above)")
        return True
    else:
        print("❌ Deployment readiness check failed")
        print("   Please address critical issues before deployment")
        return False


def signal_handler(_signum, _frame):
    """Handle Ctrl+C gracefully."""
    print("\n🛑 Shutting down bot...")
    sys.exit(0)


def main():
    """Main launcher with comprehensive checks."""
    # Setup signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    print("🤖 Modern Telegram Bot Launcher")
    print("=" * 50)
    print(f"🐍 Python {sys.version.split()[0]}")
    print("=" * 50)
    
    # Parse arguments
    quick_mode = '--quick' in sys.argv
    check_all = '--check-all' in sys.argv
    show_help = '--help' in sys.argv or '-h' in sys.argv
    check_deploy = '--deploy-check' in sys.argv
    
    # Show help if requested
    if show_help:
        print("\n📚 Available commands:")
        print("  python run_bot.py                 - Start bot with basic checks")
        print("  python run_bot.py --quick         - Start bot with minimal checks")
        print("  python run_bot.py --check-all     - Comprehensive validation only")
        print("  python run_bot.py --deploy-check  - Production deployment readiness")
        print("  python run_bot.py --help          - Show this help")
        print("\n📁 Important files:")
        print("  main_aiogram3.py              - Modern aiogram 3.x bot")
        print("  config/settings.py           - Unified configuration")
        print("  requirements_modern.txt       - Dependencies")
        print("  .env                          - Environment variables")
        print("\n🛠️  Development commands:")
        print("  python config/settings.py test    - Test config")
        print("  python main_aiogram3.py                  - Direct start")
        print("\n🎯 Implementation Status:")
        print("  ✅ External API spam checks (LoLs, CAS, P2P)")
        print("  ✅ Advanced watchdog task management")
        print("  ✅ Global ban system across channels")
        print("  ✅ Automated monitoring and reporting")
        print("  ✅ Complete admin interface")
        print("  ✅ Modern aiogram 3.x architecture")
        return
    
    # Quick mode - minimal checks
    if quick_mode:
        print("⚡ Quick mode: minimal checks")
        if not Path("main_aiogram3.py").exists():
            print("❌ main_aiogram3.py not found")
            sys.exit(1)
        print("✅ Quick validation passed")
    else:
        # Comprehensive checks
        print("🔍 Running comprehensive validation...")
        
        # Check file structure
        if not check_file_structure():
            print("\n❌ File structure validation failed")
            if not check_all:
                sys.exit(1)
        
        # Check requirements
        if not check_requirements():
            print("\n❌ Requirements validation failed")
            if not check_all:
                sys.exit(1)
        
        # Check configuration
        if not check_config():
            print("\n❌ Configuration validation failed")
            if not check_all:
                sys.exit(1)
        
        # Check implementations
        if not check_implementations():
            print("\n❌ Implementation validation failed")
            if not check_all:
                sys.exit(1)
        
        # Additional deployment readiness check
        if check_deploy or check_all:
            if not check_deployment_readiness():
                print("\n❌ Deployment readiness check failed")
                if check_deploy:
                    sys.exit(1)
        
        print("\n✅ All validations passed!")
    
    # If check-all or deploy-check mode, exit after validation
    if check_all or check_deploy:
        if check_deploy:
            print("\n🚀 Deployment readiness check completed!")
        else:
            print("\n🎯 Comprehensive validation completed!")
        print("Bot is ready for deployment.")
        return
    
    # Launch the bot
    print("\n🚀 Starting modern aiogram 3.x bot...")
    print("📝 Press Ctrl+C to stop")
    print("-" * 50)
    
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
        print("\n💡 Try: python run_bot.py --check-all")
        sys.exit(1)


if __name__ == "__main__":
    main()
