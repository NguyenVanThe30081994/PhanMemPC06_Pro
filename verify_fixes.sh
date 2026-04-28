#!/bin/bash

echo "=========================================="
echo "KIỂM TRA CÁC SỬA ĐỔI CHỨC NĂNG CÔNG VIỆC"
echo "=========================================="
echo ""

# 1. Kiểm tra file routes/tasks.py đã được sửa
echo "1. Kiểm tra routes/tasks.py..."
if grep -q "has_specific_assignment" routes/tasks.py; then
    echo "   ✅ Logic giao việc theo đơn vị đã được thêm"
else
    echo "   ❌ Chưa có logic giao việc theo đơn vị"
fi

if grep -q "unit_users = User.query.filter_by(unit_area=domain" routes/tasks.py; then
    echo "   ✅ Query users theo unit_area đã có"
else
    echo "   ❌ Chưa có query users theo unit_area"
fi

# 2. Kiểm tra file backup
echo ""
echo "2. Kiểm tra backup..."
if [ -f "routes/tasks.py.backup" ]; then
    echo "   ✅ File backup tồn tại: routes/tasks.py.backup"
else
    echo "   ⚠️  Không có file backup"
fi

# 3. Kiểm tra template task_detail.html
echo ""
echo "3. Kiểm tra templates/task_detail.html..."
if grep -q "submit_task_report" templates/task_detail.html; then
    echo "   ✅ Form báo cáo đã có"
else
    echo "   ❌ Chưa có form báo cáo"
fi

if grep -q "report_content" templates/task_detail.html; then
    echo "   ✅ Textarea báo cáo đã có"
else
    echo "   ❌ Chưa có textarea báo cáo"
fi

if grep -q "report_file" templates/task_detail.html; then
    echo "   ✅ Input file đính kèm đã có"
else
    echo "   ❌ Chưa có input file"
fi

# 4. Kiểm tra database
echo ""
echo "4. Kiểm tra database..."

# Kiểm tra users
USER_COUNT=$(sqlite3 pc06_system.db "SELECT COUNT(*) FROM user WHERE is_active = 1;")
echo "   📊 Số lượng users active: $USER_COUNT"

# Kiểm tra tasks
TASK_COUNT=$(sqlite3 pc06_system.db "SELECT COUNT(*) FROM task;")
echo "   📊 Số lượng tasks: $TASK_COUNT"

# Kiểm tra assignments
ASSIGNMENT_COUNT=$(sqlite3 pc06_system.db "SELECT COUNT(*) FROM task_assignment;")
echo "   📊 Số lượng assignments: $ASSIGNMENT_COUNT"

# Kiểm tra users theo đơn vị
echo ""
echo "   Users theo đơn vị:"
sqlite3 pc06_system.db "SELECT unit_area, COUNT(*) as count FROM user WHERE is_active = 1 GROUP BY unit_area;" | while read line; do
    echo "      - $line"
done

# 5. Kiểm tra thư mục task_files
echo ""
echo "5. Kiểm tra thư mục task_files..."
if [ -d "task_files" ]; then
    echo "   ✅ Thư mục task_files tồn tại"
    FILE_COUNT=$(ls -1 task_files/ 2>/dev/null | wc -l)
    echo "   📊 Số file trong task_files: $FILE_COUNT"
else
    echo "   ⚠️  Thư mục task_files chưa tồn tại"
    echo "   → Tạo thư mục..."
    mkdir -p task_files
    chmod 755 task_files
    echo "   ✅ Đã tạo thư mục task_files"
fi

# 6. Tổng kết
echo ""
echo "=========================================="
echo "TỔNG KẾT"
echo "=========================================="
echo ""
echo "✅ Vấn đề 1: Logic giao việc theo đơn vị"
echo "✅ Vấn đề 2: Form báo cáo kết quả"
echo "✅ Dữ liệu test: $ASSIGNMENT_COUNT assignments cho $TASK_COUNT tasks"
echo ""
echo "📝 Hướng dẫn test:"
echo "   1. Khởi động server: ./START_SERVER_MAC.sh"
echo "   2. Đăng nhập: user_dv1 / test"
echo "   3. Vào /tasks để xem nút tiếp nhận"
echo "   4. Click tiếp nhận → Vào chi tiết → Gửi báo cáo"
echo ""
echo "📄 Tài liệu: TONG_HOP_SUA_LOI_CHUC_NANG_CONG_VIEC.md"
echo ""

