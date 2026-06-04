# -*- coding: utf-8 -*-
from flask import Blueprint, request, session, redirect, url_for, flash, jsonify, current_app, Response, send_from_directory
from sqlalchemy import func
from models import db, User, AppRole, MasterData, SystemLog, Task, NewsDoc, DocumentLib, Contact, CategoryGroup, CategoryItem, ModuleRegistry, CategoryGroupModule, ModuleFieldBinding, AIAssistantConfig
from werkzeug.security import generate_password_hash
try:
    from security_utils.password_validator import validate_password, get_password_requirements
except ImportError:
    def validate_password(pwd):
        return len(pwd) >= 8, "Mật khẩu phải có ít nhất 8 ký tự"
    def get_password_requirements():
        return "Ít nhất 8 ký tự, có chữ hoa, chữ thường, chữ số"

import os, json, shutil, zipfile, io, subprocess
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
    pd = None
from datetime import datetime, timedelta
from utils import (
    DEFAULT_ROLE_MODULE_CODES,
    PERMISSION_MODULES,
    build_account_username,
    build_commander_username,
    build_default_role_permissions,
    build_role_account_username,
    clear_logs,
    extract_unit_key,
    has_module_permission,
    init_db,
    log_action,
    normalize_permission_payload,
    role_permission_form_payload,
    render_auto_template as render_template,
    role_default_permission_tier,
)
from category_helpers import (
    apply_reference_display,
    canonicalize_category_value,
    ensure_category_item_alias,
    get_module_field_items,
    get_category_items,
    module_category_options,
    resolve_category_display,
    slugify_code,
    stable_form_category_options,
    sync_record_categories,
)

admin_bp = Blueprint('admin_bp', __name__)

AI_PROVIDER_CHOICES = {
    'deepseek': 'DeepSeek',
    'gemini': 'Gemini',
    'openai': 'OpenAI',
    'groq': 'Groq',
}

AI_PROVIDER_DEFAULTS = {
    'deepseek': 'deepseek-v4-flash',
    'gemini': 'gemini-2.5-flash',
    'openai': 'gpt-4.1-mini',
    'groq': 'llama-3.3-70b-versatile',
}

USER_IMPORT_HEADER_MARKERS = (
    'đơn vị',
    'don vi',
    'tên đơn vị',
    'ten don vi',
    'unit',
    'họ tên',
    'ho ten',
    'fullname',
    'username',
    'chức vụ',
    'chuc vu',
    'vai trò',
    'vai tro',
    'position',
)

USER_IMPORT_FULLNAME_MARKERS = (
    'họ tên',
    'ho ten',
    'fullname',
    'name',
    'tên',
    'ten',
)

USER_IMPORT_POSITION_MARKERS = (
    'chức vụ',
    'chuc vu',
    'vai trò',
    'vai tro',
    'position',
    'role',
)


def _looks_like_org_unit(value):
    text = (value or '').strip().lower()
    if not text:
        return False
    markers = [
        'cong an',
        'ubnd',
        'doi ',
        'đội ',
        'phong ',
        'phòng ',
        'ban ',
        'xa ',
        'xã ',
        'phuong ',
        'phường ',
        'thi tran',
        'thị trấn',
        'quan ',
        'huyen ',
    ]
    return any(marker in text for marker in markers)


def _unit_category_options():
    return module_category_options('contacts', 'unit_name', 'Đơn vị')


def _resolve_user_unit_value(fullname, unit, username=''):
    unit_options = _unit_category_options()
    unit = canonicalize_category_value(unit or '', unit_options, prefer_stable=True)
    fullname = (fullname or '').strip()
    unit_display = resolve_category_display(unit, unit_options, fallback_label=unit)['display_name'] if unit else ''
    unit_key = extract_unit_key(unit_display) if unit_display else ''
    if unit and unit_key and unit_key not in {'xa', 'phuong', 'huyen', 'quan', 'tp', 'thi', 'tran'}:
        return unit, unit_key
    if fullname and _looks_like_org_unit(fullname):
        fullname_key = extract_unit_key(fullname)
        if fullname_key and fullname_key not in {'xa', 'phuong', 'huyen', 'quan', 'tp', 'thi', 'tran'}:
            return fullname, fullname_key
    resolved = unit or fullname or username
    return resolved, extract_unit_key(resolved)


def _looks_like_user_import_header(value):
    text = str(value or '').strip().lower()
    if not text:
        return False
    return any(marker in text for marker in USER_IMPORT_HEADER_MARKERS)


def _normalize_import_text(value):
    text = str(value or '').strip().lower().replace('đ', 'd')
    text = ' '.join(text.split())
    return text


def _find_user_import_column(df, markers, has_header=True):
    if df.empty:
        return None
    if has_header:
        normalized_markers = tuple(_normalize_import_text(marker) for marker in markers)
        for column in df.columns:
            column_text = _normalize_import_text(column)
            if any(marker in column_text for marker in normalized_markers):
                return column
    return None


def _looks_like_commander_title(value):
    text = _normalize_import_text(value)
    if not text:
        return False
    return (
        'doi truong' in text
        or 'doi pho' in text
        or 'pho doi truong' in text
    )


def _load_user_import_dataframe(file_storage, has_header=True):
    raw = file_storage.read()
    if not raw:
        raise ValueError('File Excel không có dữ liệu.')

    def _read(header_mode):
        kwargs = {}
        kwargs['header'] = 0 if header_mode else None
        return pd.read_excel(io.BytesIO(raw), **kwargs).fillna('')

    df = _read(has_header)
    inferred_has_header = has_header

    if has_header and len(df.columns):
        first_col = df.columns[0]
        if not any(_looks_like_user_import_header(col) for col in df.columns):
            if _looks_like_org_unit(str(first_col)) or not _looks_like_user_import_header(first_col):
                df = _read(False)
                inferred_has_header = False

    return df, inferred_has_header


def _user_import_unit_column(df, has_header=True):
    if df.empty:
        return None
    if has_header:
        return next((c for c in df.columns if _looks_like_user_import_header(c)), df.columns[0])
    return df.columns[0]


def _user_import_commander_columns(df, has_header=True):
    fullname_col = _find_user_import_column(df, USER_IMPORT_FULLNAME_MARKERS, has_header=has_header)
    title_col = _find_user_import_column(df, USER_IMPORT_POSITION_MARKERS, has_header=has_header)
    if fullname_col is not None and title_col is not None and fullname_col != title_col:
        return fullname_col, title_col

    if len(df.columns) >= 2:
        sample_values = [
            str(df.iloc[idx, 1]).strip()
            for idx in range(min(len(df.index), 5))
            if len(df.columns) > 1
        ]
        if any(_looks_like_commander_title(value) for value in sample_values):
            return df.columns[0], df.columns[1]

    return None, None


def _get_admin_perms():
    role_id = session.get('role_id')
    role = db.session.get(AppRole, role_id) if role_id else None
    if role and role.perms:
        try:
            return normalize_permission_payload(role.perms, is_admin=session.get('is_admin'), role_name=getattr(role, 'name', ''))
        except Exception:
            return {}
    return {}


def _build_role_user_query(selected_role_id=None, selected_unit='', search_query=''):
    selected_role = db.session.get(AppRole, selected_role_id) if selected_role_id else None
    users_query = User.query
    unit_options = _unit_category_options()

    if selected_role:
        users_query = users_query.filter(User.role_id == selected_role.id)

    selected_unit = (selected_unit or '').strip()
    if selected_unit:
        from sqlalchemy import or_

        canonical_unit = canonicalize_category_value(selected_unit, unit_options, prefer_stable=True)
        selected_unit_display = resolve_category_display(canonical_unit or selected_unit, unit_options, fallback_label=selected_unit)['display_name']
        selected_unit_key = extract_unit_key(selected_unit_display or selected_unit)
        if selected_unit_key:
            users_query = users_query.filter(
                or_(
                    User.unit_area == canonical_unit,
                    User.unit_area == selected_unit,
                    User.unit_key == selected_unit_key
                )
            )
        else:
            users_query = users_query.filter(User.unit_area.in_([canonical_unit, selected_unit]))

    search_query = (search_query or '').strip()
    if search_query:
        from sqlalchemy import or_

        term = f"%{search_query}%"
        matching_unit_values = []
        lowered_query = search_query.lower()
        for option in unit_options:
            option_name = (option.get('name') or '').strip().lower()
            if option_name and lowered_query in option_name:
                matching_unit_values.extend([
                    option.get('stable_value') or '',
                    option.get('value') or '',
                    option.get('name') or '',
                ])
        matching_unit_values = [value for value in dict.fromkeys(matching_unit_values) if value]
        conditions = [
            User.fullname.ilike(term),
            User.username.ilike(term),
            User.unit_area.ilike(term),
            User.unit_key.ilike(term),
        ]
        if matching_unit_values:
            conditions.append(User.unit_area.in_(matching_unit_values))
        users_query = users_query.filter(or_(*conditions))

    return selected_role, users_query


