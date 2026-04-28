# -*- coding: utf-8 -*-
with open('templates/task_detail.html', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')

# Kiểm tra thẻ HTML không đóng
issues = []
for i, line in enumerate(lines, 1):
    if '</div' in line and not '</div>' in line:
        issues.append(f"Line {i}: Unclosed div tag")

if issues:
    print("Issues found:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("✓ No unclosed div tags")

# Đếm Jinja tags
if_count = content.count('{' + '% if ')
endif_count = content.count('{' + '% endif %' + '}')

print(f"\nJinja tags:")
print(f"  if statements: {if_count}")
print(f"  endif statements: {endif_count}")

if if_count == endif_count:
    print("  ✓ if/endif balanced")
else:
    print(f"  ✗ MISMATCH: {if_count} if vs {endif_count} endif")
    print(f"  Difference: {endif_count - if_count} extra endif")

