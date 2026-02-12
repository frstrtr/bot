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
    # Check if running in non-interactive mode (set by deploy script)
    if [ -z "$REPLY" ]; then
        read -p "Do you want to kill it and restart? (y/n) " -n 1 -r
        echo
    fi
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Get the exact PID of the bot process before sending signal
        BOT_PID=$(pgrep -f "python3 main.py" | head -1)

        if [ -n "$BOT_PID" ]; then
            echo "Bot process found (PID: $BOT_PID). Sending Ctrl+C for graceful shutdown..."
            # Send SIGINT (Ctrl+C) to the bot process inside screen
            screen -S "$SCREEN_NAME" -X stuff $'\003'

            # Wait for process to exit using kill -0 (instant syscall, no grep overhead)
            # Poll every 0.1s — no timeout, wait as long as needed for graceful shutdown
            ELAPSED=0
            while kill -0 "$BOT_PID" 2>/dev/null; do
                sleep 0.1
                ELAPSED=$((ELAPSED + 1))
                # Progress indicator every 5 seconds
                if [ $((ELAPSED % 50)) -eq 0 ]; then
                    ELAPSED_SEC=$(echo "scale=1; $ELAPSED / 10" | bc)
                    echo "  Still waiting... (${ELAPSED_SEC}s)"
                fi
            done

            # Calculate actual time taken
            ELAPSED_SEC=$(echo "scale=1; $ELAPSED / 10" | bc)
            echo "Bot exited gracefully after ${ELAPSED_SEC}s."
        else
            echo "No running bot process found, cleaning up screen session..."
        fi

        # Clean up the screen session
        if screen -list | grep -q "$SCREEN_NAME"; then
            screen -S "$SCREEN_NAME" -X quit 2>/dev/null
            sleep 0.5
        fi
        echo "Old session cleaned up."
    else
        echo "Aborted. Use 'screen -r $SCREEN_NAME' to attach to existing session."
        exit 0
    fi
fi

# Pull latest changes
echo "Pulling latest code from git..."
git pull

# Activate virtual environment if it exists
VENV_PATH="$BOT_DIR/.venv"
if [ -d "$VENV_PATH" ]; then
    echo "Activating virtual environment..."
    PYTHON_CMD="source $VENV_PATH/bin/activate && python3"
else
    echo "Warning: No virtual environment found at $VENV_PATH, using system Python"
    PYTHON_CMD="python3"
fi

# Start bot in screen session
echo "Starting bot in screen session '$SCREEN_NAME'..."
screen -dmS "$SCREEN_NAME" bash -c "$PYTHON_CMD main.py --log-level $LOG_LEVEL 2>&1 | tee -a $LOG_FILE"

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
