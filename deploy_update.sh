#!/bin/bash
# Production deployment script with minimal service interruption
# Deploys updates, upgrades dependencies, and restarts the bot

set -e  # Exit on error

BOT_DIR="$HOME/bot"
SCREEN_NAME="bancopbot"
LOG_LEVEL="${1:-INFO}"  # Default to INFO for production

echo "==================================="
echo "🚀 Production Deployment Starting"
echo "==================================="
echo "Time: $(date)"
echo "Log level: $LOG_LEVEL"
echo ""

cd "$BOT_DIR" || {
    echo "❌ Error: Cannot find bot directory at $BOT_DIR"
    exit 1
}

# Step 1: Pull latest changes
echo "📥 Step 1/5: Pulling latest code from git..."
git pull
echo "✓ Code updated"
echo ""

# Step 2: Update dependencies
echo "📦 Step 2/5: Updating dependencies..."
if [ -d ".venv" ]; then
    source .venv/bin/activate
    pip install --upgrade -r requirements.txt
    echo "✓ Dependencies updated: aiogram 3.24.0, pydantic 2.12.5"
else
    echo "⚠️  Warning: No virtual environment found, using system Python"
    pip3 install --upgrade -r requirements.txt
fi
echo ""

# Step 3: Verify code integrity
echo "🔍 Step 3/5: Verifying code integrity..."
python -m py_compile main.py
python -c "import aiogram; import pydantic; print(f'✓ Versions OK: aiogram {aiogram.__version__}, pydantic {pydantic.__version__}')"
echo ""

# Step 4: Graceful bot shutdown
echo "🔄 Step 4/5: Shutting down old bot instance..."
if screen -list | grep -q "$SCREEN_NAME"; then
    echo "Sending shutdown signal to screen session..."
    screen -S "$SCREEN_NAME" -X quit
    
    # Wait for graceful shutdown (up to 10 seconds)
    for i in {1..10}; do
        if ! ps aux | grep -v grep | grep "python.*main.py" > /dev/null; then
            echo "✓ Bot stopped gracefully in ${i}s"
            break
        fi
        echo "Waiting for shutdown... ${i}s"
        sleep 1
    done
    
    # Force kill if still running
    if ps aux | grep -v grep | grep "python.*main.py" > /dev/null; then
        echo "⚠️  Force killing bot process..."
        pkill -9 -f "python.*main.py" || true
    fi
else
    echo "No existing bot session found"
fi
echo ""

# Step 5: Start new bot instance
echo "🚀 Step 5/5: Starting new bot instance..."
if [ -d ".venv" ]; then
    PYTHON_CMD="source $BOT_DIR/.venv/bin/activate && python"
else
    PYTHON_CMD="python3"
fi

screen -dmS "$SCREEN_NAME" bash -c "$PYTHON_CMD main.py --log-level $LOG_LEVEL 2>&1 | tee -a bancop_BOT.log"

# Wait and verify startup
sleep 3
if ps aux | grep -v grep | grep "python.*main.py" > /dev/null; then
    echo ""
    echo "==================================="
    echo "✅ DEPLOYMENT SUCCESSFUL!"
    echo "==================================="
    echo "Time: $(date)"
    echo "Screen session: $SCREEN_NAME"
    echo "Log level: $LOG_LEVEL"
    echo ""
    echo "📊 Monitor commands:"
    echo "  • Live logs:     tail -f $BOT_DIR/bancop_BOT.log"
    echo "  • Attach screen: screen -r $SCREEN_NAME"
    echo "  • Check status:  ps aux | grep 'python.*main.py'"
    echo ""
    echo "🔧 Control commands:"
    echo "  • Stop bot:      screen -S $SCREEN_NAME -X quit"
    echo "  • Restart:       ./deploy_update.sh"
    echo ""
else
    echo ""
    echo "==================================="
    echo "❌ DEPLOYMENT FAILED!"
    echo "==================================="
    echo "Bot process not detected. Check logs:"
    echo "  tail -n 100 $BOT_DIR/bancop_BOT.log"
    exit 1
fi
