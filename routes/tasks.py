from flask import Blueprint, render_template, request, session, redirect, url_for, flash, current_app
from models import db, Task, TaskAssignment, TaskComment, User, MasterData, CategoryGroup, CategoryItem
import os
from werkzeug.utils import secure_filename
from datetime import datetime
from utils import log_action, push_notif

tasks_bp = Blueprint('tasks_bp', __name__)

@tasks_bp.route('/tasks', methods=['GET', 'POST'])
def tasks():
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    # Fetch domains from dynamic categories linked to 'Công việc'
    groups = CategoryGroup.query.filter(CategoryGroup.linked_modules.contains('Công việc')).all()
    all_units = []
    for g in groups: all_units.extend(g.items)
    domains = [d.name for d in all_units]
    
    current_domain = request.args.get('domain', 'ALL')
    now_dt = datetime.now()

    # Permissions
    from models import AppRole
    import json
    role = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role.perms) if role and role.perms else {}
    is_lead = perms.get('p_task_lead') or session.get('is_admin')

    if request.method == 'POST' and is_lead:
        f = request.files.get('file')
        fn = ""
        if f and f.filename:
            fn = secure_filename(f.filename)
            f.save(os.path.join(current_app.root_path, 'task_files', fn))
        
        deadline_raw = request.form.get('deadline')
        deadline_val = None
        if deadline_raw:
            try: deadline_val = datetime.strptime(deadline_raw, '%Y-%m-%d').date()
            except: pass

        new_task = Task(
            domain=request.form.get('domain', 'Giao việc chung'),
            title=request.form.get('title', 'N/A'),
            content=request.form.get('content', ''),
            deadline=deadline_val,
            file_path=fn,
            author_id=session['uid'],
            author_name=session['fullname'],
            priority=request.form.get('priority', 'Bình thường')
        )
        db.session.add(new_task)
        db.session.commit()
        
        # Assignments - Updated to match HTML field name 'target_users'
        assign_ids = request.form.getlist('target_users')
        for aid in assign_ids:
            db.session.add(TaskAssignment(task_id=new_task.id, user_id=aid))
            push_notif(aid, "Công việc mới", f"Bạn vừa được giao: {new_task.title}", f"/tasks/{new_task.id}")
        
        db.session.commit()
        log_action(session['uid'], session['fullname'], "Giao công việc mới", "Công việc", new_task.title)
        
        from utils import push_global_notif
        push_global_notif("Công việc mới", f"Có công việc mới: {new_task.title}", f"/tasks/{new_task.id}", exclude_uid=session['uid'])

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