def _mask_secret(value):
    value = (value or '').strip()
    if not value:
        return ''
    if len(value) <= 8:
        return '*' * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def _reset_users_passwords_bulk(user_query, default_password='123456'):
    target_rows = user_query.with_entities(User.id, User.username).all()
    if not target_rows:
        return 0, False

    target_ids = [uid for uid, username in target_rows if username != 'admin']
    skipped_admin = len(target_ids) != len(target_rows)
    if not target_ids:
        return 0, skipped_admin

    default_hash = generate_password_hash(default_password, method='pbkdf2:sha256')
    User.query.filter(User.id.in_(target_ids)).update(
        {
            User.password_hash: default_hash,
            User.must_change_password: True,
        },
        synchronize_session=False,
    )
    return len(target_ids), skipped_admin


def _test_ai_runtime_connection():
    from routes.ai_assistant import call_ai_provider

    test_prompt = "Hãy trả lời ngắn gọn bằng đúng cụm từ: Kết nối AI thành công."
    result, errors = call_ai_provider(test_prompt)
    return result, errors


def _normalize_group_label(value, fallback='Chưa phân loại'):
    value = (value or '').strip()
    return value or fallback


def _build_grouped_rows(raw_counts, ordered_items=None, fallback_label='Chưa phân loại', include_zero=False, category_options=None):
    count_map = {}
    for name, count in raw_counts:
        if category_options:
            label = resolve_category_display(name, category_options, fallback_label=fallback_label)['display_name']
        else:
            label = _normalize_group_label(name, fallback_label)
        count_map[label] = count_map.get(label, 0) + int(count or 0)

    rows = []
    seen = set()

    for item in ordered_items or []:
        label = _normalize_group_label(
            item.get('name') if isinstance(item, dict) else getattr(item, 'name', ''),
            fallback_label,
        )
        rows.append({
            'name': label,
            'count': count_map.get(label, 0)
        })
        seen.add(label)

    extras = sorted(
        (
            {'name': name, 'count': count}
            for name, count in count_map.items()
            if name not in seen and (include_zero or count > 0)
        ),
        key=lambda row: (-row['count'], row['name'].lower())
    )
    rows.extend(extras)

    if not include_zero:
        rows = [row for row in rows if row['count'] > 0]
    return rows


def _workspace_card(
    title,
    description,
    primary_label,
    primary_link,
    accent_class='primary',
    stat_value='',
    stat_label='',
    secondary_label='',
    secondary_link='',
):
    return {
        'title': title,
        'description': description,
        'primary_label': primary_label,
        'primary_link': primary_link,
        'accent_class': accent_class,
        'stat_value': stat_value,
        'stat_label': stat_label,
        'secondary_label': secondary_label,
        'secondary_link': secondary_link,
    }


def _report_submission_business_date(submission):
    metadata = {}
    try:
        metadata = json.loads(getattr(submission, 'metadata_json', '') or '{}')
    except (TypeError, ValueError, json.JSONDecodeError):
        metadata = {}

    report_date_raw = str(metadata.get('report_date', '') or '').strip()
    if report_date_raw:
        try:
            return datetime.fromisoformat(report_date_raw).date()
        except ValueError:
            pass

    submitted_at = getattr(submission, 'submitted_at', None) or getattr(submission, 'created_at', None)
    return submitted_at.date() if submitted_at else None


def _task_dashboard_unit_metrics():
    from models import TaskAssignment

    total_tasks = Task.query.count()
    unit_rows = db.session.query(User.unit_key, User.unit_area).join(
        TaskAssignment, TaskAssignment.user_id == User.id
    ).distinct().all()
    pending_rows = db.session.query(User.unit_key, User.unit_area).join(
        TaskAssignment, TaskAssignment.user_id == User.id
    ).filter(
        func.lower(func.coalesce(TaskAssignment.status, '')).notin_(['submitted', 'completed'])
    ).distinct().all()

    def _collect_units(rows):
        units = set()
        for unit_key, unit_area in rows:
            value = (unit_key or unit_area or '').strip()
            if value:
                units.add(value)
        return units

    all_units = _collect_units(unit_rows)
    pending_units = _collect_units(pending_rows)
    return {
        'total_tasks': total_tasks,
        'total_units': len(all_units),
        'unreported_units': len(pending_units),
        'reported_units': max(len(all_units) - len(pending_units), 0),
    }


def _daily_report_dashboard_unit_metrics():
    from models import ReportCycle, ReportInstance, ReportSubmission, ReportType

    total_reports = ReportCycle.query.count()
    daily_cycles = db.session.query(ReportCycle.id).join(
        ReportType, ReportCycle.report_type_id == ReportType.id
    ).filter(
        ReportType.code == 'daily',
        ReportCycle.status != 'closed',
    ).all()
    daily_cycle_ids = [row[0] for row in daily_cycles]
    if not daily_cycle_ids:
        return {
            'total_reports': total_reports,
            'total_units': 0,
            'unreported_units': 0,
            'reported_units': 0,
        }

    instances = ReportInstance.query.filter(ReportInstance.cycle_id.in_(daily_cycle_ids)).all()
    if not instances:
        return {
            'total_reports': total_reports,
            'total_units': 0,
            'unreported_units': 0,
            'reported_units': 0,
        }

    today = datetime.now().date()
    instance_ids = [instance.id for instance in instances]
    submissions = ReportSubmission.query.filter(
        ReportSubmission.instance_id.in_(instance_ids)
    ).all()

    submitted_instance_ids = set()
    for submission in submissions:
        if (getattr(submission, 'status', '') or '').strip().lower() != 'submitted':
            continue
        if _report_submission_business_date(submission) == today:
            submitted_instance_ids.add(submission.instance_id)

    def _instance_unit_key(instance):
        if getattr(instance, 'report_unit_id', None):
            return f"unit:{instance.report_unit_id}"
        if getattr(instance, 'org_unit', None):
            return f"org:{instance.org_unit.strip()}"
        return f"instance:{instance.id}"

    all_units = {_instance_unit_key(instance) for instance in instances}
    pending_units = {
        _instance_unit_key(instance)
        for instance in instances
        if instance.id not in submitted_instance_ids
    }
    return {
        'total_reports': total_reports,
        'total_units': len(all_units),
        'unreported_units': len(pending_units),
        'reported_units': max(len(all_units) - len(pending_units), 0),
    }

