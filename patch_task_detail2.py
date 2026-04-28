with open("routes/tasks.py", "r") as f:
    content = f.read()

calc_progress = """    comments = TaskComment.query.filter_by(task_id=tid).order_by(TaskComment.created_at.desc()).all()
    assigns = db.session.query(TaskAssignment, User).join(User, TaskAssignment.user_id == User.id).filter(TaskAssignment.task_id == tid).all()
    
    # Calculate progress percent based on logic
    display_status = task.initial_status
    if assigns:
        all_completed = all(a.status == 'Hoàn thành' for a, u in assigns)
        if all_completed:
            display_status = 'Hoàn thành'
    
    progress_percent = 100 if display_status == 'Hoàn thành' else 0
"""

content = content.replace("    comments = TaskComment.query.filter_by(task_id=tid).order_by(TaskComment.created_at.desc()).all()\n    assigns = db.session.query(TaskAssignment, User).join(User, TaskAssignment.user_id == User.id).filter(TaskAssignment.task_id == tid).all()\n", calc_progress)

# Pass progress_percent to template
content = content.replace("now_dt=datetime.now(), is_lead=is_lead)", "now_dt=datetime.now(), is_lead=is_lead, progress_percent=progress_percent)")

with open("routes/tasks.py", "w") as f:
    f.write(content)
