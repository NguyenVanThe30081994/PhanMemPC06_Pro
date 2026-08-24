# 🚀 HƯỚNG DẪN TRIỂN KHAI NHANH - HỆ THỐNG PC06

**Ngày cập nhật:** 06/08/2026  
**Phiên bản:** 3.5.0  
**Trạng thái:** ✅ Đã sửa lỗi và sẵn sàng triển khai

---

## 📋 CHECKLIST TRƯỚC KHI TRIỂN KHAI

### ✅ Các lỗi đã được sửa:
- [x] Trang chủ `/admin` trả về 404
- [x] Menu sidebar không thu gọn được
- [x] Giao diện xác thực mật khẩu bị lệch
- [x] Thiếu các class CSS (glass-card, bento-card, animations)

### ✅ Đã kiểm tra:
- [x] Python syntax - Không có lỗi
- [x] Database files tồn tại
- [x] Templates render đúng
- [x] CSS/JS không có lỗi

---

## 🖥️ KHỞI ĐỘNG SERVER (MAC/LINUX)

### Bước 1: Di chuyển vào thư mục dự án
```bash
cd "/Users/nguyenvanthe/Documents/Không có tiêu đề/PhanMemPC06_Pro"
```

### Bước 2: Khởi động server
```bash
./START_SERVER_MAC.sh
```

**Hoặc khởi động thủ công:**
```bash
export FLASK_APP=app.py
export FLASK_ENV=development
python3 app.py
```

### Bước 3: Truy cập hệ thống
Mở trình duyệt và truy cập:
```
http://localhost:5000
```

**Tài khoản mặc định:**
- Username: `admin` hoặc `root`
- Password: (kiểm tra file `scripts/admin/reset_admin.py` nếu quên)

---

## 🔧 KHỞI ĐỘNG SERVER (WINDOWS)

### Bước 1: Mở Command Prompt hoặc PowerShell
```cmd
cd "C:\path\to\PhanMemPC06_Pro"
```

### Bước 2: Khởi động server
```cmd
Start_Server.bat
```

**Hoặc:**
```cmd
python app.py
```

---

## 🧪 KIỂM TRA CÁC LỖI ĐÃ SỬA

### 1️⃣ Kiểm tra trang chủ (404 fix)
```
✅ Truy cập: http://localhost:5000/admin
✅ Kết quả: Hiển thị dashboard với biểu đồ và thống kê
❌ Lỗi: Nếu vẫn 404, kiểm tra file routes/admin.py dòng 469
```

### 2️⃣ Kiểm tra menu sidebar (toggle fix)
```
✅ Click vào menu "Hệ thống" → submenu mở ra
✅ Click lại "Hệ thống" → submenu thu gọn
✅ Icon chevron xoay từ ↓ sang ↑
❌ Lỗi: Mở Console (F12) xem có lỗi JavaScript không
```

### 3️⃣ Kiểm tra trang re-authentication (layout fix)
```
✅ Truy cập: http://localhost:5000/reauth
✅ Hoặc: Truy cập /roles và chờ 15 phút → auto redirect
✅ Kết quả: Form nhập mật khẩu hiển thị đúng, không bị lệch
❌ Lỗi: Nếu bị lệch, clear cache browser (Ctrl+Shift+Del)
```

### 4️⃣ Kiểm tra Dark Mode (CSS fix)
```
✅ Click nút toggle theme (icon mặt trăng/mặt trời) ở góc phải trên
✅ Kết quả: Tất cả card, form, text chuyển sang dark mode
✅ Kiểm tra: .glass-card, .bento-card phải hiển thị đúng
❌ Lỗi: Nếu một số element không đổi màu, kiểm tra static/css/style.css
```

---

## 🎯 DEMO CHỨC NĂNG CHÍNH

### Dashboard (Trang chủ)
```
URL: /admin
Chức năng:
  - Hiển thị 4 stat cards
  - Biểu đồ công việc (Chart.js)
  - Danh sách hoạt động gần đây
```

