# THIẾT KẾ LẠI HỆ THỐNG PHÂN QUYỀN PC06
**Ngày:** 06/08/2026  
**Phiên bản:** 4.0.0  
**Trạng thái:** Draft - Đang thiết kế

---

## 📊 PHÂN TÍCH CẤU TRÚC TỔ CHỨC

### Cấu trúc hiện tại (Công an Tỉnh - Công an Xã)

```
┌─────────────────────────────────────────────────┐
│           QUẢN TRỊ HỆ THỐNG (Root/Admin)        │
│   - Toàn quyền hệ thống                         │
│   - Cấu hình, backup, quản lý người dùng        │
└─────────────────────────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        │                           │
┌───────▼──────────┐       ┌────────▼─────────┐
│   CẤP TỈNH (CAT) │       │  CẤP XÃ (CAX)    │
└──────────────────┘       └──────────────────┘
        │                           │
  ┌─────┴─────┐              ┌─────┴─────┐
  │           │              │           │
┌─▼─────┐ ┌──▼──────┐   ┌───▼────┐ ┌───▼────┐
│Lãnh đạo│ │Cán bộ   │   │Chỉ huy│ │Cán bộ  │
│Chỉ huy │ │nghiệp vụ│   │        │ │        │
└────────┘ └─────────┘   └────────┘ └────────┘
```

---

## 🎯 VAI TRÒ VÀ QUYỀN HẠN MỚI

### 1. **QUẢN TRỊ HỆ THỐNG** (Administrator)
**Mô tả:** Quản trị viên cao nhất, toàn quyền hệ thống

**Quyền hạn:**
- ✅ **Quản lý hệ thống:** Cấu hình, backup, restore, update
- ✅ **Quản lý người dùng:** Tạo, sửa, xóa tài khoản, phân quyền
- ✅ **Quản lý vai trò:** Tạo, sửa vai trò và quyền
- ✅ **Quản lý danh mục:** Thiết lập đơn vị, đội nghiệp vụ
- ✅ **Xem nhật ký:** Truy cập đầy đủ system logs
- ✅ **Công việc:** Tạo, giao, sửa, xóa mọi công việc
- ✅ **Thông báo:** Tạo, sửa, xóa thông báo
- ✅ **Danh bạ:** Quản lý đầy đủ
- ✅ **QR & Links:** Quản lý đầy đủ

**Đặc quyền:**
- Bypass mọi kiểm tra phân quyền
- Xem tất cả dữ liệu
- Không bị giới hạn bởi đơn vị

---

### 2. **CÁN BỘ CAT** (CAT Officer)
**Mô tả:** Cán bộ nghiệp vụ cấp Tỉnh - Người điều hành và giao việc

**Quyền hạn:**
- ✅ **Công việc:**
  - **Tạo mới:** Tạo công việc mới (3 loại: FORM, OUTLINE, FILE)
  - **Giao việc:** Giao việc cho CAX
  - **Theo dõi:** Xem tiến độ của tất cả công việc đã giao
  - **Sửa:** Sửa công việc do mình tạo (trước khi giao)
  - **Xóa:** Xóa công việc do mình tạo (nếu chưa có ai báo cáo)
  - **Export:** Xuất báo cáo Word tổng hợp
  - **Ma trận:** Xem ma trận tiến độ đầy đủ
  
- ✅ **Thông báo:**
  - **Đăng:** Tạo thông báo mới
  - **Sửa/Xóa:** Thông báo do mình đăng
  - **Upload:** File đính kèm, video
  
- ✅ **Danh bạ:**
  - **Xem:** Toàn bộ danh bạ
  - **Thêm/Sửa/Xóa:** Quản lý danh bạ
  - **Import/Export:** Excel
  
- ✅ **QR & Links:**
  - **Tạo:** QR code và short link
  - **Quản lý:** Sửa, xóa link do mình tạo

**Giới hạn:**
- ❌ Không truy cập quản trị hệ thống
- ❌ Không sửa/xóa dữ liệu của người khác
- ❌ Không xem logs hệ thống

---

### 3. **LÃNH ĐẠO - CHỈ HUY CAT** (CAT Commander)
**Mô tả:** Lãnh đạo cấp Tỉnh - Giám sát và chỉ đạo

**Quyền hạn:**
- ✅ **Công việc:**
  - **Xem:** Tất cả công việc (read-only)
  - **Ma trận:** Xem tiến độ tổng thể
  - **Dashboard:** Xem thống kê, báo cáo
  - **Export:** Xuất báo cáo
  
- ✅ **Thông báo:**
  - **Đăng:** Tạo thông báo chỉ đạo
  - **Sửa/Xóa:** Thông báo do mình đăng
  
