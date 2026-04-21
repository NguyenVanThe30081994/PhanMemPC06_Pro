#!/usr/bin/env python3
"""Migrate V3 schema - thêm các cột còn thiếu"""
import sys
sys.path.insert(0, '.')

from app import app
from models import db

with app.app_context():
    # Get current columns
    conn = db.engine.raw_connection()
    cursor = conn.cursor()
    
    tables_to_check = [
        'report_template_v3',
        'report_template_field_v3', 
        'report_version_v3',
        'report_submission_v3',
        'report_value_v3',
        'report_audit_v3'
    ]
    
    for table in tables_to_check:
        try:
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]
            print(f"\n{table}: {columns}")
        except Exception as e:
            print(f"\n{table}: {e}")
    
    conn.close()
