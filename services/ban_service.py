"""Modern ban management service with async support."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Union

from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from utils.database import BanRecord, DatabaseManager
from utils.logger import get_logger, log_async_function_call

logger = get_logger(__name__)


class BanAction:
    """Represents a ban action with details."""
    
    def __init__(
        self,
        user_id: int,
        chat_id: int,
        action_type: str,  # 'ban', 'kick', 'restrict', 'unban'
        reason: str,
        duration: Optional[timedelta] = None,
        restrictions: Optional[Dict[str, bool]] = None
    ):
        self.user_id = user_id
        self.chat_id = chat_id
        self.action_type = action_type
        self.reason = reason
        self.duration = duration
        self.restrictions = restrictions or {}
        self.timestamp = datetime.now()


class BanResult:
    """Result of a ban operation."""
    
    def __init__(
        self,
        success: bool,
        action: BanAction,
        error_message: Optional[str] = None,
        details: Optional[Dict] = None
    ):
        self.success = success
        self.action = action
        self.error_message = error_message
        self.details = details or {}


class BanService:
    """Advanced ban management and enforcement service."""
    
    def __init__(self, settings, db_manager: DatabaseManager):
        self.settings = settings
        self.db = db_manager
        
        # Ban tracking
        self.pending_bans: Dict[int, BanAction] = {}
        self.ban_queue = asyncio.Queue()
        
        # Rate limiting for ban operations
        self.ban_rate_limit = 10  # max bans per minute
        self.ban_timestamps: List[datetime] = []
        
        # Admin permissions cache
        self.admin_cache: Dict[int, Set[int]] = {}  # chat_id -> set of admin user_ids
        self.admin_cache_ttl = 300  # 5 minutes
        self.admin_cache_timestamps: Dict[int, datetime] = {}
        
        # Auto-ban thresholds
        self.auto_ban_spam_threshold = 3  # spam detections in timeframe
        self.auto_ban_timeframe = timedelta(hours=1)
    
    async def initialize(self) -> None:
        """Initialize the ban service."""
        # Start background tasks
        asyncio.create_task(self._process_ban_queue())
        logger.info("Ban service initialized")
    
    @log_async_function_call
    async def ban_user(
        self,
        bot: Bot,
        user_id: int,
        chat_id: int,
        banned_by: int,
        reason: str,
        duration: Optional[timedelta] = None,
        delete_messages: bool = True,
        notify_admins: bool = True
    ) -> BanResult:
        """Ban a user from a chat."""
        
        action = BanAction(
            user_id=user_id,
            chat_id=chat_id,
            action_type='ban',
            reason=reason,
            duration=duration
        )
        
        try:
            # Check if we have permission to ban
            can_ban, ban_check_error = await self._can_ban_user_detailed(bot, chat_id, user_id)
            if not can_ban:
                return BanResult(
                    success=False,
                    action=action,
                    error_message=ban_check_error or "Cannot ban this user (insufficient permissions or user is admin)"
                )
            
            # Check rate limiting
            if not await self._check_ban_rate_limit():
                return BanResult(
                    success=False,
                    action=action,
                    error_message="Ban rate limit exceeded"
                )
            
            # Calculate unban date if duration specified
            until_date = None
            if duration:
                until_date = datetime.now() + duration
            
            # Perform the ban
            try:
                await bot.ban_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    until_date=until_date,
                    revoke_messages=delete_messages
                )
                
                # Record the ban in database
                ban_record = BanRecord(
                    user_id=user_id,
                    banned_by=banned_by,
                    banned_at=datetime.now(),
                    reason=reason,
                    is_active=True,
                    expires_at=until_date
                )
                
                await self.db.record_ban(ban_record)
                
                # Update ban timestamps for rate limiting
                self.ban_timestamps.append(datetime.now())
                
                # Notify admins if requested
                if notify_admins:
                    await self._notify_admins_of_ban(bot, action, banned_by)
                
                logger.info(f"User {user_id} banned from chat {chat_id} by {banned_by}: {reason}")
                
                return BanResult(
                    success=True,
                    action=action,
                    details={
                        'until_date': until_date,
                        'messages_deleted': delete_messages
                    }
                )
                
            except TelegramBadRequest as e:
                error_str = str(e).lower()
                if 'user not found' in error_str or 'chat not found' in error_str:
                    error_msg = f"Cannot ban user {user_id}: user not found (likely deleted account)"
                elif 'deactivated' in error_str:
                    error_msg = f"Cannot ban user {user_id}: account deactivated"
                elif 'insufficient rights' in error_str or 'not enough rights' in error_str:
                    error_msg = f"Cannot ban user {user_id}: insufficient bot permissions"
                elif 'user is an administrator' in error_str:
                    error_msg = f"Cannot ban user {user_id}: user is administrator"
                else:
                    error_msg = f"Failed to ban user {user_id}: {str(e)}"
                
                logger.error(error_msg)
                return BanResult(
                    success=False,
                    action=action,
                    error_message=error_msg
                )
            
        except Exception as e:
            error_msg = f"Unexpected error during ban: {str(e)}"
            logger.error(error_msg)
            return BanResult(
                success=False,
                action=action,
                error_message=error_msg
            )
    
    @log_async_function_call
    async def kick_user(
        self,
        bot: Bot,
        user_id: int,
        chat_id: int,
        kicked_by: int,
        reason: str,
        notify_admins: bool = True
    ) -> BanResult:
        """Kick a user from a chat (ban then unban)."""
        
        action = BanAction(
            user_id=user_id,
            chat_id=chat_id,
            action_type='kick',
            reason=reason
        )
        
        try:
            # Check permissions
            can_ban, ban_check_error = await self._can_ban_user_detailed(bot, chat_id, user_id)
            if not can_ban:
                return BanResult(
                    success=False,
                    action=action,
                    error_message=ban_check_error or "Cannot kick this user"
                )
            
            # Ban the user
            await bot.ban_chat_member(chat_id=chat_id, user_id=user_id)
            
            # Immediately unban to allow rejoining
            await bot.unban_chat_member(chat_id=chat_id, user_id=user_id)
            
            # Note: We don't record kicks in the database as permanent bans
            
            # Notify admins if requested
            if notify_admins:
                await self._notify_admins_of_ban(bot, action, kicked_by)
            
            logger.info(f"User {user_id} kicked from chat {chat_id} by {kicked_by}: {reason}")
            
            return BanResult(success=True, action=action)
            
        except TelegramBadRequest as e:
            error_msg = f"Failed to kick user: {str(e)}"
            logger.error(error_msg)
            return BanResult(
                success=False,
                action=action,
                error_message=error_msg
            )
    
    @log_async_function_call
    async def restrict_user(
        self,
        bot: Bot,
        user_id: int,
        chat_id: int,
        restricted_by: int,
        reason: str,
        restrictions: Dict[str, bool],
        duration: Optional[timedelta] = None
    ) -> BanResult:
        """Restrict user permissions in a chat."""
        
        action = BanAction(
            user_id=user_id,
            chat_id=chat_id,
            action_type='restrict',
            reason=reason,
            duration=duration,
            restrictions=restrictions
        )
        
        try:
            # Calculate until date
            until_date = None
            if duration:
                until_date = datetime.now() + duration
            
            # Create permissions object
            permissions = types.ChatPermissions(
                can_send_messages=restrictions.get('can_send_messages', False),
                can_send_media_messages=restrictions.get('can_send_media_messages', False),
                can_send_polls=restrictions.get('can_send_polls', False),
                can_send_other_messages=restrictions.get('can_send_other_messages', False),
                can_add_web_page_previews=restrictions.get('can_add_web_page_previews', False),
                can_change_info=restrictions.get('can_change_info', False),
                can_invite_users=restrictions.get('can_invite_users', False),
                can_pin_messages=restrictions.get('can_pin_messages', False)
            )
            
            # Apply restrictions
            await bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=user_id,
                permissions=permissions,
                until_date=until_date
            )
            
            logger.info(f"User {user_id} restricted in chat {chat_id} by {restricted_by}: {reason}")
            
            return BanResult(
                success=True,
                action=action,
                details={'until_date': until_date, 'permissions': restrictions}
            )
            
        except TelegramBadRequest as e:
            error_msg = f"Failed to restrict user: {str(e)}"
            logger.error(error_msg)
            return BanResult(
                success=False,
                action=action,
                error_message=error_msg
            )
    
    @log_async_function_call
    async def unban_user(
        self,
        bot: Bot,
        user_id: int,
        chat_id: int,
        unbanned_by: int,
        reason: str = "Manual unban"
    ) -> BanResult:
        """Unban a user from a chat."""
        
        action = BanAction(
            user_id=user_id,
            chat_id=chat_id,
            action_type='unban',
            reason=reason
        )
        
        try:
            # Unban the user
            await bot.unban_chat_member(chat_id=chat_id, user_id=user_id, only_if_banned=True)
            
            # Update database - mark bans as inactive
            # This would require a database method to update ban status
            # await self.db.deactivate_user_bans(user_id, chat_id)
            
            logger.info(f"User {user_id} unbanned from chat {chat_id} by {unbanned_by}: {reason}")
            
            return BanResult(success=True, action=action)
            
        except TelegramBadRequest as e:
            error_msg = f"Failed to unban user: {str(e)}"
            logger.error(error_msg)
            return BanResult(
                success=False,
                action=action,
                error_message=error_msg
            )
    
    async def check_auto_ban_conditions(
        self,
        bot: Bot,
        user_id: int,
        chat_id: int
    ) -> Optional[BanResult]:
        """Check if user should be auto-banned based on spam history."""
        
        try:
            # Get recent spam detections
            spam_history = await self.db.get_spam_history(
                user_id, 
                hours=int(self.auto_ban_timeframe.total_seconds() / 3600)
            )
            
            if len(spam_history) >= self.auto_ban_spam_threshold:
                # Auto-ban the user
                result = await self.ban_user(
                    bot=bot,
                    user_id=user_id,
                    chat_id=chat_id,
                    banned_by=0,  # System ban
                    reason=f"Auto-ban: {len(spam_history)} spam detections",
                    duration=timedelta(hours=24),  # 24-hour ban
                    notify_admins=True
                )
                
                return result
            
        except Exception as e:
            logger.error(f"Error checking auto-ban conditions: {e}")
        
        return None
    
    async def _can_ban_user(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        """Check if we can ban a specific user (legacy method)."""
        can_ban, _ = await self._can_ban_user_detailed(bot, chat_id, user_id)
        return can_ban

    async def _can_ban_user_detailed(self, bot: Bot, chat_id: int, user_id: int) -> tuple[bool, Optional[str]]:
        """Check if we can ban a specific user with detailed error message."""
        try:
            # First check if the bot has admin permissions in this chat
            try:
                bot_member = await bot.get_chat_member(chat_id=chat_id, user_id=bot.id)
                if bot_member.status not in ['administrator', 'creator']:
                    return False, f"Bot is not admin in chat {chat_id}"
                
                # Check if bot has ban permissions
                if hasattr(bot_member, 'can_restrict_members') and not bot_member.can_restrict_members:
                    return False, f"Bot lacks ban permissions in chat {chat_id}"
                    
            except TelegramBadRequest as e:
                return False, f"Cannot check bot permissions in chat {chat_id}: {str(e)}"
            
            # Get target user info
            try:
                member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
                
                # Cannot ban administrators or creators
                if member.status in ['administrator', 'creator']:
                    return False, f"User {user_id} is admin/creator in chat {chat_id}"
                
                # Check if user is already banned
                if member.status == 'kicked':
                    return False, f"User {user_id} already banned in chat {chat_id}"
                
                return True, None
                
            except TelegramBadRequest as e:
                error_str = str(e).lower()
                if 'user not found' in error_str or 'chat not found' in error_str:
                    return False, f"User {user_id} not found in chat {chat_id} (possibly deleted account)"
                elif 'deactivated' in error_str:
                    return False, f"User {user_id} has deactivated account"
                else:
                    return False, f"Cannot access user {user_id} in chat {chat_id}: {str(e)}"
            
        except Exception as e:
            logger.error(f"Unexpected error checking ban permissions for user {user_id} in chat {chat_id}: {e}")
            return False, f"Unexpected error: {str(e)}"
    
    async def _check_ban_rate_limit(self) -> bool:
        """Check if ban rate limit is exceeded."""
        now = datetime.now()
        
        # Clean old timestamps
        cutoff = now - timedelta(minutes=1)
        self.ban_timestamps = [ts for ts in self.ban_timestamps if ts > cutoff]
        
        # Check if limit exceeded
        return len(self.ban_timestamps) < self.ban_rate_limit
    
    async def _get_chat_admins(self, bot: Bot, chat_id: int) -> Set[int]:
        """Get cached list of chat administrators."""
        now = datetime.now()
        
        # Check cache
        if (chat_id in self.admin_cache and 
            chat_id in self.admin_cache_timestamps and
            now - self.admin_cache_timestamps[chat_id] < timedelta(seconds=self.admin_cache_ttl)):
            return self.admin_cache[chat_id]
        
        try:
            # Fetch fresh admin list
            admins = await bot.get_chat_administrators(chat_id)
            admin_ids = {admin.user.id for admin in admins}
            
            # Cache the result
            self.admin_cache[chat_id] = admin_ids
            self.admin_cache_timestamps[chat_id] = now
            
            return admin_ids
            
        except TelegramBadRequest:
            # Return empty set if can't get admins
            return set()
    
    async def _notify_admins_of_ban(
        self,
        bot: Bot,
        action: BanAction,
        banned_by: int
    ) -> None:
        """Notify administrators of ban action."""
        try:
            # Get user info for notification
            try:
                user = await bot.get_chat_member(action.chat_id, action.user_id)
                username = user.user.username or f"ID: {action.user_id}"
                display_name = user.user.first_name or "Unknown"
            except:
                username = f"ID: {action.user_id}"
                display_name = "Unknown User"
            
            # Get banner info
            try:
                banner = await bot.get_chat_member(action.chat_id, banned_by)
                banner_name = banner.user.first_name or f"ID: {banned_by}"
            except:
                banner_name = "System" if banned_by == 0 else f"ID: {banned_by}"
            
            # Format notification message
            action_text = {
                'ban': '🔨 User Banned',
                'kick': '👢 User Kicked', 
                'restrict': '🔇 User Restricted',
                'unban': '✅ User Unbanned'
            }.get(action.action_type, 'Action Performed')
            
            message = (
                f"{action_text}\n\n"
                f"👤 User: {display_name} (@{username})\n"
                f"👮 By: {banner_name}\n"
                f"📝 Reason: {action.reason}\n"
                f"🕐 Time: {action.timestamp.strftime('%H:%M:%S')}"
            )
            
            if action.duration:
                message += f"\n⏰ Duration: {action.duration}"
            
            # Send to admin groups
            admin_group_id = self.settings.ADMIN_GROUP_ID
            if admin_group_id:
                try:
                    await bot.send_message(
                        chat_id=admin_group_id,
                        text=message,
                        message_thread_id=getattr(self.settings, 'ADMIN_AUTOBAN', None)
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admins: {e}")
        
        except Exception as e:
            logger.error(f"Error in admin notification: {e}")
    
    async def _process_ban_queue(self) -> None:
        """Background task to process queued ban actions."""
        while True:
            try:
                # Get next ban action from queue
                ban_action = await self.ban_queue.get()
                
                # Process the ban action
                # This would be implemented based on specific queue requirements
                
                # Mark task as done
                self.ban_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error processing ban queue: {e}")
                await asyncio.sleep(1)
    
    async def get_user_ban_history(self, user_id: int) -> List[BanRecord]:
        """Get user's ban history."""
        # This would require a database method to get ban history
        # For now, return empty list
        return []
    
    async def is_user_banned(self, user_id: int, chat_id: Optional[int] = None) -> bool:
        """Check if user is currently banned."""
        return await self.db.is_user_banned(user_id)
    
    async def get_ban_statistics(self) -> Dict[str, int]:
        """Get ban statistics."""
        try:
            stats = await self.db.get_statistics()
            return {
                'active_bans': stats.get('active_bans', 0),
                'total_bans_today': 0,  # Would need additional query
                'auto_bans_today': 0,   # Would need additional query
                'manual_bans_today': 0  # Would need additional query
            }
        except Exception as e:
            logger.error(f"Error getting ban statistics: {e}")
            return {}
    
    async def ban_user_from_all_chats(
        self,
        bot: Bot,
        user_id: int,
        banned_by: int,
        reason: str = "Manual ban",
        user_name: Optional[str] = None,
        duration: Optional[timedelta] = None,
        delete_messages: bool = True,
        notify_admins: bool = True
    ) -> Dict[str, any]:
        """Ban a user from all monitored chats using the centralized ban service."""
        
        results = {
            'success': False,
            'total_chats': 0,
            'successful_bans': 0,
            'failed_bans': 0,
            'errors': [],
            'ban_results': []
        }
        
        try:
            # Get channel list from settings
            channel_ids = getattr(self.settings, 'CHANNEL_IDS', [])
            if not channel_ids:
                results['errors'].append("No channels configured for global ban")
                logger.warning("No channels configured for global ban")
                return results
            
            results['total_chats'] = len(channel_ids)
            
            # Ban user from each chat using the centralized ban service
            for chat_id in channel_ids:
                try:
                    ban_result = await self.ban_user(
                        bot=bot,
                        user_id=user_id,
                        chat_id=chat_id,
                        banned_by=banned_by,
                        reason=reason,
                        duration=duration,
                        delete_messages=delete_messages,
                        notify_admins=False  # We'll send one global notification
                    )
                    
                    results['ban_results'].append({
                        'chat_id': chat_id,
                        'success': ban_result.success,
                        'error': ban_result.error_message
                    })
                    
                    if ban_result.success:
                        results['successful_bans'] += 1
                        logger.debug(f"Successfully banned user {user_id} in chat {chat_id}")
                    else:
                        results['failed_bans'] += 1
                        chat_name = getattr(self.settings, 'CHANNEL_DICT', {}).get(chat_id, f"Chat {chat_id}")
                        error_msg = f"Failed to ban user {user_id} in {chat_name}: {ban_result.error_message}"
                        results['errors'].append(error_msg)
                        logger.error(error_msg)
                    
                    # Rate limiting between ban attempts
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    results['failed_bans'] += 1
                    chat_name = getattr(self.settings, 'CHANNEL_DICT', {}).get(chat_id, f"Chat {chat_id}")
                    error_msg = f"Exception banning user {user_id} in {chat_name}: {str(e)}"
                    results['errors'].append(error_msg)
                    logger.error(error_msg)
                    continue
            
            # Determine overall success
            results['success'] = results['successful_bans'] > 0
            
            # Send global notification if any bans succeeded and notifications are enabled
            if results['success'] and notify_admins:
                await self._notify_global_ban(
                    bot=bot,
                    user_id=user_id,
                    user_name=user_name or "!UNDEFINED!",
                    banned_by=banned_by,
                    reason=reason,
                    results=results
                )
            
            # Log summary
            if results['success']:
                logger.info(
                    f"🚫 Global ban completed for user {user_id}:@{user_name or '!UNDEFINED!'} - "
                    f"{results['successful_bans']}/{results['total_chats']} chats - {reason}"
                )
            else:
                logger.error(f"❌ Global ban failed for user {user_id} - no successful bans")
            
            return results
            
        except Exception as e:
            error_msg = f"Critical error in ban_user_from_all_chats: {str(e)}"
            results['errors'].append(error_msg)
            logger.error(error_msg)
            return results
    
    async def _notify_global_ban(
        self,
        bot: Bot,
        user_id: int,
        user_name: str,
        banned_by: int,
        reason: str,
        results: Dict[str, any]
    ) -> None:
        """Send notification about global ban to admin group."""
        try:
            # Get banner info
            try:
                banner = await bot.get_chat_member(list(getattr(self.settings, 'CHANNEL_IDS', []))[0], banned_by)
                banner_name = banner.user.first_name or f"ID: {banned_by}"
                banner_username = f"@{banner.user.username}" if banner.user.username else ""
            except:
                banner_name = "System" if banned_by == 0 else f"ID: {banned_by}"
                banner_username = ""
            
            # Format notification message
            message = (
                f"🔨 GLOBAL BAN EXECUTED\n\n"
                f"👤 User: {user_name} (ID: {user_id})\n"
                f"👮 Banned by: {banner_name} {banner_username}\n"
                f"📝 Reason: {reason}\n"
                f"📊 Results: {results['successful_bans']}/{results['total_chats']} chats\n"
                f"🕐 Time: {datetime.now().strftime('%H:%M:%S')}"
            )
            
            if results['failed_bans'] > 0:
                message += f"\n⚠️ Failed: {results['failed_bans']} chats"
            
            # Send to admin group
            admin_group_id = getattr(self.settings, 'ADMIN_GROUP_ID', None)
            if admin_group_id:
                try:
                    await bot.send_message(
                        chat_id=admin_group_id,
                        text=message,
                        message_thread_id=getattr(self.settings, 'ADMIN_AUTOBAN', None)
                    )
                except Exception as e:
                    logger.error(f"Failed to send global ban notification: {e}")
        
        except Exception as e:
            logger.error(f"Error in global ban notification: {e}")
    
    async def cleanup_expired_bans(self, bot: Bot) -> None:
        """Clean up expired temporary bans."""
        try:
            # This would get expired bans from database and unban users
            # Implementation depends on database schema
            pass
        except Exception as e:
            logger.error(f"Error cleaning up expired bans: {e}")
