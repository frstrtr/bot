"""Admin utilities for permission checking and validation."""

from __future__ import annotations

from typing import List
import logging

logger = logging.getLogger(__name__)


class AdminManager:
    """Handles admin-related operations and permissions."""
    
    def __init__(self, admin_user_ids: List[int] = None):
        self.admin_user_ids = admin_user_ids or []
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin."""
        return user_id in self.admin_user_ids
    
    def add_admin(self, user_id: int) -> bool:
        """Add user to admin list."""
        if user_id not in self.admin_user_ids:
            self.admin_user_ids.append(user_id)
            logger.info("Added admin: %s", user_id)
            return True
        return False
    
    def remove_admin(self, user_id: int) -> bool:
        """Remove user from admin list."""
        if user_id in self.admin_user_ids:
            self.admin_user_ids.remove(user_id)
            logger.info("Removed admin: %s", user_id)
            return True
        return False
    
    def get_admin_list(self) -> List[int]:
        """Get list of admin user IDs."""
        return self.admin_user_ids.copy()
    
    def validate_admin_action(self, user_id: int, action: str) -> bool:
        """Validate if user can perform admin action."""
        if not self.is_admin(user_id):
            logger.warning("Non-admin user %s attempted action: %s", user_id, action)
            return False
        
        logger.debug("Admin %s performing action: %s", user_id, action)
        return True


# Convenience functions for backward compatibility
def is_admin(user_id: int, admin_user_ids: List[int] = None) -> bool:
    """Check if user is an admin."""
    admin_manager = AdminManager(admin_user_ids or [])
    return admin_manager.is_admin(user_id)


def validate_admin_action(user_id: int, action: str, admin_user_ids: List[int] = None) -> bool:
    """Validate if user can perform admin action."""
    admin_manager = AdminManager(admin_user_ids or [])
    return admin_manager.validate_admin_action(user_id, action)
