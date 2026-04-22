"""
Migrate Database - Add phone column and Zalo tables
"""
# -*- coding: utf-8 -*-
import sqlite3
import os
import codecs
from datetime import datetime

db_path = os.path.join(os.path.dirname(__file__), 'pc06_system.db')

def migrate():
    print("=" * 50)
    print("MIGRATE DATABASE")
    print("=" * 50)

    if not os.path.exists(db_path):
        print("Database not found. Run app first to create.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Add phone column to user
    try:
        cursor.execute("ALTER TABLE user ADD COLUMN phone VARCHAR(20)")
        print("OK: Added phone column to user")
    except:
        print("OK: Phone column already exists")

    # Create zalo_config table
    try:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS zalo_config (
            id INTEGER PRIMARY KEY,
            app_id VARCHAR(50) NOT NULL,
            secret_key VARCHAR(100) NOT NULL,
            oa_id VARCHAR(50),
            oa_secret VARCHAR(100),
            access_token TEXT,
            refresh_token TEXT,
            token_expires_at DATETIME,
            template_deadline_warning VARCHAR(50),
            template_overdue VARCHAR(50),
            template_report_remind VARCHAR(50),
            is_active BOOLEAN DEFAULT 1,
            updated_at DATETIME,
            created_at DATETIME
        )
        """)
        print("OK: Created zalo_config table")
    except Exception as e:
        print(f"Error: {e}")

    # Create zalo_message_log table
    try:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS zalo_message_log (
            id INTEGER PRIMARY KEY,
            recipient_phone VARCHAR(20) NOT NULL,
            recipient_name VARCHAR(100),
            template_type VARCHAR(30),
            task_id INTEGER,
            status VARCHAR(20),
            error_code VARCHAR(20),
            error_message TEXT,
            zalo_message_id VARCHAR(100),
            created_at DATETIME
        )
        """)
        print("OK: Created zalo_message_log table")
    except Exception as e:
        print(f"Error: {e}")

    conn.commit()
    conn.close()

    print("DONE!")

if __name__ == '__main__':
    migrate()
