# -*- coding: utf-8 -*-
import re
import unicodedata

from flask import g, has_request_context

from models import CategoryGroup, CategoryItem, CategoryItemAlias, ModuleRegistry, CategoryGroupModule, ModuleFieldBinding, db

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
    'Phân hệ hồ sơ': ['Phân hệ hồ sơ', 'Phan he ho so'],
    'Loại hồ sơ': ['Loại hồ sơ', 'Loai ho so'],
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
    'Phân hệ hồ sơ': 'dossier_tab',
    'Loại hồ sơ': 'dossier_type',
}

LEGACY_MODULE_GROUP_MAP = {
    'Danh bạ': ['Nhóm danh bạ', 'Chức vụ', 'Lĩnh vực', 'Đơn vị'],
    'Bảng tin': ['Lĩnh vực', 'Đội nghiệp vụ'],
    'Thư viện': ['Lĩnh vực', 'Loại tài liệu'],
    'Thông báo': ['Lĩnh vực', 'Đội nghiệp vụ', 'Loại tài liệu'],
    'Công việc': ['Lĩnh vực', 'Đội nghiệp vụ', 'Loại công việc', 'Mức độ ưu tiên', 'Trạng thái công việc'],
    'Sổ hồ sơ': ['Phân hệ hồ sơ', 'Loại hồ sơ'],
}

