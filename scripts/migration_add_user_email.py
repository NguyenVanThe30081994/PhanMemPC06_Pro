# -*- coding: utf-8 -*-
"""
Migration script: add `email` column to the `user` table.
Safe to run multiple times — checks for existing column before adding.

Usage:
    python scripts/migration_add_user_email.py [database_url]

Examples:
    # Default: uses SQLite from app config
    python scripts/migration_add_user_email.py

    # With external MySQL/MariaDB
    python scripts/migration_add_user_email.py mysql://user:pass@localhost/pc06_db
"""

import sys
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def add_email_column(db_url=None):
    """Add the `email` column to the `user` table if it doesn't exist."""
    if not db_url:
        # Try loading from app's environment
        db_url = os.environ.get("DATABASE_URL", "")

    is_sqlite = not db_url or db_url.startswith("sqlite")

    if is_sqlite:
        import sqlite3
        import glob

        # Find the SQLite database file
        db_candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "db.sqlite3"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pc06_system.db"),
        ]
        db_path = None
        for path in db_candidates:
            resolved = os.path.abspath(path)
            if os.path.isfile(resolved):
                db_path = resolved
                break

        if not db_path:
            # Search for any .sqlite3 or .db file
            search_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
            for pattern in ["**/*.sqlite3", "**/*.db"]:
                matches = glob.glob(os.path.join(search_dir, pattern))
                for match in matches:
                    if "node_modules" not in match:
                        db_path = match
                        break
                if db_path:
                    break

        if not db_path:
            logger.error("Could not find SQLite database file. Please provide DATABASE_URL.")
            return False

        logger.info(f"Using SQLite database: {db_path}")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

    else:
        import pymysql

        logger.info(f"Using MySQL database: {db_url}")
        conn = pymysql.connect(
            host=db_url.split("//")[1].split(":")[0] if "://" in db_url else "localhost",
            user=db_url.split("//")[1].split(":")[0] if "://" in db_url else "root",
            password=db_url.split(":")[2].split("@")[0] if ":" in db_url.split("@")[0] else "",
            database=db_url.split("/")[-1] if "/" in db_url else "",
            charset="utf8mb4",
        )
        cursor = conn.cursor()

    try:
        # Check if email column already exists
        if is_sqlite:
            cursor.execute("PRAGMA table_info(user)")
            columns = [row[1] for row in cursor.fetchall()]
        else:
            cursor.execute("DESCRIBE user")
            columns = [row[0] for row in cursor.fetchall()]

        if "email" in columns:
            logger.info("Column 'email' already exists in 'user' table. Skipping migration.")
            return True

        # Add email column
        if is_sqlite:
            cursor.execute("ALTER TABLE user ADD COLUMN email VARCHAR(200)")
        else:
            cursor.execute("ALTER TABLE user ADD COLUMN email VARCHAR(200)")

        conn.commit()
        logger.info("Successfully added 'email' column to 'user' table.")
        return True

    except Exception as e:
        conn.rollback()
        logger.error(f"Migration failed: {e}")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    db_url = sys.argv[1] if len(sys.argv) > 1 else None
    success = add_email_column(db_url)
    sys.exit(0 if success else 1)
