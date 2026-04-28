# TỔNG HỢP SỬA LỖI CHỨC NĂNG CÔNG VIỆC

## Ngày: 28/04/2026

---

## VẤN ĐỀ 1: THIẾU NÚT TIẾP NHẬN CÔNG VIỆC

### Mô tả vấn đề
- Khi admin giao việc cho đơn vị, các thành viên trong đơn vị không thấy nút "TIẾP NHẬN CÔNG VIỆC"
- Nguyên nhân: Logic cũ chỉ giao việc cho cá nhân/vai trò, không tự động giao cho đơn vị

### Giải pháp đã áp dụng

**File: `routes/tasks.py` (Dòng 110-145)**

✅ Thêm logic tự động giao việc theo đơn vị:
```python
# Kiểm tra xem có chọn giao cho cá nhân/vai trò không
has_specific_assignment = (assign_type == 'role' and assignee_role_id) or assignee_id or assign_ids

if not has_specific_assignment and domain and domain != 'Giao việc chung':
    # Không chọn cá nhân/vai trò → Tự động giao cho tất cả user thuộc đơn vị
    unit_users = User.query.filter_by(unit_area=domain, is_active=True).all()
    if unit_users:
        for u in unit_users:
            db.session.add(TaskAssignment(task_id=new_task.id, user_id=u.id, status='Chưa tiếp nhận'))
            push_notif(u.id, "Công việc mới", f"Đơn vị {domain} được giao: {new_task.title}", f"/tasks/{new_task.id}")
```

### Cách hoạt động mới

**Bước 1: Admin tạo công việc**
- Chọn "Đội nghiệp vụ 1" 
- KHÔNG chọn "Giao cho" cụ thể
- Hệ thống tự động giao cho tất cả user có `unit_area` = "Đội nghiệp vụ 1"

**Bước 2: User thuộc đơn vị**
- Đăng nhập và vào `/tasks`
- Thấy công việc với nút "TIẾP NHẬN CÔNG VIỆC" màu xanh lá
- Click để chuyển status từ "Chưa tiếp nhận" → "Đang thực hiện"

**Bước 3: Sau khi tiếp nhận**
- Nút tiếp nhận biến mất
- Hiển thị badge "Đang thực hiện"
- Form báo cáo kết quả xuất hiện

---

## VẤN ĐỀ 2: THIẾU FORM BÁO CÁO KẾT QUẢ

### Mô tả vấn đề
- Trong giao diện chi tiết công việc chưa có mục báo cáo kết quả
- Báo cáo cần ngắn gọn kèm theo file kết quả

### Giải pháp đã áp dụng

**File: `templates/task_detail.html` (Dòng 135-174)**

✅ Đã có form báo cáo nhưng bị lỗi HTML
✅ Đã sửa lỗi thiếu thẻ đóng `</form>` và `</div>`
✅ Form chỉ hiển thị khi user đã tiếp nhận công việc

### Cấu trúc form báo cáo

```html
<!-- Chỉ hiển thị khi đã tiếp nhận -->
{% if user_assign and user_assign.status != 'Chưa tiếp nhận' and user_assign.status != 'Chưa bắt đầu' %}

<form action="/tasks/<id>/submit_report" method="POST" enctype="multipart/form-data">
    
    <!-- 1. Nội dung tóm tắt (bắt buộc) -->
    <textarea name="report_content" required>
        Mô tả ngắn gọn kết quả đạt được...
    </textarea>
    
    <!-- 2. File đính kèm (tùy chọn) -->
    <input type="file" name="report_file">
    
    <!-- 3. Đánh dấu hoàn thành (tùy chọn) -->
    <input type="checkbox" name="mark_completed" value="1">
    
    <!-- 4. Nút gửi -->
    <button type="submit">GỬI BÁO CÁO</button>
    
</form>
{% endif %}
```

### Cách sử dụng form báo cáo

**Bước 1:** Tiếp nhận công việc trước (click nút "TIẾP NHẬN CÔNG VIỆC")

**Bước 2:** Vào trang chi tiết `/tasks/<id>`

**Bước 3:** Kéo xuống thấy card "Báo cáo Công việc" với:
- Textarea để nhập nội dung tóm tắt (bắt buộc)
- Input file để đính kèm tài liệu (tùy chọn)
- Checkbox "Đánh dấu Hoàn thành" (tùy chọn)

**Bước 4:** Điền thông tin và click "GỬI BÁO CÁO"

