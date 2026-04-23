# Hướng Dẫn Migration: Sửa Lỗi "no such column: report_data.is_latest"

## 🔴 Vấn Đề

Lỗi xảy ra trên production server:
```
sqlite3.OperationalError: no such column: report_data.is_latest
```

**Nguyên nhân**: Code đã được cập nhật để sử dụng cột `is_latest`, nhưng database trên server chưa được migrate.

## ✅ Giải Pháp

### Bước 1: Upload Migration Script lên Server

Upload file `migrate_add_is_latest.py` lên server tại thư mục gốc của ứng dụng:
```
/home/dea35688/domains/pc06tuyenquang.net/public_html/PhanMemPC06_Pro/
```

### Bước 2: SSH vào Server

```bash
ssh dea35688@pc06tuyenquang.net
```

### Bước 3: Di chuyển vào thư mục ứng dụng

```bash
cd /home/dea35688/domains/pc06tuyenquang.net/public_html/PhanMemPC06_Pro/
```

### Bước 4: Chạy Migration Script

```bash
python3 migrate_add_is_latest.py
```

**Hoặc** nếu database file có tên khác:
```bash
python3 migrate_add_is_latest.py path/to/your/database.db
```

### Bước 5: Kiểm Tra Kết Quả

Script sẽ hiển thị:
- ✅ Nếu thành công: "Migration completed successfully!"
- ❌ Nếu thất bại: Thông báo lỗi chi tiết

### Bước 6: Restart Ứng Dụng

Sau khi migration thành công, restart Flask application:

**Nếu dùng systemd:**
```bash
sudo systemctl restart pc06_app
```

**Nếu dùng passenger:**
```bash
touch tmp/restart.txt
```

**Hoặc restart Apache/Nginx:**
```bash
sudo systemctl restart apache2
# hoặc
sudo systemctl restart nginx
```

### Bước 7: Kiểm Tra Lại

1. Truy cập trang thống kê: `/stats?rid=1`
2. Kiểm tra log file để đảm bảo không còn lỗi `is_latest`

---

## 🔧 Fallback Code

Code đã được cập nhật với fallback mechanism. Nếu cột `is_latest` không tồn tại, hệ thống sẽ:
1. Tự động phát hiện lỗi
2. Log warning message
3. Chạy query không có filter `is_latest`
4. Trang web vẫn hoạt động bình thường (nhưng có thể hiển thị dữ liệu cũ)

**Tuy nhiên**, bạn vẫn NÊN chạy migration để đảm bảo:
- Chỉ hiển thị dữ liệu mới nhất
- Tránh duplicate records trong thống kê
- Cải thiện performance

---

## 📋 Chi Tiết Migration

Migration script sẽ:
1. ✅ Kiểm tra xem cột `is_latest` đã tồn tại chưa
2. ✅ Thêm cột `is_latest BOOLEAN DEFAULT 1` vào bảng `report_data`
3. ✅ Set tất cả records hiện tại thành `is_latest=1`
4. ✅ Verify migration thành công

**Lưu ý**: Script an toàn và idempotent (có thể chạy nhiều lần mà không gây lỗi)

---

## 🆘 Troubleshooting

### Lỗi: "Database file not found"
- Kiểm tra bạn đang ở đúng thư mục
- Kiểm tra tên file database (có thể là `app.db`, `database.db`, etc.)
- Chạy: `ls -la *.db` để tìm file database

### Lỗi: "Permission denied"
- Chạy với quyền phù hợp: `sudo python3 migrate_add_is_latest.py`
- Hoặc thay đổi owner: `sudo chown dea35688:dea35688 pc06_system.db`

### Lỗi: "Database is locked"
- Dừng ứng dụng Flask trước khi chạy migration
- Đợi vài giây rồi thử lại

---

## 📞 Liên Hệ

Nếu gặp vấn đề, cung cấp:
1. Output của migration script
2. Nội dung file log
3. Kết quả của: `python3 -c "import sqlite3; print(sqlite3.version)"`
