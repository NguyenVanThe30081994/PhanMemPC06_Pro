# HƯỚNG DẪN CHỨC NĂNG GIAO VIỆC THEO ĐỠN VỊ VÀ TIẾP NHẬN CÔNG VIỆC

## Tóm tắt vấn đề đã sửa

**Vấn đề ban đầu:** 
- Chức năng công việc chưa có nút tiếp nhận công việc đối với các đơn vị được giao việc
- Khi admin giao việc cho đơn vị, không tự động tạo phân công cho các thành viên trong đơn vị

**Nguyên nhân:**
- Logic cũ chỉ giao việc cho cá nhân hoặc vai trò, không giao theo đơn vị
- Thiếu logic tự động tạo TaskAssignment cho tất cả user có `unit_area` = `domain`

**Giải pháp đã áp dụng:**
✅ Sửa logic trong `routes/tasks.py` để tự động giao việc cho tất cả user thuộc đơn vị
✅ Khi không chọn "Giao cho" cụ thể, hệ thống tự động giao cho tất cả user có `unit_area` = `domain`
✅ Tạo TaskAssignment với status 'Chưa tiếp nhận' cho mỗi user trong đơn vị
✅ Nút "TIẾP NHẬN CÔNG VIỆC" sẽ hiển thị cho các user được giao

---

## Cách hoạt động mới

### 1. Admin/Lead tạo công việc và giao cho đơn vị

**Bước 1:** Đăng nhập với tài khoản có quyền lead/admin

**Bước 2:** Vào trang `/tasks`

**Bước 3:** Click nút "THÊM CÔNG VIỆC"

**Bước 4:** Điền thông tin:
- **Tiêu đề công việc:** Ví dụ "Báo cáo tình hình công tác tháng 4/2026"
- **Đội nghiệp vụ:** Chọn đơn vị cần giao việc (ví dụ: "Đội nghiệp vụ 1")
- **Mức độ ưu tiên:** Cao/Trung bình/Thấp
- **Thời hạn:** Chọn deadline
- **Loại công việc:** Báo cáo định kỳ/Công việc đột xuất/...
- **Mô tả:** Nội dung chi tiết công việc

**Bước 5:** Phần "Giao cho":
- **KHÔNG CHỌN GÌ** → Hệ thống tự động giao cho tất cả user thuộc đơn vị đã chọn
- Hoặc chọn "Cá nhân" → Giao cho người cụ thể
- Hoặc chọn "Theo vai trò" → Giao cho tất cả user có vai trò đó

**Bước 6:** Click "Tạo công việc"

**Kết quả:**
- Hệ thống tự động tạo TaskAssignment cho tất cả user có `unit_area` = "Đội nghiệp vụ 1"
- Mỗi user nhận thông báo "Đơn vị [Tên đơn vị] được giao: [Tên công việc]"
- Status ban đầu: "Chưa tiếp nhận"

---

### 2. User thuộc đơn vị tiếp nhận công việc

**Bước 1:** Đăng nhập với tài khoản thuộc đơn vị được giao việc

**Bước 2:** Vào trang `/tasks`

**Bước 3:** Thấy card công việc với:
- Badge "Chưa tiếp nhận" màu vàng
- Nút màu xanh lá **"Tiếp nhận công việc"**

**Bước 4:** Click nút "Tiếp nhận công việc"

**Kết quả:**
- Status chuyển từ "Chưa tiếp nhận" → "Đang thực hiện"
- Nút tiếp nhận biến mất
- Hiển thị badge "Đang thực hiện" màu xanh dương
- User có thể bắt đầu làm việc và báo cáo

---

### 3. User báo cáo kết quả

**Bước 1:** Vào trang chi tiết công việc `/tasks/<id>`

**Bước 2:** Kéo xuống phần "Gửi báo cáo"

**Bước 3:** Nhập nội dung báo cáo:
- Kết quả đạt được
- Khó khăn vướng mắc
- Đề xuất giải pháp