- ✅ **Danh bạ:**
  - **Xem:** Toàn bộ danh bạ
  - **Tìm kiếm:** Search, filter
  
- ✅ **QR & Links:**
  - **Xem:** Tất cả links
  - **Tạo:** Tạo link mới nếu cần

**Giới hạn:**
- ❌ Không tạo/giao công việc (chỉ xem)
- ❌ Không sửa/xóa công việc
- ❌ Không quản lý danh bạ (chỉ xem)

**Lý do:** Lãnh đạo cần nắm bắt tình hình nhưng không trực tiếp điều hành

---

### 4. **CÁN BỘ CAX** (CAX Officer)
**Mô tả:** Cán bộ cấp Xã/Phường - Người thực hiện và báo cáo

**Quyền hạn:**
- ✅ **Công việc:**
  - **Xem:** Công việc được giao cho đơn vị mình
  - **Tiếp nhận:** Nhận việc
  - **Báo cáo:** Nộp báo cáo, upload file
  - **Cập nhật:** Cập nhật tiến độ
  
- ✅ **Thông báo:**
  - **Xem:** Đọc thông báo
  - **Download:** Tải file đính kèm
  
- ✅ **Danh bạ:**
  - **Xem:** Tra cứu danh bạ
  - **Tìm kiếm:** Search theo tên, đơn vị
  
- ✅ **QR & Links:**
  - **Xem:** Xem links công khai
  - **Quét:** Quét QR code

**Giới hạn:**
- ❌ Không tạo/giao công việc
- ❌ Không xem công việc của đơn vị khác
- ❌ Không đăng thông báo
- ❌ Không quản lý danh bạ

**Lý do:** CAX chỉ thực hiện nhiệm vụ được giao, không điều hành

---

### 5. **CHỈ HUY CAX** (CAX Commander)
**Mô tả:** Chỉ huy cấp Xã/Phường - Giám sát đơn vị

**Quyền hạn:**
- ✅ **Công việc:**
  - **Xem:** Công việc của đơn vị mình
  - **Phân công:** Phân công cho cán bộ trong đơn vị
  - **Giám sát:** Xem tiến độ cán bộ
  - **Duyệt:** Duyệt báo cáo trước khi nộp lên CAT (tùy chọn)
  
- ✅ **Thông báo:**
  - **Xem:** Đọc thông báo
  - **Download:** Tải file
  
- ✅ **Danh bạ:**
  - **Xem:** Tra cứu danh bạ đầy đủ
  - **Export:** Xuất danh bạ (nếu cần)
  
- ✅ **QR & Links:**
  - **Xem:** Xem links
  - **Tạo:** Tạo link cho đơn vị (nếu cần)

**Giới hạn:**
- ❌ Không tạo công việc mới (chỉ CAT tạo)
- ❌ Không xem công việc của đơn vị khác
- ❌ Không đăng thông báo hệ thống

**Lý do:** Chỉ huy CAX điều phối nội bộ đơn vị, không ra ngoài phạm vi

---

## 📋 MA TRẬN PHÂN QUYỀN CHI TIẾT

### Module: **Công việc (Tasks)**

| Chức năng | Quản trị | Cán bộ CAT | Lãnh đạo CAT | Cán bộ CAX | Chỉ huy CAX |
|-----------|----------|------------|--------------|------------|-------------|
| **Xem danh sách** | ✅ Tất cả | ✅ Tất cả | ✅ Tất cả | ✅ Của đơn vị | ✅ Của đơn vị |
| **Xem chi tiết** | ✅ | ✅ | ✅ | ✅ Được giao | ✅ Được giao |
| **Tạo mới** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Sửa** | ✅ Tất cả | ✅ Do mình tạo | ❌ | ❌ | ❌ |
| **Xóa** | ✅ Tất cả | ✅ Do mình tạo | ❌ | ❌ | ❌ |
| **Giao việc** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Tiếp nhận** | - | - | - | ✅ | ✅ |
| **Báo cáo** | - | - | - | ✅ | ✅ |
| **Phân công nội bộ** | ✅ | ✅ | ❌ | ❌ | ✅ |
| **Xem ma trận** | ✅ Toàn bộ | ✅ Toàn bộ | ✅ Toàn bộ | ✅ Của mình | ✅ Của đơn vị |
| **Export Word** | ✅ | ✅ | ✅ | ❌ | ✅ |
| **Import Excel** | ✅ | ✅ | ❌ | ❌ | ❌ |

---

### Module: **Thông báo (Notifications)**

