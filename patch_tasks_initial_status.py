with open("routes/tasks.py", "r") as f:
    content = f.read()

content = content.replace("initial_status=request.form.get('initial_status') or 'Chưa bắt đầu'", "initial_status='Chưa tiếp nhận'")
content = content.replace("db.session.add(TaskAssignment(task_id=new_task.id, user_id=u.id, status=new_task.initial_status))", "db.session.add(TaskAssignment(task_id=new_task.id, user_id=u.id, status='Chưa tiếp nhận'))")
content = content.replace("db.session.add(TaskAssignment(task_id=new_task.id, user_id=int(aid), status=new_task.initial_status))", "db.session.add(TaskAssignment(task_id=new_task.id, user_id=int(aid), status='Chưa tiếp nhận'))")

with open("routes/tasks.py", "w") as f:
    f.write(content)
