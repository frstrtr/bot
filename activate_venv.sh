#!/bin/bash
# Auto-activate virtual environment for bot project
# Usage: source activate_venv.sh

# Check if we're already in the venv
if [[ "$VIRTUAL_ENV" == *"/home/user0/bot/venv" ]]; then
    echo "✅ Virtual environment already activated: $VIRTUAL_ENV"
else
    # Activate the venv
    if [ -f "/home/user0/bot/venv/bin/activate" ]; then
        source /home/user0/bot/venv/bin/activate
        echo "✅ Virtual environment activated: $VIRTUAL_ENV"
        echo "🐍 Python: $(which python)"
        echo "📦 aiogram: $(python -c 'import aiogram; print(aiogram.__version__)' 2>/dev/null || echo 'Not installed')"
    else
        echo "❌ Virtual environment not found at /home/user0/bot/venv"
        echo "Please run: python3 -m venv venv && pip install -r requirements_modern.txt"
    fi
fi

# Change to bot directory
cd /home/user0/bot 2>/dev/null || echo "⚠️  Could not change to bot directory"
