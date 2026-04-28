# -*- coding: utf-8 -*-
"""
Comment out các endpoint không tồn tại trong PC06
"""
import re

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Danh sách các endpoint không tồn tại trong PC06
invalid_endpoints = [
    'forms_bp.input_data',
    'forms_bp.stats', 
    'forms_bp.progress',
    'ocr_bp.ocr_index',
    'bdhv_bp.',
]

# Comment out các dòng chứa endpoint không tồn tại
lines = content.split('\n')
new_lines = []

for line in lines:
    should_comment = False
    for endpoint in invalid_endpoints:
        if endpoint in line and 'url_for' in line:
            should_comment = True
            break
    
    if should_comment:
        # Comment out dòng này
        new_lines.append('                {# ' + line.strip() + ' #}')
    else:
        new_lines.append(line)

new_content = '\n'.join(new_lines)

# Ghi lại
with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("✓ Đã comment out các endpoint không tồn tại")

# Đếm số dòng đã comment
commented = sum(1 for line in new_lines if line.strip().startswith('{#') and 'url_for' in line)
print(f"  Số dòng đã comment: {commented}")
