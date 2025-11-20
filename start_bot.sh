#!/bin/bash
# Script to start the Telegram bot in a screen session

BOT_DIR="$HOME/bot"
SCREEN_NAME="bancopbot"
LOG_FILE="bancop_BOT.log"
LOG_LEVEL="${1:-DEBUG}"  # Default to DEBUG, can be overridden with first argument

echo "Starting bot with log level: $LOG_LEVEL"

# Change to bot directory
cd "$BOT_DIR" || {
    echo "Error: Cannot find bot directory at $BOT_DIR"
    exit 1
}

# Check if screen session already exists
if screen -list | grep -q "$SCREEN_NAME"; then
    echo "Screen session '$SCREEN_NAME' already exists."
    read -p "Do you want to kill it and restart? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Killing existing screen session..."
        screen -S "$SCREEN_NAME" -X quit
        sleep 2
    else
        echo "Aborted. Use 'screen -r $SCREEN_NAME' to attach to existing session."
        exit 0
    fi
fi

# Pull latest changes
echo "Pulling latest code from git..."
git pull

# Start bot in screen session
echo "Starting bot in screen session '$SCREEN_NAME'..."
screen -dmS "$SCREEN_NAME" bash -c "python3 main.py --log-level $LOG_LEVEL 2>&1 | tee -a $LOG_FILE"

# Wait a moment for the bot to start
sleep 3

# Check if bot is running
if ps aux | grep -v grep | grep "python3 main.py" > /dev/null; then
    echo "✓ Bot started successfully!"
    echo "  - Screen session: $SCREEN_NAME"
    echo "  - Log level: $LOG_LEVEL"
    echo "  - Log file: $BOT_DIR/$LOG_FILE"
    echo ""
    echo "Commands:"
    echo "  View logs:      tail -f $BOT_DIR/$LOG_FILE"
    echo "  Attach screen:  screen -r $SCREEN_NAME"
    echo "  Stop bot:       screen -S $SCREEN_NAME -X quit"
    echo "  Check status:   ps aux | grep 'python3 main.py'"
    echo ""
    echo "To start with different log level: ./start_bot.sh INFO"
else
    echo "✗ Failed to start bot. Check logs:"
    echo "  tail -n 50 $BOT_DIR/$LOG_FILE"
    exit 1
fi