**Kết quả:**
- Báo cáo được lưu dưới dạng comment với tag `[BÁO CÁO]`
- Nếu tick "Hoàn thành", status chuyển sang "Hoàn thành"
- File đính kèm được lưu vào thư mục `task_files/`

---

## BACKEND XỬ LÝ BÁO CÁO

**File: `routes/tasks.py` - Route `/tasks/<tid>/submit_report`**

```python
@tasks_bp.route('/tasks/<int:tid>/submit_report', methods=['POST'])
def submit_task_report(tid):
    # 1. Kiểm tra user đã đăng nhập
    if not session.get('uid'): 
        return redirect(url_for('auth_bp.login'))
    
    # 2. Lấy dữ liệu từ form
    report_content = request.form.get('report_content')
    mark_completed = request.form.get('mark_completed')
    f = request.files.get('report_file')
    
    # 3. Kiểm tra user có được giao việc không
    assign = TaskAssignment.query.filter_by(task_id=tid, user_id=session['uid']).first()
    if not assign:
        flash('Bạn không được giao công việc này.', 'danger')
        return redirect(url_for('tasks_bp.task_detail', tid=tid))
    
    # 4. Lưu file đính kèm (nếu có)
    fn = ""
    if f and f.filename:
        fn = secure_filename(f.filename)
        f.save(os.path.join(current_app.root_path, 'task_files', fn))
    
    # 5. Tạo comment báo cáo
    if report_content:
        msg = f"[BÁO CÁO] {report_content}"
        if fn:
            msg += f" (Đính kèm: {fn})"
        db.session.add(TaskComment(
            task_id=tid, 
            user_id=session['uid'], 
            user_name=session['fullname'], 
            content=msg
        ))
    
    # 6. Cập nhật status nếu đánh dấu hoàn thành
    if mark_completed == '1':
        assign.status = 'Hoàn thành'
        if fn:
            assign.result_file = fn
    
    db.session.commit()
    flash('Đã gửi báo cáo thành công!', 'success')
    return redirect(url_for('tasks_bp.task_detail', tid=tid))
```

---

## DỮ LIỆU TEST ĐÃ TẠO

### Users
```
ID | Họ tên       | Đơn vị          | Username  | Password
---|--------------|-----------------|-----------|----------
1  | Admin        | Hệ thống        | admin     | (admin)
2  | Nguyễn Văn A | Đội nghiệp vụ 1 | user_dv1  | test
3  | Trần Thị B   | Đội nghiệp vụ 1 | user_dv2  | test
4  | Lê Văn C     | Đội nghiệp vụ 2 | user_dv3  | test
```

### Task test
```
ID: 1
Tiêu đề: Báo cáo tình hình công tác tháng 4/2026
Đơn vị: Đội nghiệp vụ 1
Deadline: 05/05/2026
Priority: Cao
Được giao cho: Nguyễn Văn A (ID 2), Trần Thị B (ID 3)
Status: Chưa tiếp nhận
```

---

## HƯỚNG DẪN TEST TOÀN BỘ FLOW

### Test Case 1: Giao việc cho đơn vị

1. Đăng nhập với admin
2. Vào `/tasks` → Click "THÊM CÔNG VIỆC"
3. Điền thông tin:
   - Tiêu đề: "Test giao việc cho đơn vị"
   - Đội nghiệp vụ: "Đội nghiệp vụ 1"
   - Deadline: 30/05/2026
   - Priority: Cao
   - Mô tả: "Kiểm tra chức năng giao việc"
4. KHÔNG chọn "Giao cho" cụ thể
5. Click "Tạo công việc"
6. **Kết quả mong đợi:** 
   - Hiển thị "Đã giao công việc cho 2 người thuộc Đội nghiệp vụ 1!"
   - Nguyễn Văn A và Trần Thị B nhận được TaskAssignment

### Test Case 2: Tiếp nhận công việc

1. Logout admin
2. Đăng nhập với `user_dv1` / `test`
3. Vào `/tasks`
4. **Kết quả mong đợi:**
   - Thấy công việc "Báo cáo tình hình công tác tháng 4/2026"
   - Badge "Chưa tiếp nhận" màu vàng
   - Nút "Tiếp nhận công việc" màu xanh lá
5. Click nút "Tiếp nhận công việc"
6. **Kết quả mong đợi:**
   - Status chuyển sang "Đang thực hiện"
   - Nút tiếp nhận biến mất
   - Badge "Đang thực hiện" màu xanh dương

### Test Case 3: Báo cáo kết quả

1. Tiếp tục với user `user_dv1`
2. Click "Xem chi tiết" công việc
3. **Kết quả mong đợi:**
   - Thấy card "Báo cáo Công việc" với form