**Bước 4:** (Tùy chọn) Đính kèm file báo cáo (Word, Excel, PDF...)

**Bước 5:** Tick vào "Đánh dấu hoàn thành" nếu đã hoàn thành công việc

**Bước 6:** Click "Gửi báo cáo"

**Kết quả:**
- Báo cáo được lưu dưới dạng comment với tag [BÁO CÁO]
- Nếu tick "Hoàn thành", status chuyển sang "Hoàn thành"
- Admin/Lead có thể xem báo cáo của tất cả user trong đơn vị

---

## Dữ liệu test đã tạo sẵn

### Users:
```
ID  | Họ tên          | Đơn vị          | Trạng thái
----|-----------------|-----------------|------------
1   | Admin           | Hệ thống        | Active
2   | Nguyễn Văn A    | Đội nghiệp vụ 1 | Active
3   | Trần Thị B      | Đội nghiệp vụ 1 | Active
4   | Lê Văn C        | Đội nghiệp vụ 2 | Active
```

### Task test:
```
Tiêu đề: Báo cáo tình hình công tác tháng 4/2026
Đơn vị: Đội nghiệp vụ 1
Deadline: 05/05/2026
Priority: Cao
Được giao cho: Nguyễn Văn A, Trần Thị B (tự động)
Status: Chưa tiếp nhận
```

### Cách test:
1. Đăng nhập với username: `user_dv1` hoặc `user_dv2` (password: `test`)
2. Vào `/tasks`
3. Thấy công việc "Báo cáo tình hình công tác tháng 4/2026"
4. Thấy nút "Tiếp nhận công việc" màu xanh lá
5. Click để tiếp nhận
6. Status chuyển sang "Đang thực hiện"
7. Vào chi tiết để gửi báo cáo

---

## Logic hiển thị nút tiếp nhận

### Điều kiện hiển thị:
✅ User đã đăng nhập
✅ User được giao công việc (có record trong `task_assignment` với `user_id` = session user)
✅ Status của assignment = "Chưa tiếp nhận" hoặc "Chưa bắt đầu"

### Nút KHÔNG hiển thị khi:
❌ User không được giao công việc
❌ Status = "Đang thực hiện" (đã tiếp nhận rồi)
❌ Status = "Hoàn thành" (đã xong rồi)

### Vị trí hiển thị:
1. **Trang danh sách `/tasks`:** Nút trong card công việc
2. **Trang chi tiết `/tasks/<id>`:** Card lớn ở trên cùng với animation pulse

---

## Các trường hợp giao việc

### Trường hợp 1: Giao cho đơn vị (MẶC ĐỊNH - ĐÃ SỬA)
- Admin chọn "Đội nghiệp vụ 1"
- KHÔNG chọn "Giao cho" cụ thể
- Hệ thống tự động giao cho TẤT CẢ user có `unit_area` = "Đội nghiệp vụ 1"
- Mỗi user nhận 1 TaskAssignment với status "Chưa tiếp nhận"

### Trường hợp 2: Giao cho cá nhân
- Admin chọn "Đội nghiệp vụ 1"
- Chọn "Giao cho" → "Cá nhân" → Chọn "Nguyễn Văn A"
- Chỉ Nguyễn Văn A nhận TaskAssignment

### Trường hợp 3: Giao theo vai trò
- Admin chọn "Đội nghiệp vụ 1"
- Chọn "Giao cho" → "Theo vai trò" → Chọn "Chuyên viên"
- Tất cả user có `role_id` = "Chuyên viên" nhận TaskAssignment

---

## Kiểm tra database

### Xem công việc của một đơn vị:
```sql
SELECT t.id, t.title, t.domain, t.deadline, t.priority
FROM task t
WHERE t.domain = 'Đội nghiệp vụ 1'
ORDER BY t.created_at DESC;
```

