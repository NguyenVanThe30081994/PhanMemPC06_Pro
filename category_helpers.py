# -*- coding: utf-8 -*-
import re
import unicodedata

from models import CategoryGroup, CategoryItem, ModuleRegistry, CategoryGroupModule, ModuleFieldBinding

CATEGORY_GROUP_ALIASES = {
    'Nhóm danh bạ': ['Nhóm danh bạ', 'Nhom danh ba'],
    'Chức vụ': ['Chức vụ', 'Chuc vu'],
    'Lĩnh vực': ['Lĩnh vực', 'Linh vuc'],
    'Đơn vị': ['Đơn vị', 'Don vi'],
    'Đội nghiệp vụ': ['Đội nghiệp vụ', 'Dong nghiep vu'],
    'Loại công việc': ['Loại công việc', 'Loai cong viec'],
    'Mức độ ưu tiên': ['Mức độ ưu tiên', 'Muc do uu tien'],
    'Trạng thái công việc': ['Trạng thái công việc', 'Trang thai cong viec'],
    'Loại tài liệu': ['Loại tài liệu', 'Loai tai lieu'],
}

GROUP_CODE_ALIASES = {
    'Nhóm danh bạ': 'contact_group',
    'Chức vụ': 'contact_role',
    'Lĩnh vực': 'news_domain',
    'Đơn vị': 'contact_unit',
    'Đội nghiệp vụ': 'task_unit',
    'Loại công việc': 'task_type',
    'Mức độ ưu tiên': 'task_priority',
    'Trạng thái công việc': 'task_status',
    'Loại tài liệu': 'library_type',
}

LEGACY_MODULE_GROUP_MAP = {
    'Danh bạ': ['Nhóm danh bạ', 'Chức vụ', 'Lĩnh vực', 'Đơn vị'],
    'Bảng tin': ['Lĩnh vực', 'Đội nghiệp vụ'],
    'Thư viện': ['Lĩnh vực', 'Loại tài liệu'],
    'Công việc': ['Đội nghiệp vụ', 'Loại công việc', 'Mức độ ưu tiên', 'Trạng thái công việc'],
}


def slugify_code(value):
    text = unicodedata.normalize('NFKD', str(value or '').strip().lower())
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace('đ', 'd')
    text = re.sub(r'[^0-9a-z]+', ' ', text)
    return '_'.join(part for part in text.split() if part)


def resolve_group_code(name):
    if not name:
        return None
    return GROUP_CODE_ALIASES.get(name) or slugify_code(name)


def get_category_group(*canonical_names):
    for canonical_name in canonical_names:
        group_code = resolve_group_code(canonical_name)
        if group_code:
            group = CategoryGroup.query.filter_by(code=group_code).first()
            if group:
                return group
        aliases = CATEGORY_GROUP_ALIASES.get(canonical_name, [canonical_name])
        group = CategoryGroup.query.filter(CategoryGroup.name.in_(aliases)).first()
        if group:
            return group
    return None


def get_category_items(*canonical_names):
    group = get_category_group(*canonical_names)
    if not group:
        return []
    return CategoryItem.query.filter_by(group_id=group.id, is_active=True).order_by(CategoryItem.sort_order.asc(), CategoryItem.name.asc()).all()


def get_module_registry(module_code):
    return ModuleRegistry.query.filter_by(code=module_code, is_active=True).first()


def get_bound_group(module_code, field_code):
    module = get_module_registry(module_code)
    if module:
        binding = ModuleFieldBinding.query.filter_by(module_id=module.id, field_code=field_code).first()
        if binding and binding.group and binding.group.is_active:
            return binding.group

    legacy_map = {
        'news': {'category': ['Lĩnh vực', 'Đội nghiệp vụ']},
        'library': {'category': ['Lĩnh vực', 'Loại tài liệu']},
        'tasks': {
            'domain': ['Đội nghiệp vụ'],
            'task_type': ['Loại công việc'],
            'priority': ['Mức độ ưu tiên'],
            'initial_status': ['Trạng thái công việc']
        },
        'contacts': {
            'contact_group': ['Nhóm danh bạ'],
            'role': ['Chức vụ'],
            'unit_name': ['Đơn vị'],
            'category': ['Lĩnh vực']
        }
    }
    for group_name in legacy_map.get(module_code, {}).get(field_code, []):
        group = get_category_group(group_name)
        if group:
            return group
    return None


def get_module_field_items(module_code, field_code):
    group = get_bound_group(module_code, field_code)
    if not group:
        return []
    return CategoryItem.query.filter_by(group_id=group.id, is_active=True).order_by(CategoryItem.sort_order.asc(), CategoryItem.name.asc()).all()


def get_module_categories(module_name):
    result = {}
    for group_name in LEGACY_MODULE_GROUP_MAP.get(module_name, []):
        result[group_name] = get_category_items(group_name)
    return result
