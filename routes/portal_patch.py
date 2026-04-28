# Patch routes/portal.py for file upload security
import re

with open('routes/portal.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add import at the top
if 'from utils.file_validator import validate_file_upload' not in content:
    import_section = content.find('from flask import')
    if import_section != -1:
        next_section = content.find('\n\n', import_section)
        content = content[:next_section] + '\ntry:\n    from utils.file_validator import validate_file_upload\nexcept ImportError:\n    def validate_file_upload(f):\n        return True, "OK", f.filename' + content[next_section:]

# Fix news file upload (around line 124-128)
old_news_upload = '''    if request.method == 'POST' and is_news_lead:
        f = request.files.get('file')
        fn = ""
        if f and f.filename:
            fn = secure_filename(f.filename)
            f.save(os.path.join(current_app.root_path, 'uploads', fn))'''

new_news_upload = '''    if request.method == 'POST' and is_news_lead:
        f = request.files.get('file')
        fn = ""
        if f and f.filename:
            # Validate file
            is_valid, message, safe_fn = validate_file_upload(f)
            if not is_valid:
                flash(f'Lỗi upload file: {message}', 'danger')
                return redirect(url_for('portal_bp.news'))
            fn = safe_fn
            f.save(os.path.join(current_app.root_path, 'uploads', fn))'''

content = content.replace(old_news_upload, new_news_upload)

# Fix library file upload (around line 172-175)
old_lib_upload = '''    if request.method == 'POST' and is_lib_lead:
        f = request.files.get('file')
        if f and f.filename:
            fn = secure_filename(f.filename)
            f.save(os.path.join(current_app.root_path, 'library_files', fn))'''

new_lib_upload = '''    if request.method == 'POST' and is_lib_lead:
        f = request.files.get('file')
        if f and f.filename:
            # Validate file
            is_valid, message, safe_fn = validate_file_upload(f)
            if not is_valid:
                flash(f'Lỗi upload file: {message}', 'danger')
                return redirect(url_for('portal_bp.library'))
            fn = safe_fn
            f.save(os.path.join(current_app.root_path, 'library_files', fn))'''

content = content.replace(old_lib_upload, new_lib_upload)

with open('routes/portal.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ routes/portal.py patched successfully")
