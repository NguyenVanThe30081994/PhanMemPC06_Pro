with open("routes/tasks.py", "r") as f:
    content = f.read()

new_routes = """
@tasks_bp.route('/tasks/<int:tid>/update_status', methods=['POST'])
def update_task_status(tid):
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    action = request.form.get('action')
    assign = TaskAssignment.query.filter_by(task_id=tid, user_id=session['uid']).first()
    
    if assign and action == 'accept':
        assign.status = 'Đang thực hiện'
        db.session.commit()
        flash('Đã tiếp nhận công việc!', 'success')
        
    return redirect(url_for('tasks_bp.task_detail', tid=tid))

@tasks_bp.route('/tasks/<int:tid>/submit_report', methods=['POST'])
def submit_task_report(tid):
    if not session.get('uid'): return redirect(url_for('auth_bp.login'))
    
    report_content = request.form.get('report_content')
    mark_completed = request.form.get('mark_completed')
    f = request.files.get('report_file')
    
    assign = TaskAssignment.query.filter_by(task_id=tid, user_id=session['uid']).first()
    if not assign:
        flash('Bạn không được giao công việc này.', 'danger')
        return redirect(url_for('tasks_bp.task_detail', tid=tid))
        
    fn = ""
    if f and f.filename:
        fn = secure_filename(f.filename)
        f.save(os.path.join(current_app.root_path, 'task_files', fn))
        
    if report_content:
        # Create a comment as a report
        msg = f"[BÁO CÁO] {report_content}"
        if fn:
            msg += f" (Đính kèm: {fn})"
            
        db.session.add(TaskComment(task_id=tid, user_id=session['uid'], user_name=session['fullname'], content=msg))
        
    if mark_completed == '1':
        assign.status = 'Hoàn thành'
        if fn:
            assign.result_file = fn
            
    db.session.commit()
    flash('Đã gửi báo cáo thành công!', 'success')
    return redirect(url_for('tasks_bp.task_detail', tid=tid))
"""

content += new_routes

with open("routes/tasks.py", "w") as f:
    f.write(content)
