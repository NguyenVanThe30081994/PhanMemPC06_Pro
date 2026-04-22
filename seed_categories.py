# -*- coding: utf-8 -*-
"""
Script tự động tạo danh mục mặc định cho hệ thống PC06.
Chạy một lần để khởi tạo các CategoryGroup và CategoryItem cơ bản.
"""

from app import app
from models import db, CategoryGroup, CategoryItem, ModuleRegistry, CategoryGroupModule, ModuleFieldBinding
from category_helpers import resolve_group_code, slugify_code

MODULES = [
    {"code": "news", "name": "Bảng tin", "sort_order": 10},
    {"code": "library", "name": "Thư viện", "sort_order": 20},
    {"code": "tasks", "name": "Công việc", "sort_order": 30},
    {"code": "contacts", "name": "Danh bạ", "sort_order": 40},
]

# Định nghĩa các nhóm danh mục và các mục mặc định của chúng
DEFAULT_CATEGORIES = {
    "Nhóm danh bạ": {
        "code": "contact_group",
        "linked_modules": "Danh bạ",
        "aliases": ["Nhom danh ba"],
        "bindings": [{"module": "contacts", "field": "contact_group", "label": "Nhóm danh bạ", "required": True}],
        "items": [
            "Cán bộ chủ chốt", "Cán bộ địa bàn", "Cộng tác viên", "Cơ quan ban ngành",
            "Tổ chức xã hội", "Doanh nghiệp", "Kế hoạch", "Ngoại lệ"
        ]
    },
    "Chức vụ": {
        "code": "contact_role",
        "linked_modules": "Danh bạ",
        "aliases": ["Chuc vu"],
        "bindings": [{"module": "contacts", "field": "role", "label": "Chức vụ", "required": True}],
        "items": [
            "Trưởng CA xã", "Phó CA xã", "Công an viên", "Cộng tác viên", "Cán bộ địa bàn",
            "Chủ tịch UBND", "Phó Chủ tịch UBND", "Cán bộ văn phòng", "Trưởng phòng",
            "Phó phòng", "Chuyên viên", "Khác"
        ]
    },
    "Lĩnh vực": {
        "code": "news_domain",
        "linked_modules": "Bảng tin,Thư viện,Danh bạ",
        "aliases": ["Linh vuc"],
        "bindings": [
            {"module": "news", "field": "category", "label": "Lĩnh vực / Đội nghiệp vụ", "required": True},
            {"module": "library", "field": "category", "label": "Lĩnh vực", "required": True},
            {"module": "contacts", "field": "category", "label": "Lĩnh vực", "required": False}
        ],
        "items": [
            "An ninh chính trị nội bộ", "An ninh kinh tế", "An ninh mạng", "Trật tự xã hội",
            "Phòng cháy chữa cháy", "Giao thông", "Cứu nạn cứu hộ", "Phòng ngừa tội phạm",
            "Đấu tranh tội phạm", "Xây dựng phong trào", "Cải cách hành chính", "Hợp tác quốc tế",
            "Tuyên truyền pháp luật", "Đào tạo bồi dưỡng", "Công tác xây dựng lực lượng",
            "Khen thưởng kỷ luật", "Quản lý hành chính", "Tổng hợp"
        ]
    },
    "Đơn vị": {
        "code": "contact_unit",
        "linked_modules": "Danh bạ",
        "aliases": ["Don vi"],
        "bindings": [{"module": "contacts", "field": "unit_name", "label": "Đơn vị", "required": True}],
        "items": [
            "Phòng PC06", "Công an huyện", "Công an thị xã", "Công an thành phố", "Công an xã",
            "Công an phường", "Công an thị trấn", "UBND xã", "UBND phường", "UBND thị trấn", "Ban Công an xã"
        ]
    },
    "Đội nghiệp vụ": {
        "code": "task_unit",
        "linked_modules": "Công việc,Bảng tin",
        "aliases": ["Dong nghiep vu"],
        "bindings": [
            {"module": "tasks", "field": "domain", "label": "Đội nghiệp vụ", "required": True}
        ],
        "items": [
            "Đội An ninh", "Đội Trật tự", "Đội PC&CC", "Đội Giao thông", "Đội Cảnh sát hình sự",
            "Đội Cảnh sát kinh tế", "Đội Cảnh sát ma túy", "Đội Cảnh sát môi trường",
            "Đội Cảnh sát giao thông", "Đội Cảnh sát PCCC&CNCH", "Phòng Tổng hợp", "Phòng Chính trị", "Phòng Hậu cần"
        ]
    },
    "Loại công việc": {
        "code": "task_type",
        "linked_modules": "Công việc",
        "aliases": ["Loai cong viec"],
        "bindings": [{"module": "tasks", "field": "task_type", "label": "Loại công việc", "required": False}],
        "items": [
            "Công việc thường xuyên", "Công việc đột xuất", "Chỉ đạo điều hành", "Đề án dự án", "Kế hoạch",
            "Báo cáo", "Tổng kết", "Kiểm tra", "Thanh tra", "Phối hợp liên ngành", "Hội nghị", "Tập huấn", "Học tập"
        ]
    },
    "Mức độ ưu tiên": {
        "code": "task_priority",
        "linked_modules": "Công việc",
        "aliases": ["Muc do uu tien"],
        "bindings": [{"module": "tasks", "field": "priority", "label": "Mức độ ưu tiên", "required": False}],
        "items": ["Khẩn cấp", "Cao", "Trung bình", "Thấp"]
    },
    "Trạng thái công việc": {
        "code": "task_status",
        "linked_modules": "Công việc",
        "aliases": ["Trang thai cong viec"],
        "bindings": [{"module": "tasks", "field": "initial_status", "label": "Trạng thái công việc", "required": False}],
        "items": ["Chưa bắt đầu", "Đang thực hiện", "Tạm dừng", "Hoàn thành", "Quá hạn", "Đã hủy"]
    },
    "Loại tài liệu": {
        "code": "library_type",
        "linked_modules": "Thư viện",
        "aliases": ["Loai tai lieu"],
        "bindings": [{"module": "library", "field": "document_type", "label": "Loại tài liệu", "required": False}],
        "items": [
            "Văn bản pháp luật", "Công văn chỉ đạo", "Biểu mẫu", "Quy trình quy chế", "Tài liệu đào tạo",
            "Tài liệu tham khảo", "Báo cáo tổng kết", "Kế hoạch", "Dự thảo", "Khác"
        ]
    }
}