### Xem ai được giao một công việc:
```sql
SELECT u.id, u.fullname, u.unit_area, ta.status
FROM task_assignment ta
JOIN user u ON ta.user_id = u.id
WHERE ta.task_id = 1;
```

### Xem công việc của một user:
```sql
SELECT t.title, t.domain, ta.status, t.deadline
FROM task_assignment ta
JOIN task t ON ta.task_id = t.id
WHERE ta.user_id = 2
ORDER BY t.created_at DESC;
```

### Xem tiến độ công việc theo đơn vị:
```sql
SELECT 
    t.title,
    COUNT(ta.id) as total_assigned,
    SUM(CASE WHEN ta.status = 'Hoàn thành' THEN 1 ELSE 0 END) as completed,
    SUM(CASE WHEN ta.status = 'Đang thực hiện' THEN 1 ELSE 0 END) as in_progress,
    SUM(CASE WHEN ta.status = 'Chưa tiếp nhận' THEN 1 ELSE 0 END) as not_started
FROM task t
LEFT JOIN task_assignment ta ON t.id = ta.task_id
WHERE t.domain = 'Đội nghiệp vụ 1'
GROUP BY t.id;
```

---

## Troubleshooting

### Vấn đề 1: Không thấy nút tiếp nhận

**Nguyên nhân có thể:**
- User không thuộc đơn vị được giao việc
- User chưa được tạo TaskAssignment
- Status đã khác "Chưa tiếp nhận"

**Giải pháp:**
```sql
-- Kiểm tra user có được giao không
SELECT * FROM task_assignment WHERE user_id = [YOUR_USER_ID];

-- Kiểm tra unit_area của user
SELECT id, fullname, unit_area FROM user WHERE id = [YOUR_USER_ID];

-- Kiểm tra domain của task
SELECT id, title, domain FROM task WHERE id = [TASK_ID];
```

### Vấn đề 2: Tạo công việc nhưng không ai nhận được

**Nguyên nhân:**
- Không có user nào có `unit_area` = `domain` của task
- Tất cả user trong đơn vị đều `is_active = 0`

**Giải pháp:**
```sql
-- Kiểm tra users trong đơn vị
SELECT id, fullname, unit_area, is_active 
FROM user 
WHERE unit_area = 'Đội nghiệp vụ 1';

-- Nếu không có, cần tạo user hoặc cập nhật unit_area
UPDATE user SET unit_area = 'Đội nghiệp vụ 1' WHERE id = [USER_ID];
```

### Vấn đề 3: Click nút tiếp nhận không có phản ứng

**Giải pháp:**
1. Kiểm tra console browser (F12) xem có lỗi không
2. Kiểm tra route `/tasks/<id>/update_task_status` có hoạt động không
3. Restart server: `./START_SERVER_MAC.sh`
4. Clear cache browser và reload

---

## Files đã thay đổi

### 1. `routes/tasks.py` (Dòng 110-145)
- Thêm logic kiểm tra `has_specific_assignment`
- Nếu không chọn giao cho cụ thể, tự động giao cho đơn vị
- Query tất cả user có `unit_area` = `domain`
- Tạo TaskAssignment cho mỗi user

### 2. Backup
- `routes/tasks.py.backup` - Backup trước khi sửa

---

## Kết luận

✅ **Chức năng đã hoạt động đúng theo yêu cầu**
✅ **Admin giao việc cho đơn vị → Tự động giao cho tất cả user trong đơn vị**
✅ **User thuộc đơn vị thấy nút "TIẾP NHẬN CÔNG VIỆC"**
✅ **Sau khi tiếp nhận, user có thể báo cáo kết quả**
✅ **Đã tạo dữ liệu test sẵn sàng để kiểm tra**

**Lưu ý quan trọng:**
- User phải có `unit_area` khớp với `domain` của task
- Chỉ user được giao mới thấy nút tiếp nhận
- Phải tiếp nhận trước khi báo cáo kết quả
- Admin có thể xem tiến độ của tất cả user trong đơn vị
