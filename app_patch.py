# Script to patch app.py with security improvements
import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace hardcoded secret key
old_secret = "app.secret_key = 'PC06_FINAL_V3_5_2026'"
new_secret = """# Import config
try:
    from config import SECRET_KEY, SESSION_LIFETIME, MAX_CONTENT_LENGTH, SESSION_COOKIE_SECURE, SESSION_COOKIE_HTTPONLY, SESSION_COOKIE_SAMESITE, CSRF_TOKEN_LIFETIME
except ImportError:
    SECRET_KEY = 'PC06_FINAL_V3_5_2026'
    SESSION_LIFETIME = 28800
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    CSRF_TOKEN_LIFETIME = 3600

app.secret_key = SECRET_KEY"""

content = content.replace(old_secret, new_secret)

# Update session lifetime
content = re.sub(
    r"app\.config\['PERMANENT_SESSION_LIFETIME'\] = timedelta\(minutes=30\)",
    f"app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(seconds=SESSION_LIFETIME)",
    content
)

# Update max content length
content = re.sub(
    r"app\.config\['MAX_CONTENT_LENGTH'\] = 100 \* 1024 \* 1024",
    "app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH",
    content
)

# Update session cookie secure
content = re.sub(
    r"app\.config\['SESSION_COOKIE_SECURE'\] = False",
    "app.config['SESSION_COOKIE_SECURE'] = SESSION_COOKIE_SECURE",
    content
)

# Update CSRF time limit
content = re.sub(
    r"app\.config\['WTF_CSRF_TIME_LIMIT'\] = 3600",
    "app.config['WTF_CSRF_TIME_LIMIT'] = CSRF_TOKEN_LIFETIME",
    content
)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("✅ app.py patched successfully")
