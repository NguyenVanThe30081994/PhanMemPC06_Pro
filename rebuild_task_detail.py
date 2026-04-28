# -*- coding: utf-8 -*-
"""
Rebuild task_detail.html với cấu trúc đúng
"""

# Đọc file hiện tại
with open('templates/task_detail.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Kiểm tra xem có phần nào bị lỗi không
lines = content.split('\n')

# Tìm các vấn đề
issues = []
for i, line in enumerate(lines, 1):
    # Kiểm tra thẻ HTML không đóng
    if '</div' in line and not '</div>' in line:
        issues.append(f"Line {i}: Unclosed div tag: {line.strip()}")
    
    # Kiểm tra duplicate sections
    if i > 1 and 'COMMENTS SECTION' in line and 'COMMENTS SECTION' in lines[i-2]:
        issues.append(f"Line {i}: Duplicate COMMENTS SECTION")

if issues:
    print("Issues found:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("✓ No obvious HTML issues found")

# Đếm các thẻ Jinja
if_count = content.count('{% if ')
elif_count = content.count('{% elif ')
else_count = content.count('{% else %}')
endif_count = content.count('{% endif %}')

print(f"\nJinja tags:")
print(f"  {% if %}: {if_count}")
print(f"  {% elif %}: {elif_count}")
print(f"  {% else %}: {else_count}")
print(f"  {% endif %}: {endif_count}")

if if_count == endif_count:
    print("  ✓ if/endif balanced")
else:
    print(f"  ✗ MISMATCH: {if_count} if vs {endif_count} endif")

