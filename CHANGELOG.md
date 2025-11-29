# Changelog

## [2025-11-30]

### Added
- **Intensive Watchdog**: Aggressive spam checking for users in active_checks who post messages
  - Phase 1: 6 checks every 10 seconds (first minute)
  - Phase 2: 8 checks every 30 seconds (next 4 minutes)
  - Total: 14 API checks in 5 minutes for suspicious users

- **Bulk Message Deletion**: Delete ALL stored messages when user is banned as spammer
  - Rate limited to 50ms between deletions (max 20/sec, under Telegram's 30/sec limit)
  - Works with both intensive watchdog and regular watchdog

- **Auto-delete Timeout**: `/forward -t` and `/copy -t` now support auto-delete
  - Example: `/forward -t 60 <link> <target>` - deletes after 60 seconds

### Improved
- **Smart Topic/Reply Fallback** for `/forward`, `/copy`, and `/say` commands:
  - First try as `message_thread_id` (forum topic)
  - If "thread not found", try as `reply_to_message_id` (regular group)
  - If reply fails, fall back to plain send
  - Success message shows "(topic 123)" or "(reply to msg 123)" accordingly

### Fixed
- Double `@` in intensive watchdog logs (was showing `@@username`)
- `/say` thread fallback now tries reply-to before plain send
