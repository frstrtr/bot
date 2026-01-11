# Production Migration Plan: aiogram3-final

**Date:** UTC Midnight, December 3, 2025  
**From:** bancop3 (aiogram 2.x) → **To:** bancop4 (aiogram 3.x)

---

## Pre-Migration Status

| Server | Role | Branch | Bot | Status |
|--------|------|--------|-----|--------|
| bancop3 | Production | aiogram3 (2.x) | bancop_bot | Running |
| bancop4 | Test | aiogram3-final (3.x) | snumsbot | Running |

---

## Migration Steps

### Step 1: Stop Both Bots

```bash
# Stop bancop3 (production) - find screen name first
gcloud compute ssh bancop3 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="screen -ls"

# Stop the bot (adjust screen name if different)
gcloud compute ssh bancop3 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="screen -S bot -X stuff $'\003'"

# Stop bancop4 (test)
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="screen -S testbot -X stuff $'\003'"

# Verify both stopped
gcloud compute ssh bancop3 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="screen -ls"
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="screen -ls"
```

### Step 2: Create Snapshots (AFTER bots stopped)

```bash
# Snapshot bancop3 (production backup - CRITICAL)
gcloud compute snapshots create bancop3-pre-migration-20251203 \
  --source-disk=bancop3 \
  --source-disk-zone=africa-south1-b \
  --project=multichat-bot-396516 \
  --description="Pre-migration snapshot of bancop3 production server before aiogram3-final switch"

# Snapshot bancop4 (test environment backup)
gcloud compute snapshots create bancop4-test-backup-20251203 \
  --source-disk=bancop4 \
  --source-disk-zone=africa-south1-b \
  --project=multichat-bot-396516 \
  --description="Backup of bancop4 test environment before production switch"

# Verify snapshots created
gcloud compute snapshots list --project=multichat-bot-396516
```

### Step 3: Backup Test Environment Files on bancop4

```bash
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="cd ~/bot && mkdir -p backup_test_env_20251203 && cp .env messages.db config.xml groups.xml banned_users.txt inout_*.txt backup_test_env_20251203/ 2>/dev/null; echo 'Backup contents:' && ls -la backup_test_env_20251203/"
```

### Step 4: Copy Production Files from bancop3 to bancop4

```bash
# Copy database (most critical - 33MB)
gcloud compute scp bancop3:~/bot/messages.db bancop4:~/bot/messages.db \
  --zone=africa-south1-b --project=multichat-bot-396516

# Copy active user checks (for migration to new DB schema)
gcloud compute scp bancop3:~/bot/active_user_checks.txt bancop4:~/bot/ \
  --zone=africa-south1-b --project=multichat-bot-396516

# Copy production .env (already prepared with production config)
gcloud compute scp bancop3:~/bot/.env bancop4:~/bot/.env \
  --zone=africa-south1-b --project=multichat-bot-396516

# Verify files copied
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="ls -la ~/bot/messages.db ~/bot/active_user_checks.txt ~/bot/.env"
```

### Step 5: Start Production Bot on bancop4

```bash
# Start the bot with new screen name
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="screen -dmS prodbot bash -c 'cd ~/bot && source .venv/bin/activate && python main.py; exec bash'"

# Verify it's running
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="screen -ls"
```

### Step 6: Verify Migration Success

```bash
# Check logs for startup success
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="tail -50 ~/bot/bancop_BOT.log"

# Check database schema was updated
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="sqlite3 ~/bot/messages.db '.tables'"

# Should show: recent_messages  user_baselines

# Verify active_user_checks were migrated
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="sqlite3 ~/bot/messages.db 'SELECT COUNT(*) FROM user_baselines WHERE monitoring_active=1'"
```

---

## Verification Checklist

- [ ] Bot responds in admin group
- [ ] Bot logs show successful startup
- [ ] No errors in first 5 minutes of logs
- [ ] `/whois` command works
- [ ] Join/leave events are logged
- [ ] Database has `user_baselines` table
- [ ] Active user checks migrated from txt file

---

## Rollback Plan

### Quick Rollback (restart old production)

```bash
# Stop bancop4
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="screen -S prodbot -X stuff $'\003'"

# Restart bancop3 (unchanged, fully functional)
gcloud compute ssh bancop3 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="screen -dmS bot bash -c 'cd ~/bot && source .venv/bin/activate && python main.py; exec bash'"
```

### Restore Test Environment on bancop4

```bash
gcloud compute ssh bancop4 --zone=africa-south1-b --project=multichat-bot-396516 \
  --command="cd ~/bot && cp backup_test_env_20251203/* . 2>/dev/null"
```

### Full Restore from Snapshot (if needed)

```bash
# Create new disk from snapshot
gcloud compute disks create bancop3-restored \
  --source-snapshot=bancop3-pre-migration-20251203 \
  --zone=africa-south1-b \
  --project=multichat-bot-396516

# Then attach to instance (requires stopping instance first)
```

---

## Post-Migration

### bancop3 (Archive)
- Remains stopped as backup
- Can be restarted immediately if rollback needed
- Keep snapshot for 30 days

### bancop4 (New Production)
- Monitor logs for first 24 hours
- Check for any rate limiting or errors
- Verify all 24 monitored groups work correctly

---

## Important Files Reference

| File | Description | Size (bancop3) |
|------|-------------|----------------|
| messages.db | Main database | ~33MB |
| active_user_checks.txt | Users being monitored | ~4KB |
| .env | Production configuration | ~3KB |
| config.xml | Legacy config (fallback) | ~5KB |
| groups.xml | Monitored groups (fallback) | ~6KB |

---

## Contact / Notes

- Admin Group: (configure in .env)
- Technolog Group: (configure in .env)
- Bot: (configure in .env)
- Admin User ID: (configure in .env)