4. Điền form:
   - Nội dung: "Đã hoàn thành báo cáo tháng 4. Kết quả: 100% công việc đạt yêu cầu."
   - Đính kèm file: (chọn file Excel/Word)
   - Tick "Đánh dấu Hoàn thành"
5. Click "GỬI BÁO CÁO"
6. **Kết quả mong đợi:**
   - Hiển thị "Đã gửi báo cáo thành công!"
   - Status chuyển sang "Hoàn thành"
   - Báo cáo xuất hiện trong phần comments với tag [BÁO CÁO]
   - File được lưu vào `task_files/`

### Test Case 4: Admin xem tiến độ

1. Đăng nhập lại với admin
2. Vào `/tasks` → Click vào công việc
3. **Kết quả mong đợi:**
   - Thấy danh sách "Người được giao" với status của từng người:
     * Nguyễn Văn A: Hoàn thành ✓
     * Trần Thị B: Chưa tiếp nhận (hoặc Đang thực hiện)
   - Thấy báo cáo của Nguyễn Văn A trong phần comments
   - Có thể download file đính kèm

---

## KIỂM TRA DATABASE

### Xem assignments của một công việc
```sql
SELECT 
    u.fullname,
    u.unit_area,
    ta.status,
    ta.result_file,
    ta.updated_at
FROM task_assignment ta
JOIN user u ON ta.user_id = u.id
WHERE ta.task_id = 1;
```

### Xem báo cáo của một công việc
```sql
SELECT 
    tc.user_name,
    tc.content,
    tc.created_at
FROM task_comment tc
WHERE tc.task_id = 1
AND tc.content LIKE '[BÁO CÁO]%'
ORDER BY tc.created_at DESC;
```

### Xem tiến độ theo đơn vị
```sql
SELECT 
    t.title,
    t.domain,
    COUNT(ta.id) as total,
    SUM(CASE WHEN ta.status = 'Hoàn thành' THEN 1 ELSE 0 END) as completed,
    SUM(CASE WHEN ta.status = 'Đang thực hiện' THEN 1 ELSE 0 END) as in_progress,
    SUM(CASE WHEN ta.status = 'Chưa tiếp nhận' THEN 1 ELSE 0 END) as not_started
FROM task t
LEFT JOIN task_assignment ta ON t.id = ta.task_id
WHERE t.domain = 'Đội nghiệp vụ 1'
GROUP BY t.id;
```

---

## FILES ĐÃ THAY ĐỔI

### 1. `routes/tasks.py`
- **Dòng 110-145:** Thêm logic giao việc theo đơn vị
- **Backup:** `routes/tasks.py.backup`

### 2. `templates/task_detail.html`
- **Dòng 135-174:** Sửa lỗi HTML form báo cáo
- Thêm thẻ đóng `</form>` và `</div>` bị thiếu

### 3. Database
- Thêm 3 users test (user_dv1, user_dv2, user_dv3)
- Thêm 1 task test với assignments

---

## TROUBLESHOOTING

### Vấn đề: Không thấy nút tiếp nhận
```sql
-- Kiểm tra user có được giao không
SELECT * FROM task_assignment WHERE user_id = [YOUR_USER_ID];

-- Kiểm tra unit_area
SELECT id, fullname, unit_area FROM user WHERE id = [YOUR_USER_ID];
```

### Vấn đề: Không thấy form báo cáo
- Kiểm tra đã tiếp nhận công việc chưa (status phải khác "Chưa tiếp nhận")
- Kiểm tra HTML có lỗi không (F12 → Console)
- Restart server

### Vấn đề: Upload file báo cáo lỗi
```bash
# Kiểm tra thư mục task_files tồn tại
ls -la task_files/

# Nếu không có, tạo mới
mkdir -p task_files
chmod 755 task_files
```

---

## KẾT LUẬN

✅ **Vấn đề 1 - Đã sửa:** Nút tiếp nhận công việc hiển thị đúng cho đơn vị được giao
✅ **Vấn đề 2 - Đã sửa:** Form báo cáo kết quả hoạt động đúng
✅ **Đã test:** Toàn bộ flow từ giao việc → tiếp nhận → báo cáo
✅ **Dữ liệu test:** Sẵn sàng để kiểm tra ngay

**Lưu ý quan trọng:**
- User phải có `unit_area` khớp với `domain` của task
- Phải tiếp nhận trước khi báo cáo
- Báo cáo được lưu dưới dạng comment với tag [BÁO CÁO]
- File đính kèm lưu trong `task_files/`