@admin_bp.route('/admin')
def index():
    try:
        if not session.get('uid'): 
            return redirect(url_for('auth_bp.login'))

        from models import Task, DocumentLib, Contact, ReportTemplate, ReportCycle, ReportTemplateVersion
        from category_helpers import get_module_field_items, get_category_items

        task_domain_items = module_category_options('tasks', 'domain', 'Đội nghiệp vụ')
        contact_group_items = module_category_options('contacts', 'contact_group', 'Nhóm danh bạ')
        document_field_items = module_category_options('library', 'category', 'Lĩnh vực', 'Loại tài liệu')
        # Filter out 5 Đội nghiệp vụ manually since it's hardcoded constraint
        fixed_report_teams = [{'name': f'Đội {i}'} for i in range(1, 6)]

        task_raw_counts = db.session.query(
            Task.domain,
            func.count(Task.id)
        ).group_by(Task.domain).all()

        document_raw_counts = db.session.query(
            DocumentLib.category,
            func.count(DocumentLib.id)
        ).group_by(DocumentLib.category).all()

        contact_raw_counts = db.session.query(
            Contact.contact_group,
            func.count(Contact.id)
        ).group_by(Contact.contact_group).all()

        report_raw_counts = db.session.query(
            ReportTemplate.professional_unit,
            func.count(ReportCycle.id)
        ).join(
            ReportTemplateVersion, ReportCycle.template_version_id == ReportTemplateVersion.id
        ).join(
            ReportTemplate, ReportTemplateVersion.template_id == ReportTemplate.id
        ).group_by(ReportTemplate.professional_unit).all()

        task_dashboard = _build_grouped_rows(
            task_raw_counts,
            task_domain_items,
            fallback_label='Chưa phân đội',
            include_zero=True,
            category_options=task_domain_items,
        )
        document_dashboard = _build_grouped_rows(
            document_raw_counts,
            document_field_items,
            fallback_label='Chưa phân lĩnh vực',
            include_zero=True,
            category_options=document_field_items,
        )
        contact_dashboard = _build_grouped_rows(
            contact_raw_counts,
            contact_group_items,
            fallback_label='Chưa phân nhóm',
            include_zero=True,
            category_options=contact_group_items,
        )
        
        # Build report dashboard using exactly Đội 1 -> Đội 5
        report_dashboard = _build_grouped_rows(
            report_raw_counts,
            fixed_report_teams,
            fallback_label='Chưa phân đội',
            include_zero=True,
        )

        # Ensure that only Đội 1 to Đội 5 and the fallback (if any exist) are present? 
        # The instruction says "Cố định sẽ có 05 đội nghiệp vụ Đội 1 -> Đội 5"
        # So we can ensure these rows always appear, even if 0.
        # `_build_grouped_rows` filters out rows with 0 count, but the instruction implies it should be fixed.
        # Let's override the result for report_dashboard to strictly ensure we have these 5 items.
        
        report_dashboard_map = {row['name']: row['count'] for row in report_dashboard}
        fixed_report_dashboard = []
        for i in range(1, 6):
            team_name = f'Đội {i}'
            fixed_report_dashboard.append({
                'name': team_name,
                'count': report_dashboard_map.get(team_name, 0)
            })
        
        # Dashboard báo cáo chỉ hiển thị các đội nghiệp vụ cố định.
        # Các bản ghi test chưa gán đội không đưa vào thẻ tổng quan này.
        for row in report_dashboard:
            if row['name'].startswith('Đội ') and row['name'] not in [f'Đội {i}' for i in range(1, 6)]:
                fixed_report_dashboard.append(row)

        is_admin = bool(session.get('is_admin'))
        role_obj = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
        role_name = role_obj.name if role_obj else 'Thành viên'
        perms = json.loads(role_obj.perms) if role_obj and role_obj.perms else {}
        perms = normalize_permission_payload(perms, is_admin=is_admin, role_name=role_name)

        def can_module(module_code, tier='view'):
            return has_module_permission(perms, module_code, tier=tier, is_admin=is_admin, role_name=role_name)

        def can_access_report_center():
            return bool(
                can_module('form', 'view')
                or can_module('input', 'view')
                or can_module('input', 'process')
                or can_module('input', 'exec')
                or can_module('stat', 'view')
                or can_module('stat', 'process')
                or can_module('stat', 'exec')
            )

        report_center_link = '/admin/reports' if can_module('form', 'process') else '/reports'

        task_metrics = _task_dashboard_unit_metrics()
        daily_report_metrics = _daily_report_dashboard_unit_metrics()

        overview_metrics = [
            {
                'title': 'Số công việc',
                'value': task_metrics['total_tasks'],
                'href': '/tasks',
                'accent_class': 'primary',
            },
            {
                'title': 'Đơn vị chưa báo cáo công việc',
                'value': task_metrics['unreported_units'],
                'href': '/tasks',
                'accent_class': 'warning',
            },
            {
                'title': 'Số báo cáo',
                'value': daily_report_metrics['total_reports'],
                'href': report_center_link,
                'accent_class': 'success',
            },
            {
                'title': 'Đơn vị chưa báo cáo trong ngày',
                'value': daily_report_metrics['unreported_units'],
                'href': report_center_link,
                'accent_class': 'indigo',
            },
        ]

        overview_chart = {
            'chart_labels': [item['title'] for item in overview_metrics],
            'chart_values': [item['value'] for item in overview_metrics],
        }
        completion_chart = {
            'chart_labels': [
                'ĐV đã báo cáo công việc',
                'ĐV chưa báo cáo công việc',
                'ĐV đã báo cáo trong ngày',
                'ĐV chưa báo cáo trong ngày',
            ],
            'chart_values': [
                task_metrics['reported_units'],
                task_metrics['unreported_units'],
                daily_report_metrics['reported_units'],
                daily_report_metrics['unreported_units'],
            ],
        }

        dashboard_cards = [
            {
                'title': 'Báo cáo',
                'row_label': 'Đội nghiệp vụ',
                'count_label': 'Số báo cáo',
                'icon': 'fa-solid fa-chart-pie',
                'accent_class': 'success',
                'link': '/admin/reports',
                'rows': fixed_report_dashboard,
                'total': sum(row['count'] for row in fixed_report_dashboard),
                'empty_text': 'Chưa có báo cáo nào.'
            },
            {
                'title': 'Công việc được giao',
                'row_label': 'Đội nghiệp vụ',
                'count_label': 'Số việc đã giao',
                'icon': 'fa-solid fa-list-check',
                'accent_class': 'primary',
                'link': '/tasks',
                'rows': task_dashboard,
                'total': sum(row['count'] for row in task_dashboard),
                'empty_text': 'Chưa có công việc nào.'
            },
            {
                'title': 'Thông tin tài liệu',
                'row_label': 'Lĩnh vực',
                'count_label': 'Số tài liệu',
                'icon': 'fa-solid fa-folder-open',
                'accent_class': 'warning',
                'link': '/library',
                'rows': document_dashboard,
                'total': sum(row['count'] for row in document_dashboard),
                'empty_text': 'Chưa có tài liệu nào.'
            },
            {
                'title': 'Danh bạ',
                'row_label': 'Nhóm danh bạ',
                'count_label': 'Số liên hệ',
                'icon': 'fa-solid fa-address-book',
                'accent_class': 'indigo',
                'link': '/contacts',
                'rows': contact_dashboard,
                'total': sum(row['count'] for row in contact_dashboard),
                'empty_text': 'Chưa có liên hệ nào.'
            },
        ]

        card_totals = {card['title']: card['total'] for card in dashboard_cards}
        workspace_groups = [
            {
                'title': 'Làm việc hằng ngày',
                'description': 'Các khu vực thao tác chính để nhận việc, nộp báo cáo và theo dõi xử lý.',
                'cards': [],
            },
            {
                'title': 'Tra cứu và hỗ trợ',
                'description': 'Nhóm chức năng phục vụ tìm kiếm thông tin, tài liệu và hỗ trợ người dùng.',
                'cards': [],
            },
            {
                'title': 'Quản trị hệ thống',
                'description': 'Thiết lập tài khoản, danh mục và cấu hình hệ thống theo quyền được cấp.',
                'cards': [],
            },
        ]

        if can_module('task', 'view'):
            workspace_groups[0]['cards'].append(_workspace_card(
                title='Công việc',
                description='Xem việc được giao, mở chi tiết để tiếp nhận, nộp kết quả hoặc theo dõi tiến độ.',
                primary_label='Mở công việc',
                primary_link='/tasks',
                secondary_label='Xem tổng quan giao việc',
                secondary_link='/tasks',
                accent_class='primary',
                stat_value=card_totals.get('Công việc được giao', 0),
                stat_label='đợt công việc đang có',
            ))

        if can_access_report_center():
            workspace_groups[0]['cards'].append(_workspace_card(
                title='Báo cáo',
                description='Vào đúng trung tâm báo cáo để nhập số liệu, kiểm tra tiến độ hoặc quản lý biểu mẫu.',
                primary_label='Mở báo cáo',
                primary_link=report_center_link,
                secondary_label='Xem tiến độ báo cáo',
                secondary_link=report_center_link,
                accent_class='success',
                stat_value=card_totals.get('Báo cáo', 0),
                stat_label='biểu mẫu hoặc đợt báo cáo',
            ))

        if can_module('attendance', 'view'):
            workspace_groups[0]['cards'].append(_workspace_card(
                title='Điểm danh',
                description='Ghi nhận quân số, cập nhật ca trực hoặc theo dõi tình trạng điểm danh theo ngày.',
                primary_label='Mở điểm danh',
                primary_link='/attendance',
                accent_class='warning',
                stat_value='Trong ngày',
                stat_label='cập nhật theo thời điểm',
            ))

        workspace_groups[0]['cards'].append(_workspace_card(
            title='Xếp hạng',
            description='Theo dõi kết quả thi đua và so sánh mức độ hoàn thành giữa các đơn vị.',
            primary_label='Xem xếp hạng',
            primary_link='/ranking',
            accent_class='indigo',
            stat_value='Toàn hệ thống',
            stat_label='bảng theo dõi thi đua',
        ))

        if can_module('lib', 'view') or can_module('news', 'view'):
            workspace_groups[1]['cards'].append(_workspace_card(
                title='Tài liệu và bảng tin',
                description='Tra cứu văn bản, thông báo và tài liệu dùng chung tại một nơi dễ tìm hơn.',
                primary_label='Mở thư viện',
                primary_link='/library' if can_module('lib', 'view') else '/news',
                secondary_label='Mở bảng tin' if can_module('news', 'view') else '',
                secondary_link='/news' if can_module('news', 'view') else '',
                accent_class='warning',
                stat_value=card_totals.get('Thông tin tài liệu', 0),
                stat_label='tài liệu đang lưu',
            ))

        if can_module('contact', 'view'):
            workspace_groups[1]['cards'].append(_workspace_card(
                title='Danh bạ',
                description='Tra cứu nhanh đầu mối liên hệ theo đơn vị, nhóm hoặc chức danh.',
                primary_label='Mở danh bạ',
                primary_link='/contacts',
                accent_class='indigo',
                stat_value=card_totals.get('Danh bạ', 0),
                stat_label='liên hệ sẵn có',
            ))

        workspace_groups[1]['cards'].append(_workspace_card(
            title='Hướng dẫn và AI',
            description='Khi chưa rõ cách thao tác, mở tài liệu hướng dẫn hoặc dùng trợ lý AI để hỏi nhanh.',
            primary_label='Mở hướng dẫn',
            primary_link='/guide',
            secondary_label='Mở trợ lý AI',
            secondary_link='/ai',
            accent_class='primary',
        ))

        workspace_groups[1]['cards'].append(_workspace_card(
            title='QR và liên kết',
            description='Quản lý liên kết nhanh, mã QR và các đường dẫn dùng chung của đơn vị.',
            primary_label='Mở QR và link',
            primary_link='/links',
            accent_class='success',
        ))

        if can_module('user', 'view'):
            workspace_groups[2]['cards'].append(_workspace_card(
                title='Tài khoản và vai trò',
                description='Quản lý người dùng, phân quyền theo vai trò và rà soát quyền truy cập.',
                primary_label='Mở quản lý tài khoản',
                primary_link='/roles',
                accent_class='primary',
            ))

        if can_module('sys', 'view'):
            workspace_groups[2]['cards'].append(_workspace_card(
                title='Thiết lập hệ thống',
                description='Cấu hình danh mục, AI, nhật ký hoạt động, cập nhật và công cụ quản trị hệ thống.',
                primary_label='Mở thiết lập danh mục',
                primary_link='/admin/module-categories',
                secondary_label='Mở nhật ký hoạt động',
                secondary_link='/logs',
                accent_class='warning',
            ))

        workspace_groups = [group for group in workspace_groups if group['cards']]
        dashboard_snapshots = []
        for card in dashboard_cards:
            snapshot = dict(card)
            snapshot['rows'] = card['rows'][:5]
            dashboard_snapshots.append(snapshot)

        now_str = datetime.now().strftime('Ngày %d tháng %m, %Y')
        
        return render_template('admin_dashboard.html', 
            title='Trang chủ',
            now_str=now_str, 
            dashboard_cards=dashboard_cards,
            dashboard_snapshots=dashboard_snapshots,
            workspace_groups=workspace_groups,
            overview_metrics=overview_metrics,
            overview_chart=overview_chart,
            completion_chart=completion_chart)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"Lỗi: {str(e)}", 500

