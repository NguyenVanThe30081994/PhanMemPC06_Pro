# -*- coding: utf-8 -*-
"""
Import Zalo Config - Read zalo_config.txt and save to database
Run: python import_zalo_config.py
"""
import sqlite3
import os
import codecs
from datetime import datetime

db_path = os.path.join(os.path.dirname(__file__), 'pc06_system.db')

def import_config():
    print("Reading zalo_config.txt...")
    
    # Read config file with UTF-8
    config = {}
    with codecs.open('zalo_config.txt', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip().strip('"')
    
    # Check required fields
    required = ['app_id', 'secret_key', 'access_token']
    missing = [k for k in required if not config.get(k)]
    if missing:
        print(f"Missing: {missing}")
        print("Edit zalo_config.txt first!")
        return
    
    # Save to DB
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM zalo_config")
    cursor.execute("""
        INSERT INTO zalo_config (
            app_id, secret_key, oa_id, oa_secret,
            access_token, refresh_token, token_expires_at,
            template_deadline_warning, template_overdue, template_report_remind,
            is_active, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
    """, (
        config.get('app_id', ''),
        config.get('secret_key', ''),
        config.get('oa_id', ''),
        config.get('oa_secret', ''),
        config.get('access_token', ''),
        config.get('refresh_token', ''),
        datetime.now().isoformat(),
        config.get('template_deadline_warning', ''),
        config.get('template_overdue', ''),
        config.get('template_report_remind', '')
    ))
    conn.commit()
    conn.close()
    
    print("DONE! Zalo config saved to database.")

if __name__ == '__main__':
    import_config()
