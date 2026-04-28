# Fix imports from utils to security_utils
import re

files_to_fix = [
    'routes/admin.py',
    'routes/portal.py', 
    'routes/auth.py'
]

for filepath in files_to_fix:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace imports
        content = re.sub(
            r'from utils\.file_validator import',
            'from security_utils.file_validator import',
            content
        )
        content = re.sub(
            r'from utils\.password_validator import',
            'from security_utils.password_validator import',
            content
        )
        content = re.sub(
            r'from utils\.security_helpers import',
            'from security_utils.security_helpers import',
            content
        )
        content = re.sub(
            r'from utils import validate_',
            'from security_utils import validate_',
            content
        )
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print(f"✅ Fixed {filepath}")
    except Exception as e:
        print(f"❌ Error fixing {filepath}: {e}")

print("\n✅ All imports fixed!")