| Chức năng | Quản trị | Cán bộ CAT | Lãnh đạo CAT | Cán bộ CAX | Chỉ huy CAX |
|-----------|----------|------------|--------------|------------|-------------|
| **Xem** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Đăng mới** | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Sửa** | ✅ Tất cả | ✅ Do mình đăng | ✅ Do mình đăng | ❌ | ❌ |
| **Xóa** | ✅ Tất cả | ✅ Do mình đăng | ✅ Do mình đăng | ❌ | ❌ |
| **Upload file** | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Phân loại** | ✅ | ✅ | ✅ | - | - |

---

### Module: **Danh bạ (Contacts)**

| Chức năng | Quản trị | Cán bộ CAT | Lãnh đạo CAT | Cán bộ CAX | Chỉ huy CAX |
|-----------|----------|------------|--------------|------------|-------------|
| **Xem** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Thêm** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Sửa** | ✅ Tất cả | ✅ Tất cả | ❌ | ❌ | ❌ |
| **Xóa** | ✅ Tất cả | ✅ Tất cả | ❌ | ❌ | ❌ |
| **Import Excel** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Export Excel** | ✅ | ✅ | ✅ | ❌ | ✅ |
| **Tìm kiếm** | ✅ | ✅ | ✅ | ✅ | ✅ |

---

### Module: **QR & Links (Shortlinks)**

| Chức năng | Quản trị | Cán bộ CAT | Lãnh đạo CAT | Cán bộ CAX | Chỉ huy CAX |
|-----------|----------|------------|--------------|------------|-------------|
| **Xem** | ✅ Tất cả | ✅ Tất cả | ✅ Tất cả | ✅ Công khai | ✅ Công khai |
| **Tạo mới** | ✅ | ✅ | ✅ | ❌ | ✅ |
| **Sửa** | ✅ Tất cả | ✅ Do mình tạo | ✅ Do mình tạo | ❌ | ✅ Do mình tạo |
| **Xóa** | ✅ Tất cả | ✅ Do mình tạo | ✅ Do mình tạo | ❌ | ✅ Do mình tạo |
| **Tạo QR** | ✅ | ✅ | ✅ | ❌ | ✅ |

---

### Module: **Hệ thống (System)**

| Chức năng | Quản trị | Cán bộ CAT | Lãnh đạo CAT | Cán bộ CAX | Chỉ huy CAX |
|-----------|----------|------------|--------------|------------|-------------|
| **Quản lý người dùng** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Quản lý vai trò** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Quản lý danh mục** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Xem logs** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Backup/Restore** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Cập nhật hệ thống** | ✅ | ❌ | ❌ | ❌ | ❌ |

---

## 🔧 CẤU TRÚC DATABASE MỚI

### Bảng: `app_roles` (Vai trò)

```sql
CREATE TABLE app_roles (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    code VARCHAR(50) NOT NULL UNIQUE,  -- 'admin', 'cat_officer', 'cat_commander', 'cax_officer', 'cax_commander'
    level VARCHAR(20),  -- 'system', 'cat', 'cax'
    description TEXT,
    perms TEXT,  -- JSON ma trận quyền
    is_system BOOLEAN DEFAULT 0,  -- Vai trò hệ thống không cho xóa
    created_at DATETIME,
    updated_at DATETIME
);
```

### Seed data mặc định:

```sql
-- 1. Quản trị hệ thống
INSERT INTO app_roles (name, code, level, description, is_system, perms) VALUES (
    'Quản trị hệ thống',
    'admin',
    'system',
    'Quản trị viên cao nhất, toàn quyền hệ thống',
    1,
    '{"task": {"view": true, "process": true, "exec": true}, "notify": {"view": true, "process": true}, "contact": {"view": true, "process": true}, "user": {"view": true, "process": true}, "sys": {"view": true, "process": true}}'
);

-- 2. Cán bộ CAT
INSERT INTO app_roles (name, code, level, description, is_system, perms) VALUES (
    'Cán bộ CAT',
    'cat_officer',
    'cat',
    'Cán bộ nghiệp vụ cấp Tỉnh - Giao việc và điều hành',
    1,
    '{"task": {"view": true, "process": true, "exec": false}, "notify": {"view": true, "process": true}, "contact": {"view": true, "process": true}, "user": {"view": false, "process": false}, "sys": {"view": false, "process": false}}'
);

-- 3. Lãnh đạo - Chỉ huy CAT
INSERT INTO app_roles (name, code, level, description, is_system, perms) VALUES (
    'Lãnh đạo - Chỉ huy CAT',
    'cat_commander',
    'cat',
    'Lãnh đạo cấp Tỉnh - Giám sát và chỉ đạo',
    1,
    '{"task": {"view": true, "process": false, "exec": false}, "notify": {"view": true, "process": true}, "contact": {"view": true, "process": false}, "user": {"view": false, "process": false}, "sys": {"view": false, "process": false}}'
);

-- 4. Cán bộ CAX
INSERT INTO app_roles (name, code, level, description, is_system, perms) VALUES (
    'Cán bộ CAX',
    'cax_officer',
    'cax',
    'Cán bộ cấp Xã - Thực hiện và báo cáo',
    1,
    '{"task": {"view": true, "process": false, "exec": true}, "notify": {"view": true, "process": false}, "contact": {"view": true, "process": false}, "user": {"view": false, "process": false}, "sys": {"view": false, "process": false}}'
);

-- 5. Chỉ huy CAX
INSERT INTO app_roles (name, code, level, description, is_system, perms) VALUES (
    'Chỉ huy CAX',
    'cax_commander',
    'cax',
    'Chỉ huy cấp Xã - Giám sát đơn vị',
    1,
    '{"task": {"view": true, "process": false, "exec": true}, "notify": {"view": true, "process": false}, "contact": {"view": true, "process": false}, "user": {"view": false, "process": false}, "sys": {"view": false, "process": false}}'
);
```

