#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Add database indexes for performance optimization
"""
import sqlite3
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def add_indexes():
    """Add missing indexes to improve query performance"""
    db_path = 'pc06_system.db'
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    indexes = [
        # Notification indexes
        ('idx_notification_user_created', 'notification', 'user_id, created_at DESC'),
        ('idx_notification_is_read', 'notification', 'is_read'),
        
        # Task indexes
        ('idx_task_author_deadline', 'task', 'author_id, deadline'),
        ('idx_task_domain', 'task', 'domain'),
        ('idx_task_created_at', 'task', 'created_at DESC'),
        
        # Task assignment indexes
        ('idx_task_assignment_task', 'task_assignment', 'task_id'),
        ('idx_task_assignment_user', 'task_assignment', 'user_id'),
        ('idx_task_assignment_status', 'task_assignment', 'status'),
        ('idx_task_assignment_composite', 'task_assignment', 'task_id, user_id, status'),
        
        # Task comment indexes
        ('idx_task_comment_task_created', 'task_comment', 'task_id, created_at DESC'),
        ('idx_task_comment_user', 'task_comment', 'user_id'),
        
        # System log indexes
        ('idx_system_log_user_created', 'system_log', 'user_id, created_at DESC'),
        ('idx_system_log_module', 'system_log', 'module'),
        ('idx_system_log_created', 'system_log', 'created_at DESC'),
        
        # Short link indexes
        ('idx_short_link_created_by', 'short_link', 'created_by'),
        ('idx_short_link_created_at', 'short_link', 'created_at DESC'),
    ]
    
    success_count = 0
    skip_count = 0
    error_count = 0
    
    print("🔧 Adding database indexes...\n")
    
    for idx_name, table_name, columns in indexes:
        try:
            # Check if index already exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                (idx_name,)
            )
            if cursor.fetchone():
                print(f"⏭️  {idx_name} (already exists)")
                skip_count += 1
                continue
            
            # Create index
            sql = f"CREATE INDEX {idx_name} ON {table_name}({columns})"
            cursor.execute(sql)
            print(f"✅ {idx_name}")
            success_count += 1
            
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                print(f"⚠️  {idx_name} (table {table_name} not found)")
            else:
                print(f"❌ {idx_name}: {e}")
            error_count += 1
        except Exception as e:
            print(f"❌ {idx_name}: {e}")
            error_count += 1
    
    conn.commit()
    conn.close()
    
    print(f"\n📊 Summary:")
    print(f"   ✅ Created: {success_count}")
    print(f"   ⏭️  Skipped: {skip_count}")
    print(f"   ❌ Errors: {error_count}")
    print(f"   📝 Total: {len(indexes)}")
    
    return error_count == 0

if __name__ == '__main__':
    success = add_indexes()
    sys.exit(0 if success else 1)
