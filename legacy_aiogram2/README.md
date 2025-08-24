# Legacy aiogram 2.x Files Archive

This directory contains archived files from the original aiogram 2.x implementation, preserved for reference.

## Archived Files

### Main Bot Files
- **`main.py`** - Original aiogram 2.x bot implementation (6,615 lines)
  - Contains all the original functionality with aiogram 2.x patterns
  - Includes the DRY improvements (normalize_username, POSTED_USERNAMES dedup)
  - Last working version before migration to aiogram 3.x

- **`main_aiogram2.py`** - Compatibility version
  - Backup copy of aiogram 2.x implementation

### Dependencies
- **`requirements.txt`** - Original aiogram 2.x dependencies
  - aiogram==2.x
  - Python 3.10 compatible packages

- **`requirements_new.txt`** - Intermediate dependency file
  - Transitional requirements during migration

### Configuration
- **`config_old.xml`** - Original XML configuration backup
- **`groups_old.xml`** - Original groups XML configuration backup

## Migration Status

✅ **Migration to aiogram 3.x completed successfully**

The bot has been fully migrated to:
- **aiogram 3.15.0** (from aiogram 2.x)
- **Python 3.13.7** (from Python 3.10)
- **Modern service architecture** (from monolithic structure)

## Current Active Files

Use these files for the modern bot:
- `main_aiogram3.py` - Modern aiogram 3.x implementation
- `run_bot.py` - Smart launcher with validation
- `requirements_modern.txt` - Modern dependencies
- `.env` - Environment configuration

## Notes

- These files are preserved for reference and emergency fallback
- The migration preserved all functionality while modernizing the architecture
- Original bot had 6,615 lines, modern version is ~800 lines with better structure

---
*Archived on August 24, 2025 during aiogram 3.x migration cleanup*