@admin_bp.route('/admin/db-tool', methods=['GET', 'POST'])
def db_tool():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    return render_template('db_tool.html')


@admin_bp.route('/admin/categories')
def category_admin():
    """Trang quản lý danh mục tập trung"""
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    from models import Category
    categories = Category.query.order_by(Category.type, Category.order, Category.name).all()
    return render_template('category_admin.html', categories=categories)


@admin_bp.route('/admin/db-manage', methods=['POST'])
def db_manage():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    action = request.form.get('action')
    try:
        if action == 'reset':
            from utils import init_db
            db.drop_all()
            db.create_all()
            init_db(current_app)
            
            flash('Hệ thống đã được Reset về trạng thái ban đầu!', 'success')
            session.clear() # Force re-login
            return redirect(url_for('auth_bp.login'))
            
        elif action == 'backup':
            # Use the correct database name from app.py
            db_path = os.path.join(current_app.root_path, 'pc06_system.db')
            if os.path.exists(db_path):
                return send_from_directory(current_app.root_path, 'pc06_system.db', as_attachment=True)
            else: 
                flash(f'Không tìm thấy file database tại {db_path}!', 'danger')
    except Exception as e:
        flash(f'Lỗi thao tác: {e}', 'danger')
    return redirect(url_for('admin_bp.db_tool'))

@admin_bp.route('/roles', methods=['GET', 'POST'])
def roles():
    perms = _get_admin_perms()
    is_admin = bool(session.get('is_admin'))
    can_view_roles = has_module_permission(perms, 'user', 'view', is_admin=is_admin)

    if not can_view_roles:
        flash('Bạn không có quyền truy cập trang tài khoản và vai trò.', 'warning')
        return redirect(url_for('admin_bp.index'))

    if request.method == 'POST':
        if not is_admin:
            flash('Chỉ quản trị viên mới được thay đổi tài khoản và vai trò.', 'danger')
            return redirect(url_for('admin_bp.roles'))
        action = request.form.get('action')
        try:
            if action == 'add_role':
                name = request.form['name']
                p_list = request.form.getlist('perms')
                p_json = json.dumps({p: 1 for p in p_list}, ensure_ascii=False)
                db.session.add(AppRole(name=name, perms=p_json))
                log_action(session['uid'], session['fullname'], "Thêm vai trò", "Vai trò", name)
            elif action == 'edit_perms':
                rid = request.form['role_id']
                p_list = request.form.getlist('perms')
                r = db.session.get(AppRole, rid)
                if r:
                    r.perms = json.dumps({p: 1 for p in p_list}, ensure_ascii=False)
                    log_action(session['uid'], session['fullname'], "Sửa quyền vai trò", "Vai trò", r.name)
            elif action == 'add_user':
                username = request.form.get('username')
                fullname = request.form.get('fullname')
                unit = request.form.get('unit', 'Chưa xác định')
                role_id = request.form.get('role_id')
                password = request.form.get('password', '')
                unit, unit_key = _resolve_user_unit_value(fullname, unit, username)
                role = db.session.get(AppRole, role_id) if role_id else None
                
                if not role_id:
                    flash('Thiếu thông tin bắt buộc!', 'danger')
                else:
                    if not username:
                        username = build_role_account_username(role.name if role else '', unit, unit_key)
                    if not username:
                        flash('Không thể sinh tên đăng nhập từ đơn vị đã chọn!', 'danger')
                    else:
                        u = User(username=username, fullname=fullname, unit_area=unit, unit_key=unit_key, role_id=role_id)
                        u.set_password(password)
                        db.session.add(u)
                        log_action(session['uid'], session['fullname'], "Thêm tài khoản", "Tài khoản", u.username)
            elif action == 'edit_user':
                uid = request.form.get('user_id')
                u = db.session.get(User, uid)
                if u:
                    u.username = request.form.get('username')
                    u.fullname = request.form.get('fullname')
                    resolved_unit, resolved_key = _resolve_user_unit_value(
                        u.fullname,
                        request.form.get('unit'),
                        u.username
                    )
                    u.unit_area = resolved_unit
                    u.unit_key = resolved_key
                    u.role_id = request.form.get('role_id')
                    pwd = request.form.get('password')
                    if pwd and pwd.strip() and pwd != '******':
                        u.set_password(pwd)
                    log_action(session['uid'], session['fullname'], "Sửa tài khoản", "Tài khoản", u.username)
            db.session.commit()
            flash('Thao tác thành công!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi: {e}', 'danger')
        return redirect(url_for('admin_bp.roles'))

    selected_role_id = request.args.get('role_id', type=int)
    selected_unit = (request.args.get('unit') or '').strip()
    search_query = (request.args.get('q') or '').strip()
    unit_options = _unit_category_options()
    selected_unit = canonicalize_category_value(selected_unit, unit_options, prefer_stable=True) if selected_unit else ''

    roles = AppRole.query.order_by(AppRole.name.asc()).all()
    for role in roles:
        form_perms = role_permission_form_payload(role.perms, role_name=role.name)
        setattr(role, 'form_perms_json', json.dumps(form_perms, ensure_ascii=False))
        setattr(role, 'default_permission_tier', role_default_permission_tier(role.name))
    selected_role, users_query = _build_role_user_query(
        selected_role_id=selected_role_id,
        selected_unit=selected_unit,
        search_query=search_query
    )

    unit_options_query = db.session.query(User.unit_area)
    if selected_role:
        unit_options_query = unit_options_query.filter(User.role_id == selected_role.id)
    available_units = sorted({
        resolve_category_display(unit_name, unit_options, fallback_label=unit_name)['display_name']
        for unit_name, in unit_options_query.distinct().all()
        if unit_name and str(unit_name).strip()
    }, key=lambda value: value.lower())

    users = users_query.order_by(User.fullname.asc(), User.username.asc()).all()
    users = sync_record_categories(users, unit_options, attr_name='unit_area', prefer_stable=True)
    users = apply_reference_display(users, 'unit_area', unit_options, display_attr='unit_area_display', fallback_label='Chưa có đơn vị')

    from sqlalchemy import func
    raw_role_counts = db.session.query(
        User.role_id,
        func.count(User.id)
    ).group_by(User.role_id).all()
    role_user_counts = {int(role_id): int(count) for role_id, count in raw_role_counts if role_id}

    selected_unit_display = resolve_category_display(selected_unit, unit_options, fallback_label=selected_unit)['display_name'] if selected_unit else ''
    return render_template(
        'roles.html',
        can_manage_roles=is_admin,
        roles=roles,
        users=users,
        selected_role=selected_role,
        selected_role_id=selected_role.id if selected_role else None,
        selected_unit=selected_unit,
        selected_unit_display=selected_unit_display,
        search_query=search_query,
        available_units=available_units,
        role_user_counts=role_user_counts,
        total_role_count=len(roles),
        total_user_count=sum(role_user_counts.values()),
        permission_modules=PERMISSION_MODULES,
        default_role_permission_map=json.dumps(build_default_role_permissions(''), ensure_ascii=False),
        default_role_module_codes=json.dumps(list(DEFAULT_ROLE_MODULE_CODES), ensure_ascii=False),
        units=[u[0] for u in db.session.query(MasterData.name).distinct().all() if u[0]],
        unit_cats=stable_form_category_options(unit_options)
    )


