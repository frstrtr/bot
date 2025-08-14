#!/usr/bin/env python3
"""
Bot launcher script for easy switching between versions.
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(cmd, background=False):
    """Run a command and return result."""
    try:
        if background:
            # Run in background
            process = subprocess.Popen(cmd, shell=True)
            return process
        else:
            # Run and wait
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
            return result
    except (subprocess.SubprocessError, OSError) as e:
        print(f"Error running command: {e}")
        return None


def check_environment():
    """Check if virtual environment and dependencies are ready."""
    venv_path = Path("venv")
    if not venv_path.exists():
        print("❌ Virtual environment not found. Creating...")
        result = run_command("python3 -m venv venv")
        if result.returncode != 0:
            print("Failed to create virtual environment")
            return False
    
    # Check if aiogram 3.x is installed
    result = run_command("source venv/bin/activate && python -c 'import aiogram; print(aiogram.__version__)' 2>/dev/null")
    if result and result.returncode == 0 and result.stdout.strip().startswith('3.'):
        print("✅ Environment ready")
        return True
    else:
        print("❌ aiogram 3.x not found. Installing...")
        install_result = run_command("source venv/bin/activate && pip install -r requirements_modern.txt")
        if install_result and install_result.returncode == 0:
            print("✅ Dependencies installed")
            return True
        else:
            print("Failed to install dependencies")
            return False


def run_bot_v3():
    """Run the modern aiogram 3.x bot."""
    print("🚀 Starting aiogram 3.x bot...")
    
    if not check_environment():
        return False
    
    cmd = "source venv/bin/activate && python main_aiogram3.py"
    process = run_command(cmd, background=True)
    
    if process:
        print(f"✅ Bot started with PID: {process.pid}")
        print("📝 Use Ctrl+C to stop the bot")
        try:
            process.wait()
        except KeyboardInterrupt:
            print("\n🛑 Stopping bot...")
            process.terminate()
            process.wait()
            print("✅ Bot stopped")
    
    return True


def run_bot_v2():
    """Run the aiogram 2.x compatibility bot."""
    print("🚀 Starting aiogram 2.x compatibility bot...")
    
    # Use system python for aiogram 2.x (from requirements.txt)
    cmd = "python3 main_aiogram2.py"
    process = run_command(cmd, background=True)
    
    if process:
        print(f"✅ Bot started with PID: {process.pid}")
        print("📝 Use Ctrl+C to stop the bot")
        try:
            process.wait()
        except KeyboardInterrupt:
            print("\n🛑 Stopping bot...")
            process.terminate()
            process.wait()
            print("✅ Bot stopped")
    
    return True


def test_config():
    """Test configuration loading."""
    print("🧪 Testing configuration...")
    
    result = run_command("source venv/bin/activate && python config/settings_simple.py test")
    if result.returncode == 0:
        print("✅ Configuration test passed")
        print(result.stdout)
        return True
    else:
        print("❌ Configuration test failed")
        print(result.stderr)
        return False


def show_config():
    """Show current configuration."""
    print("⚙️  Current configuration:")
    
    result = run_command("source venv/bin/activate && python config/settings_simple.py show")
    if result.returncode == 0:
        print(result.stdout)
    else:
        print("❌ Failed to load configuration")
        print(result.stderr)


def install_dependencies():
    """Install modern dependencies."""
    print("📦 Installing modern dependencies...")
    
    if not Path("venv").exists():
        print("Creating virtual environment...")
        create_result = run_command("python3 -m venv venv")
        if create_result.returncode != 0:
            print("❌ Failed to create virtual environment")
            return False
    
    print("Installing dependencies...")
    install_result = run_command("source venv/bin/activate && pip install -r requirements_modern.txt")
    
    if install_result.returncode == 0:
        print("✅ Dependencies installed successfully")
        return True
    else:
        print("❌ Failed to install dependencies")
        print(install_result.stderr)
        return False


def show_status():
    """Show bot status and information."""
    print("📊 Bot Status Information")
    print("=" * 50)
    
    # Check files
    files_to_check = [
        ("main_aiogram3.py", "Modern aiogram 3.x bot"),
        ("main_aiogram2.py", "Compatibility aiogram 2.x bot"),
        (".env", "Configuration file"),
        ("requirements_modern.txt", "Modern dependencies"),
        ("venv/", "Virtual environment")
    ]
    
    print("\n📁 Files:")
    for file_path, description in files_to_check:
        path = Path(file_path)
        status = "✅" if path.exists() else "❌"
        print(f"  {status} {file_path:<25} - {description}")
    
    # Check configuration
    print("\n⚙️  Configuration:")
    config_result = run_command("source venv/bin/activate && python config/settings_simple.py test 2>/dev/null")
    if config_result and config_result.returncode == 0:
        print("  ✅ Configuration loaded successfully")
        # Extract key info from stdout
        for line in config_result.stdout.split('\n'):
            if any(keyword in line for keyword in ['Bot name:', 'Bot token:', 'Admin group:']):
                print(f"  📋 {line}")
    else:
        print("  ❌ Configuration has issues")
    
    # Check dependencies
    print("\n📦 Dependencies:")
    aiogram_result = run_command("source venv/bin/activate && python -c 'import aiogram; print(aiogram.__version__)' 2>/dev/null")
    if aiogram_result and aiogram_result.returncode == 0:
        version = aiogram_result.stdout.strip()
        print(f"  ✅ aiogram: {version}")
        if version.startswith('3.'):
            print("  🎯 Using modern aiogram 3.x")
        else:
            print("  ⚠️  Using older aiogram version")
    else:
        print("  ❌ aiogram not found in virtual environment")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Bot launcher for aiogram 2.x/3.x versions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python launch.py --v3                    # Run aiogram 3.x bot
  python launch.py --v2                    # Run aiogram 2.x bot
  python launch.py --test                  # Test configuration
  python launch.py --install               # Install dependencies
  python launch.py --status                # Show status info
        """
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--v3', action='store_true', help='Run modern aiogram 3.x bot')
    group.add_argument('--v2', action='store_true', help='Run aiogram 2.x compatibility bot')
    group.add_argument('--test', action='store_true', help='Test configuration')
    group.add_argument('--config', action='store_true', help='Show configuration')
    group.add_argument('--install', action='store_true', help='Install modern dependencies')
    group.add_argument('--status', action='store_true', help='Show bot status')
    
    args = parser.parse_args()
    
    # Change to script directory
    script_dir = Path(__file__).parent
    if script_dir != Path('.'):
        print(f"📁 Changing to {script_dir}")
        import os
        os.chdir(script_dir)
    
    try:
        success = False  # Initialize success variable
        
        if args.v3:
            success = run_bot_v3()
        elif args.v2:
            success = run_bot_v2()
        elif args.test:
            success = test_config()
        elif args.config:
            show_config()
            success = True
        elif args.install:
            success = install_dependencies()
        elif args.status:
            show_status()
            success = True
        
        if not success:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except (subprocess.SubprocessError, OSError) as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
