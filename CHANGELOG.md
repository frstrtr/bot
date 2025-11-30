# Changelog

## [2025-12-01]

### Added
- **Mention analysis in ban reports**: Autoreport and autoban banners now show mention statistics
  - Total mention count in message
  - Hidden mentions detection (mentions disguised with invisible characters)
  - Adds warning "⚠️ HIDDEN MENTIONS DETECTED" when spammers use invisible chars

- **Missed join notification**: Users with no join record (bot was offline) now trigger suspicious alert
  - Notification sent to ADMIN_SUSPICIOUS thread
  - Includes LOLS check, Ban, and Mark as Legit buttons
  - Message: "Possible missed join event - user joined while bot was offline"

- **Mark as Legit button in IN thread**: Join notifications now have legitimization button
  - Quick access to mark users as legitimate from technolog IN thread

- **Ban User button in OUT thread**: Users leaving chats can now be banned directly
  - Shows ban button for users who left voluntarily (not already detected as spam)

- **LOLS check button for channel messages**: Channel message detection in originals thread
  - Added "ℹ️ Check Channel in LOLS" button before "🚫 Ban Channel" button

### Improved
- **Simplified high ID account alerts**: Replaced Actions dropdown with direct "🚫 Ban User" button
  - Faster access to ban suspicious new accounts

- **Detailed channel ban failure reporting**: When channel ban fails, now shows per-chat details
  - Lists each chat where ban failed with specific error message
  - Helps diagnose permission issues across different chats

### Fixed
- **Duplicate usernames in TECHNO_NAMES**: Added tracking set to prevent duplicate posts
  - Four posting locations now check `POSTED_USERNAMES` before sending
  - Codes 1156 (banned), 1526 (spammer), 1962 (autoban), etc. no longer duplicate

- **COMM logs showing `@!UNDEFINED!`**: Fixed command logs for users without username
  - Changed format to only include `@` when username exists
  - Affects: /say, /reply, /forward, /copy, /broadcast commands
  - Now shows: `44816530:!UNDEFINED!` instead of `44816530:@!UNDEFINED!`

- **Admin reports showing `@None`**: Fixed P2P spamcheck and ban reports for users without username
  - Handle `"None"` string (not just Python `None`) in username checks
  - Fixed in: P2P spamcheck reports, ban action confirmations, suspicious user handling
  - Now shows: `8279862148:!UNDEFINED!` instead of `8279862148:@None`

- **Admin username display**: Unified all admin username placeholders to `!UNDEFINED!`
  - Replaced inconsistent `!NoName!`, `!NoAdminName!` with `!UNDEFINED!`
  - Fixed in: ban actions, cancel actions, channel bans, stop_checks, manual bans

- **Monitoring duration logs**: Updated from "3hr" to "24hr" to match actual duration
  - Sleep times array goes up to 86405 seconds (24 hours)
  - Fixed in: startup logs, cancellation messages, coroutine names
  - Properly handles admins without @ username in all notification messages

- **TECHNO_NAMES duplicate fix**: Use consistent `normalize_username()` function
  - Replaced local `_extract_username()` with shared `normalize_username()` from utils
  - Ensures both 1156 and 1526 codes use identical normalization for duplicate detection

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

- **Fixed missing buttons in suspicious action cancel handlers**
  - `suspiciouscancel`: Added "Mark as Legit" button to collapsed keyboard
  - `cancelban/cancelglobalban/canceldelmsg`: Now restore full collapsed keyboard
  - All cancel actions restore: Check Spam Data, Actions, Mark as Legit buttons
  - Legitimization (final action) correctly shows only Check Spam Data button
