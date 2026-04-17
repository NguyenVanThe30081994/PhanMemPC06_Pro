# Phiên bản đóng gói offline PhanMemPC06_Pro

## Hướng dẫn sử dụng

### 1. Chạy ứng dụng

**Cách 1:** Double-click vào file `RUN_SERVER.bat`

**Cách 2:** Double-click trực tiếp vào `PhanMemPC06_Server.exe`

### 2. Truy cập ứng dụng

Mở trình duyệt web và truy cập:
- **Local:** http://localhost:5000
- **Network:** http://<IP_may>:5000

### 3. Đăng nhập

Tài khoản mặc định:
- **Username:** admin
- **Password:** admin123

> [!IMPORTANT]
> Vui lòng đổi password sau khi đăng nhập lần đầu!

### 4. Cấu trúc thư mục

```
offline_package/
├── PhanMemPC06_Server.exe    # Server executable
├── RUN_SERVER.bat            # Script chạy server
├── pc06_system.db            # Database SQLite
├── uploads/                  # Thư mục upload files
├── backups/                  # Thư mục backup
├── logs/                     # Thư mục logs
├── task_files/               # Thư mục task files
├── library_files/            # Thư mục thư viện
└── tmp/                      # Thư mục tạm
```

### 5. Tính năng

- ✅ Hoạt động 100% offline
- ✅ Database SQLite tự động tạo
- ✅ Backup dữ liệu tự động
- ✅ Upload/Download files
- ✅ Báo cáo Excel
- ✅ Quản lý người dùng
- ✅ Phân quyền người dùng

### 6. Lưu ý

- Dữ liệu được lưu trong thư mục của ứng dụng
- Di chuyển thư mục = di chuyển toàn bộ dữ liệu
- Nên sao lưu thư mục `backups` định kỳ
- Tắt server bằng phím `Ctrl+C` trong cửa sổ console

### 7. Yêu cầu hệ thống

- Windows 7/8/10/11
- Không cần cài đặt Python
- Không cần kết nối Internet
- Ram tối thiểu: 2GB
- Dung lượng ổ cứng: ~500MB

---

**Phiên bản:** 3.5.0
**Liên hệ hỗ trợ:** Người phát triển
