# -*- coding: utf-8 -*-
"""
Merge PC06 menu items vào base.html của BDHVS
"""

# Đọc base.html của BDHVS
with open('templates/base_bdhvs.html', 'r', encoding='utf-8') as f:
    bdhvs_content = f.read()

# Đọc base.html của PC06 để lấy menu items
with open('templates/base.html', 'r', encoding='utf-8') as f:
    pc06_content = f.read()

# Menu items của PC06 cần giữ lại
pc06_menu_items = """
                <a href="/admin" class="nav-link-top {% if request.endpoint == 'admin_bp.index' %}active{% endif %}">Tổng quan</a>
                {% if perms.get('p_task_lead') or perms.get('p_task_exec') %}
                <a href="/tasks" class="nav-link-top {% if request.endpoint == 'tasks_bp.tasks' %}active{% endif %}">Công việc</a>
                {% endif %}
                <a href="/ranking" class="nav-link-top {% if request.endpoint == 'ranking_bp.index' %}active{% endif %}">Xếp hạng</a>
                
                <div class="dropdown">
                    <a class="nav-link-top dropdown-toggle {% if request.endpoint in ['portal_bp.news', 'portal_bp.library'] %}active{% endif %}" href="#" role="button" data-bs-toggle="dropdown">
                        Cổng thông tin
                    </a>
                    <ul class="dropdown-menu">
                        <li><a class="dropdown-item" href="/news">Tin tức</a></li>
                        <li><a class="dropdown-item" href="/library">Thư viện</a></li>
                    </ul>
                </div>
                
                <a href="/contacts" class="nav-link-top {% if request.endpoint == 'portal_bp.contacts' %}active{% endif %}">Danh bạ</a>
                <a href="{{ url_for('reporting_bp.index') }}" class="nav-link-top {% if request.path.startswith('/reporting') %}active{% endif %}">Báo cáo</a>
                <a href="{{ url_for('shortlink_bp.manage_links') }}" class="nav-link-top {% if request.path.startswith('/links') %}active{% endif %}">QR & Link</a>
                <a href="/ai" class="nav-link-top {% if request.path.startswith('/ai') %}active{% endif %}">AI Trợ lý</a>
                
                {% if session.get('is_admin') %}
                <div class="dropdown">
                    <a class="nav-link-top dropdown-toggle {% if request.endpoint in ['admin_bp.roles', 'admin_bp.categories', 'admin_bp.zalo_config'] %}active{% endif %}" href="#" role="button" data-bs-toggle="dropdown">
                        Quản trị
                    </a>
                    <ul class="dropdown-menu">
                        <li><a class="dropdown-item" href="/roles">Phân quyền</a></li>
                        <li><a class="dropdown-item" href="/categories">Danh mục</a></li>
                        <li><a class="dropdown-item" href="/admin/zalo">Cấu hình Zalo</a></li>
                        <li><a class="dropdown-item" href="/admin/ai-settings">Cấu hình AI</a></li>
                    </ul>
                </div>
                {% endif %}
"""

print("Menu items của PC06 đã được chuẩn bị")
print(f"Số dòng: {len(pc06_menu_items.split(chr(10)))}")

# Tìm vị trí để insert menu trong BDHVS base.html
# Tìm phần nav-center
if '<div class="nav-center' in bdhvs_content:
    print("✓ Tìm thấy nav-center trong BDHVS base.html")
else:
    print("✗ Không tìm thấy nav-center")

# Lưu menu items vào file tạm
with open('pc06_menu_items.txt', 'w', encoding='utf-8') as f:
    f.write(pc06_menu_items)

print("✓ Đã lưu menu items vào pc06_menu_items.txt")