LEGACY_ITEM_ALIAS_SEEDS = {
    'news_domain': {
        'nghi_quyet_57': [
            'Phát triển KHCN, ĐMST, CĐS',
            'Phat trien KHCN, DMST, CDS',
            'phat_trien_khcn_dmst_cds',
        ],
    },
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
        'notify': {
            'category': ['Lĩnh vực', 'Đội nghiệp vụ'],
            'document_type': ['Loại tài liệu'],
        },
        'news': {'category': ['Lĩnh vực', 'Đội nghiệp vụ']},
        'library': {'category': ['Lĩnh vực', 'Loại tài liệu']},
        'tasks': {
            'category': ['Lĩnh vực', 'Đội nghiệp vụ'],
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
        },
        'dossiers': {
            'category_tab': ['Phân hệ hồ sơ'],
            'loai': ['Loại hồ sơ'],
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


def ensure_category_item_alias(item, alias_name):
    alias_name = (alias_name or '').strip()
    if not item or not alias_name:
        return None
    alias_slug = slugify_code(alias_name)
    existing = CategoryItemAlias.query.filter_by(item_id=item.id, alias_slug=alias_slug).first()
    if existing:
        if existing.alias_name != alias_name:
            existing.alias_name = alias_name
        return existing
    alias = CategoryItemAlias(item_id=item.id, alias_name=alias_name, alias_slug=alias_slug)
    db.session.add(alias)
    return alias


def _bootstrap_seed_aliases(items):
    if not items:
        return
    group_code = ((getattr(items[0], 'group', None) and getattr(items[0].group, 'code', None)) or '').strip()
    seed_map = LEGACY_ITEM_ALIAS_SEEDS.get(group_code, {})
    if not seed_map:
        return
    item_by_slug = {
        slugify_code((item.name or item.code or '').strip()): item
        for item in items
        if (item.name or item.code)
    }
    changed = False
    for target_slug, aliases in seed_map.items():
        target_item = item_by_slug.get(target_slug)
        if not target_item:
            continue
        for alias_name in aliases:
            alias_slug = slugify_code(alias_name)
            exists = CategoryItemAlias.query.filter_by(item_id=target_item.id, alias_slug=alias_slug).first()
            if exists:
                continue
            ensure_category_item_alias(target_item, alias_name)
            changed = True
    if changed:
        db.session.commit()


def module_category_options(module_code, field_code, *fallback_names):
    items = get_module_field_items(module_code, field_code)
    if not items:
        items = get_category_items(*fallback_names)
    _bootstrap_seed_aliases(items)
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
    cache_key = tuple(
        (
            item.get('id'),
            item.get('code'),
            item.get('value'),
            item.get('stable_value'),
            item.get('name'),
            item.get('slug'),
        )
        for item in (category_options or [])
    )
    if has_request_context():
        cache = getattr(g, '_category_resolver_cache', None)
        if cache is None:
            cache = {}
            g._category_resolver_cache = cache
        if cache_key in cache:
            return cache[cache_key]

    mapping = {}
    item_ids = [item.get('id') for item in category_options or [] if item.get('id') is not None]
    alias_rows = CategoryItemAlias.query.filter(CategoryItemAlias.item_id.in_(item_ids)).all() if item_ids else []
    alias_map = {}
    for alias in alias_rows:
        alias_map.setdefault(alias.item_id, []).append(alias)
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
        for alias in alias_map.get(item.get('id'), []):
            for key in {
                (alias.alias_name or '').strip().lower(),
                (alias.alias_slug or '').strip().lower(),
                slugify_code(alias.alias_name or ''),
            }:
                if key:
                    mapping[str(key).strip().lower()] = item
    if has_request_context():
        g._category_resolver_cache[cache_key] = mapping
    return mapping


def _lookup_category_item_by_ref(raw_value):
    text = (raw_value or '').strip()
    if not text.lower().startswith('category_item:'):
        return None
    try:
        item_id = int(text.split(':', 1)[1].strip())
    except (TypeError, ValueError):
        return None
    if has_request_context():
        ref_cache = getattr(g, '_category_item_ref_cache', None)
        if ref_cache is None:
            ref_cache = {}
            g._category_item_ref_cache = ref_cache
        if item_id in ref_cache:
            return ref_cache[item_id]
        item = db.session.get(CategoryItem, item_id)
        ref_cache[item_id] = item
        return item
    return db.session.get(CategoryItem, item_id)


def resolve_category_display(value, category_options, fallback_label='Chưa phân loại', allow_unknown_label=True):
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
    ref_item = _lookup_category_item_by_ref(raw_value)
    if ref_item and (ref_item.name or '').strip():
        ref_name = ref_item.name.strip()
        return {
            'raw_value': raw_value,
            'display_name': ref_name,
            'filter_value': slugify_code(ref_name) or '__uncategorized__',
            'option': {
                'id': ref_item.id,
                'code': (ref_item.code or '').strip(),
                'value': (ref_item.code or ref_name).strip(),
                'stable_value': f'category_item:{ref_item.id}',
                'name': ref_name,
                'slug': slugify_code(ref_name),
            },
        }
    if not allow_unknown_label:
        return {
            'raw_value': raw_value,
            'display_name': fallback_label,
            'filter_value': '__uncategorized__',
            'option': None,
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


def decorate_records_with_category(records, category_options, fallback_label='Chưa phân loại', attr_name='category', allow_unknown_label=True):
    decorated = []
    for record in records or []:
        category_info = resolve_category_display(
            getattr(record, attr_name, ''),
            category_options,
            fallback_label=fallback_label,
            allow_unknown_label=allow_unknown_label,
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


# ==================== QUẢN TRỊ TẬP TRUNG & ĐỒNG BỘ 2 CHIỀU ====================

UNIFIED_MODULE_SPECS = [
    {'code': 'notify', 'name': 'Thông báo', 'sort_order': 10},
    {'code': 'tasks', 'name': 'Công việc', 'sort_order': 30},
    {'code': 'contacts', 'name': 'Danh bạ', 'sort_order': 40},
    {'code': 'dossiers', 'name': 'Sổ theo dõi hồ sơ', 'sort_order': 50},
]

DEFAULT_DOSSIER_TAB_ITEMS = [
    ('tam_tru', 'Tạm trú', 10),
    ('thuong_tru', 'Thường trú', 20),
    ('ct10', 'Phiếu XM CT10', 30),
    ('tich_hop', 'Tích hợp giấy tờ', 40),
    ('lam_sach', 'Làm sạch dữ liệu', 50),
    ('khac', 'Hồ sơ khác', 60),
]

DEFAULT_DOSSIER_LOAI_ITEMS = [
    ('can-cuoc', 'Căn cước', 10),
    ('cu-tru', 'Cư trú', 20),
    ('dinh-danh', 'Định danh VNeID', 30),
    ('xac-thuc', 'Xác thực ĐA06', 40),
    ('khac', 'Hồ sơ khác', 50),
]

DEFAULT_UNIFIED_GROUP_SPECS = [
    ('contact_group', 'Nhóm danh bạ', 'Danh bạ', 10, []),
    ('contact_role', 'Chức vụ', 'Danh bạ', 20, []),
    ('news_domain', 'Lĩnh vực', 'Thông báo,Công việc,Danh bạ', 30, []),
    ('contact_unit', 'Đơn vị', 'Danh bạ', 40, []),
    ('task_unit', 'Đội nghiệp vụ', 'Công việc,Thông báo', 50, []),
    ('task_type', 'Loại công việc', 'Công việc', 60, []),
    ('task_priority', 'Mức độ ưu tiên', 'Công việc', 70, []),
    ('task_status', 'Trạng thái công việc', 'Công việc', 80, []),
    ('library_type', 'Loại tài liệu', 'Thông báo', 90, []),
    ('dossier_tab', 'Phân hệ hồ sơ', 'Sổ theo dõi hồ sơ', 100, DEFAULT_DOSSIER_TAB_ITEMS),
    ('dossier_type', 'Loại hồ sơ', 'Sổ theo dõi hồ sơ', 110, DEFAULT_DOSSIER_LOAI_ITEMS),
]

DEFAULT_UNIFIED_FIELD_BINDINGS = [
    ('notify', 'category', 'Lĩnh vực / Đội nghiệp vụ', 'news_domain', True),
    ('notify', 'document_type', 'Loại tài liệu', 'library_type', False),
    ('tasks', 'category', 'Lĩnh vực', 'news_domain', False),
    ('tasks', 'domain', 'Đội nghiệp vụ', 'task_unit', True),
    ('tasks', 'task_type', 'Loại công việc', 'task_type', False),
    ('tasks', 'priority', 'Mức độ ưu tiên', 'task_priority', False),
    ('tasks', 'initial_status', 'Trạng thái công việc', 'task_status', False),
    ('contacts', 'contact_group', 'Nhóm danh bạ', 'contact_group', True),
    ('contacts', 'role', 'Chức vụ', 'contact_role', True),
    ('contacts', 'unit_name', 'Đơn vị', 'contact_unit', True),
    ('contacts', 'category', 'Lĩnh vực', 'news_domain', False),
    ('dossiers', 'category_tab', 'Phân hệ hồ sơ', 'dossier_tab', True),
    ('dossiers', 'loai', 'Loại hồ sơ', 'dossier_type', False),
]


def _clear_category_request_caches():
    if has_request_context():
        for attr in ('_category_resolver_cache', '_category_item_ref_cache', '_task_assignment_unit_options'):
            if hasattr(g, attr):
                delattr(g, attr)


def _find_item_in_group(group, raw_value):
    text = (raw_value or '').strip()
    if not group or not text:
        return None
    if text.lower().startswith('category_item:'):
        item = _lookup_category_item_by_ref(text)
        if item and item.group_id == group.id:
            return item
        return None
    text_lower = text.lower()
    text_slug = slugify_code(text)
    items = CategoryItem.query.filter_by(group_id=group.id).all()
    for item in items:
        if (item.code or '').strip().lower() == text_lower or (item.name or '').strip().lower() == text_lower:
            return item
        if text_slug and (slugify_code(item.name or '') == text_slug or slugify_code(item.code or '') == text_slug):
            return item
    if items:
        aliases = CategoryItemAlias.query.filter(
            CategoryItemAlias.item_id.in_([i.id for i in items])
        ).all()
        item_map = {i.id: i for i in items}
        for alias in aliases:
            if (alias.alias_name or '').strip().lower() == text_lower or (text_slug and (alias.alias_slug or '') == text_slug):
                return item_map.get(alias.item_id)
    return None


def _ensure_item_in_group(group, name, code=None, is_active=True, sort_order=None):
    clean_name = (name or '').strip()
    if not group or not clean_name or clean_name.lower().startswith('category_item:'):
        return None, False
    existing = _find_item_in_group(group, clean_name)
    if not existing and code:
        existing = _find_item_in_group(group, code)
    if existing:
        return existing, False
    item_code = (code or slugify_code(clean_name) or clean_name[:80]).strip()
    max_order = db.session.query(db.func.max(CategoryItem.sort_order)).filter_by(group_id=group.id).scalar() or 0
    order_val = int(sort_order) if sort_order is not None else int(max_order) + 10
    item = CategoryItem(
        group_id=group.id,
        code=item_code,
        name=clean_name,
        is_active=bool(is_active),
        sort_order=order_val,
    )
    db.session.add(item)
    db.session.flush()
    return item, True


def ensure_unified_category_catalog(commit=True):
    """Đảm bảo ModuleRegistry, các nhóm danh mục mặc định (bao gồm Sổ hồ sơ) và ModuleFieldBinding đầy đủ."""
    module_map = {}
    for spec in UNIFIED_MODULE_SPECS:
        mod = ModuleRegistry.query.filter_by(code=spec['code']).first()
        if not mod:
            mod = ModuleRegistry(
                code=spec['code'],
                name=spec['name'],
                sort_order=spec['sort_order'],
                is_active=True,
            )
            db.session.add(mod)
            db.session.flush()
        module_map[spec['code']] = mod

    group_map = {}
    for gcode, gname, linked_modules, gorder, default_items in DEFAULT_UNIFIED_GROUP_SPECS:
        grp = CategoryGroup.query.filter_by(code=gcode).first()
        if not grp:
            grp = CategoryGroup.query.filter_by(name=gname).first()
        if not grp:
            grp = CategoryGroup(
                code=gcode,
                name=gname,
                linked_modules=linked_modules,
                is_active=True,
                sort_order=gorder,
            )
            db.session.add(grp)
            db.session.flush()
        elif not grp.code:
            grp.code = gcode
        group_map[gcode] = grp

        for mod_name in [m.strip() for m in linked_modules.split(',') if m.strip()]:
            mod_obj = next((m for m in module_map.values() if m.name == mod_name), None)
            if mod_obj and not CategoryGroupModule.query.filter_by(group_id=grp.id, module_id=mod_obj.id).first():
                db.session.add(CategoryGroupModule(group_id=grp.id, module_id=mod_obj.id))

        for item_code, item_name, item_order in default_items:
            _ensure_item_in_group(grp, item_name, code=item_code, is_active=True, sort_order=item_order)

    for mod_code, field_code, field_label, group_code, required in DEFAULT_UNIFIED_FIELD_BINDINGS:
        mod_obj = module_map.get(mod_code)
        grp_obj = group_map.get(group_code)
        if not mod_obj or not grp_obj:
            continue
        binding = ModuleFieldBinding.query.filter_by(module_id=mod_obj.id, field_code=field_code).first()
        if not binding:
            db.session.add(
                ModuleFieldBinding(
                    module_id=mod_obj.id,
                    field_code=field_code,
                    field_label=field_label,
                    group_id=grp_obj.id,
                    is_required=required,
                )
            )

    if commit:
        db.session.commit()
        _clear_category_request_caches()
    return module_map, group_map


def _bound_targets_for_group(group):
    """Trả về danh sách (model_cls, field_attr, is_code_field) gắn với nhóm danh mục này."""
    from models import (
        Contact, DocumentLib, Dossier, NewsDoc, NotificationDoc, ShortLink, Task,
    )
    binding_model_map = {
        ('notify', 'category'): [(NotificationDoc, 'category', False), (NewsDoc, 'category', False), (DocumentLib, 'category', False), (ShortLink, 'category', False)],
        ('notify', 'document_type'): [],
        ('tasks', 'category'): [(Task, 'category', False)],
        ('tasks', 'domain'): [(Task, 'domain', False), (ShortLink, 'domain', False)],
        ('tasks', 'task_type'): [(Task, 'task_type', False)],
        ('tasks', 'priority'): [(Task, 'priority', False)],
        ('contacts', 'contact_group'): [(Contact, 'contact_group', False)],
        ('contacts', 'role'): [(Contact, 'role', False)],
        ('contacts', 'unit_name'): [(Contact, 'unit_name', False)],
        ('contacts', 'category'): [],
        ('dossiers', 'category_tab'): [(Dossier, 'category_tab', True)],
        ('dossiers', 'loai'): [(Dossier, 'loai', True)],
    }
    group_code_fallbacks = {
        'news_domain': [('notify', 'category'), ('tasks', 'category')],
        'task_unit': [('tasks', 'domain')],
        'task_type': [('tasks', 'task_type')],
        'task_priority': [('tasks', 'priority')],
        'contact_group': [('contacts', 'contact_group')],
        'contact_role': [('contacts', 'role')],
        'contact_unit': [('contacts', 'unit_name')],
        'dossier_tab': [('dossiers', 'category_tab')],
        'dossier_type': [('dossiers', 'loai')],
    }
    pairs = set()
    bindings = ModuleFieldBinding.query.filter_by(group_id=group.id).all()
    for b in bindings:
        if b.module and b.module.code:
            pairs.add((b.module.code, b.field_code))
    for p in group_code_fallbacks.get((group.code or '').strip(), []):
        pairs.add(p)
    targets = []
    seen = set()
    for pair in pairs:
        for triple in binding_model_map.get(pair, []):
            key = (triple[0].__name__, triple[1])
            if key not in seen:
                seen.add(key)
                targets.append(triple)
    return targets


def harvest_feature_categories_to_admin(commit=True):
    """Quét và gom toàn bộ danh mục đã tạo/phát sinh trong các chức năng về quản trị tập trung."""
    import json
    from models import (
        Category, Contact, ContactGroup, ContactRole, DocumentLib, Dossier,
        LibraryField, MasterData, NewsCategory, NewsDoc, NotificationDoc,
        ProfessionalUnit, ShortLink, Task, TaskImportDraft, Unit,
    )
    ensure_unified_category_catalog(commit=False)

    added_count = 0

    def _harvest_val(group, raw_val, display_hint=None):
        nonlocal added_count
        val = (raw_val or '').strip()
        if not val or val.lower().startswith('category_item:') or val == '__uncategorized__':
            return
        if _find_item_in_group(group, val):
            return
        _, created = _ensure_item_in_group(group, display_hint or val, code=slugify_code(val) or val)
        if created:
            added_count += 1

    # 1. Đồng bộ đơn vị hành chính -> contact_unit
    unit_group = get_bound_group('contacts', 'unit_name') or get_category_group('Đơn vị')
    if unit_group:
        for u in Unit.query.order_by(Unit.sort_order.asc(), Unit.id.asc()).all():
            if (u.code or '').strip().lower() == 'hethong':
                continue
            existing = _find_item_in_group(unit_group, u.code) or _find_item_in_group(unit_group, u.name)
            if not existing:
                _, created = _ensure_item_in_group(
                    unit_group, u.name, code=u.code, is_active=bool(u.is_active), sort_order=u.sort_order or 0
                )
                if created:
                    added_count += 1

    # 2. Quét danh mục từ bảng Công việc & Bản nháp cấu hình
    g_task_cat = get_bound_group('tasks', 'category') or get_category_group('Lĩnh vực')
    g_task_dom = get_bound_group('tasks', 'domain') or get_category_group('Đội nghiệp vụ')
    g_task_type = get_bound_group('tasks', 'task_type') or get_category_group('Loại công việc')
    g_task_prio = get_bound_group('tasks', 'priority') or get_category_group('Mức độ ưu tiên')
    for t in Task.query.with_entities(Task.category, Task.domain, Task.task_type, Task.priority).all():
        if g_task_cat:
            _harvest_val(g_task_cat, t.category)
        if g_task_dom:
            _harvest_val(g_task_dom, t.domain)
        if g_task_type:
            _harvest_val(g_task_type, t.task_type)
        if g_task_prio:
            _harvest_val(g_task_prio, t.priority)

    for draft in TaskImportDraft.query.with_entities(TaskImportDraft.working_config_json).all():
        if not draft.working_config_json:
            continue
        try:
            cfg = json.loads(draft.working_config_json)
        except Exception:
            continue
        if not isinstance(cfg, dict):
            continue
        if g_task_cat:
            _harvest_val(g_task_cat, cfg.get('category'))
        if g_task_dom:
            _harvest_val(g_task_dom, cfg.get('domain'))
        if g_task_type:
            _harvest_val(g_task_type, cfg.get('task_type'))
        if g_task_prio:
            _harvest_val(g_task_prio, cfg.get('priority'))

    # 3. Quét Danh bạ
    g_c_grp = get_bound_group('contacts', 'contact_group') or get_category_group('Nhóm danh bạ')
    g_c_role = get_bound_group('contacts', 'role') or get_category_group('Chức vụ')
    for c in Contact.query.with_entities(Contact.contact_group, Contact.role, Contact.unit_name).all():
        if g_c_grp:
            _harvest_val(g_c_grp, c.contact_group)
        if g_c_role:
            _harvest_val(g_c_role, c.role)
        if unit_group:
            _harvest_val(unit_group, c.unit_name)

    # 4. Quét Thông báo, Bảng tin, Thư viện, Liên kết rút gọn
    g_notify_cat = get_bound_group('notify', 'category') or get_category_group('Lĩnh vực')
    if g_notify_cat:
        for (cat_val,) in NotificationDoc.query.with_entities(NotificationDoc.category).distinct().all():
            _harvest_val(g_notify_cat, cat_val)
        for (cat_val,) in NewsDoc.query.with_entities(NewsDoc.category).distinct().all():
            _harvest_val(g_notify_cat, cat_val)
        for (cat_val,) in DocumentLib.query.with_entities(DocumentLib.category).distinct().all():
            _harvest_val(g_notify_cat, cat_val)
    for cat_val, dom_val in ShortLink.query.with_entities(ShortLink.category, ShortLink.domain).distinct().all():
        if g_notify_cat:
            _harvest_val(g_notify_cat, cat_val)
        if g_task_dom:
            _harvest_val(g_task_dom, dom_val)

    # 5. Quét Sổ theo dõi hồ sơ
    g_d_tab = get_bound_group('dossiers', 'category_tab') or get_category_group('Phân hệ hồ sơ')
    g_d_loai = get_bound_group('dossiers', 'loai') or get_category_group('Loại hồ sơ')
    tab_hint_map = {code: label for code, label, _ in DEFAULT_DOSSIER_TAB_ITEMS}
    loai_hint_map = {code: label for code, label, _ in DEFAULT_DOSSIER_LOAI_ITEMS}
    for d_tab, d_loai in Dossier.query.with_entities(Dossier.category_tab, Dossier.loai).distinct().all():
        if g_d_tab and d_tab:
            _harvest_val(g_d_tab, d_tab, display_hint=tab_hint_map.get(d_tab, d_tab))
        if g_d_loai and d_loai:
            _harvest_val(g_d_loai, d_loai, display_hint=loai_hint_map.get(d_loai, d_loai))

    # 6. Quét các bảng danh mục legacy nếu có dữ liệu
    legacy_sources = [
        (ContactGroup, g_c_grp),
        (ContactRole, g_c_role),
        (ProfessionalUnit, g_task_dom),
        (LibraryField, g_notify_cat),
        (NewsCategory, g_notify_cat),
    ]
    for model_cls, grp in legacy_sources:
        if not grp:
            continue
        for row in model_cls.query.all():
            _harvest_val(grp, getattr(row, 'name', ''))
    for row in MasterData.query.all():
        target_grp = g_c_grp if (row.category or '').lower() in ('group', 'contact_group') else g_notify_cat
        if target_grp:
            _harvest_val(target_grp, row.value)
    type_to_group = {
        'position': g_c_role,
        'unit': unit_group,
        'district': unit_group,
        'other': g_notify_cat,
    }
    for row in Category.query.all():
        grp = type_to_group.get(row.type) or g_notify_cat
        if grp:
            _harvest_val(grp, row.name)

    if commit:
        db.session.commit()
        _clear_category_request_caches()
    return {'added_items': added_count}


def _rewrite_model_category_references(group, match_values, new_stable_value=None, new_code_value=None, new_plain_name=None):
    """Cập nhật toàn bộ bản ghi đang lưu theo tập giá trị cũ sang tham chiếu mới."""
    import json
    from models import TaskImportDraft

    match_lowers = {str(v).strip().lower() for v in (match_values or []) if str(v or '').strip()}
    if not match_lowers:
        return 0
    updated = 0
    for model_cls, field_attr, is_code_field in _bound_targets_for_group(group):
        replacement = new_code_value if is_code_field else (new_stable_value or new_plain_name)
        if replacement is None:
            continue
        col = getattr(model_cls, field_attr)
        rows = model_cls.query.filter(col.isnot(None), col != '').all()
        for row in rows:
            cur_val = str(getattr(row, field_attr, '') or '').strip()
            if cur_val.lower() in match_lowers and cur_val != replacement:
                setattr(row, field_attr, replacement)
                updated += 1

    # Đồng bộ working_config_json trong TaskImportDraft
    cfg_fields = set()
    for b in ModuleFieldBinding.query.filter_by(group_id=group.id).all():
        if b.module and b.module.code == 'tasks' and b.field_code in ('category', 'domain', 'task_type', 'priority'):
            cfg_fields.add(b.field_code)
    for k, gcode in (('category', 'news_domain'), ('domain', 'task_unit'), ('task_type', 'task_type'), ('priority', 'task_priority')):
        if (group.code or '') == gcode:
            cfg_fields.add(k)
    if cfg_fields and (new_stable_value or new_plain_name):
        rep_val = new_stable_value or new_plain_name
        for draft in TaskImportDraft.query.filter(TaskImportDraft.working_config_json.isnot(None)).all():
            try:
                cfg = json.loads(draft.working_config_json)
            except Exception:
                continue
            if not isinstance(cfg, dict):
                continue
            changed = False
            for f in cfg_fields:
                cur = str(cfg.get(f) or '').strip()
                if cur.lower() in match_lowers and cur != rep_val:
                    cfg[f] = rep_val
                    changed = True
            if changed:
                draft.working_config_json = json.dumps(cfg, ensure_ascii=False)
                updated += 1
    return updated


def rename_and_propagate_category_item(item, new_name):
    """Đổi tên CategoryItem và cập nhật đồng bộ sang tất cả chức năng & Unit liên quan."""
    from models import Dossier, Unit, User
    clean_name = (new_name or '').strip()
    if not item or not clean_name:
        return 0
    old_name = (item.name or '').strip()
    old_code = (item.code or '').strip()
    if not item.code:
        item.code = slugify_code(old_name or clean_name)
    item.name = clean_name
    if old_name and old_name != clean_name:
        ensure_category_item_alias(item, old_name)

    stable_ref = f'category_item:{item.id}'
    match_vals = [old_name, old_code, slugify_code(old_name), stable_ref]
    updated = _rewrite_model_category_references(
        item.group,
        match_vals,
        new_stable_value=stable_ref,
        new_code_value=item.code,
        new_plain_name=clean_name,
    )

    if item.group and item.group.code == 'contact_unit':
        unit = None
        if item.code:
            unit = Unit.query.filter_by(code=item.code).first()
        if not unit and old_name:
            unit = Unit.query.filter(db.func.lower(Unit.name) == old_name.lower()).first()
        if unit:
            unit.name = clean_name
            updated += 1
        user_q = User.query.filter(
            db.or_(
                User.unit_key == item.code,
                db.func.lower(User.unit_area) == old_name.lower(),
                User.unit_area == stable_ref,
            )
        ).all()
        for u in user_q:
            u.unit_area = clean_name
            updated += 1
        dos_q = Dossier.query.filter(
            db.or_(
                Dossier.unit_code == item.code,
                db.func.lower(Dossier.unit_area) == old_name.lower(),
            )
        ).all()
        for d in dos_q:
            if (d.unit_area or '').strip().lower() == old_name.lower() or not d.unit_area:
                d.unit_area = clean_name
                updated += 1

    db.session.commit()
    _clear_category_request_caches()
    return updated


def toggle_and_propagate_category_item(item):
    """Ẩn hoặc hiện CategoryItem và đồng bộ trạng thái sang Unit tương ứng."""
    from models import Unit
    if not item:
        return False
    item.is_active = not bool(item.is_active)
    if item.group and item.group.code == 'contact_unit':
        unit = Unit.query.filter(
            db.or_(Unit.code == item.code, db.func.lower(Unit.name) == (item.name or '').lower())
        ).first()
        if unit:
            unit.is_active = item.is_active
    db.session.commit()
    _clear_category_request_caches()
    return item.is_active


def merge_category_items(source_item, target_item):
    """Gộp danh mục thừa/trùng (source) sang danh mục chuẩn (target) trên toàn bộ dữ liệu."""
    from models import Dossier, Unit, User
    if not source_item or not target_item or source_item.id == target_item.id:
        return 0
    if source_item.group_id != target_item.group_id:
        return 0
    src_stable = f'category_item:{source_item.id}'
    tgt_stable = f'category_item:{target_item.id}'
    match_vals = [src_stable, source_item.code, source_item.name, slugify_code(source_item.name or '')]
    updated = _rewrite_model_category_references(
        target_item.group,
        match_vals,
        new_stable_value=tgt_stable,
        new_code_value=target_item.code or slugify_code(target_item.name or ''),
        new_plain_name=target_item.name,
    )

    if target_item.group and target_item.group.code == 'contact_unit':
        src_unit = Unit.query.filter(
            db.or_(Unit.code == source_item.code, db.func.lower(Unit.name) == (source_item.name or '').lower())
        ).first()
        tgt_unit = Unit.query.filter(
            db.or_(Unit.code == target_item.code, db.func.lower(Unit.name) == (target_item.name or '').lower())
        ).first()
        for u in User.query.filter(
            db.or_(
                User.unit_key == source_item.code,
                db.func.lower(User.unit_area) == (source_item.name or '').lower(),
                User.unit_area == src_stable,
                *( [User.unit_id == src_unit.id] if src_unit else [] ),
            )
        ).all():
            u.unit_area = target_item.name
            if target_item.code:
                u.unit_key = target_item.code
            if tgt_unit:
                u.unit_id = tgt_unit.id
            updated += 1
        for d in Dossier.query.filter(
            db.or_(
                Dossier.unit_code == source_item.code,
                db.func.lower(Dossier.unit_area) == (source_item.name or '').lower(),
            )
        ).all():
            d.unit_area = target_item.name
            if target_item.code:
                d.unit_code = target_item.code
                d.unit_key = target_item.code
            updated += 1
        if src_unit and (not tgt_unit or src_unit.id != tgt_unit.id):
            src_unit.is_active = False

    if (source_item.name or '').strip():
        ensure_category_item_alias(target_item, source_item.name)
    for alias in CategoryItemAlias.query.filter_by(item_id=source_item.id).all():
        ensure_category_item_alias(target_item, alias.alias_name)
        db.session.delete(alias)
    db.session.flush()
    db.session.delete(source_item)
    db.session.commit()
    _clear_category_request_caches()
    return updated


def safe_delete_category_item(item):
    """Xóa CategoryItem an toàn: khử ref category_item:<id> về tên hiển thị và xóa alias."""
    if not item:
        return
    stable_ref = f'category_item:{item.id}'
    plain_name = (item.name or item.code or '').strip()
    if item.group:
        _rewrite_model_category_references(
            item.group,
            [stable_ref],
            new_stable_value=plain_name,
            new_code_value=item.code or slugify_code(plain_name),
            new_plain_name=plain_name,
        )
    for alias in CategoryItemAlias.query.filter_by(item_id=item.id).all():
        db.session.delete(alias)
    db.session.flush()
    db.session.delete(item)
    db.session.commit()
    _clear_category_request_caches()


def sync_unit_to_category_item(unit, old_name=None, old_code=None, deleted=False):
    """Đồng bộ thay đổi từ Quản lý Đơn vị hành chính sang nhóm Đơn vị (contact_unit)."""
    if not unit or (unit.code or '').strip().lower() == 'hethong':
        return
    ensure_unified_category_catalog(commit=False)
    unit_group = get_bound_group('contacts', 'unit_name') or get_category_group('Đơn vị')
    if not unit_group:
        return
    item = (
        (old_code and _find_item_in_group(unit_group, old_code))
        or _find_item_in_group(unit_group, unit.code)
        or (old_name and _find_item_in_group(unit_group, old_name))
        or _find_item_in_group(unit_group, unit.name)
    )
    if deleted:
        if item:
            safe_delete_category_item(item)
        return
    if not item:
        _ensure_item_in_group(unit_group, unit.name, code=unit.code, is_active=bool(unit.is_active), sort_order=unit.sort_order or 0)
        db.session.commit()
        _clear_category_request_caches()
        return
    prev_name = (item.name or '').strip()
    item.code = unit.code or item.code
    item.name = unit.name
    item.is_active = bool(unit.is_active)
    if prev_name and prev_name != unit.name:
        ensure_category_item_alias(item, prev_name)
    db.session.commit()
    _clear_category_request_caches()
