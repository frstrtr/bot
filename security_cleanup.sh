#!/bin/bash

# Security cleanup script - removes sensitive data from tracked files
# Run this before committing to ensure no sensitive information is exposed

echo "🔒 CLEANING SENSITIVE DATA FROM TRACKED FILES"
echo "=============================================="

# Backup sensitive values
BOT_ID="1234567890"
ADMIN_ID="9876543210" 
BOT_TOKEN_PART="AAHrxbBgR4JHq8hT3Cydbj41kmIk-PbasOQ"

# Replacement values
PLACEHOLDER_BOT_ID="1234567890"
PLACEHOLDER_ADMIN_ID="9876543210"
PLACEHOLDER_TOKEN_PART="XXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

echo "📄 Cleaning documentation files..."

# Clean markdown files
for file in *.md; do
    if [ -f "$file" ]; then
        if grep -q "$BOT_ID" "$file"; then
            echo "  🧹 Cleaning $file"
            sed -i "s/$BOT_ID/$PLACEHOLDER_BOT_ID/g" "$file"
        fi
    fi
done

echo "📄 Cleaning log files..."

# Clean log files that contain admin ID
for file in daily_spam_*.txt inout_*.txt aiogram3_inout/inout_*.txt inout/inout_*.txt; do
    if [ -f "$file" ]; then
        if grep -q "$ADMIN_ID" "$file"; then
            echo "  🧹 Cleaning $file"
            sed -i "s/$ADMIN_ID/$PLACEHOLDER_ADMIN_ID/g" "$file"
        fi
    fi
done

echo "✅ Cleanup complete!"
echo ""
echo "🔍 Verifying cleanup..."

# Verify no sensitive data remains
FOUND_SENSITIVE=0

if grep -r "$BOT_ID" --include="*.md" --include="*.txt" . | grep -v ".env" >/dev/null 2>&1; then
    echo "❌ Bot ID still found in tracked files"
    FOUND_SENSITIVE=1
fi

if grep -r "$ADMIN_ID" --include="*.txt" . | grep -v ".env" >/dev/null 2>&1; then
    echo "❌ Admin ID still found in tracked files"
    FOUND_SENSITIVE=1
fi

if [ $FOUND_SENSITIVE -eq 0 ]; then
    echo "✅ No sensitive data found in tracked files"
    echo "🚀 Safe to commit!"
else
    echo "⚠️  Some sensitive data may still be present"
    echo "🔍 Please review manually"
fi
