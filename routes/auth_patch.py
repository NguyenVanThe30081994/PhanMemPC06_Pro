# Patch routes/auth.py for security logging
import re

with open('routes/auth.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add import at the top
if 'from utils.security_helpers import log_security_event' not in content:
    import_section = content.find('from flask import')
    if import_section != -1:
        next_section = content.find('\n\n', import_section)
        content = content[:next_section] + '\ntry:\n    from utils.security_helpers import log_security_event\nexcept ImportError:\n    def log_security_event(event, details=""):\n        pass' + content[next_section:]

# Find failed login and add logging
old_failed_login = '''        if not usr or not usr.check_password(pwd):
            flash('Tên đăng nhập hoặc mật khẩu không đúng!', 'danger')
            return render_template('login.html')'''

new_failed_login = '''        if not usr or not usr.check_password(pwd):
            log_security_event('FAILED_LOGIN', f'Username: {uname}')
            flash('Tên đăng nhập hoặc mật khẩu không đúng!', 'danger')
            return render_template('login.html')'''

content = content.replace(old_failed_login, new_failed_login)

# Find successful login and add logging
old_success_login = '''            session['uid'] = usr.id
            session['username'] = usr.username
            session['fullname'] = usr.fullname
            session['role_id'] = usr.role_id
            session['must_change'] = usr.must_change_password'''

new_success_login = '''            session['uid'] = usr.id
            session['username'] = usr.username
            session['fullname'] = usr.fullname
            session['role_id'] = usr.role_id
            session['must_change'] = usr.must_change_password
            log_security_event('SUCCESSFUL_LOGIN', f'User: {usr.fullname}')'''

content = content.replace(old_success_login, new_success_login)

with open('routes/auth.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ routes/auth.py patched successfully")
