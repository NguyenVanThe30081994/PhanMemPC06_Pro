# Patch routes/admin.py for security fixes
import re

with open('routes/admin.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix SQL injection in db-manage route
old_code = '''        for table, col, col_type in migrations:
            try:
                cursor.execute(f"PRAGMA table_info({table})")
                cols = [c[1] for c in cursor.fetchall()]
                if col not in cols:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                    conn.commit()
                    results.append(f"✅ Đã thêm cột {col} vào bảng {table}")
                else:
                    results.append(f"ℹ️ Cột {col} đã tồn tại trong bảng {table}")
            except Exception as e:
                results.append(f"❌ Lỗi tại bảng {table}, cột {col}: {str(e)}")'''

new_code = '''        # Import security validators
        try:
            from utils.security_helpers import validate_table_name, validate_column_name, validate_column_type
        except ImportError:
            # Fallback validation
            import re
            def validate_table_name(t):
                return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', t))
            def validate_column_name(c):
                return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', c))
            def validate_column_type(ct):
                allowed = {'INTEGER', 'TEXT', 'REAL', 'BLOB', 'BOOLEAN', 'VARCHAR(50)', 'VARCHAR(100)', 'VARCHAR(255)', 'DATE', 'DATETIME', 'FLOAT'}
                return ct.upper() in allowed or 'VARCHAR' in ct.upper() or 'DEFAULT' in ct.upper()
        
        for table, col, col_type in migrations:
            try:
                # Validate inputs to prevent SQL injection
                if not validate_table_name(table):
                    results.append(f"❌ Invalid table name: {table}")
                    continue
                if not validate_column_name(col):
                    results.append(f"❌ Invalid column name: {col}")
                    continue
                if not validate_column_type(col_type.split()[0]):
                    results.append(f"❌ Invalid column type: {col_type}")
                    continue
                
                cursor.execute(f"PRAGMA table_info({table})")
                cols = [c[1] for c in cursor.fetchall()]
                if col not in cols:
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")
                    conn.commit()
                    results.append(f"✅ Đã thêm cột {col} vào bảng {table}")
                else:
                    results.append(f"ℹ️ Cột {col} đã tồn tại trong bảng {table}")
            except Exception as e:
                results.append(f"❌ Lỗi tại bảng {table}, cột {col}: {str(e)}")'''

content = content.replace(old_code, new_code)

# Fix default password issue - find and replace
content = re.sub(
    r"password = request\.form\.get\('password', '123456'\)",
    "password = request.form.get('password', '')",
    content
)

# Add password validation import at the top
if 'from utils.password_validator import validate_password' not in content:
    # Find the imports section
    import_section = content.find('from flask import')
    if import_section != -1:
        # Find end of imports
        next_section = content.find('\n\n', import_section)
        content = content[:next_section] + '\ntry:\n    from utils.password_validator import validate_password, get_password_requirements\nexcept ImportError:\n    def validate_password(pwd):\n        return len(pwd) >= 8, "Mật khẩu phải có ít nhất 8 ký tự"\n    def get_password_requirements():\n        return "Ít nhất 8 ký tự, có chữ hoa, chữ thường, chữ số"' + content[next_section:]

with open('routes/admin.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ routes/admin.py patched successfully")
