# -*- coding: utf-8 -*-
"""
Patch để sửa logic giao việc theo đơn vị
Khi tạo công việc và chọn đơn vị, tự động giao cho tất cả user thuộc đơn vị đó
"""

patch_content = '''
        db.session.commit()
        
        # Assignments - Ưu tiên giao theo đơn vị (domain/unit_area)
        assign_ids = request.form.getlist('target_users')
        assignee_id = request.form.get('assignee_id')
        assign_type = request.form.get('assign_type', 'user')
        assignee_role_id = request.form.get('assignee_role_id')
        
        # Kiểm tra xem có chọn giao cho cá nhân/vai trò không
        has_specific_assignment = (assign_type == 'role' and assignee_role_id) or assignee_id or assign_ids
        
        if not has_specific_assignment and domain and domain != 'Giao việc chung':
            # Không chọn cá nhân/vai trò → Tự động giao cho tất cả user thuộc đơn vị
            unit_users = User.query.filter_by(unit_area=domain, is_active=True).all()
            if unit_users:
                for u in unit_users:
                    db.session.add(TaskAssignment(task_id=new_task.id, user_id=u.id, status='Chưa tiếp nhận'))
                    push_notif(u.id, "Công việc mới", f"Đơn vị {domain} được giao: {new_task.title}", f"/tasks/{new_task.id}")
                flash(f'Đã giao công việc cho {len(unit_users)} người thuộc {domain}!', 'success')
            else:
                flash(f'Không tìm thấy user nào thuộc đơn vị {domain}', 'warning')
        elif assign_type == 'role' and assignee_role_id:
            # Giao cho tất cả user có role này và đang hoạt động
            role_users = User.query.filter_by(role_id=int(assignee_role_id), is_active=True).all()
            for u in role_users:
                db.session.add(TaskAssignment(task_id=new_task.id, user_id=u.id, status='Chưa tiếp nhận'))
                push_notif(u.id, "Công việc mới", f"Bạn vừa được giao: {new_task.title}", f"/tasks/{new_task.id}")
        else:
            # Giao cho cá nhân (từ assignee_id hoặc target_users)
            if assignee_id and assignee_id not in [str(a) for a in assign_ids]:
                assign_ids.append(assignee_id)
            
            for aid in assign_ids:
                if aid:
                    db.session.add(TaskAssignment(task_id=new_task.id, user_id=int(aid), status='Chưa tiếp nhận'))
                    push_notif(int(aid), "Công việc mới", f"Bạn vừa được giao: {new_task.title}", f"/tasks/{new_task.id}")
'''

print("Patch content prepared. Apply manually to routes/tasks.py around line 110-135")
print("\nKey changes:")
print("1. Check if no specific assignment (individual/role) is selected")
print("2. If not, auto-assign to all users with unit_area = domain")
print("3. Create TaskAssignment for each user in that unit")
