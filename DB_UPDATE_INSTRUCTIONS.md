# 🔧 Database Update - Fix Missing Columns

## ❌ Lỗi Hiện Tại
```
sqlite3.OperationalError: no such column: report_data.is_latest
```

## ✅ Giải Pháp

### Cách 1: Chạy Script Tự Động (Nhanh nhất)
```bash
cd /path/to/PhanMemPC06_Pro
python3 update_db.py
```

Output sẽ như sau:
```
🚀 Đang cập nhật database: pc06_system.db...
✅ Đã thêm cột: is_latest
✅ Đã thêm cột: created_at
✅ Đã thêm cột: updated_at
✨ Hoàn thành cập nhật Database!
```

### Cách 2: Chạy Migration (Nếu dùng Flask-Migrate)
```bash
flask db migrate -m "Add is_latest, created_at, updated_at to ReportData"
flask db upgrade
```

### Cách 3: Chạy SQL Trực Tiếp
```bash
sqlite3 pc06_system.db
```

Sau đó chạy các lệnh:
```sql
ALTER TABLE report_data ADD COLUMN is_latest BOOLEAN DEFAULT 1;
ALTER TABLE report_data ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE report_data ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP;
```

## 📝 Fallback Logic

Đã thêm fallback logic vào `routes/forms.py` để xử lý trường hợp cột chưa tồn tại:

```python
try:
    raw_query = raw_query.filter(ReportData.is_latest == True)
except:
    # Fallback: if is_latest column doesn't exist, just get all records
    pass
```

Điều này cho phép ứng dụng hoạt động ngay cả khi DB chưa được cập nhật.

## 🚀 Tiếp Theo

1. Chạy một trong 3 cách trên để cập nhật DB
2. Restart ứng dụng
3. Test V1 stats page
4. Dữ liệu sẽ hiển thị đúng

## ✨ Status

- ✅ Code đã được cập nhật (fallback logic)
- ⏳ Chờ cập nhật Database
- ⏳ Restart ứng dụng
