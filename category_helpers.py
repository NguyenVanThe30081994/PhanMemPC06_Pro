# -*- coding: utf-8 -*-
from models import CategoryGroup, CategoryItem

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

MODULE_GROUP_MAP = {
    'Danh bạ': ['Nhóm danh bạ', 'Chức vụ', 'Lĩnh vực', 'Đơn vị'],
    'Bảng tin': ['Lĩnh vực', 'Đội nghiệp vụ'],
    'Thư viện': ['Lĩnh vực', 'Loại tài liệu'],
    'Công việc': ['Đội nghiệp vụ', 'Loại công việc', 'Mức độ ưu tiên', 'Trạng thái công việc'],
}


def get_category_group(*canonical_names):
    for canonical_name in canonical_names:
        aliases = CATEGORY_GROUP_ALIASES.get(canonical_name, [canonical_name])
        group = CategoryGroup.query.filter(CategoryGroup.name.in_(aliases)).first()
        if group:
            return group
    return None


def get_category_items(*canonical_names):
    group = get_category_group(*canonical_names)
    if not group:
        return []
    return CategoryItem.query.filter_by(group_id=group.id).order_by(CategoryItem.name.asc()).all()


def get_module_categories(module_name):
    result = {}
    for group_name in MODULE_GROUP_MAP.get(module_name, []):
        result[group_name] = get_category_items(group_name)
    return result