### Công việc
```
URL: /tasks
Chức năng:
  - Tạo công việc (3 loại: FORM, OUTLINE, FILE)
  - Ma trận tiến độ
  - Export báo cáo Word
  - Import từ Excel
```

### Thông báo
```
URL: /thong-bao
Chức năng:
  - Tạo thông báo mới
  - Upload file đính kèm
  - Phân loại theo lĩnh vực
```

### Danh bạ
```
URL: /contacts
Chức năng:
  - Import từ Excel
  - Export template
  - Search và filter
```

### Hệ thống
```
URL: /roles
Chức năng:
  - Quản lý tài khoản
  - Phân quyền
  - Import user từ Excel
  - Reset password bulk
```

---

## 🔐 ĐĂNG NHẬP LẦN ĐẦU

### Reset mật khẩu admin (nếu cần)
```bash
PC06_CONFIRM=YES python3 scripts/admin/reset_admin.py
```

> Script quản trị nằm trong `scripts/admin/`, bắt buộc biến môi trường
> `PC06_CONFIRM=YES` mới chạy (chống thao tác nhầm trên production).

Script này sẽ:
- Tạo user `admin` với mật khẩu mặc định
- Hoặc reset mật khẩu nếu đã tồn tại

### Đăng nhập
1. Truy cập `http://localhost:5000`
2. Nhập username: `admin`
3. Nhập password (mật khẩu đã reset)
4. Click "Đăng nhập"

