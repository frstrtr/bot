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
- **Missed joins detection**: Users who joined while bot was offline are now properly checked
  - Previously: No join record → default to 2020 → user appears 5 years old → NO checks
  - Now: No join record → check first message date → if nothing, treat as NEW user
  - Unknown users get spam checks and intensive watchdog assigned
  - **Synthetic join event**: First message from unknown user now saves a join record to DB
    - Future messages from the same user will have accurate "first seen" date
    - Prevents repeated "first time seen" processing

### UI Improvements
- **Removed duplicate "View Original Message" buttons** from action keyboards
  - Expanded action menu (ban/delete options) - removed duplicate
  - Collapsed action menu - removed duplicate
  - Stop checks/legitimization handler - removed duplicate
  - Confirmation keyboards - removed duplicate
  - Link remains in message text, no need for button duplication

- **Enhanced autoreport keyboard**: Added "Check Spam Data" and "Legitimization" buttons
  - Admins can now legitimize users directly from autoreport notifications
  - Quick access to LOLS spam data check

- **Action confirmations now reply to notification message**
  - Ban, delete, legitimization confirmations are threaded as replies
  - Easier to track which notification triggered which action
  - Applied to all callback action handlers (5 locations)

- **Leave events logged to OUT thread**: Spam checks for users leaving the group
  - Previously: All spam check logs went to TECHNO_IN regardless of join/leave
  - Now: Users leaving (LEFT, KICKED, RESTRICTED) logged to TECHNO_OUT
  - Only clean users joining logged to TECHNO_IN
  - Ban button only shown for non-spammers joining

- **Other chats detection on user leave**: Shows which other monitored chats user is still in
  - When user leaves one chat, bot checks membership in all other monitored chats
  - Displays clickable links: `@chatusername (ChatName)` format
  - Each chat on separate line with bullet points for readability
  - Adds "Ban from All Chats" button if user left but is still in other chats
  - Useful for detecting spammers who leave after posting but lurk elsewhere

- **Fixed `@None` username in startup/shutdown logs**
  - Use `format_username_for_log()` helper function consistently
  - Handle both `None` value and `"None"` string cases
  - Logs now show `@username` or `!UNDEFINED!` (never `@None`)
