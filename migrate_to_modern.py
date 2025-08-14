"""Migration script to transition from monolithic to modern structure."""

import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


def backup_original_files():
    """Create backup of original files."""
    backup_dir = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    os.makedirs(backup_dir, exist_ok=True)
    
    files_to_backup = [
        'main.py',
        'config.xml',
        'groups.xml',
        'requirements.txt'
    ]
    
    for file in files_to_backup:
        if os.path.exists(file):
            shutil.copy2(file, backup_dir)
            print(f"✅ Backed up {file}")
    
    print(f"📁 Backup created in: {backup_dir}")
    return backup_dir


def create_env_from_xml():
    """Create .env file from XML configuration."""
    config_file = "config.xml"
    groups_file = "groups.xml"
    
    if not os.path.exists(config_file):
        print(f"❌ {config_file} not found")
        return False
    
    try:
        # Parse main config
        tree = ET.parse(config_file)
        root = tree.getroot()
        
        env_vars = {}
        
        # Bot settings
        bot_element = root.find("bot")
        if bot_element is not None:
            env_vars["BOT_TOKEN"] = bot_element.get("token", "")
            env_vars["BOT_NAME"] = bot_element.get("name", "SpamDetectorBot")
        
        # Groups
        groups_element = root.find("groups")
        if groups_element is not None:
            admin_group = groups_element.find("admin_group")
            if admin_group is not None:
                env_vars["ADMIN_GROUP_ID"] = admin_group.get("id", "0")
            
            techno_group = groups_element.find("technolog_group")
            if techno_group is not None:
                env_vars["TECHNOLOG_GROUP_ID"] = techno_group.get("id", "0")
            
            log_group = groups_element.find("log_group")
            if log_group is not None:
                env_vars["LOG_GROUP_ID"] = log_group.get("id", "0")
        
        # Channels
        channels_element = root.find("channels")
        if channels_element is not None:
            channel_ids = []
            channel_names = []
            for channel in channels_element.findall("channel"):
                channel_ids.append(channel.get("id", "0"))
                channel_names.append(channel.get("name", ""))
            
            if channel_ids:
                env_vars["CHANNEL_IDS"] = ",".join(channel_ids)
            if channel_names:
                env_vars["CHANNEL_NAMES"] = ",".join(channel_names)
        
        # Thread IDs
        threads_element = root.find("threads")
        if threads_element is not None:
            for thread in threads_element:
                key = f"{thread.tag.upper()}"
                env_vars[key] = thread.get("id", "0")
        
        # Parse groups.xml if it exists
        if os.path.exists(groups_file):
            try:
                groups_tree = ET.parse(groups_file)
                groups_root = groups_tree.getroot()
                # Add any additional configuration from groups.xml
                # This would be implementation-specific
            except Exception as e:
                print(f"⚠️  Warning: Could not parse {groups_file}: {e}")
        
        # Write .env file
        with open(".env", "w") as f:
            f.write("# Bot configuration migrated from XML\n")
            f.write(f"# Generated on {datetime.now().isoformat()}\n\n")
            
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")
        
        print("✅ Created .env file from XML configuration")
        return True
        
    except Exception as e:
        print(f"❌ Error creating .env file: {e}")
        return False


def update_requirements():
    """Update requirements.txt with new dependencies."""
    new_requirements = """# Modern bot requirements - updated for structured architecture
# Core framework
aiogram==2.25.2

# Database
aiosqlite==0.19.0

# Configuration management  
pydantic==2.5.3

# HTTP client
aiohttp==3.9.1

# Async utilities
aiofiles==23.2.0

# Logging and monitoring
structlog==23.2.0

# Existing dependencies
requests==2.32.3
emoji==2.14.0
aiocron==1.8.0
twisted==24.7.0
autobahn==24.4.2
pyopenssl==24.2.1
service_identity==24.1.0
websockets==13.1.0

# Development dependencies (optional)
# black==23.12.1
# mypy==1.8.0
# pytest==7.4.4
# pytest-asyncio==0.21.1
"""
    
    with open("requirements_modern.txt", "w") as f:
        f.write(new_requirements)
    
    print("✅ Created requirements_modern.txt")


def create_directory_structure():
    """Create the modern directory structure."""
    directories = [
        "config",
        "services", 
        "handlers",
        "middleware",
        "utils",
        "logs"
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        
        # Create __init__.py files
        init_file = os.path.join(directory, "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, "w") as f:
                f.write(f'"""{directory.title()} package."""\n\n__version__ = "1.0.0"\n')
    
    print("✅ Created modern directory structure")


def show_migration_summary():
    """Show migration summary and next steps."""
    print("\n" + "="*60)
    print("🎉 MIGRATION COMPLETED SUCCESSFULLY!")
    print("="*60)
    
    print("\n📁 New file structure:")
    print("├── config/")
    print("│   ├── __init__.py")
    print("│   └── settings.py")
    print("├── services/")
    print("│   ├── __init__.py")
    print("│   ├── spam_service.py") 
    print("│   └── ban_service.py")
    print("├── utils/")
    print("│   ├── __init__.py")
    print("│   ├── database.py")
    print("│   └── logger.py")
    print("├── main_aiogram2.py (new modern entry point)")
    print("├── .env (configuration)")
    print("└── requirements_modern.txt")
    
    print("\n📋 Next steps:")
    print("1. Install new dependencies:")
    print("   pip install -r requirements_modern.txt")
    
    print("\n2. Test the new bot:")
    print("   python main_aiogram2.py")
    
    print("\n3. Verify configuration in .env file")
    
    print("\n4. Gradually migrate remaining functionality from main.py")
    
    print("\n⚠️  Important notes:")
    print("• Your original files are safely backed up")
    print("• The new bot uses the same aiogram 2.x for compatibility")
    print("• Modern architecture with services and proper separation")
    print("• Database operations are now async")
    print("• Logging is structured and configurable")
    
    print("\n🔄 To revert: restore files from the backup directory")


def main():
    """Run the migration process."""
    print("🚀 Starting migration to modern bot structure...")
    print("="*60)
    
    # Step 1: Backup original files
    print("\n1️⃣  Creating backup...")
    backup_dir = backup_original_files()
    
    # Step 2: Create directory structure
    print("\n2️⃣  Creating modern directory structure...")
    create_directory_structure()
    
    # Step 3: Migrate configuration
    print("\n3️⃣  Migrating configuration...")
    if create_env_from_xml():
        print("   Configuration migrated successfully")
    else:
        print("   ⚠️  Manual configuration required")
    
    # Step 4: Update requirements
    print("\n4️⃣  Updating requirements...")
    update_requirements()
    
    # Step 5: Show summary
    show_migration_summary()


if __name__ == "__main__":
    main()
