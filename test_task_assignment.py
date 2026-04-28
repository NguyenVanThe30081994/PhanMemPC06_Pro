# -*- coding: utf-8 -*-
"""
Test script to verify task assignment and accept button functionality
"""
from app import app, db
from models import Task, TaskAssignment, User
from datetime import datetime, date

with app.app_context():
    print("=== KIỂM TRA CHỨC NĂNG GIAO VIỆC ===\n")
    
    # 1. Kiểm tra users
    users = User.query.filter_by(is_active=True).all()
    print(f"1. Số lượng user đang hoạt động: {len(users)}")
    for u in users[:5]:
        print(f"   - {u.fullname} (ID: {u.id}, Đơn vị: {u.unit_area})")
    
    # 2. Kiểm tra tasks
    tasks = Task.query.all()
    print(f"\n2. Số lượng công việc: {len(tasks)}")
    
    # 3. Kiểm tra assignments
    assignments = TaskAssignment.query.all()
    print(f"\n3. Số lượng phân công: {len(assignments)}")
    
    if len(assignments) > 0:
        print("\n   Chi tiết phân công:")
        for ta in assignments[:10]:
            user = User.query.get(ta.user_id)
            task = Task.query.get(ta.task_id)
            print(f"   - Task: {task.title if task else 'N/A'}")
            print(f"     User: {user.fullname if user else 'N/A'}")
            print(f"     Status: {ta.status}")
            print()
    
    # 4. Tạo task mẫu nếu chưa có
    if len(tasks) == 0 and len(users) > 0:
        print("\n4. Tạo công việc mẫu để test...")
        admin = users[0]
        
        test_task = Task(
            domain='Đội nghiệp vụ 1',
            title='Công việc test - Kiểm tra nút tiếp nhận',
            content='Đây là công việc test để kiểm tra chức năng tiếp nhận công việc',
            deadline=date(2026, 5, 15),
            author_id=admin.id,
            author_name=admin.fullname,
            priority='Cao',
            task_type='Công việc thường xuyên',
            initial_status='Chưa tiếp nhận',
            created_at=datetime.now()
        )
        db.session.add(test_task)
        db.session.commit()
        
        # Giao cho user đầu tiên
        test_assignment = TaskAssignment(
            task_id=test_task.id,
            user_id=admin.id,
            status='Chưa tiếp nhận'
        )
        db.session.add(test_assignment)
        db.session.commit()
        
        print(f"   ✓ Đã tạo công việc: {test_task.title}")
        print(f"   ✓ Đã giao cho: {admin.fullname}")
        print(f"   ✓ Trạng thái: Chưa tiếp nhận")
        print(f"\n   → Vào /tasks để xem nút 'TIẾP NHẬN CÔNG VIỆC'")
    
    # 5. Kiểm tra logic hiển thị nút tiếp nhận
    print("\n5. Kiểm tra logic hiển thị nút tiếp nhận:")
    print("   - Nút sẽ hiển thị khi:")
    print("     • User được giao công việc (có TaskAssignment)")
    print("     • Status = 'Chưa tiếp nhận' hoặc 'Chưa bắt đầu'")
    print("   - Vị trí hiển thị:")
    print("     • Trang danh sách: /tasks (trong card công việc)")
    print("     • Trang chi tiết: /tasks/<id> (phần trên cùng)")
    
    print("\n=== KẾT THÚC KIỂM TRA ===")
