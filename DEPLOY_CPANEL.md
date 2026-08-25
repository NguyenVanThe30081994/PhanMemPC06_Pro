# Triển khai lên cPanel (hướng dẫn sửa lỗi pip / Flask)

## Lỗi bạn đang gặp

```bash
$ unzip -o pc06_full.zip
unzip: cannot find or open pc06_full.zip

$ python3 -m pip install -r requirements.txt
Ignoring Pillow: markers 'python_version >= "3.10"' don't match your environment
Could not find a version that satisfies the requirement Flask==3.1.3 (from versions: 0.1, ... 2.0.3)
```

**Nguyên nhân:** có 2 vấn đề, không phải lỗi mã nguồn:

1. `pc06_full.zip` **chưa được upload lên server** — gói nằm trên máy Mac của bạn
   (`~/Desktop/pc06_full.zip`). Phải tải nó lên thư mục project trước (File Manager → Upload, hoặc FTP).
2. `python3` mặc định trong SSH của cPanel rất cũ (đầu ra pip cho thấy Python **3.6**),
   trong khi ứng dụng cần **Python ≥ 3.9** (Flask 3.1, pandas 2.2 bắt buộc). Vì vậy pip
   không tìm thấy phiên bản nào phù hợp.

## Cách làm đúng

### Bước 1 — Upload gói
- File Manager → `~/domains/pc06tuyenquang.net/public_html/PhanMemPC06_Pro` → **Upload** `pc06_full.zip`.
- Hoặc dùng FTP với cùng đường dẫn.

### Bước 2 — Tìm Python đủ mới trên server
Chạy lần lượt, chọn cái cao nhất ≥ 3.9:

```bash
# Cách 1: cPanel "Setup Python App" (khuyến nghị) — nó tạo venv riêng
#   cPanel → Software → Setup Python App → Tạo app với Python 3.11/3.12
#   Nó tạo venv tại ~/virtualenv/<tên_app>/ và file passenger_wsgi.py

# Cách 2: tìm python mới có sẵn
ls /opt/cpanel/ea-python*/usr/bin/python3* 2>/dev/null
ls /usr/bin/python3.* 2>/dev/null
which python3.9 python3.10 python3.11 python3.12 2>/dev/null
```

### Bước 3 — Cài dependencies vào đúng Python
```bash
cd ~/domains/pc06tuyenquang.net/public_html/PhanMemPC06_Pro

# Giải nén (sau khi đã upload)
unzip -o pc06_full.zip

# Nếu có venv từ "Setup Python App": dùng thẳng python của nó
~/virtualenv/<tên_app>/bin/python -m pip install -r requirements.txt

# Hoặc tự tạo venv với python mới tìm được (vd python3.11)
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> ⚠️ **Không dùng** `python3 -m pip` (bản 3.6) — nó không thể cài Flask 3.1.
> Nếu server **không có** Python ≥ 3.9 nào (kể cả Setup Python App), gói shared hosting
> này không chạy được bản mới — cần nâng cấp hosting hoặc dùng VPS.

### Bước 4 — Khởi động lại
```bash
touch tmp/restart.txt
```

### Kiểm tra
```bash
# Xác nhận phiên bản Python đang chạy app (phải ≥ 3.9)
~/virtualenv/<tên_app>/bin/python --version

# Mở https://pc06tuyenquang.net/PhanMemPC06_Pro/ và kiểm tra giao diện mới
```

## Ghi chú về cơ sở dữ liệu
Gói `pc06_full.zip` **không chứa file DB** — dữ liệu production của bạn không bị ghi đè.
Khi app khởi động, nó tự chạy migration (thêm cột `outline_table_schema_json`,
`table_cells_json`...) vào DB hiện có.

---

## 🔒 CHECKLIST BẢO MẬT TRÊN HOST (bắt buộc kiểm tra 1 lần sau khi cài)

Theo `docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md`. Lần lượt xác nhận:

1. **File `.env` quyền 600** (chỉ chủ account đọc được):
   ```bash
   chmod 600 ~/domains/<domain>/public_html/PhanMemPC06_Pro/.env
   ```
2. **Biến môi trường production** trong `.env`:
   ```
   FLASK_ENV=production        # bật SESSION_COOKIE_SECURE + ép HTTPS (PC06_FORCE_HTTPS)
   DEBUG=False
   SECRET_KEY=<chuỗi ngẫu nhiên riêng>  # python3 -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