def seed_categories():
    """Tạo tất cả các danh mục mặc định nếu chưa tồn tại."""
    with app.app_context():
        print("🔄 Bắt đầu khởi tạo danh mục mặc định...")

        created_groups = 0
        created_items = 0
        updated_groups = 0

        module_map = {}
        for module_data in MODULES:
            module = ModuleRegistry.query.filter_by(code=module_data['code']).first()
            if not module:
                module = ModuleRegistry(**module_data)
                db.session.add(module)
                db.session.flush()
            else:
                module.name = module_data['name']
                module.sort_order = module_data['sort_order']
                module.is_active = True
            module_map[module.code] = module

        for group_name, group_data in DEFAULT_CATEGORIES.items():
            aliases = group_data.get("aliases", [])
            group_code = group_data.get('code') or resolve_group_code(group_name)
            group = CategoryGroup.query.filter(
                (CategoryGroup.code == group_code) | (CategoryGroup.name.in_([group_name, *aliases]))
            ).first()

            if not group:
                group = CategoryGroup(
                    code=group_code,
                    name=group_name,
                    linked_modules=group_data.get("linked_modules", ""),
                    is_active=True,
                    sort_order=0
                )
                db.session.add(group)
                db.session.flush()
                created_groups += 1
                print(f"  ✅ Tạo nhóm: {group_name}")
            else:
                if group.name != group_name:
                    print(f"  🔁 Chuẩn hóa tên nhóm: {group.name} -> {group_name}")
                    group.name = group_name
                    updated_groups += 1
                if group.code != group_code:
                    group.code = group_code
                    updated_groups += 1
                if group.linked_modules != group_data.get("linked_modules", ""):
                    group.linked_modules = group_data.get("linked_modules", "")
                    updated_groups += 1
                group.is_active = True
                print(f"  ⏭️  Nhóm đã tồn tại: {group_name}")

            existing_links = {link.module.code for link in group.module_links if link.module}
            for link_name in [part.strip() for part in (group_data.get('linked_modules') or '').split(',') if part.strip()]:
                module_code = next((m['code'] for m in MODULES if m['name'] == link_name), None)
                if module_code and module_code not in existing_links:
                    db.session.add(CategoryGroupModule(group_id=group.id, module_id=module_map[module_code].id))
                    existing_links.add(module_code)

            existing_items = {item.name for item in group.items}
            for index, item_name in enumerate(group_data.get("items", []), start=1):
                if item_name not in existing_items:
                    item = CategoryItem(
                        group_id=group.id,
                        code=slugify_code(item_name),
                        name=item_name,
                        is_active=True,
                        sort_order=index
                    )
                    db.session.add(item)
                    created_items += 1
                    print(f"      ➕ Thêm mục: {item_name}")

            for binding_data in group_data.get('bindings', []):
                module = module_map.get(binding_data['module'])
                if not module:
                    continue
                binding = ModuleFieldBinding.query.filter_by(module_id=module.id, field_code=binding_data['field']).first()
                if not binding:
                    binding = ModuleFieldBinding(
                        module_id=module.id,
                        field_code=binding_data['field'],
                        field_label=binding_data.get('label'),
                        group_id=group.id,
                        is_required=binding_data.get('required', False),
                        allow_multiple_groups=binding_data.get('allow_multiple_groups', False)
                    )
                    db.session.add(binding)
                else:
                    binding.group_id = group.id
                    binding.field_label = binding_data.get('label')
                    binding.is_required = binding_data.get('required', False)
                    binding.allow_multiple_groups = binding_data.get('allow_multiple_groups', False)

        db.session.commit()

        print(f"\n✅ Hoàn thành!")
        print(f"   - Nhóm danh mục mới: {created_groups}")
        print(f"   - Nhóm danh mục cập nhật: {updated_groups}")
        print(f"   - Mục danh mục mới: {created_items}")
        print(f"\n📝 Người quản trị có thể vào 'Thiết lập danh mục' để thêm/sửa/xóa các mục.")


if __name__ == "__main__":
    seed_categories()