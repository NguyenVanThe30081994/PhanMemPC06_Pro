"""
Auto Backup Script for PC06 System
Automatically backs up the SQLite database and uploads folder
"""
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

# Configuration
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(PROJECT_ROOT, 'backups')
DB_PATH = os.path.join(PROJECT_ROOT, 'pc06_system.db')
UPLOAD_DIR = os.path.join(PROJECT_ROOT, 'uploads')
TASK_FILES_DIR = os.path.join(PROJECT_ROOT, 'task_files')
LIB_FILES_DIR = os.path.join(PROJECT_ROOT, 'library_files')

# Backup settings
MAX_BACKUPS = 10  # Keep only last 10 backups

def create_backup():
    """Create a new backup of the database and important folders"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"pc06_backup_{timestamp}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    
    print(f"Starting backup: {backup_name}")
    
    # Create backup directory
    os.makedirs(backup_path, exist_ok=True)
    
    # 1. Backup Database
    if os.path.exists(DB_PATH):
        db_backup_path = os.path.join(backup_path, 'pc06_system.db')
        shutil.copy2(DB_PATH, db_backup_path)
        print(f"  ✓ Database backed up")
    else:
        print(f"  ✗ Database not found: {DB_PATH}")
    
    # 2. Backup Uploads (optional - comment out if not needed)
    # if os.path.exists(UPLOAD_DIR):
    #     uploads_backup = os.path.join(backup_path, 'uploads')
    #     shutil.copytree(UPLOAD_DIR, uploads_backup)
    #     print(f"  ✓ Uploads backed up")
    
    # 3. Backup Task Files
    if os.path.exists(TASK_FILES_DIR):
        task_backup = os.path.join(backup_path, 'task_files')
        shutil.copytree(TASK_FILES_DIR, task_backup)
        print(f"  ✓ Task files backed up")
    
    # 4. Backup Library Files
    if os.path.exists(LIB_FILES_DIR):
        lib_backup = os.path.join(backup_path, 'library_files')
        shutil.copytree(LIB_FILES_DIR, lib_backup)
        print(f"  ✓ Library files backed up")
    
    # 5. Create backup info file
    info_path = os.path.join(backup_path, 'backup_info.txt')
    with open(info_path, 'w', encoding='utf-8') as f:
        f.write(f"PC06 Backup Information\n")
        f.write(f"========================\n")
        f.write(f"Backup Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Database Size: {os.path.getsize(DB_PATH) / 1024:.2f} KB\n")
    
    print(f"  ✓ Backup completed: {backup_path}")
    
    # Clean old backups
    cleanup_old_backups()
    
    return backup_path

def cleanup_old_backups():
    """Remove old backups keeping only MAX_BACKUPS most recent"""
    if not os.path.exists(BACKUP_DIR):
        return
    
    backups = sorted(
        [d for d in os.listdir(BACKUP_DIR) if d.startswith('pc06_backup_')],
        reverse=True
    )
    
    if len(backups) > MAX_BACKUPS:
        for old_backup in backups[MAX_BACKUPS:]:
            old_path = os.path.join(BACKUP_DIR, old_backup)
            shutil.rmtree(old_path)
            print(f"  ✓ Removed old backup: {old_backup}")

def restore_backup(backup_name):
    """Restore from a specific backup"""
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    
    if not os.path.exists(backup_path):
        print(f"Backup not found: {backup_name}")
        return False
    
    # Restore database
    db_backup = os.path.join(backup_path, 'pc06_system.db')
    if os.path.exists(db_backup):
        shutil.copy2(db_backup, DB_PATH)
        print(f"  ✓ Database restored")
    
    # Restore files (optional)
    # ...
    
    print(f"  ✓ Restore completed from: {backup_name}")
    return True

def list_backups():
    """List all available backups"""
    if not os.path.exists(BACKUP_DIR):
        print("No backups directory found")
        return
    
    backups = sorted(
        [d for d in os.listdir(BACKUP_DIR) if d.startswith('pc06_backup_')],
        reverse=True
    )
    
    print("\nAvailable Backups:")
    print("-" * 40)
    for backup in backups:
        backup_path = os.path.join(BACKUP_DIR, backup)
        size = sum(os.path.getsize(os.path.join(backup_path, f)) 
                   for f in os.listdir(backup_path) 
                   if os.path.isfile(os.path.join(backup_path, f)))
        date = backup.replace('pc06_backup_', '').replace('_', ' ')
        print(f"  {date} - {size / 1024:.2f} KB")
    print("-" * 40)

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == 'backup':
            create_backup()
        elif command == 'list':
            list_backups()
        elif command == 'restore' and len(sys.argv) > 2:
            restore_backup(sys.argv[2])
        else:
            print("Usage: python auto_backup.py [backup|list|restore <backup_name>]")
    else:
        # Run daily backup by default
        print("Running scheduled backup...")
        create_backup()
