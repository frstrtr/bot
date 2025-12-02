# Changelog

## [2025-12-02]

### Added
- **Bot mention detection and handling**: Automatic handling of messages mentioning other bots
  - Detects mentions ending with "bot" (case insensitive, e.g., `@somebot`, `@AnotherBot`)
  - **For monitored users** (in `active_user_checks_dict`, within 24hr monitoring window):
    - Sends to **AUTOREPORT** thread
    - **Deletes message** from chat
    - Stores deletion reason `bot_mention: @somebot` in database
  - **For non-monitored users** (established users):
    - Sends to **SUSPICIOUS** thread (no deletion)
    - Bot mentions shown in suspicious content report
    - Message remains in chat for admin review

- **Deletion reason tracking**: New `deletion_reason` column in `recent_messages` table
  - Stores reason when bot deletes a message (e.g., `bot_mention: @spambot`)
  - Auto-migration for existing databases (ALTER TABLE if column doesn't exist)
  - Displayed in `/whois` command under "🗑 Deleted Messages" section

- **Configuration migration to .env format**: Migrated from XML-only to `.env` file configuration
  - Added `.env.example` template with all configuration options
  - `python-dotenv` support in `utils_config.py`
  - `.env` file preferred, falls back to XML for backwards compatibility
  - Added `P2P_SERVER_URL` configuration option
  - Updated `requirements.txt` with `python-dotenv>=1.0.0` and `certifi>=2024.0.0`

### Changed
- **`/whois` command enhanced**: Now shows deleted messages section
  - Lists messages deleted by bot with reasons
  - Shows deletion date and chat where message was deleted
  - Up to 5 most recent deletions shown

## [2025-12-01]

### Added
- **`/whois` command**: Comprehensive user lookup from database
  - **Available in Orders thread (TECHNO_ADMIN)** in admin group
  - **Available for superadmin in direct messages** with bot (ADMIN_USER_ID)
  - Usage: `/whois 123456789` (by ID) or `/whois @username` (by username)
  - Shows: user ID, username, name, status badges (BANNED/LEGIT/MONITORING/PREMIUM)
  - Timeline: first seen, last seen, joined date, monitoring end date
  - Chats: list of chats where user was seen (up to 5 shown)
  - **Admin status**: Shows if user is admin in any monitored chats (👑 badge)
  - **Roaming history**: Chronological join/leave events across monitored chats (up to 10 shown)
    - Format: `➡️ JOIN ChatName (2025-12-01 14:30)` / `⬅️ LEFT ChatName (2025-12-01 15:00)`
  - Ban details (if banned): date, source (lols/cas/p2p/admin), offense type, reason, who banned, detection sources, time to first message
  - Profile links: ID-based, Android, iOS
  - External check: LOLS bot link
  - Action buttons: Start Monitoring, Actions (Ban/Delete), Check on LOLS
  - For unknown users: shows "Not Found" with LOLS check link

- **Ban source tracking with combinations**: `BanSource` enum and helpers for detailed ban origin tracking
  - Sources: `lols`, `cas`, `p2p`, `local`, `admin`, `autoreport`, `autoban`
  - `build_ban_source()`: Create combined sources (e.g., `"cas+lols+p2p"` when detected by multiple APIs)
  - `parse_ban_source()`: Parse combined string back to individual flags
  - `build_admin_ban_info()`: Create admin profile dict for manual ban tracking
  - `build_detection_details()`: Build JSON with raw API responses (LOLS/CAS/P2P) and admin info
  - Example: User detected by LOLS and CAS → `ban_source="cas+lols"`, `offense_details={"lols": {...}, "cas": {...}}`

- **Standardized offense types enum**: `OffenseType` enum in `utils.py` for consistent ban tracking
  - Auto-ban triggers: `fast_message`, `spam_pattern`, `spam_sentences`, `custom_emoji_spam`, `caps_emoji_spam`, `via_inline_bot`, `night_message`, `latency_banned`
  - Bot mention: `bot_mention`, `bot_mention_monitored`, `bot_mention_missed_join`
  - Forward/Channel: `forwarded_spam`, `channel_spam`, `forwarded_channel_spam`
  - Account-based: `high_id_spam`, `high_id_join`
  - Content-based: `suspicious_links`, `suspicious_mentions`, `suspicious_phones`, `suspicious_emails`, `suspicious_bot_commands`, `hidden_mentions`, `suspicious_content`
  - Profile-based: `profile_change_watch`, `profile_change_leave`, `profile_change_periodic`
  - External DB: `lols_banned`, `cas_banned`, `p2p_banned`, `local_db_banned`
  - Admin actions: `admin_ban`, `admin_report`
  - Behavior-based: `quick_leave`, `join_leave_pattern`, `week_old_suspicious`
  - Helper function `classify_offense_from_reason()` to map reason strings to offense types

- **Extended ban tracking in database**: Comprehensive ban details stored in `user_baselines`
  - Ban source tracking: combined sources (e.g., `"cas+lols+p2p"`)
  - Admin details: `banned_by_admin_id`, `banned_by_admin_username`
  - Chat context: `banned_in_chat_id`, `banned_in_chat_title`
  - Offense details: `offense_type`, `offense_details` (JSON with API responses), `first_message_text`
  - Timing: `time_to_first_message` (seconds from join to first message)
  - Detection flags: `detected_by_lols`, `detected_by_cas`, `detected_by_p2p`, `detected_by_local`, `detected_by_admin`

### Fixed
- **Prevent duplicate autoreport/suspicious notifications**: Messages sent to AUTOREPORT thread are now tracked
  - Added `autoreported_messages` set to track (chat_id, message_id) pairs
  - All ADMIN_SUSPICIOUS notifications now check `was_autoreported()` before sending
  - Prevents same message from appearing in both AUTOREPORT and SUSPICIOUS threads

- **User baselines database integration**: Full integration of `user_baselines` table
  - Loads active monitoring from database on startup (with legacy file migration)
  - Saves baseline to DB when user joins chat
  - Updates DB status on: monitoring complete, user marked legit, user banned
  - Helper function `move_user_to_banned()` for consistent ban handling
  - No more file-based persistence for active checks (uses SQLite)
  - Legacy `active_user_checks.txt` automatically migrated to DB and renamed to `.bak`

- **User baselines database table**: New `user_baselines` table for persistent user monitoring
  - Stores profile snapshot at join time (username, first_name, last_name, photo_count)
  - Tracks monitoring state (active, ended_at, is_legit, is_banned)
  - Join context (chat_id, chat_username, chat_title)
  - Reserved fields for future extensions (bio, premium, verified, language_code)
  - Flexible JSON `metadata` field for arbitrary data
  - Helper functions: `save_user_baseline()`, `get_user_baseline()`, `get_active_user_baselines()`, `update_user_baseline_status()`, `delete_user_baseline()`

- **Persistent monitoring across restarts**: Monitoring timers now persist across bot restarts
  - Extracts `joined_at` timestamp from stored baseline data
  - Calculates elapsed time and skips past check intervals
  - Resumes monitoring from correct position (not from beginning)
  - Shows "resuming from X min, skipped: 1min, 3min, ..." in single log line
  - Handles edge case: users monitored >24hrs are removed immediately with log message

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

- **Monitoring duration logs**: Now uses `MONITORING_DURATION_HOURS` constant (default: 24)
  - Duration is no longer hardcoded in log messages
  - Single source of truth: change constant to adjust all logs and sleep times
  - Fixed in: startup logs, cancellation messages, check command replies

- **Stop checks confirmation showing `@None`**: Fixed username display in legitimization messages
  - Handle `"None"` string when extracting username from active_user_checks_dict
  - Now shows: `!UNDEFINED!` instead of `@None`

- **Auto-report monitored users with bot mentions**: Users in active monitoring who mention bots
  - If message contains `@...bot` mention, sends to AUTOREPORT instead of SUSPICIOUS
  - Faster spam detection for users promoting bot services

- **Duplicate missed join notifications**: Fixed repeated notifications for same user
  - After first notification, marks user's first message as join event in DB
  - Prevents duplicate "Missed Join Detected" alerts on every message

- **MessageEntity attribute access error**: Fixed `'MessageEntity' object has no attribute 'get'`
  - Entity objects in aiogram are objects, not dicts
  - Use `getattr()` with fallback for object attribute access

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