3. **`DATABASE_URL` trỏ MySQL host-local**, không SQLite:
   ```
   DATABASE_URL=mysql://<user_cpanel>_<dbuser>:<mật_khẩu>@localhost/<user_cpanel>_dbname
   ```
4. **Dữ liệu mutable ngoài public_html** — tránh lộ qua web và khỏi bị xóa nhầm khi deploy lại:
   ```
   PC06_DATA_DIR=/home/<cpanel_user>/pc06_data
   ```
5. **Ghim Google OAuth redirect URI** (nếu dùng đăng nhập Google):
   ```
   GOOGLE_OAUTH_REDIRECT_URI=https://<domain>/auth/google/callback
   ```
   Đồng thời khai báo đúng URL này trong Google Cloud Console → Credentials.
6. **HTTPS**: bật AutoSSL/Let's Encrypt cho domain TRƯỚC khi đặt `FLASK_ENV=production`
   (app sẽ redirect 308 http→https). Kiểm tra: mở `http://<domain>` phải nhảy sang https.
7. **ModSecurity** (B6'): cPanel → Security → ModSecurity → bật cho domain.
   Chạy vài ngày ở chế độ ghi nhận nếu hosting hỗ trợ, rồi chuyển sang chặn.
8. **Số process Passenger** (B5'): giữ 1–2 process để deadline watchdog nền
   (APScheduler) không nhân bản job. Nếu buộc chạy nhiều process, đặt
   `PC06_TASK_SCHEDULER=0` cho các bản sao phụ.

## 💾 BACKUP DATABASE HẰNG ĐÊM (cron cPanel)

Không dùng nút backup trong web làm phương án chính. Dùng cron:

1. Tạo `~/.my.cnf` quyền 600 chứa thông tin MySQL (để cron không lộ mật khẩu):
   ```ini
   [client]
   host=localhost
   user=<user_cpanel>_<dbuser>
   password=<mật_khẩu>
   ```
2. Thêm cron (cPanel → Advanced → Cron Jobs), 02:30 mỗi đêm:
   ```
   30 2 * * * /home/<cpanel_user>/public_html/PhanMemPC06_Pro/scripts/admin/backup_mysql.sh >> /home/<cpanel_user>/pc06_backups/backup.log 2>&1
   ```
   Script lưu `~/pc06_backups/<db>_<thời_điểm>.sql.gz`, **giữ 14 ngày**
   (đổi bằng biến `RETENTION_DAYS`).
3. **Quy trình thử khôi phục — thực hiện 1 quý/lần**:
   ```bash
   # Tạo DB rỗng mới rồi import thử, so sánh số bảng/dòng với DB thật
   gunzip < ~/pc06_backups/<db>_<stamp>.sql.gz | mysql --host=localhost -u <user> -p <tên_db_thử>
   ```

## 🛡️ PHÒNG THỦ SÂU TRÊN WEB SERVER

File `.htaccess` trong thư mục app đã chặn sẵn (không cần cấu hình thêm):
- Ép HTTPS ở tầng Apache (308) song song với app-level `PC06_FORCE_HTTPS`.
- Deny tệp nhạy cảm mọi cấp thư mục: `.env*`, `.git*`, `*.db/*.sqlite`,
  `*.sql`, `*.bat`, `*.sh`, `*.pyc`, `passenger_wsgi.py`, `requirements.txt`.
- Deny (403) các thư mục `backups/ logs/ tmp/ scripts/ tests/ docs/` — pattern
  tương đối nên khớp cả khi app ở domain root lẫn thư mục con.

Sau mỗi lần deploy: mở thử trang chủ + một URL trong `/static/...` để chắc chắn
trang vẫn chạy bình thường, rồi thử truy cập `/.env` phải nhận 403/404.
