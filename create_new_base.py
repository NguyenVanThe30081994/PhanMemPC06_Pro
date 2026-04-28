# -*- coding: utf-8 -*-
"""
Tạo base.html mới cho PC06 với giao diện BDHVS và menu PC06
"""
import re

# Đọc base.html của BDHVS
with open('templates/base_bdhvs.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Đọc menu items của PC06
with open('pc06_menu_items.txt', 'r', encoding='utf-8') as f:
    pc06_menu = f.read()

# Tìm và thay thế phần nav-center trong BDHVS
# Pattern: tìm từ <div class="nav-center đến hết các menu items
pattern = r'(<div class="nav-center[^>]*>)(.*?)(</div>\s*<!-- End nav-center -->)'

def replace_menu(match):
    start = match.group(1)
    end = match.group(3)
    return start + '\n' + pc06_menu + '\n            ' + end

# Thay thế
new_content = re.sub(pattern, replace_menu, content, flags=re.DOTALL)

# Kiểm tra xem đã thay thế chưa
if new_content != content:
    print("✓ Đã thay thế menu thành công")
    
    # Lưu file mới
    with open('templates/base.html', 'w', encoding='utf-8') as f:
        f.write(new_content)
    
    print("✓ Đã tạo base.html mới")
    print(f"  Kích thước: {len(new_content)} bytes")
else:
    print("✗ Không thể thay thế menu, thử cách khác...")
    
    # Cách 2: Tìm vị trí chính xác hơn
    if 'nav-center' in content:
        # Tìm vị trí bắt đầu của nav-center
        start_pos = content.find('<div class="nav-center')
        if start_pos > 0:
            # Tìm vị trí kết thúc (</div> sau nav-center)
            # Đếm số lượng <div> và </div> để tìm đúng thẻ đóng
            temp = content[start_pos:]
            div_count = 0
            pos = 0
            for i, char in enumerate(temp):
                if temp[i:i+5] == '<div ':
                    div_count += 1
                elif temp[i:i+6] == '</div>':
                    div_count -= 1
                    if div_count == 0:
                        end_pos = start_pos + i + 6
                        break
            
            # Thay thế
            before = content[:start_pos]
            after = content[end_pos:]
            
            new_nav = f'''<div class="nav-center d-none d-lg-flex align-items-center justify-content-center gap-2 flex-grow-1" style="max-width: 1200px; margin: 0 auto;">
{pc06_menu}
            </div>'''
            
            new_content = before + new_nav + after
            
            with open('templates/base.html', 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            print("✓ Đã tạo base.html mới (cách 2)")
            print(f"  Kích thước: {len(new_content)} bytes")

