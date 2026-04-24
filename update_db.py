import sqlite3
import os

def update_database():
    db_path = 'pc06_system.db' # Tên file db của bạn
    if not os.path.exists(db_path):
        print(f"❌ Không tìm thấy file database tại {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print(f"🚀 Đang cập nhật database: {db_path}...")

    # Danh sách các cột cần thêm vào bảng report_data
    columns_to_add = [
        ("is_latest", "BOOLEAN DEFAULT 1"),
        ("created_at", "DATETIME DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at", "DATETIME DEFAULT CURRENT_TIMESTAMP")
    ]

    for col_name, col_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE report_data ADD COLUMN {col_name} {col_type}")
            print(f"✅ Đã thêm cột: {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"ℹ️ Cột {col_name} đã tồn tại, bỏ qua.")
            else:
                print(f"❌ Lỗi khi thêm cột {col_name}: {e}")

    conn.commit()
    conn.close()
    print("✨ Hoàn thành cập nhật Database!")

if __name__ == "__main__":
    update_database()
