#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Migration Script: Add is_latest column to report_data table
Run this on production server to fix the "no such column: report_data.is_latest" error
"""
import sqlite3
import os
import sys

def migrate_database(db_path='pc06_system.db'):
    """Add is_latest column to report_data table"""
    
    if not os.path.exists(db_path):
        print(f"❌ ERROR: Database file not found at: {db_path}")
        print(f"   Current directory: {os.getcwd()}")
        print(f"   Please run this script from the application root directory")
        return False
    
    print(f"🔍 Found database: {db_path}")
    print(f"📊 Connecting to database...")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(report_data)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'is_latest' in columns:
            print(f"✅ Column 'is_latest' already exists in report_data table")
            print(f"   No migration needed!")
            conn.close()
            return True
        
        print(f"🚀 Adding 'is_latest' column to report_data table...")
        
        # Add the column
        cursor.execute("ALTER TABLE report_data ADD COLUMN is_latest BOOLEAN DEFAULT 1")
        
        # Set all existing records to is_latest=1 (True)
        cursor.execute("UPDATE report_data SET is_latest = 1 WHERE is_latest IS NULL")
        
        conn.commit()
        
        # Verify the column was added
        cursor.execute("PRAGMA table_info(report_data)")
        columns_after = [row[1] for row in cursor.fetchall()]
        
        if 'is_latest' in columns_after:
            print(f"✅ SUCCESS: Column 'is_latest' added successfully!")
            print(f"✅ All existing records marked as is_latest=1")
            
            # Show record count
            cursor.execute("SELECT COUNT(*) FROM report_data")
            count = cursor.fetchone()[0]
            print(f"📊 Total records in report_data: {count}")
            
            conn.close()
            return True
        else:
            print(f"❌ ERROR: Column was not added successfully")
            conn.close()
            return False
            
    except sqlite3.Error as e:
        print(f"❌ SQLite Error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("  PC06 Database Migration: Add is_latest Column")
    print("=" * 60)
    print()
    
    # Allow custom database path as command line argument
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'pc06_system.db'
    
    success = migrate_database(db_path)
    
    print()
    print("=" * 60)
    if success:
        print("✅ Migration completed successfully!")
        print()
        print("Next steps:")
        print("  1. Restart your Flask application")
        print("  2. Test the stats page to verify it works")
        print("  3. Check logs for any remaining errors")
    else:
        print("❌ Migration failed!")
        print()
        print("Troubleshooting:")
        print("  1. Make sure you're in the correct directory")
        print("  2. Check database file permissions")
        print("  3. Verify the database file is not corrupted")
    print("=" * 60)
    
    sys.exit(0 if success else 1)
