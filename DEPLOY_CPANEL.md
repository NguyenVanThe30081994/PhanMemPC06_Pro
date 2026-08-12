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
