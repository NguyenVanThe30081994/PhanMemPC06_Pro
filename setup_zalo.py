"""
Setup Zalo OA - Simple SQLite version
Run this, enter your info, done!
"""
import sqlite3
import os
from datetime import datetime

db_path = os.path.join(os.path.dirname(__file__), 'pc06_system.db')

def setup():
    print("=" * 50)
    print("ZALO OA SETUP")
    print("=" * 50)

    # Get input
    print("\n[1] ZALO INFO:")
    app_id = input("App ID: ").strip()
    secret_key = input("Secret Key: ").strip()
    oa_id = input("OA ID: ").strip()
    oa_secret = input("OA Secret: ").strip()

    print("\n[2] TEMPLATE IDS:")
    template_deadline = input("Template - Sap han: ").strip()
    template_overdue = input("Template - Qua han: ").strip()
    template_report = input("Template - Bao cao: ").strip()

    print("\n[3] TOKENS:")
    access_token = input("Access Token: ").strip()
    refresh_token = input("Refresh Token: ").strip()

    # Save to DB
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Delete old config
    cursor.execute("DELETE FROM zalo_config")

    # Insert new
    cursor.execute("""
        INSERT INTO zalo_config (
            app_id, secret_key, oa_id, oa_secret,
            access_token, refresh_token, token_expires_at,
            template_deadline_warning, template_overdue, template_report_remind,
            is_active, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
    """, (app_id, secret_key, oa_id, oa_secret,
          access_token, refresh_token, datetime.now().isoformat(),
          template_deadline, template_overdue, template_report))

    conn.commit()
    conn.close()

    print("\n" + "=" * 50)
    print("SAVED!")
    print("=" * 50)

if __name__ == '__main__':
    setup()
