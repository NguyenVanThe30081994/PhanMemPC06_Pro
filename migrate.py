"""
Migrate Database - Add phone column
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

    conn.commit()
    conn.close()

    print("DONE!")

if __name__ == '__main__':
    migrate()
