# -*- coding: utf-8 -*-
import re

# Đọc file hiện tại
with open('routes/tasks.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Tìm và thay thế phần assignment logic
old_pattern = r'''        db\.session\.commit\(\)
        
        # Assignments - handle both 'target_users' \(old\) and 'assignee_id' \(new\)
        assign_ids = request\.form\.getlist\('target_users'\)
        assignee_id = request\.form\.get\('assignee_id'\)
        assign_type = request\.form\.get\('assign_type', 'user'\)
        assignee_role_id = request\.form\.get\('assignee_role_id'\)
        
        # Xử lý giao theo cá nhân hoặc vai trò
        if assign_type == 'role' and assignee_role_id:
            # Giao cho tất cả user có role này và đang hoạt động
            role_users = User\.query\.filter_by\(role_id=int\(assignee_role_id\), is_active=True\)\.all\(\)
            for u in role_users:
                db\.session\.add\(TaskAssignment\(task_id=new_task\.id, user_id=u\.id, status='Chưa tiếp nhận'\)\)
                push_notif\(u\.id, "Công việc mới", f"Bạn vừa được giao: \{new_task\.title\}", f"/tasks/\{new_task\.id\}"\)
        else:
            # Giao cho cá nhân \(từ assignee_id hoặc target_users\)
            if assignee_id and assignee_id not in \[str\(a\) for a in assign_ids\]:
                assign_ids\.append\(assignee_id\)
            
            for aid in assign_ids:
                if aid:
                    db\.session\.add\(TaskAssignment\(task_id=new_task\.id, user_id=int\(aid\), status='Chưa tiếp nhận'\)\)
                    push_notif\(int\(aid\), "Công việc mới", f"Bạn vừa được giao: \{new_task\.title\}", f"/tasks/\{new_task\.id\}"\)'''

new_code = '''        db.session.commit()
        
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
                    push_notif(int(aid), "Công việc mới", f"Bạn vừa được giao: {new_task.title}", f"/tasks/{new_task.id}")'''

# Thay thế
if re.search(old_pattern, content):
    content = re.sub(old_pattern, new_code, content)
    print("✓ Đã tìm thấy và thay thế code cũ")
else:
    print("✗ Không tìm thấy pattern cũ, thử cách khác...")
    # Tìm vị trí để insert
    marker = "        db.session.commit()\n        \n        # Assignments"
    if marker in content:
        # Tìm đoạn code cần thay thế theo cách đơn giản hơn
        start = content.find("        # Assignments - handle both")
        if start > 0:
            # Tìm dòng kết thúc (trước db.session.commit() tiếp theo)
            end = content.find("        db.session.commit()", start + 10)
            if end > start:
                content = content[:start] + new_code[content.find("        # Assignments"):] + "\n        " + content[end:]
                print("✓ Đã thay thế bằng cách tìm vị trí")

# Ghi lại file
with open('routes/tasks.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ Đã cập nhật routes/tasks.py")