@admin_bp.route('/admin/users/export')
def export_users():
    if not session.get('is_admin'):
        flash('Chỉ quản trị viên mới được xuất danh sách tài khoản.', 'danger')
        return redirect(url_for('admin_bp.roles'))
    if not HAS_PANDAS:
        flash('Máy chủ chưa cài thư viện xuất Excel.', 'danger')
        return redirect(url_for('admin_bp.roles'))

    selected_role_id = request.args.get('role_id', type=int)
    selected_unit = (request.args.get('unit') or '').strip()
    search_query = (request.args.get('q') or '').strip()
    unit_options = _unit_category_options()
    selected_unit = canonicalize_category_value(selected_unit, unit_options, prefer_stable=True) if selected_unit else ''
    selected_role, users_query = _build_role_user_query(
        selected_role_id=selected_role_id,
        selected_unit=selected_unit,
        search_query=search_query
    )
    users = users_query.order_by(User.fullname.asc(), User.username.asc()).all()
    users = sync_record_categories(users, unit_options, attr_name='unit_area', prefer_stable=True)
    users = apply_reference_display(users, 'unit_area', unit_options, display_attr='unit_area_display', fallback_label='')
    selected_unit_display = resolve_category_display(selected_unit, unit_options, fallback_label=selected_unit)['display_name'] if selected_unit else ''

    rows = []
    for index, user in enumerate(users, start=1):
        rows.append({
            'STT': index,
            'Tài khoản': user.username or '',
            'Họ và tên': user.fullname or '',
            'Đơn vị': user.unit_area_display or '',
            'Mã đơn vị': user.unit_key or '',
            'Vai trò': user.role.name if user.role else '',
            'Trạng thái': 'Hoạt động' if user.is_active else 'Vô hiệu hóa',
            'Yêu cầu đổi mật khẩu': 'Có' if user.must_change_password else 'Không',
        })

    if not rows:
        rows.append({
            'STT': '',
            'Tài khoản': '',
            'Họ và tên': '',
            'Đơn vị': '',
            'Mã đơn vị': '',
            'Vai trò': '',
            'Trạng thái': '',
            'Yêu cầu đổi mật khẩu': '',
        })

    export_filters = pd.DataFrame([
        {'Tiêu chí': 'Vai trò', 'Giá trị': selected_role.name if selected_role else 'Tất cả'},
        {'Tiêu chí': 'Đơn vị', 'Giá trị': selected_unit_display or 'Tất cả'},
        {'Tiêu chí': 'Từ khóa', 'Giá trị': search_query or 'Không có'},
        {'Tiêu chí': 'Số tài khoản', 'Giá trị': len(users)},
        {'Tiêu chí': 'Thời gian xuất', 'Giá trị': datetime.now().strftime('%d/%m/%Y %H:%M:%S')},
    ])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        pd.DataFrame(rows).to_excel(writer, index=False, sheet_name='TaiKhoan')
        export_filters.to_excel(writer, index=False, sheet_name='BoLoc')

        account_sheet = writer.sheets['TaiKhoan']
        for column_cells in account_sheet.columns:
            max_length = max(len(str(cell.value or '')) for cell in column_cells)
            account_sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 36)
        account_sheet.freeze_panes = 'A2'

        filter_sheet = writer.sheets['BoLoc']
        filter_sheet.column_dimensions['A'].width = 22
        filter_sheet.column_dimensions['B'].width = 36

    file_parts = ['danh_sach_tai_khoan']
    if selected_role:
        file_parts.append(slugify_code(selected_role.name) or f'role_{selected_role.id}')
    if selected_unit_display:
        file_parts.append(slugify_code(selected_unit_display) or 'don_vi')
    filename = f"{'_'.join(file_parts)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

    return Response(
        output.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-disposition": f"attachment; filename={filename}"}
    )

@admin_bp.route('/admin/user/delete/<int:uid>', methods=['POST'])
def delete_user(uid):
    if not session.get('is_admin'):
        flash('Chỉ quản trị viên mới được xóa tài khoản.', 'danger')
        return redirect(url_for('admin_bp.roles'))
    u = db.session.get(User, uid)
    if u:
        if u.username == 'admin':
            flash('Không thể xóa tài khoản Quản trị hệ thống!', 'danger')
        else:
            name = u.username
            db.session.delete(u)
            db.session.commit()
            log_action(session['uid'], session['fullname'], "Xóa tài khoản", "Tài khoản", name)
            flash(f'Đã xóa tài khoản {name} thành công!', 'success')
    return redirect(url_for('admin_bp.roles'))


@admin_bp.route('/admin/users/delete-bulk', methods=['POST'])
def delete_users_bulk():
    if not session.get('is_admin'):
        flash('Chỉ quản trị viên mới được xóa tài khoản.', 'danger')
        return redirect(url_for('admin_bp.roles'))

    raw_selected = request.form.get('selected_ids', '').strip()
    try:
        selected_ids = json.loads(raw_selected) if raw_selected else []
    except Exception:
        selected_ids = []

    selected_ids = [int(uid) for uid in selected_ids if str(uid).isdigit()]
    if not selected_ids:
        flash('Chưa chọn tài khoản nào để xóa.', 'warning')
        return redirect(url_for('admin_bp.roles'))

    users = User.query.filter(User.id.in_(selected_ids)).all()
    deleted_names = []
    skipped_admin = False
    for user in users:
        if user.username == 'admin':
            skipped_admin = True
            continue
        deleted_names.append(user.username)
        db.session.delete(user)

    db.session.commit()
    if deleted_names:
        log_action(
            session['uid'],
            session['fullname'],
            "Xóa hàng loạt tài khoản",
            "Tài khoản",
            ", ".join(deleted_names[:20]) + ("..." if len(deleted_names) > 20 else "")
        )
        flash(f'Đã xóa {len(deleted_names)} tài khoản.', 'success')
    if skipped_admin:
        flash('Tài khoản admin hệ thống được giữ lại và không bị xóa.', 'warning')
    return redirect(url_for('admin_bp.roles'))


@admin_bp.route('/admin/users/reset-password-bulk', methods=['POST'])
def reset_users_password_bulk():
    if not session.get('is_admin'):
        flash('Chỉ quản trị viên mới được reset mật khẩu hàng loạt.', 'danger')
        return redirect(url_for('admin_bp.roles'))

    raw_selected = request.form.get('selected_ids', '').strip()
    try:
        selected_ids = json.loads(raw_selected) if raw_selected else []
    except Exception:
        selected_ids = []

    selected_ids = [int(uid) for uid in selected_ids if str(uid).isdigit()]
    selected_role_id = request.form.get('role_id', type=int)
    selected_unit = (request.form.get('unit') or '').strip()
    search_query = (request.form.get('q') or '').strip()
    unit_options = _unit_category_options()
    selected_unit = canonicalize_category_value(selected_unit, unit_options, prefer_stable=True) if selected_unit else ''
    selected_role, users_query = _build_role_user_query(
        selected_role_id=selected_role_id,
        selected_unit=selected_unit,
        search_query=search_query
    )

    if selected_ids:
        reset_query = User.query.filter(User.id.in_(selected_ids))
    else:
        reset_query = users_query

    updated_count, skipped_admin = _reset_users_passwords_bulk(reset_query, default_password='123456')
    if updated_count == 0 and not skipped_admin:
        flash('Không có tài khoản nào trong danh sách hiện tại để reset mật khẩu.', 'warning')
        return redirect(url_for('admin_bp.roles', role_id=selected_role_id, unit=selected_unit, q=search_query))
    if updated_count == 0 and skipped_admin:
        flash('Tài khoản admin hệ thống được giữ lại và không bị reset mật khẩu.', 'warning')
        return redirect(url_for('admin_bp.roles', role_id=selected_role_id, unit=selected_unit, q=search_query))

    db.session.commit()

    filter_parts = []
    if selected_role:
        filter_parts.append(f"vai_tro={selected_role.name}")
    if selected_unit:
        selected_unit_display = resolve_category_display(selected_unit, unit_options, fallback_label=selected_unit)['display_name']
        filter_parts.append(f"don_vi={selected_unit_display}")
    if search_query:
        filter_parts.append(f"tu_khoa={search_query}")

    log_action(
        session['uid'],
        session['fullname'],
        "Reset mật khẩu hàng loạt",
        "Tài khoản",
        f"so_luong={updated_count} | mat_khau_mac_dinh=123456" + (f" | {'; '.join(filter_parts)}" if filter_parts else "")
    )
    flash(f'Đã reset {updated_count} tài khoản về mật khẩu mặc định 123456 và yêu cầu đổi mật khẩu khi đăng nhập.', 'success')
    if skipped_admin:
        flash('Tài khoản admin hệ thống được giữ lại và không bị reset mật khẩu.', 'warning')
    return redirect(url_for('admin_bp.roles', role_id=selected_role_id, unit=selected_unit, q=search_query))

