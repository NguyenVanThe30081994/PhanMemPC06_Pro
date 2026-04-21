#!/usr/bin/env python3
"""Script migrate V3 schema - chạy trên production"""
import sqlite3
import os

# Tìm database file
db_path = os.path.join(os.path.dirname(__file__), 'pc06_system.db')
if not os.path.exists(db_path):
    db_path = os.path.join(os.path.dirname(__file__), '..', 'pc06_system.db')

print(f"Database: {db_path}")

def migrate():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    try:
        # 1. Thêm template_code, updated_at vào report_template_v3 nếu chưa có
        c.execute("PRAGMA table_info(report_template_v3)")
        cols = [col[1] for col in c.fetchall()]
        print(f"Cột hiện tại: {cols}")
        
        if 'template_code' not in cols:
            c.execute("ALTER TABLE report_template_v3 ADD COLUMN template_code VARCHAR(50)")
            print("Added template_code")
        
        if 'updated_at' not in cols:
            c.execute("ALTER TABLE report_template_v3 ADD COLUMN updated_at TIMESTAMP")
            print("Added updated_at")
        
        # 2. Tạo bảng report_template_field_v3 nếu chưa có
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='report_template_field_v3'")
        if not c.fetchone():
            c.execute(""""
                CREATE TABLE report_template_field_v3 (
                    id INTEGER PRIMARY KEY,
                    template_id INTEGER REFERENCES report_template_v3(id),
                    field_code VARCHAR(100) NOT NULL,
                    field_name VARCHAR(255),
                    header_path TEXT,
                    column_index INTEGER,
                    data_type VARCHAR(20) DEFAULT 'text',
                    editable BOOLEAN DEFAULT 1,
                    required BOOLEAN DEFAULT 0,
                    default_value TEXT,
                    validation_rules TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.execute("CREATE INDEX idx_field_template ON report_template_field_v3(template_id)")
            print("Created report_template_field_v3")
        
        # 3. Thêm cột vào report_version_v3
        c.execute("PRAGMA table_info(report_version_v3)")
        cols = [col[1] for col in c.fetchall()]
        
        for col, dtype in [('schema_json', 'TEXT'), ('excel_blob', 'BLOB'), ('header_row_count', 'INTEGER DEFAULT 3'), ('created_by', 'VARCHAR(100)'), ('is_published', 'BOOLEAN DEFAULT 0')]:
            if col not in cols:
                c.execute(f"ALTER TABLE report_version_v3 ADD COLUMN {col} {dtype}")
                print(f"Added {col} to report_version_v3")
        
        # 4. Thêm cột vào report_submission_v3
        c.execute("PRAGMA table_info(report_submission_v3)")
        cols = [col[1] for col in c.fetchall()]
        
        for col, dtype in [('unit_id', 'VARCHAR(100) DEFAULT \'\''), ('period_id', 'VARCHAR(50)'), ('submitted_at', 'TIMESTAMP')]:
            if col not in cols:
                c.execute(f"ALTER TABLE report_submission_v3 ADD COLUMN {col} {dtype}")
                print(f"Added {col} to report_submission_v3")
        
        # 5. Thêm cột vào report_value_v3
        c.execute("PRAGMA table_info(report_value_v3)")
        cols = [col[1] for col in c.fetchall()]
        
        for col, dtype in [('field_id', 'INTEGER'), ('field_code', 'VARCHAR(100)')]:
            if col not in cols:
                c.execute(f"ALTER TABLE report_value_v3 ADD COLUMN {col} {dtype}")
                print(f"Added {col} to report_value_v3")
        
        # 6. Tạo bảng report_audit_v3 nếu chưa có
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='report_audit_v3'")
        if not c.fetchone():
            c.execute("""
                CREATE TABLE report_audit_v3 (
                    id INTEGER PRIMARY KEY,
                    submission_id INTEGER REFERENCES report_submission_v3(id),
                    user_id INTEGER REFERENCES user(id),
                    field_code VARCHAR(100),
                    old_value TEXT,
                    new_value TEXT,
                    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            c.execute("CREATE INDEX idx_audit_submission ON report_audit_v3(submission_id)")
            print("Created report_audit_v3")
        
        conn.commit()
        print("\nMigrate hoan tat!")
        
    except Exception as e:
        conn.rollback()
        print(f"Loi: {e}")
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
