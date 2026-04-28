import re

with open("routes/tasks.py", "r") as f:
    content = f.read()

# Read the is_lead logic from tasks route and put it into task_detail route
is_lead_logic = """    role = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role.perms) if role and role.perms else {}
    is_lead = perms.get('p_task_lead') or session.get('is_admin')
"""

replacement = """    task = db.session.get(Task, tid)
    if not task: return "Not Found", 404
    
""" + is_lead_logic

content = content.replace("    task = db.session.get(Task, tid)\n    if not task: return \"Not Found\", 404\n    ", replacement)

# Pass is_lead to template
content = content.replace("now_dt=datetime.now())", "now_dt=datetime.now(), is_lead=is_lead)")

with open("routes/tasks.py", "w") as f:
    f.write(content)
