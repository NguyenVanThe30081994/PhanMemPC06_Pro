import sqlite3
import os

db_path = 'pc06_system.db'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("UPDATE system_log SET module = 'Hệ thống' WHERE module IS NULL OR module = '' OR module = '-'")
    conn.commit()
    print(f"✅ Đã cập nhật {cursor.rowcount} bản ghi nhật ký cũ.")
    conn.close()
else:
    print("❌ Không tìm thấy tệp cơ sở dữ liệu.")
