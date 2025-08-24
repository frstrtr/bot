"""Profile management utilities for user data handling."""

from __future__ import annotations

import html
from typing import Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class ProfileManager:
    """Handles user profile operations and change tracking."""
    
    @staticmethod
    def make_profile_dict(
        first_name: str = None, 
        last_name: str = None, 
        username: str = None, 
        photo_count: int = None
    ) -> Dict[str, Any]:
        """Create a normalized profile dictionary."""
        return {
            'first_name': first_name or '',
            'last_name': last_name or '',
            'username': username or '',
            'photo_count': photo_count or 0,
        }
    
    @staticmethod
    def format_profile_field(
        old_val: str, 
        new_val: str, 
        label: str, 
        is_username: bool = False
    ) -> str:
        """Format a profile field change for display."""
        if is_username:
            old_disp = ("@" + old_val) if old_val else "@!UNDEFINED!"
            new_disp = ("@" + new_val) if new_val else "@!UNDEFINED!"
        else:
            old_disp = html.escape(old_val) if old_val else ""
            new_disp = html.escape(new_val) if new_val else ""
        
        if old_val != new_val:
            return f"{label}: {old_disp or '∅'} ➜ <b>{new_disp or '∅'}</b>"
        return f"{label}: {new_disp or '∅'}"
    
    @staticmethod
    def compare_profiles(
        old_profile: Dict[str, Any], 
        new_profile: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """Compare two profile dictionaries and return changes."""
        changes = []
        has_changes = False
        
        # Compare each field
        for field in ['first_name', 'last_name', 'username', 'photo_count']:
            old_val = old_profile.get(field, '')
            new_val = new_profile.get(field, '')
            
            if old_val != new_val:
                has_changes = True
                is_username = field == 'username'
                change_text = ProfileManager.format_profile_field(
                    str(old_val), str(new_val), field.replace('_', ' ').title(), is_username
                )
                changes.append(change_text)
        
        change_summary = '\n'.join(changes) if changes else "No changes detected"
        return has_changes, change_summary
    
    @staticmethod
    def normalize_username(username: str) -> str:
        """Normalize username by removing @ prefix and handling None values."""
        if not username or username in ("None", "!UNDEFINED!"):
            return ""
        
        username = username.strip()
        if username.startswith("@"):
            username = username[1:]
        
        return username or ""
    
    @staticmethod
    def extract_user_info(user) -> Dict[str, Any]:
        """Extract user information into a standardized dictionary."""
        try:
            return ProfileManager.make_profile_dict(
                first_name=getattr(user, 'first_name', None),
                last_name=getattr(user, 'last_name', None),
                username=getattr(user, 'username', None),
                photo_count=0  # Would need separate API call to get actual count
            )
        except AttributeError as e:
            logger.warning("Error extracting user info: %s", e)
            return ProfileManager.make_profile_dict()


# Convenience functions for backward compatibility
def make_profile_dict(
    first_name: str = None, 
    last_name: str = None, 
    username: str = None, 
    photo_count: int = None
) -> Dict[str, Any]:
    """Create a normalized profile dictionary."""
    return ProfileManager.make_profile_dict(first_name, last_name, username, photo_count)


def format_profile_field(
    old_val: str, 
    new_val: str, 
    label: str, 
    is_username: bool = False
) -> str:
    """Format a profile field change for display."""
    return ProfileManager.format_profile_field(old_val, new_val, label, is_username)


def compare_profiles(
    old_profile: Dict[str, Any], 
    new_profile: Dict[str, Any]
) -> Tuple[bool, str]:
    """Compare two profile dictionaries and return changes."""
    return ProfileManager.compare_profiles(old_profile, new_profile)


def normalize_username(username: str) -> str:
    """Normalize username by removing @ prefix and handling None values."""
    return ProfileManager.normalize_username(username)
