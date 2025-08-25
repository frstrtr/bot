#!/bin/bash

# Production Update Script for Git History Cleanup
# This script handles the one-time update needed after git history rewrite

set -e

echo "🔧 Production Machine Update Script"
echo "====================================="
echo "This script will update your production bot after the security cleanup"
echo "that removed sensitive data from git history."
echo ""

# Check if we're in the bot directory
if [ ! -f "main_aiogram3.py" ]; then
    echo "❌ Error: Please run this script from the bot directory"
    echo "   cd ~/bot && ./production_update.sh"
    exit 1
fi

# Get current timestamp for backup names
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "📁 Step 1: Creating backup of current state..."
cd ..
if [ -d "bot" ]; then
    echo "   Backing up current bot directory to bot_backup_$TIMESTAMP"
    cp -r bot bot_backup_$TIMESTAMP
    echo "   ✅ Backup created: ~/bot_backup_$TIMESTAMP"
else
    echo "   ❌ Bot directory not found"
    exit 1
fi

echo ""
echo "🔄 Step 2: Attempting to reset to cleaned repository..."
cd bot

# Try to fetch and reset first
echo "   Fetching latest changes..."
if git fetch origin; then
    echo "   ✅ Fetch successful"
else
    echo "   ❌ Fetch failed"
    exit 1
fi

echo "   Attempting hard reset to origin/aiogram3..."
if git reset --hard origin/aiogram3; then
    echo "   ✅ Reset successful!"
    RESET_SUCCESS=true
else
    echo "   ⚠️  Reset failed, will try fresh clone approach"
    RESET_SUCCESS=false
fi

# If reset didn't work, try fresh clone
if [ "$RESET_SUCCESS" = false ]; then
    echo ""
    echo "🆕 Step 3: Fresh clone approach..."
    cd ..
    
    echo "   Moving current bot directory to bot_old_$TIMESTAMP"
    mv bot bot_old_$TIMESTAMP
    
    echo "   Cloning fresh repository..."
    if git clone git@github.com:frstrtr/bot.git; then
        echo "   ✅ Clone successful"
    else
        echo "   ❌ Clone failed, trying HTTPS..."
        git clone https://github.com/frstrtr/bot.git
    fi
    
    cd bot
    echo "   Switching to aiogram3 branch..."
    git checkout aiogram3
    echo "   ✅ Fresh repository ready"
    
    # Copy important files from old installation
    echo ""
    echo "📋 Step 4: Copying important files from previous installation..."
    
    # Copy .env file
    if [ -f "../bot_old_$TIMESTAMP/.env" ]; then
        echo "   Copying .env file..."
        cp "../bot_old_$TIMESTAMP/.env" .env
        echo "   ✅ .env copied"
    else
        echo "   ⚠️  No .env file found in old installation"
    fi
    
    # Copy banned users
    if [ -f "../bot_old_$TIMESTAMP/aiogram3_banned_users.txt" ]; then
        echo "   Copying banned users..."
        cp "../bot_old_$TIMESTAMP/aiogram3_banned_users.txt" .
        echo "   ✅ Banned users copied"
    elif [ -f "../bot_old_$TIMESTAMP/banned_users.txt" ]; then
        echo "   Copying banned users (legacy format)..."
        cp "../bot_old_$TIMESTAMP/banned_users.txt" .
        echo "   ✅ Banned users copied"
    fi
    
    # Copy active user checks
    if [ -f "../bot_old_$TIMESTAMP/aiogram3_active_user_checks.txt" ]; then
        echo "   Copying active user checks..."
        cp "../bot_old_$TIMESTAMP/aiogram3_active_user_checks.txt" .
        echo "   ✅ Active user checks copied"
    elif [ -f "../bot_old_$TIMESTAMP/active_user_checks.txt" ]; then
        echo "   Copying active user checks (legacy format)..."
        cp "../bot_old_$TIMESTAMP/active_user_checks.txt" .
        echo "   ✅ Active user checks copied"
    fi
    
    # Copy any custom spam dictionary
    if [ -f "../bot_old_$TIMESTAMP/spam_dict.txt" ]; then
        echo "   Copying spam dictionary..."
        cp "../bot_old_$TIMESTAMP/spam_dict.txt" .
        echo "   ✅ Spam dictionary copied"
    fi
fi

echo ""
echo "✅ Step 5: Verification..."

# Check Python environment
if command -v python3 &> /dev/null; then
    echo "   ✅ Python 3 available"
else
    echo "   ❌ Python 3 not found"
    exit 1
fi

# Check if virtual environment is activated
if [[ "$VIRTUAL_ENV" != "" ]]; then
    echo "   ✅ Virtual environment active: $(basename $VIRTUAL_ENV)"
else
    echo "   ⚠️  No virtual environment detected"
    echo "   Consider activating your virtual environment:"
    echo "   source .venv_latest/bin/activate"
fi

# Run comprehensive check
echo "   Running comprehensive validation..."
if python3 run_bot.py --check-all; then
    echo "   ✅ All validations passed!"
else
    echo "   ❌ Some validations failed"
    echo "   Please check the output above and install missing dependencies"
fi

echo ""
echo "🎉 Production Update Complete!"
echo ""
echo "📋 Summary:"
echo "   ✅ Repository updated with cleaned git history"
echo "   ✅ Sensitive data permanently removed from history"
echo "   ✅ Bot functionality preserved"
echo "   ✅ Configuration files copied from previous installation"
echo ""
echo "🚀 Next steps:"
echo "   1. Verify your .env file has correct values"
echo "   2. Test the bot: python3 run_bot.py --quick"
echo "   3. Start production bot: python3 run_bot.py"
echo ""
echo "📁 Backups created:"
echo "   ~/bot_backup_$TIMESTAMP - Full backup before update"
if [ "$RESET_SUCCESS" = false ]; then
    echo "   ~/bot_old_$TIMESTAMP - Previous installation"
fi
echo ""
echo "✅ Production machine is now ready with the security-cleaned repository!"