@admin_bp.route('/admin/user/toggle-status/<int:uid>')
def toggle_user_status(uid):
    if not session.get('is_admin'):
        flash('Chỉ quản trị viên mới được thay đổi trạng thái tài khoản.', 'danger')
        return redirect(url_for('admin_bp.roles'))
    u = db.session.get(User, uid)
    if u:
        if u.username == 'admin':
            flash('Không thể vô hiệu hóa tài khoản Quản trị hệ thống!', 'danger')
        else:
            u.is_active = not u.is_active
            db.session.commit()
            status_text = "kích hoạt" if u.is_active else "vô hiệu hóa"
            log_action(session['uid'], session['fullname'], f"{status_text.capitalize()} tài khoản", "Tài khoản", u.username)
            flash(f'Đã {status_text} tài khoản {u.username}!', 'success')
    return redirect(url_for('admin_bp.roles'))

@admin_bp.route('/logs', methods=['GET', 'POST'])
def logs():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    
    # Get distinct list of users for dropdown filter
    user_list = [u[0] for u in db.session.query(SystemLog.fullname).distinct().order_by(SystemLog.fullname).all() if u[0]]
    
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    user_str = request.args.get('user')
    q = SystemLog.query
    
    if start_str: 
        try: q = q.filter(SystemLog.created_at >= datetime.strptime(start_str, '%Y-%m-%d'))
        except: pass
    if end_str: 
        try: q = q.filter(SystemLog.created_at <= datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1))
        except: pass
    if user_str:
        q = q.filter(SystemLog.fullname.ilike(f'%{user_str}%'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'clear_all':
            clear_logs()
            flash('Đã xóa toàn bộ nhật ký!', 'success')
        elif action == 'clear_range':
            s = request.form.get('s_date')
            e = request.form.get('e_date')
            clear_logs(datetime.strptime(s, '%Y-%m-%d'), datetime.strptime(e, '%Y-%m-%d') + timedelta(days=1))
            flash(f'Đã xóa nhật ký từ {s} đến {e}', 'success')
        elif action == 'backup':
            logs_all = q.order_by(SystemLog.created_at.desc()).all()
            df = pd.DataFrame([{ 'Thời gian': l.created_at, 'Người dùng': l.fullname, 'Chức năng': l.module, 'Hành động': l.action, 'Chi tiết': l.details } for l in logs_all])
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False)
            return Response(output.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-disposition": "attachment; filename=system_logs.xlsx"})
        return redirect(url_for('admin_bp.logs'))

    return render_template('logs.html', logs=q.order_by(SystemLog.created_at.desc()).limit(200).all(), 
                           start=start_str, end=end_str, user_search=user_str, user_list=user_list)

@admin_bp.route('/admin/users/import', methods=['POST'])
def import_users():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    f = request.files.get('import_excel')
    role_id = request.form.get('role_id', 2) # Default to 2 if not selected
    role = db.session.get(AppRole, role_id) if role_id else None
    has_header = request.form.get('has_header') == '1'
    
    if f and f.filename.endswith(('.xlsx', '.xls')):
        try:
            df, inferred_has_header = _load_user_import_dataframe(f, has_header=has_header)
            created_count = 0
            skipped_empty = 0
            skipped_invalid = 0
            import_mode = 'unit'

            fullname_col, title_col = _user_import_commander_columns(df, has_header=inferred_has_header)
            if fullname_col is not None and title_col is not None:
                import_mode = 'commander'
                for _, row in df.iterrows():
                    fullname = str(row.get(fullname_col, '')).strip()
                    position_name = str(row.get(title_col, '')).strip()
                    if not fullname and not position_name:
                        skipped_empty += 1
                        continue

                    base_uname = build_commander_username(fullname, position_name)
                    if not fullname or not position_name or not base_uname:
                        skipped_invalid += 1
                        continue

                    uname = base_uname
                    counter = 2
                    while User.query.filter_by(username=uname).first():
                        uname = f"{base_uname}_{counter}"
                        counter += 1

                    u = User(
                        username=uname,
                        fullname=fullname,
                        unit_area=f"PC06 - {position_name}",
                        unit_key='pc06',
                        role_id=role_id
                    )
                    u.set_password('123456')
                    db.session.add(u)
                    created_count += 1
            else:
                col_name = _user_import_unit_column(df, has_header=inferred_has_header)
                if col_name is None:
                    flash('Không đọc được cột đơn vị từ file Excel.', 'danger')
                    return redirect(url_for('admin_bp.roles'))

                for _, row in df.iterrows():
                    unit_name = str(row.get(col_name, '')).strip()
                    if not unit_name:
                        skipped_empty += 1
                        continue

                    resolved_unit, unit_key = _resolve_user_unit_value(unit_name, unit_name, unit_name)
                    display_unit = resolve_category_display(resolved_unit, _unit_category_options(), fallback_label=unit_name)['display_name']
                    base_uname = build_role_account_username(role.name if role else '', display_unit, unit_key)
                    uname = base_uname
                    
                    counter = 2
                    while User.query.filter_by(username=uname).first():
                        uname = f"{base_uname}_{counter}"
                        counter += 1
                    
                    u = User(
                        username=uname,
                        fullname=unit_name,
                        unit_area=resolved_unit,
                        unit_key=unit_key,
                        role_id=role_id
                    )
                    u.set_password('123456')
                    db.session.add(u)
                    created_count += 1
            db.session.commit()
            log_action(
                session['uid'],
                session['fullname'],
                "Import tài khoản hàng loạt",
                "Tài khoản",
                f"Tạo {created_count}/{len(df)} dòng; kieu={import_mode}; bo_qua_trong={skipped_empty}; bo_qua_khong_hop_le={skipped_invalid}; has_header={inferred_has_header}"
            )
            header_note = 'có tiêu đề' if inferred_has_header else 'không có tiêu đề'
            mode_note = 'chỉ huy đội' if import_mode == 'commander' else 'đơn vị'
            flash(f'Đã nhập {created_count} tài khoản {mode_note} từ {len(df)} dòng dữ liệu ({header_note}).', 'success')
            if skipped_empty:
                flash(f'Có {skipped_empty} dòng trống bị bỏ qua.', 'warning')
            if skipped_invalid:
                flash('Có dòng bị bỏ qua vì thiếu họ tên/chức vụ hoặc chức vụ không phải Đội trưởng, Đội phó.', 'warning')
        except Exception as e: 
            db.session.rollback()
            flash(f'Lỗi import: {e}', 'danger')
    return redirect(url_for('admin_bp.roles'))



@admin_bp.route('/admin/system/update', methods=['GET', 'POST'])
def system_update():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    if request.method == 'POST':
        f = request.files.get('update_pkg')
        if f and f.filename.endswith('.zip'):
            upload_dir = os.path.join(current_app.root_path, 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            p = os.path.join(upload_dir, 'pkg.zip')
            f.save(p)
            
            # 1. Validate ZIP
            if not zipfile.is_zipfile(p):
                flash('File không phải định dạng ZIP hợp lệ!', 'danger')
                return redirect(url_for('admin_bp.system_update'))
            
            try:
                # 2. Safety Backup
                backup_dir = os.path.join(current_app.root_path, 'backups', 'auto_update', datetime.now().strftime('%Y%m%d_%H%M%S'))
                os.makedirs(backup_dir, exist_ok=True)
                
                # Correct DB Path for backup
                db_path = os.path.join(current_app.root_path, 'pc06_system.db')
                if os.path.exists(db_path):
                    shutil.copy2(db_path, os.path.join(backup_dir, 'pc06_system_pre_update.db'))
                
                # Snapshot core logic folders
                for folder in ['routes', 'templates', 'static']:
                    src = os.path.join(current_app.root_path, folder)
                    if os.path.exists(src):
                        # Use dirs_exist_ok=True if available or just skip if exists
                        shutil.copytree(src, os.path.join(backup_dir, folder), dirs_exist_ok=True)
                
                # 3. Unpack and Restart
                shutil.unpack_archive(p, current_app.root_path)
                restart = os.path.join(current_app.root_path, 'tmp', 'restart.txt')
                os.makedirs(os.path.dirname(restart), exist_ok=True)
                with open(restart, 'w', encoding='utf-8') as f_out: f_out.write(str(datetime.now()))
                
                log_action(session['uid'], session['fullname'], "Cập nhật hệ thống thành công (V3.5.0)", "Hệ thống")
                flash('Cập nhật thành công! Hệ thống đang khởi động lại...', 'success')
            except Exception as e: 
                flash(f'Lỗi cập nhật: {e}', 'danger')
                log_action(session['uid'], session['fullname'], f"Cập nhật thất bại: {e}", "Hệ thống")
        return redirect(url_for('admin_bp.system_update'))
    
    # Get git info
    git_info = {'branch': 'main', 'version': 'v3.5.0', 'commit_msg': 'Phiên bản hiện tại', 'commit_author': 'PC06', 'commit_date': datetime.now().strftime('%d/%m/%Y')}
    try:
        br = subprocess.run(['git', 'branch', '--show-current'], cwd=current_app.root_path, capture_output=True, text=True)
        if br.stdout: git_info['branch'] = br.stdout.strip()
        
        ver = subprocess.run(['git', 'describe', '--tags', '--always'], cwd=current_app.root_path, capture_output=True, text=True)
        if ver.stdout: git_info['version'] = ver.stdout.strip()
        
        msg = subprocess.run(['git', 'log', '-1', '--format=%s'], cwd=current_app.root_path, capture_output=True, text=True)
        if msg.stdout: git_info['commit_msg'] = msg.stdout.strip()
        
        author = subprocess.run(['git', 'log', '-1', '--format=%an'], cwd=current_app.root_path, capture_output=True, text=True)
        if author.stdout: git_info['commit_author'] = author.stdout.strip()
        
        date = subprocess.run(['git', 'log', '-1', '--format=%ad', '--date=short'], cwd=current_app.root_path, capture_output=True, text=True)
        if date.stdout: git_info['commit_date'] = date.stdout.strip()
    except: pass
    
    return render_template('system_update.html', git_info=git_info)


@admin_bp.route('/admin/ai-settings', methods=['GET', 'POST'])
def ai_settings():
    if not session.get('is_admin'):
        return redirect(url_for('auth_bp.login'))

    config = AIAssistantConfig.query.first()

    if request.method == 'POST':
        action = (request.form.get('action') or 'save').strip()
        provider = (request.form.get('provider') or 'deepseek').strip().lower()
        if provider not in AI_PROVIDER_CHOICES:
            provider = 'deepseek'

        model_name = (request.form.get('model_name') or AI_PROVIDER_DEFAULTS[provider]).strip()
        system_prompt = (request.form.get('system_prompt') or '').strip()
        new_api_key = (request.form.get('api_key') or '').strip()
        clear_api_key = bool(request.form.get('clear_api_key'))
        is_active = bool(request.form.get('is_active'))

        try:
            if not config:
                config = AIAssistantConfig()
                db.session.add(config)

            config.provider = provider
            config.model_name = model_name or AI_PROVIDER_DEFAULTS[provider]
            config.system_prompt = system_prompt or None
            config.is_active = is_active

            if clear_api_key:
                config.api_key = None
            elif new_api_key:
                config.api_key = new_api_key

            db.session.commit()

            if action == 'test_connection':
                result, errors = _test_ai_runtime_connection()
                if result and result.get('ok'):
                    flash(
                        f"Kết nối AI thành công qua {AI_PROVIDER_CHOICES.get(result['provider'], result['provider'])} / {result['model']}.",
                        'success'
                    )
                else:
                    error_message = (errors[0].get('error') if errors else 'Không lấy được phản hồi từ provider')
                    flash(f"Không kết nối được AI: {error_message}", 'danger')
                log_action(
                    session['uid'],
                    session['fullname'],
                    "Kiểm tra kết nối trợ lý AI",
                    "Hệ thống",
                    f"{AI_PROVIDER_CHOICES.get(provider, provider)} / {config.model_name}"
                )
            else:
                log_action(
                    session['uid'],
                    session['fullname'],
                    "Cập nhật cấu hình trợ lý AI",
                    "Hệ thống",
                    f"{AI_PROVIDER_CHOICES.get(provider, provider)} / {config.model_name}"
                )
                flash('Đã lưu cấu hình AI thành công!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi cấu hình AI: {e}', 'danger')

        return redirect(url_for('admin_bp.ai_settings'))

    provider = ((config.provider if config else None) or 'deepseek').strip().lower()
    if provider not in AI_PROVIDER_CHOICES:
        provider = 'deepseek'

    current_key = (config.api_key or '').strip() if config else ''
    env_key_names = {
        'deepseek': 'DEEPSEEK_API_KEY',
        'gemini': 'GEMINI_API_KEY',
        'openai': 'OPENAI_API_KEY',
        'groq': 'GROQ_API_KEY',
    }
    env_key_name = env_key_names.get(provider, '')
    env_has_key = bool((os.getenv(env_key_name, '') or '').strip())

    status = {
        'provider': provider,
        'provider_label': AI_PROVIDER_CHOICES.get(provider, provider),
        'model_name': (config.model_name if config and config.model_name else AI_PROVIDER_DEFAULTS[provider]),
        'has_db_key': bool(current_key),
        'masked_db_key': _mask_secret(current_key),
        'env_key_name': env_key_name,
        'env_has_key': env_has_key,
        'is_active': bool(config.is_active) if config else False,
        'effective_source': 'database' if current_key and (config and config.is_active) else ('environment' if env_has_key else 'none'),
    }

    return render_template(
        'admin_ai_settings.html',
        config=config,
        provider_choices=AI_PROVIDER_CHOICES,
        provider_defaults=AI_PROVIDER_DEFAULTS,
        status=status
    )

@admin_bp.route('/admin/system/git-pull', methods=['POST'])
def git_pull():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    
    try:
        # Check if git is available
        git_check = subprocess.run(['git', '--version'], capture_output=True, text=True)
        if git_check.returncode != 0:
            flash('Git không khả dụng trên máy chủ này!', 'danger')
            return redirect(url_for('admin_bp.system_update'))
        
        # Check if this is a git repo
        repo_check = subprocess.run(['git', 'rev-parse', '--git-dir'], 
                                cwd=current_app.root_path, capture_output=True, text=True)
        if repo_check.returncode != 0:
            flash('Thư mục này không phải là Git repository!', 'danger')
            return redirect(url_for('admin_bp.system_update'))
        
        # Check remote
        remote_check = subprocess.run(['git', 'remote', '-v'], 
                                    cwd=current_app.root_path, capture_output=True, text=True)
        if not remote_check.stdout.strip():
            flash('Chưa cấu hình Git remote! Vui lòng thêm remote: git remote add origin <url>', 'warning')
            return redirect(url_for('admin_bp.system_update'))
        
        # Perform Git Pull
        result = subprocess.run(['git', 'pull', 'origin', 'main'], 
                             cwd=current_app.root_path, 
                             capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            # Check if it's auth error
            if 'Permission denied' in result.stderr or 'authentication' in result.stderr.lower():
                flash('Lỗi xác thực GitHub! Cần cấu hình SSH Key hoặc Personal Access Token.', 'danger')
                log_action(session['uid'], session['fullname'], "Git pull thất bại: Lỗi xác thực", "Hệ thống")
            else:
                flash(f'Lỗi Git: {result.stderr}', 'danger')
                log_action(session['uid'], session['fullname'], f"Git pull thất bại: {result.stderr}", "Hệ thống")
            return redirect(url_for('admin_bp.system_update'))
        
        # Reload Database Migrations
        init_db(current_app)
        
        # Restart Passenger App
        restart_path = os.path.join(current_app.root_path, 'tmp', 'restart.txt')
        os.makedirs(os.path.dirname(restart_path), exist_ok=True)
        with open(restart_path, 'w') as f: f.write(str(datetime.now()))
        
        log_action(session['uid'], session['fullname'], "Cập nhật via GitHub thành công", "Hệ thống")
        flash(f'Đã cập nhật từ GitHub! {result.stdout}', 'success')
    except subprocess.TimeoutExpired:
        flash('Git pull quá thời gian! Kiểm tra kết nối mạng.', 'danger')
        log_action(session['uid'], session['fullname'], "Git pull thất bại: Timeout", "Hệ thống")
    except Exception as e:
        flash(f'Lỗi hệ thống: {str(e)}', 'danger')
        log_action(session['uid'], session['fullname'], f"Git pull thất bại: {str(e)}", "Hệ thống")
    
    return redirect(url_for('admin_bp.system_update'))

@admin_bp.route('/admin/git/status')
def git_status():
    """API: Get git status"""
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 403
    try:
        result = subprocess.run(['git', 'status', '--short'], cwd=current_app.root_path, 
                              capture_output=True, text=True)
        return jsonify({'output': result.stdout or 'Không có thay đổi'})
    except Exception as e:
        return jsonify({'output': f'Lỗi: {str(e)}'})

@admin_bp.route('/admin/git/log')
def git_log():
    """API: Get recent commits"""
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 403
    try:
        result = subprocess.run(['git', 'log', '--oneline', '-5'], cwd=current_app.root_path, 
                              capture_output=True, text=True)
        lines = result.stdout.strip().split('\n')
        commits = []
        for line in lines:
            if ' ' in line:
                hash_msg = line.split(' ', 1)
                commits.append({'hash': hash_msg[0], 'msg': hash_msg[1] if len(hash_msg) > 1 else '', 
                              'author': 'Admin', 'date': ' recently'})
        return jsonify({'commits': commits[:5]})
    except Exception as e:
        return jsonify({'commits': []})

@admin_bp.route('/admin/git/remote', methods=['GET', 'POST'])
def git_remote():
    """API: Get or set git remote"""
    if not session.get('is_admin'): return jsonify({'error': 'Unauthorized'}), 403
    
    if request.method == 'POST':
        remote_url = request.form.get('remote_url', '').strip()
        if not remote_url:
            return jsonify({'status': 'error', 'message': 'Thiếu URL'})
        
        try:
            # Check if remote exists
            check = subprocess.run(['git', 'remote'], cwd=current_app.root_path, capture_output=True, text=True)
            if 'origin' in check.stdout:
                # Update existing
                subprocess.run(['git', 'remote', 'set-url', 'origin', remote_url], 
                             cwd=current_app.root_path, capture_output=True)
            else:
                # Add new
                subprocess.run(['git', 'remote', 'add', 'origin', remote_url], 
                             cwd=current_app.root_path, capture_output=True)
            return jsonify({'status': 'success', 'message': 'Đã cập nhật remote URL'})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)})
    
    # GET: Return current remote
    try:
        result = subprocess.run(['git', 'remote', '-v'], cwd=current_app.root_path, 
                              capture_output=True, text=True)
        return jsonify({'output': result.stdout})
    except Exception as e:
        return jsonify({'output': '', 'error': str(e)})

@admin_bp.route('/admin/module-categories', methods=['GET', 'POST'])
def module_categories():
    if not session.get('is_admin'): return redirect(url_for('auth_bp.login'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add_group':
            name = request.form.get('name', '').strip()
            code = request.form.get('code', '').strip() or slugify_code(name)
            targets = request.form.getlist('targets')
            links = ", ".join(targets)
            if name:
                group = CategoryGroup(name=name, code=code, linked_modules=links, is_active=True)
                db.session.add(group)
                db.session.flush()
                for target_name in targets:
                    module = ModuleRegistry.query.filter_by(name=target_name).first()
                    if module:
                        db.session.add(CategoryGroupModule(group_id=group.id, module_id=module.id))
                db.session.commit()
                flash(f'Đã thêm danh mục hệ thống: {name}', 'success')
                
        elif action == 'delete_group':
            group_id = request.form.get('group_id')
            group = CategoryGroup.query.get(group_id)
            if group:
                name = group.name
                # Delete all items in group first
                CategoryItem.query.filter_by(group_id=group_id).delete()
                db.session.delete(group)
                db.session.commit()
                flash(f'Đã xóa danh mục hệ thống: {name}', 'warning')
                
        elif action == 'add_item':
            group_id = request.form.get('group_id')
            item_name = request.form.get('item_name', '').strip()
            if group_id and item_name:
                db.session.add(CategoryItem(group_id=group_id, code=slugify_code(item_name), name=item_name))
                db.session.commit()
                flash(f'Đã thêm thành phần: {item_name}', 'success')

        elif action == 'import_items_excel':
            group_id = request.form.get('group_id')
            excel_file = request.files.get('items_excel')

            if not group_id:
                flash('Thiếu nhóm danh mục để import!', 'danger')
            elif not excel_file or not excel_file.filename:
                flash('Vui lòng chọn file Excel để import!', 'danger')
            elif not excel_file.filename.lower().endswith(('.xlsx', '.xls')):
                flash('Chỉ hỗ trợ file .xlsx hoặc .xls', 'danger')
            else:
                try:
                    group = CategoryGroup.query.get(group_id)
                    if not group:
                        flash('Không tìm thấy nhóm danh mục!', 'danger')
                    else:
                        df = pd.read_excel(io.BytesIO(excel_file.read()), sheet_name=0)
                        if len(df.columns) == 0:
                            flash('File Excel không có cột dữ liệu!', 'danger')
                        else:
                            total_rows = len(df.index)
                            first_col = df.columns[0]
                            raw_values = [str(v).strip() for v in df[first_col].tolist() if pd.notna(v)]

                            seen = set()
                            deduped = []
                            for val in raw_values:
                                if not val:
                                    continue
                                key = val.lower()
                                if key in seen:
                                    continue
                                seen.add(key)
                                deduped.append(val)

                            existing = {
                                str(i.name).strip().lower()
                                for i in CategoryItem.query.filter_by(group_id=group_id).all()
                            }

                            added = 0
                            for name in deduped:
                                if name.lower() in existing:
                                    continue
                                db.session.add(CategoryItem(group_id=group_id, code=slugify_code(name), name=name))
                                existing.add(name.lower())
                                added += 1

                            db.session.commit()
                            skipped = max(total_rows - added, 0)
                            flash(
                                f'Import thành công: tổng dòng {total_rows}, thêm mới {added}, bỏ qua trống/trùng {skipped}.',
                                'success'
                            )
                except Exception as e:
                    db.session.rollback()
                    flash(f'Lỗi import Excel: {e}', 'danger')
                
        elif action == 'delete_item':
            item_id = request.form.get('item_id')
            item = CategoryItem.query.get(item_id)
            if item:
                name = item.name
                db.session.delete(item)
                db.session.commit()
                flash(f'Đã xóa thành phần: {name}', 'info')

        elif action == 'rename_item':
            item_id = request.form.get('item_id')
            item_name = request.form.get('item_name', '').strip()
            item = CategoryItem.query.get(item_id)
            if not item:
                flash('Không tìm thấy thành phần cần sửa.', 'warning')
            elif not item_name:
                flash('Tên thành phần không được để trống.', 'warning')
            else:
                duplicate = CategoryItem.query.filter(
                    CategoryItem.group_id == item.group_id,
                    func.lower(CategoryItem.name) == item_name.lower(),
                    CategoryItem.id != item.id,
                ).first()
                if duplicate:
                    flash(f'Tên thành phần "{item_name}" đã tồn tại trong danh mục này.', 'warning')
                else:
                    old_name = item.name
                    if not item.code:
                        item.code = slugify_code(item.name)
                    item.name = item_name
                    ensure_category_item_alias(item, old_name)
                    db.session.commit()
                    flash(f'Đã đổi tên thành phần: {old_name} -> {item_name}', 'success')

        elif action == 'save_binding':
            module_id = request.form.get('module_id')
            field_code = request.form.get('field_code', '').strip()
            field_label = request.form.get('field_label', '').strip()
            group_id = request.form.get('group_id')
            is_required = 1 if request.form.get('is_required') else 0

            if module_id and field_code and group_id:
                binding = ModuleFieldBinding.query.filter_by(module_id=module_id, field_code=field_code).first()
                if not binding:
                    binding = ModuleFieldBinding(module_id=module_id, field_code=field_code)
                    db.session.add(binding)
                binding.field_label = field_label or field_code
                binding.group_id = int(group_id)
                binding.is_required = bool(is_required)
                binding.allow_multiple_groups = False
                db.session.commit()
                flash('Đã cập nhật liên kết field thành công!', 'success')

        return redirect(url_for('admin_bp.module_categories'))

    groups = CategoryGroup.query.order_by(CategoryGroup.sort_order.asc(), CategoryGroup.name.asc()).all()
    modules = ModuleRegistry.query.order_by(ModuleRegistry.sort_order.asc(), ModuleRegistry.name.asc()).all()
    current_pane = (request.args.get('pane') or 'groups').strip().lower()
    if current_pane not in {'groups', 'categories', 'bindings'}:
        current_pane = 'groups'
    bindings = ModuleFieldBinding.query.all()
    binding_map = {(binding.module_id, binding.field_code): binding for binding in bindings}
    module_fields = {
        'news': [
            {'code': 'category', 'label': 'Danh mục bảng tin'}
        ],
        'library': [
            {'code': 'category', 'label': 'Danh mục thư viện'},
            {'code': 'document_type', 'label': 'Loại tài liệu'}
        ],
        'tasks': [
            {'code': 'domain', 'label': 'Đội nghiệp vụ'},
            {'code': 'task_type', 'label': 'Loại công việc'},
            {'code': 'priority', 'label': 'Mức độ ưu tiên'},
            {'code': 'initial_status', 'label': 'Trạng thái khởi tạo'}
        ],
        'contacts': [
            {'code': 'contact_group', 'label': 'Nhóm danh bạ'},
            {'code': 'role', 'label': 'Chức vụ'},
            {'code': 'unit_name', 'label': 'Đơn vị'},
            {'code': 'category', 'label': 'Lĩnh vực'}
        ]
    }
    sidebar_submenu_items = [
        {
            'label': 'Nhóm danh mục',
            'href': url_for('admin_bp.module_categories', pane='groups'),
            'active': current_pane == 'groups',
        },
        {
            'label': 'Danh mục',
            'href': url_for('admin_bp.module_categories', pane='categories'),
            'active': current_pane == 'categories',
        },
        {
            'label': 'Liên kết field',
            'href': url_for('admin_bp.module_categories', pane='bindings'),
            'active': current_pane == 'bindings',
        },
    ]
    return render_template(
        'module_categories.html',
        groups=groups,
        modules=modules,
        module_fields=module_fields,
        binding_map=binding_map,
        current_pane=current_pane,
        sidebar_submenu_parent='module_categories',
        sidebar_submenu_title='Thiết lập danh mục',
        sidebar_submenu_items=sidebar_submenu_items,
    )

@admin_bp.route('/admin/categories/delete-old/<string:cat_type>/<int:cat_id>')
def delete_category_old(cat_type, cat_id):
    """Legacy route - chuyển hướng về module_categories"""
    return redirect(url_for('admin_bp.module_categories'))
