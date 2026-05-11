"""
Migrate Database - Add phone column
"""
# -*- coding: utf-8 -*-
import sqlite3
import os


def _resolve_db_path():
    env_data_dir = (os.environ.get('PC06_DATA_DIR') or '').strip()
    if env_data_dir:
        if os.path.isabs(env_data_dir):
            data_root = env_data_dir
        else:
            data_root = os.path.abspath(os.path.join(os.path.dirname(__file__), env_data_dir))
        return os.path.join(data_root, 'pc06_system.db')
    return os.path.join(os.path.dirname(__file__), 'pc06_system.db')


db_path = _resolve_db_path()

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
