# -*- coding: utf-8 -*-
import re

# Đọc file
with open('templates/task_detail.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Sửa lỗi: Xóa phần trùng lặp và thẻ endif thừa
old_pattern = r'''                </div
            </div>
        </div>
        {% endif %}

        <!-- 4\. COMMENTS SECTION -->
        <div class="card border-0 shadow-sm rounded-4" style="background-color: var\(--bg-surface\);">
            <div class="card-header border-bottom p-4" style="background-color: var\(--bg-surface\); border-color: var\(--border\) !important;">
                <h5 class="fw-bold text-main mb-0"><i class="fa-solid fa-comments me-2 text-primary"></i>Phản hồi & Thảo luận</h5>'''

new_code = '''                </div>
            </div>
            <div class="card-body p-4">
                <form action="{{ url_for('tasks_bp.task_detail', tid=task.id) }}" method="POST" class="mb-4">
                    <div class="mb-3">
                        <textarea name="content" class="form-control rounded-3 border-2" placeholder="Nhập ý kiến phản hồi, thảo luận về công việc..." style="height: 100px; background-color: white; padding: 1rem; font-size: 14px;" required></textarea>'''

# Thay thế
content = re.sub(old_pattern, new_code, content)

# Ghi lại
with open('templates/task_detail.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("✓ Đã sửa lỗi template task_detail.html")