### Đổi mật khẩu ngay sau khi đăng nhập
1. Click vào dropdown tên người dùng (góc phải trên)
2. Chọn "Đổi mật khẩu"
3. Nhập mật khẩu cũ và mật khẩu mới
4. Mật khẩu mới phải có:
   - Ít nhất 8 ký tự
   - Có chữ hoa
   - Có chữ thường
   - Có số
   - Có ký tự đặc biệt (@, #, $, %, etc.)

---

## 🐛 XỬ LÝ SỰ CỐ

### Lỗi: "Module not found"
```bash
# Cài đặt lại dependencies
pip3 install -r requirements.txt
```

### Lỗi: "Database is locked"
```bash
# Dừng tất cả các instance đang chạy
pkill -f "python.*app.py"

# Xóa file lock
rm -f pc06_system.db-journal

# Khởi động lại
./START_SERVER_MAC.sh
```

### Lỗi: "Port 5000 already in use"
```bash
# Tìm process đang dùng port 5000
lsof -i :5000

# Kill process đó
kill -9 <PID>

# Hoặc đổi port trong app.py
export PC06_PORT=5001
python3 app.py
```

### Lỗi: Giao diện bị vỡ/CSS không load
```bash
# Clear cache browser: Ctrl+Shift+Delete (hoặc Cmd+Shift+Delete trên Mac)
# Hoặc hard refresh: Ctrl+F5 (Cmd+Shift+R trên Mac)

# Kiểm tra static files
ls -la static/css/
ls -la static/js/

# Nếu thiếu file, restore từ backup
```

### Lỗi: JavaScript không hoạt động
```bash
# Mở Console (F12)
# Kiểm tra lỗi JavaScript
# Thường là do thiếu file hoặc syntax error

# Kiểm tra file main.js
cat static/js/main.js
```

---

## 📊 MONITORING & LOGS

### Xem logs ứng dụng
```bash
tail -f logs/app.log
```

### Xem logs database
```bash
# SQLite
sqlite3 pc06_system.db "SELECT * FROM system_logs ORDER BY timestamp DESC LIMIT 10;"
```

### Xem activity logs trong web
```
URL: /logs
Yêu cầu: Phải có quyền "sys" module
```

---

## 💾 BACKUP & RESTORE

### Backup database
```bash
# Backup SQLite
cp pc06_system.db "backups/pc06_system_$(date +%Y%m%d_%H%M%S).db"

# Hoặc dùng web interface
URL: /admin/db-tool
Chức năng: Click "Tạo bản sao lưu"
```

### Restore database
```bash
# Stop server
pkill -f "python.*app.py"

# Restore
cp backups/pc06_system_20260806.db pc06_system.db

# Restart server
./START_SERVER_MAC.sh
```

---

## 🌐 TRIỂN KHAI PRODUCTION (cPanel/MySQL)

### Bước 1: Cấu hình database
```bash
# Tạo file .env
cat > .env << EOF
DATABASE_URL=mysql+pymysql://username:password@localhost/pc06_db
SECRET_KEY=your-secret-key-here
SESSION_LIFETIME=28800
DEBUG=False
EOF
```

### Bước 2: Migrate database
```bash
python3 migrate.py --dry-run
python3 migrate.py
```

### Bước 3: Cài đặt dependencies
```bash
pip3 install -r requirements.txt --user
```

### Bước 4: Cấu hình Passenger (cPanel)
```bash
# Tạo file passenger_wsgi.py
# Đã có sẵn trong dự án

# Restart Passenger
touch tmp/restart.txt
```

### Bước 5: Cấu hình data directory
```bash
export PC06_DATA_DIR=/home/username/pc06_data
mkdir -p $PC06_DATA_DIR/{uploads,tasks,backups,logs,tmp}
```

---

## 🔒 BẢO MẬT PRODUCTION

### Checklist bảo mật:
- [ ] Đổi SECRET_KEY mặc định
- [ ] Đặt DEBUG=False
- [ ] Bật HTTPS (SESSION_COOKIE_SECURE=True)
- [ ] Cấu hình firewall
- [ ] Giới hạn login attempts
- [ ] Backup thường xuyên
- [ ] Update dependencies định kỳ
- [ ] Review logs hàng ngày

### Đổi SECRET_KEY:
```bash
# Generate secret key mới
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Copy vào .env
echo "SECRET_KEY=<key-vừa-tạo>" >> .env
```

---

## 📞 HỖ TRỢ

### Lỗi không thể tự giải quyết:

1. **Kiểm tra logs:**
   ```bash
   tail -100 logs/app.log
   ```

2. **Kiểm tra Console browser:**
   - Mở DevTools (F12)
   - Tab Console: Xem lỗi JavaScript
   - Tab Network: Xem request bị lỗi

3. **Test Python syntax:**
   ```bash
   python3 -m py_compile app.py
   python3 -m py_compile routes/*.py
   ```

4. **Restore từ backup:**
   - Nếu mọi thứ đều fail, restore lại database và code từ backup

---

## 📚 TÀI LIỆU THAM KHẢO

- **BAO_CAO_SUA_LOI_20260806.md** - Chi tiết các lỗi đã sửa
- **README.md** - Tổng quan dự án
- **CHANGELOG.md** - Lịch sử thay đổi
- **docs/** - Tài liệu kỹ thuật chi tiết

---

## ✅ CHECKLIST SAU KHI TRIỂN KHAI

### Kiểm tra chức năng cơ bản:
- [ ] Đăng nhập thành công
- [ ] Dashboard hiển thị đúng
- [ ] Menu sidebar toggle hoạt động
- [ ] Tạo công việc mới
- [ ] Tạo thông báo mới
- [ ] Import danh bạ từ Excel
- [ ] Export báo cáo Word
- [ ] Dark mode hoạt động
- [ ] Mobile responsive

### Kiểm tra bảo mật:
- [ ] CSRF token hoạt động
- [ ] Login lockout sau 5 lần thất bại
- [ ] Session timeout sau 8 giờ
- [ ] Re-authentication cho sensitive pages
- [ ] Password policy được enforce

### Performance:
- [ ] Page load < 3 giây
- [ ] API response < 500ms
- [ ] Database query optimized

---

**Chúc bạn triển khai thành công! 🎉**
