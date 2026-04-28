# HƯỚNG DẪN SỬ DỤNG NÚT TIẾP NHẬN CÔNG VIỆC

## Tóm tắt vấn đề

**Vấn đề:** Chức năng công việc chưa có nút tiếp nhận công việc đối với các đơn vị được giao việc.

**Nguyên nhân:** Database chưa có công việc nào được tạo và phân công. Code đã được implement đầy đủ.

**Giải pháp:** Đã tạo dữ liệu mẫu và xác nhận chức năng hoạt động đúng.

---

## Cách hoạt động của chức năng

### 1. Tạo công việc và giao việc (Dành cho Lead/Admin)

**Bước 1:** Vào trang `/tasks`

**Bước 2:** Click nút "THÊM CÔNG VIỆC"

**Bước 3:** Điền thông tin công việc:
- Tiêu đề công việc
- Đội nghiệp vụ
- Mức độ ưu tiên
- Thời hạn
- Loại công việc
- Mô tả công việc

**Bước 4:** Chọn cách giao việc:
- **Giao cho cá nhân:** Chọn người cụ thể từ danh sách
- **Giao theo vai trò:** Chọn vai trò → Tất cả user có vai trò đó sẽ nhận việc

**Bước 5:** Click "Tạo công việc"

### 2. Tiếp nhận công việc (Dành cho người được giao)

**Cách 1: Từ trang danh sách `/tasks`**

1. Đăng nhập với tài khoản được giao việc
2. Vào trang `/tasks`
3. Tìm card công việc được giao
4. Thấy nút màu xanh lá **"Tiếp nhận công việc"**
5. Click nút để tiếp nhận

**Cách 2: Từ trang chi tiết `/tasks/<id>`**

1. Click "Xem chi tiết" trên card công việc
2. Thấy card lớn ở trên cùng với gradient tím
3. Thấy nút to **"TIẾP NHẬN CÔNG VIỆC"** (có animation pulse)
4. Click nút để tiếp nhận

**Sau khi tiếp nhận:**
- Status chuyển từ "Chưa tiếp nhận" → "Đang thực hiện"
- Nút tiếp nhận biến mất
- Hiển thị badge "Đang thực hiện" màu xanh dương
- Có thể bắt đầu làm việc và gửi báo cáo

### 3. Gửi báo cáo và hoàn thành

**Bước 1:** Vào trang chi tiết công việc `/tasks/<id>`

**Bước 2:** Kéo xuống phần "Gửi báo cáo"

**Bước 3:** Nhập nội dung báo cáo

**Bước 4:** (Tùy chọn) Đính kèm file báo cáo

**Bước 5:** Tick vào "Đánh dấu hoàn thành" nếu đã xong

**Bước 6:** Click "Gửi báo cáo"

---

## Điều kiện hiển thị nút tiếp nhận

Nút "TIẾP NHẬN CÔNG VIỆC" chỉ hiển thị khi:

✅ User đã đăng nhập
✅ User được giao công việc (có record trong `task_assignment`)
✅ Status của assignment = "Chưa tiếp nhận" hoặc "Chưa bắt đầu"

Nút sẽ KHÔNG hiển thị khi:
❌ User không được giao công việc
❌ Status = "Đang thực hiện" (đã tiếp nhận rồi)
❌ Status = "Hoàn thành" (đã xong rồi)

---

## Dữ liệu test đã tạo sẵn

Để test chức năng, đã tạo sẵn:

```
Công việc: "Công việc test - Kiểm tra nút tiếp nhận"
- Domain: Đội nghiệp vụ 1
- Deadline: 15/05/2026
- Priority: Cao
- Được giao cho: User ID 1 (Tài khoản quản trị)
- Status: Chưa tiếp nhận
```

**Cách test:**
1. Đăng nhập với tài khoản admin (user ID 1)
2. Vào `/tasks`
3. Sẽ thấy nút "Tiếp nhận công việc" màu xanh lá
4. Click để test

---

## Kiểm tra database

### Xem tất cả công việc:
```sql
SELECT id, title, domain, initial_status, deadline 
FROM task;
```

### Xem phân công của một user:
```sql
SELECT ta.id, ta.status, t.title, u.fullname
FROM task_assignment ta
JOIN task t ON ta.task_id = t.id
JOIN user u ON ta.user_id = u.id
WHERE ta.user_id = 1;
```

### Xem ai được giao một công việc:
```sql
SELECT u.id, u.fullname, u.unit_area, ta.status
FROM task_assignment ta
JOIN user u ON ta.user_id = u.id
WHERE ta.task_id = 1;
```

---

## Troubleshooting

### Vấn đề: Không thấy nút tiếp nhận

**Giải pháp 1:** Kiểm tra user có được giao việc không
```sql
SELECT * FROM task_assignment WHERE user_id = [YOUR_USER_ID];
```

**Giải pháp 2:** Kiểm tra status hiện tại
```sql
SELECT ta.status, t.title 
FROM task_assignment ta 
JOIN task t ON ta.task_id = t.id 
WHERE ta.user_id = [YOUR_USER_ID];
```

**Giải pháp 3:** Đảm bảo đăng nhập đúng user
- Logout và login lại
- Kiểm tra session trong browser

### Vấn đề: Click nút không có phản ứng

**Giải pháp:**
1. Kiểm tra console browser (F12) xem có lỗi không
2. Kiểm tra route `/tasks/<id>/update_task_status` có hoạt động không
3. Restart server: `./START_SERVER_MAC.sh`

---

## Kết luận

✅ **Chức năng đã hoạt động đúng**
✅ **Code đã được implement đầy đủ**
✅ **Đã tạo dữ liệu test**
✅ **Sẵn sàng sử dụng**

**Lưu ý quan trọng:**
- Chỉ người được giao việc mới thấy nút tiếp nhận
- Mỗi công việc phải được giao cho user cụ thể hoặc vai trò
- Sau khi tiếp nhận, status tự động chuyển sang "Đang thực hiện"
