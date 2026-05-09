# -*- coding: utf-8 -*-
import re
import unicodedata

from models import CategoryGroup, CategoryItem, ModuleRegistry, CategoryGroupModule, ModuleFieldBinding, db

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


def module_category_options(module_code, field_code, *fallback_names):
    items = get_module_field_items(module_code, field_code)
    if not items:
        items = get_category_items(*fallback_names)
    results = []
    for item in items:
        value = (item.code or slugify_code(item.name) or item.name or '').strip()
        if not value:
            continue
        results.append({
            'id': item.id,
            'code': (item.code or '').strip(),
            'value': value,
            'stable_value': f"category_item:{item.id}",
            'name': (item.name or '').strip() or value,
            'slug': slugify_code(item.name or value),
        })
    return results


def category_resolver(category_options):
    mapping = {}
    for item in category_options or []:
        keys = {
            f"category_item:{item.get('id')}" if item.get('id') is not None else '',
            str(item.get('id')) if item.get('id') is not None else '',
            (item.get('value') or '').strip().lower(),
            (item.get('code') or '').strip().lower(),
            (item.get('name') or '').strip().lower(),
            slugify_code(item.get('value') or ''),
            slugify_code(item.get('code') or ''),
            slugify_code(item.get('name') or ''),
        }
        for key in keys:
            if key:
                mapping[str(key).strip().lower()] = item
    return mapping


def resolve_category_display(value, category_options, fallback_label='Chưa phân loại'):
    raw_value = (value or '').strip()
    if not raw_value:
        return {
            'raw_value': '',
            'display_name': fallback_label,
            'filter_value': '__uncategorized__',
            'option': None,
        }
    resolver = category_resolver(category_options)
    item = resolver.get(raw_value.lower()) or resolver.get(slugify_code(raw_value))
    if item:
        return {
            'raw_value': raw_value,
            'display_name': item['name'],
            'filter_value': item['slug'] or slugify_code(item['name']) or '__uncategorized__',
            'option': item,
        }
    return {
        'raw_value': raw_value,
        'display_name': raw_value,
        'filter_value': slugify_code(raw_value) or '__uncategorized__',
        'option': None,
    }


def canonicalize_category_value(value, category_options, prefer_stable=False):
    resolved = resolve_category_display(value, category_options, fallback_label='')
    option = resolved.get('option')
    if not option:
        return (value or '').strip()
    preferred = option.get('stable_value') if prefer_stable else option.get('value')
    return (preferred or option.get('value') or option.get('name') or '').strip()


def sync_record_categories(records, category_options, attr_name='category', prefer_stable=False):
    changed = False
    for record in records or []:
        current_value = getattr(record, attr_name, '') or ''
        canonical_value = canonicalize_category_value(
            current_value,
            category_options,
            prefer_stable=prefer_stable,
        )
        if canonical_value and canonical_value != current_value:
            setattr(record, attr_name, canonical_value)
            changed = True
    if changed:
        db.session.commit()
    return records


def stable_form_category_options(category_options):
    return [
        {
            **item,
            'value': item.get('stable_value') or item.get('value') or '',
        }
        for item in category_options or []
    ]


def decorate_records_with_category(records, category_options, fallback_label='Chưa phân loại', attr_name='category'):
    decorated = []
    for record in records or []:
        category_info = resolve_category_display(
            getattr(record, attr_name, ''),
            category_options,
            fallback_label=fallback_label,
        )
        decorated.append({
            'record': record,
            'category_display': category_info['display_name'],
            'category_filter': category_info['filter_value'],
            'category_raw': category_info['raw_value'],
            'category_option': category_info['option'],
        })
    return decorated


def category_filter_counts(items, category_options, empty_label='Chưa phân loại'):
    counts = {item['slug']: 0 for item in category_options or [] if item.get('slug')}
    uncategorized_total = 0
    for item in items or []:
        filter_value = item.get('category_filter') or '__uncategorized__'
        if filter_value in counts:
            counts[filter_value] += 1
        else:
            uncategorized_total += 1
    filters = []
    for option in category_options or []:
        filters.append({
            'name': option['name'],
            'filter_value': option['slug'] or '__uncategorized__',
            'count': counts.get(option['slug'], 0),
        })
    if uncategorized_total:
        filters.append({
            'name': empty_label,
            'filter_value': '__uncategorized__',
            'count': uncategorized_total,
        })
    return filters


def apply_reference_display(records, attr_name, category_options, display_attr=None, fallback_label=''):
    display_attr = display_attr or f"{attr_name}_display"
    for record in records or []:
        value = getattr(record, attr_name, '')
        display_name = resolve_category_display(value, category_options, fallback_label=fallback_label)['display_name']
        setattr(record, display_attr, display_name)
    return records
