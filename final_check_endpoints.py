# -*- coding: utf-8 -*-
"""
Kiểm tra tất cả các endpoint trong base.html
"""
import re

with open('templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Tìm tất cả url_for
pattern = r"url_for\(['\"]([^'\"]+)['\"]"
matches = re.findall(pattern, content)

# Lọc ra các endpoint (không phải static)
endpoints = [m for m in matches if not m.startswith('static')]

# Đếm số lần xuất hiện
from collections import Counter
endpoint_counts = Counter(endpoints)

print("Các endpoint được sử dụng trong base.html:")
print("=" * 60)
for endpoint, count in sorted(endpoint_counts.items()):
    # Kiểm tra xem có bị comment không
    is_commented = False
    for line in content.split('\n'):
        if endpoint in line and 'url_for' in line:
            if line.strip().startswith('{#'):
                is_commented = True
                break
    
    status = "✓ OK" if is_commented or endpoint.endswith('_bp.') or '.' not in endpoint else "⚠ CHECK"
    print(f"  {endpoint:40} x{count:2}  {status}")

print("\n" + "=" * 60)
print(f"Tổng số endpoint: {len(endpoint_counts)}")
