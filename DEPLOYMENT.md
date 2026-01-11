# Production Deployment Guide

## Quick Deployment (Recommended)

### Single Command Deployment
```bash
cd ~/bot && ./deploy_update.sh
```

This will:
1. Pull latest code from git
2. Upgrade dependencies (aiogram 3.24.0, pydantic 2.12.5)
3. Verify code integrity
4. Gracefully shutdown old bot (10s timeout)
5. Start new bot instance

**Expected downtime:** ~10-15 seconds

---

## Manual Deployment (Alternative)

If you prefer manual control:

### Step 1: On Production Server
```bash
cd ~/bot
git pull
```

### Step 2: Activate Virtual Environment
```bash
source .venv/bin/activate
```

### Step 3: Upgrade Dependencies
```bash
pip install --upgrade -r requirements.txt
```

### Step 4: Verify Updates
```bash
python -c "import aiogram; import pydantic; print(f'aiogram: {aiogram.__version__}, pydantic: {pydantic.__version__}')"
```
Expected output: `aiogram: 3.24.0, pydantic: 2.12.5`

### Step 5: Restart Bot
```bash
# Stop current bot
screen -S bancopbot -X quit

# Wait 2-3 seconds
sleep 3

# Start new instance
./start_bot.sh INFO
```

---

## Monitoring

### Check Bot Status
```bash
ps aux | grep 'python.*main.py'
```

### View Live Logs
```bash
tail -f ~/bot/bancop_BOT.log
```

### Attach to Screen Session
```bash
screen -r bancopbot
# Press Ctrl+A, then D to detach
```

---

## Rollback (If Needed)

If something goes wrong:

```bash
cd ~/bot

# Stop current bot
screen -S bancopbot -X quit

# Rollback code
git reset --hard HEAD~3  # Go back 3 commits (before updates)

# Reinstall old dependencies
pip install --upgrade -r requirements.txt

# Restart
./start_bot.sh INFO
```

---

## What Changed in This Update

### Dependency Updates
- **aiogram**: 3.22.0 → 3.24.0
  - Bot API 9.3 support
  - Bug fixes (link formatting, callback params)
  - Improved type hints
  
- **pydantic**: 2.11.x → 2.12.5
  - Required by aiogram 3.23+
  - Performance improvements

### Code Fixes
1. **Monitoring Period Check**: Fixed missed final spam check when bot restarts after 24h elapsed
2. **@UNDEFINED Links**: Fixed suspicious warnings to use `!UNDEFINED!` instead of `@UNDEFINED`

### No Breaking Changes
All updates are backward compatible. No code changes required.

---

## Troubleshooting

### Bot Won't Start
```bash
# Check logs
tail -n 100 ~/bot/bancop_BOT.log

# Verify Python environment
source .venv/bin/activate
python -c "import aiogram; print(aiogram.__version__)"
```

### Syntax Errors
```bash
python -m py_compile main.py
```

### Missing Dependencies
```bash
pip install --upgrade -r requirements.txt
```

---

## Support

For issues, check:
1. Bot logs: `tail -f ~/bot/bancop_BOT.log`
2. Screen session: `screen -r bancopbot`
3. Process status: `ps aux | grep python`
