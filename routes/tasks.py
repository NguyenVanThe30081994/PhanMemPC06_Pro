from flask import Blueprint, render_template as flask_render_template, request, session, redirect, url_for, flash, current_app
from models import db, Task, TaskAssignment, TaskComment, User, MasterData, CategoryGroup, CategoryItem
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from utils import log_action, push_notif, render_auto_template as render_template

tasks_bp = Blueprint('tasks_bp', __name__)

@tasks_bp.route('/tasks', methods=['GET', 'POST'])
def tasks():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    # === LẤY DANH MỤC THEO NHÓM ===
    group_dongnghiepvu = CategoryGroup.query.filter((CategoryGroup.name == 'Dong nghiep vu') | (CategoryGroup.name == 'Đội nghiệp vụ')).first()
    all_category_items = CategoryItem.query.filter_by(group_id=group_dongnghiepvu.id).all() if group_dongnghiepvu else []
    domains = [d.name for d in all_category_items]
    
    current_domain = request.args.get('domain', 'ALL')
    now_dt = datetime.now()

    # Permissions
    from models import AppRole
    import json
    role = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role.perms) if role and role.perms else {}
    is_lead = perms.get('p_task_lead') or session.get('is_admin')

    if request.method == 'POST' and is_lead:
        # File upload - handle both 'file' and 'task_file'
        f = request.files.get('task_file') or request.files.get('file')
        fn = ""
        if f and f.filename:
            fn = secure_filename(f.filename)
            f.save(os.path.join(current_app.root_path, 'task_files', fn))
        
        deadline_raw = request.form.get('deadline')
        deadline_type = request.form.get('deadline_type', 'custom')
        
        deadline_val = None
        now = datetime.now()
        
        if deadline_type == 'custom' and deadline_raw:
            try:
                deadline_val = datetime.strptime(deadline_raw, '%Y-%m-%d').date()
            except:
                pass
        elif deadline_type == 'week':
            # Chọn thứ trong tuần
            weekday = int(request.form.get('weekday', 0))
            days_until = (weekday - now.weekday()) % 7
            if days_until == 0: days_until = 7  # Tuần sau
            deadline_val = (now + timedelta(days=days_until)).date()
        elif deadline_type == 'month':
            # Ngày cụ thể trong tháng
            day_of_month = int(request.form.get('day_of_month', 1))
            if now.month == 12:
                try: deadline_val = datetime(now.year, 12, day_of_month).date()
                except: deadline_val = datetime(now.year, 12, 28).date()
            else:
                try: deadline_val = datetime(now.year, now.month, day_of_month).date()
                except: deadline_val = datetime(now.year, now.month, 28).date()
        elif deadline_type == 'quarter':
            # Ngày và tháng cụ thể trong quý
            day_of_month = int(request.form.get('day_of_month', 1))
            month_of_period = int(request.form.get('month_of_period', 3))  # Default tháng 3
            quarter = (now.month - 1) // 3 + 1
            target_month = quarter * 3 - (3 - month_of_period)
            if target_month < 1: target_month = 1
            try: deadline_val = datetime(now.year, target_month, day_of_month).date()
            except: deadline_val = datetime(now.year, target_month, 28).date()
        elif deadline_type == '6months':
            # Ngày và tháng (6 hoặc 12)
            day_of_month = int(request.form.get('day_of_month', 1))
            month_of_period = int(request.form.get('month_of_period', 6))
            try: deadline_val = datetime(now.year, month_of_period, day_of_month).date()
            except: deadline_val = datetime(now.year, 6, 28).date()
        elif deadline_type == 'year':
            # Ngày và tháng cụ thể trong năm
            day_of_month = int(request.form.get('day_of_month', 31))
            month_of_period = int(request.form.get('month_of_period', 12))
            try: deadline_val = datetime(now.year, month_of_period, day_of_month).date()
            except: deadline_val = datetime(now.year, 12, 31).date()

        # Get domain from either 'unit_name' (new modal) or 'domain' (old form)
        domain = request.form.get('unit_name') or request.form.get('domain') or 'Giao việc chung'
        
        # Get content from either 'description' (new modal) or 'content' (old form)
        content = request.form.get('description') or request.form.get('content') or ''

        new_task = Task(
            domain=domain,
            title=request.form.get('title', 'N/A'),
            content=content,
            deadline=deadline_val,
            file_path=fn,
            author_id=session['uid'],
            author_name=session.get('fullname', 'Admin'),
            priority=request.form.get('priority', 'Bình thường')
        )
        db.session.add(new_task)
        db.session.commit()
        
        # Assignments - handle both 'target_users' (old) and 'assignee_id' (new)
        assign_ids = request.form.getlist('target_users')
        assignee_id = request.form.get('assignee_id')
        if assignee_id and assignee_id not in [str(a) for a in assign_ids]:
            assign_ids.append(assignee_id)
            
        for aid in assign_ids:
            if aid:
                db.session.add(TaskAssignment(task_id=new_task.id, user_id=int(aid)))
                push_notif(int(aid), "Công việc mới", f"Bạn vừa được giao: {new_task.title}", f"/tasks/{new_task.id}")
        
        db.session.commit()
        log_action(session['uid'], session.get('fullname', 'Admin'), "Giao công việc mới", "Công việc", new_task.title)
        
        from utils import push_global_notif
        push_global_notif("Công việc mới", f"Có công việc mới: {new_task.title}", f"/tasks/{new_task.id}", exclude_uid=session.get('uid'))

        flash('Đã giao công việc thành công!', 'success')
        return redirect(url_for('tasks_bp.tasks'))

    # List tasks based on role and filter by domain
    query = Task.query
    if current_domain != 'ALL':
        query = query.filter_by(domain=current_domain)
        
    if is_lead:
        all_tasks = query.order_by(Task.created_at.desc()).all()
    else:
        all_tasks = query.join(TaskAssignment, Task.id == TaskAssignment.task_id).filter(TaskAssignment.user_id == session['uid']).order_by(Task.created_at.desc()).all()
    
    # Calculate stats
    total_count = len(all_tasks)
    overdue_count = 0
    completed_count = 0
    for t in all_tasks:
        if t.deadline and t.deadline < now_dt.date():
            overdue_count += 1
        # Check if all assignments are completed
        if t.assignments:
            if all(a.status == 'Hoàn thành' for a in t.assignments):
                completed_count += 1
    
    pending_count = total_count - completed_count

    return render_template('tasks.html', 
                           tasks=all_tasks, 
                           users=User.query.all(),
                           pro_units=MasterData.query.all(),
                           domains=domains, 
                           current_domain=current_domain, 
                           now_dt=now_dt,
                           stats={
                               'total': total_count,
                               'completed': completed_count,
                               'pending': pending_count,
                               'overdue': overdue_count
                           })

@tasks_bp.route('/tasks/<int:tid>', methods=['GET', 'POST'])
def task_detail(tid):
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    task = db.session.get(Task, tid)
    if not task: return "Not Found", 404
    
    comments = TaskComment.query.filter_by(task_id=tid).order_by(TaskComment.created_at.desc()).all()
    assigns = db.session.query(TaskAssignment, User).join(User, TaskAssignment.user_id == User.id).filter(TaskAssignment.task_id == tid).all()
    
    if request.method == 'POST':
        content = request.form.get('content')
        if content:
            db.session.add(TaskComment(task_id=tid, user_id=session['uid'], user_name=session['fullname'], content=content))
            db.session.commit()
            flash('Đã gửi phản hồi!', 'success')
            return redirect(url_for('tasks_bp.task_detail', tid=tid))
            
    return render_template('task_detail.html', task=task, comments=comments, assigns=assigns)
