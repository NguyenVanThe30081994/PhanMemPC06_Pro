# -*- coding: utf-8 -*-
"""
Xóa các endpoint không tồn tại trong PC06 từ base.html
"""

with open('templates/base.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Xóa các dòng chứa endpoint không tồn tại
new_lines = []
skip_until_endif = False
skip_until_close_div = False

for i, line in enumerate(lines):
    # Bỏ qua section "Dữ liệu và Báo cáo" (dòng 595-615)
    if 'Dữ liệu & Báo cáo' in line:
        skip_until_close_div = True
        continue
    
    if skip_until_close_div:
        if '</div>' in line and 'collapse' in line:
            skip_until_close_div = False
        continue
    
    # Bỏ qua dòng có ocr_bp
    if 'ocr_bp' in line:
        continue
    
    # Bỏ qua dòng có forms_bp
    if 'forms_bp' in line:
        continue
    
    # Bỏ qua dòng có bdhv_bp
    if 'bdhv_bp' in line:
        continue
    
    new_lines.append(line)

# Ghi lại file
with open('templates/base.html', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"✓ Đã xóa các endpoint không tồn tại")
print(f"  Số dòng trước: {len(lines)}")
print(f"  Số dòng sau: {len(new_lines)}")
print(f"  Đã xóa: {len(lines) - len(new_lines)} dòng")