---

## 📊 GIẢI THÍCH MA TRẬN QUYỀN

### Các cấp độ quyền (Permission Tiers):

1. **`view`** - Xem/Đọc
   - Xem danh sách, chi tiết
   - Tìm kiếm, lọc
   - Export (nếu được phép)

2. **`process`** - Xử lý/Quản lý
   - Tạo mới
   - Sửa (của mình hoặc tất cả)
   - Xóa (của mình hoặc tất cả)
   - Giao việc, phân công

3. **`exec`** - Thực thi/Báo cáo
   - Tiếp nhận công việc
   - Nộp báo cáo
   - Cập nhật tiến độ
   - Upload file kết quả

### Ví dụ:
- **Cán bộ CAT:** `task.view=true, task.process=true, task.exec=false`
  - ✅ Xem tất cả công việc
  - ✅ Tạo, sửa, xóa công việc
  - ❌ Không báo cáo (vì họ giao việc, không làm)

- **Cán bộ CAX:** `task.view=true, task.process=false, task.exec=true`
  - ✅ Xem công việc được giao
  - ❌ Không tạo/sửa/xóa
  - ✅ Báo cáo, nộp kết quả

---

## 🎨 CẢI TIẾN GIAO DIỆN

### 1. Trang danh sách công việc (tasks_rebuild.html)

**Cũ:** Hiển thị nhiều section rối mắt  
**Mới:** Tabs gọn gàng, focus vào việc cần làm

```
[Header Bar]
  - Stats compact: 4 chỉ số ngắn gọn
  - Actions: Nút tạo việc (chỉ CAT Officer)

[Tabs]
  ├─ Cần xử lý ngay (badge đỏ)
  ├─ Việc của tôi (badge xanh)
  ├─ Tôi giao (badge vàng) - Chỉ CAT
  └─ Chỉ xem (badge xám) - Nếu có

[Task Cards]
  - Card gọn, highlight status
  - Click vào → Chi tiết
```

### 2. Menu sidebar

**Cải tiến:**
- Animation mượt mà (không giật lag)
- Transition 300ms với easing
- Mở/đóng smooth
- Lưu trạng thái vào localStorage

### 3. Trang chi tiết công việc

**Theo vai trò:**
- **CAT Officer:** Hiển thị nút Sửa/Xóa
- **CAT Commander:** Chỉ xem, không có nút action
- **CAX Officer/Commander:** Hiển thị form báo cáo

---

## 📝 TRIỂN KHAI

### Bước 1: Update database
```bash
python3 migrate_roles_v4.py
```

### Bước 2: Update code logic
- `utils.py`: Cập nhật helper functions
- `task_policies.py`: Logic phân quyền chi tiết
- `routes/tasks.py`: Check permissions

### Bước 3: Update templates
- `tasks_rebuild.html`: Layout mới với tabs
- `task_detail_rebuild.html`: Hiển thị buttons theo role
- `base.html`: Smooth animations

### Bước 4: Testing
- Test từng vai trò
- Verify permissions
- Check UI/UX

---

## ✅ CHECKLIST

- [ ] Thiết kế database schema
- [ ] Tạo migration script
- [ ] Cập nhật seed data
- [ ] Sửa helper functions
- [ ] Cập nhật task policies
- [ ] Sửa routes logic
- [ ] Cập nhật templates
- [ ] Fix menu animations
- [ ] Testing đầy đủ
- [ ] Viết tài liệu hướng dẫn

---

**Kết luận:** Hệ thống phân quyền mới rõ ràng, logic, phù hợp với cơ cấu tổ chức thực tế CAT/CAX.
