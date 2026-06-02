# -*- coding: utf-8 -*-
import json
import mimetypes
import os
import uuid
from datetime import date, datetime

from flask import Blueprint, abort, current_app, flash, redirect, request, send_file, session, url_for
from werkzeug.utils import secure_filename

from attendance_utils import (
    build_slots_for_date,
    describe_weekdays,
    normalize_attendance_config,
    normalize_schedule_times,
    normalize_time_string,
    normalize_weekdays,
    parse_hhmm,
    resolve_slot_status,
)
from category_helpers import module_category_options, resolve_category_display
from models import AppRole, AttendanceConfig, AttendanceSubmission, User, db
from utils import (
    extract_unit_key,
    has_module_permission,
    log_action,
    normalize_permission_payload,
    render_auto_template as render_template,
)

attendance_bp = Blueprint('attendance_bp', __name__)

IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
STATUS_META = {
    'completed': {'label': 'Đã điểm danh', 'class_name': 'success'},
    'available': {'label': 'Đang mở', 'class_name': 'primary'},
    'upcoming': {'label': 'Sắp đến', 'class_name': 'secondary'},
    'missed': {'label': 'Quá hạn', 'class_name': 'danger'},
}


def _attendance_role_context():
    role = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    role_name = getattr(role, 'name', '') or ''
    perms = {}
    if role and role.perms:
        try:
            perms = normalize_permission_payload(role.perms, is_admin=session.get('is_admin'), role_name=role_name)
        except Exception:
            perms = {}
    return perms, role_name


def _can_view_attendance(perms, role_name):
    if not session.get('uid'):
        return False
    return bool(
        session.get('is_admin')
        or has_module_permission(perms, 'attendance', 'view', is_admin=session.get('is_admin'), role_name=role_name)
        or has_module_permission(perms, 'task', 'view', is_admin=session.get('is_admin'), role_name=role_name)
    )


def _can_submit_attendance(perms, role_name):
    if not session.get('uid'):
        return True
    return bool(
        session.get('is_admin')
        or has_module_permission(perms, 'attendance', 'exec', is_admin=session.get('is_admin'), role_name=role_name)
        or has_module_permission(perms, 'attendance', 'process', is_admin=session.get('is_admin'), role_name=role_name)
        or has_module_permission(perms, 'task', 'exec', is_admin=session.get('is_admin'), role_name=role_name)
        or has_module_permission(perms, 'task', 'process', is_admin=session.get('is_admin'), role_name=role_name)
    )


def _can_manage_attendance(perms, role_name):
    return bool(
        session.get('is_admin')
        or has_module_permission(perms, 'attendance', 'process', is_admin=session.get('is_admin'), role_name=role_name)
        or has_module_permission(perms, 'sys', 'process', is_admin=session.get('is_admin'), role_name=role_name)
    )


def _get_current_config():
    active_config = AttendanceConfig.query.filter_by(is_active=True).order_by(AttendanceConfig.updated_at.desc(), AttendanceConfig.id.desc()).first()
    latest_config = AttendanceConfig.query.order_by(AttendanceConfig.updated_at.desc(), AttendanceConfig.id.desc()).first()
    return active_config, latest_config


def _build_attendance_config_list():
    records = []
    configs = AttendanceConfig.query.order_by(AttendanceConfig.updated_at.desc(), AttendanceConfig.id.desc()).all()
    for config in configs:
        normalized = normalize_attendance_config(config)
        records.append({
            'id': config.id,
            'name': normalized.get('name') or config.name or 'Điểm danh tự động',
            'mode': normalized.get('mode') or 'interval',
            'mode_label': 'Theo khung giờ cố định' if normalized.get('mode') == 'schedule' else 'Tự động theo chu kỳ',
            'is_active': bool(config.is_active),
            'summary': _format_config_summary(normalized),
            'updated_at': config.updated_at or config.created_at,
            'note': (normalized.get('note') or '').strip(),
        })
    return records


def _unit_category_options():
    return module_category_options('contacts', 'unit_name', 'Đơn vị')


def _build_unit_option_maps(unit_options):
    key_map = {}
    for option in unit_options or []:
        stable_key = (option.get('stable_value') or option.get('value') or option.get('code') or '').strip()
        alias_keys = {
            stable_key,
            (option.get('value') or '').strip(),
            (option.get('code') or '').strip(),
            (option.get('name') or '').strip(),
        }
        for alias_key in alias_keys:
            if alias_key:
                key_map[alias_key] = {
                    'unit_key': stable_key,
                    'unit_name': (option.get('name') or option.get('value') or '').strip() or stable_key,
                }
    return key_map


def _dedupe_unit_options(unit_option_map):
    unique_options = {}
    for item in (unit_option_map or {}).values():
        unit_key = (item.get('unit_key') or '').strip()
        if unit_key and unit_key not in unique_options:
            unique_options[unit_key] = item
    return sorted(unique_options.values(), key=lambda item: (item.get('unit_name') or '').lower())


def _attendance_return_endpoint():
    path = (request.path or '').strip().lower()
    if path.startswith('/diem-danh'):
        return 'attendance_bp.public_attendance'
    return 'attendance_bp.attendance_home'


def _attendance_home_redirect(edit_submission_id=None):
    params = {}
    slot_key = (request.form.get('return_slot_key') or request.args.get('slot_key') or '').strip()
    edit_config_id = request.form.get('return_edit_config_id', type=int) or request.args.get('edit_config_id', type=int) or 0
    if slot_key:
        params['slot_key'] = slot_key
    if edit_config_id:
        params['edit_config_id'] = edit_config_id
    if edit_submission_id:
        params['edit_submission_id'] = edit_submission_id
    return redirect(url_for('attendance_bp.attendance_home', **params))


def _resolve_unit_display(value, unit_options, fallback_label='Chưa có đơn vị'):
    raw_value = (value or '').strip()
    if not raw_value:
        return fallback_label
    return resolve_category_display(raw_value, unit_options, fallback_label=raw_value)['display_name']


def _is_system_unit(unit_name):
    normalized = (unit_name or '').strip().lower()
    return normalized in {'hệ thống', 'he thong', 'system'}


def _get_public_submitter_user():
    public_user = User.query.filter_by(username='public_attendance').first()
    if public_user:
        return public_user

    public_user = User(
        username='public_attendance',
        fullname='Điểm danh công khai',
        role_id=None,
        unit_area='Hệ thống',
        unit_key=extract_unit_key('Hệ thống'),
        is_active=False,
        must_change_password=False,
    )
    public_user.set_password(uuid.uuid4().hex)
    db.session.add(public_user)
    db.session.commit()
    return public_user


def _format_config_summary(config_payload):
    if not config_payload:
        return ''
    weekday_text = describe_weekdays(config_payload['active_weekdays'])
    if config_payload['mode'] == 'schedule':
        schedule_text = ', '.join(config_payload['schedule_times']) if config_payload['schedule_times'] else 'Chưa có mốc giờ'
        return f"Khung giờ cố định: {schedule_text}. Áp dụng: {weekday_text}. Mở trước {config_payload['early_checkin_minutes']} phút, cho phép trễ {config_payload['late_allow_minutes']} phút."
    return (
        f"Lặp mỗi {config_payload['interval_minutes']} phút từ {config_payload['day_start_time']} đến {config_payload['day_end_time']}. "
        f"Áp dụng: {weekday_text}. Mở trước {config_payload['early_checkin_minutes']} phút, cho phép trễ {config_payload['late_allow_minutes']} phút."
    )


def _build_slot_rows(config, current_time):
    if not config:
        return []
    today = current_time.date()
    today_slots = build_slots_for_date(today, config)
    if not today_slots:
        return []

    rows = []
    for slot in today_slots:
        status = resolve_slot_status(slot, now=current_time)
        meta = STATUS_META.get(status, STATUS_META['upcoming'])
        row = dict(slot)
        row['submission'] = None
        row['status'] = status
        row['status_label'] = meta['label']
        row['status_class'] = meta['class_name']
        rows.append(row)
    return rows


def _build_monitor_slot_context(slot_rows, current_time, selected_slot_key=''):
    if not slot_rows:
        return {
            'selected_slot': None,
            'slot_options': [],
        }

    slot_options = []
    selected_slot = None
    available_slot = None
    latest_past_slot = None

    for slot in slot_rows:
        slot_status = resolve_slot_status(slot, now=current_time)
        meta = STATUS_META.get(slot_status, STATUS_META['upcoming'])
        slot_option = {
            'slot_key': slot['slot_key'],
            'slot_label': slot['slot_label'],
            'slot_time': slot['slot_time'],
            'status': slot_status,
            'status_label': meta['label'],
            'status_class': meta['class_name'],
            'due_at': slot['due_at'],
            'window_start_at': slot['window_start_at'],
            'window_end_at': slot['window_end_at'],
        }
        slot_options.append(slot_option)

        if slot['slot_key'] == selected_slot_key:
            selected_slot = slot_option
        if slot_status == 'available' and available_slot is None:
            available_slot = slot_option
        if slot['due_at'] <= current_time:
            if latest_past_slot is None or slot['due_at'] > latest_past_slot['due_at']:
                latest_past_slot = slot_option

    if selected_slot is None:
        selected_slot = available_slot or latest_past_slot or slot_options[0]

    return {
        'selected_slot': selected_slot,
        'slot_options': slot_options,
    }


def _build_unit_attendance_stats(config, selected_slot, unit_options):
    empty_stats = {
        'selected_slot': selected_slot,
        'total_units': 0,
        'checked_units_count': 0,
        'pending_units_count': 0,
        'submission_count': 0,
        'coverage_percent': 0,
        'checked_units': [],
        'pending_units': [],
    }
    if not config or not selected_slot:
        return empty_stats

    unit_option_map = _build_unit_option_maps(unit_options)
    unit_map = {}

    for option in unit_options or []:
        unit_key = (option.get('stable_value') or option.get('value') or option.get('code') or '').strip()
        unit_name = (option.get('name') or option.get('value') or '').strip()
        if not unit_key or not unit_name or _is_system_unit(unit_name):
            continue
        unit_map[unit_key] = {
            'unit_key': unit_key,
            'unit_name': unit_name,
            'member_count': 0,
            'submission_count': 0,
            'submitted': False,
            'latest_submission_at': None,
            'latest_submitter': '',
            'latest_note': '',
        }

    for user in User.query.filter_by(is_active=True).order_by(User.fullname.asc(), User.username.asc()).all():
        unit_info = unit_option_map.get((getattr(user, 'unit_area', None) or '').strip()) or unit_option_map.get((getattr(user, 'unit_key', None) or '').strip())
        if not unit_info:
            unit_display = _resolve_unit_display(getattr(user, 'unit_area', None), unit_options, fallback_label='')
            if not unit_display or _is_system_unit(unit_display):
                continue
            unit_identifier = (getattr(user, 'unit_key', None) or unit_display).strip()
            if not unit_identifier:
                continue
            unit_info = {'unit_key': unit_identifier, 'unit_name': unit_display}
        record = unit_map.setdefault(
            unit_info['unit_key'],
            {
                'unit_key': unit_info['unit_key'],
                'unit_name': unit_info['unit_name'],
                'member_count': 0,
                'submission_count': 0,
                'submitted': False,
                'latest_submission_at': None,
                'latest_submitter': '',
                'latest_note': '',
            },
        )
        record['member_count'] += 1

    submissions = AttendanceSubmission.query.filter_by(
        config_id=config.id,
        slot_key=selected_slot['slot_key'],
    ).order_by(AttendanceSubmission.submitted_at.desc(), AttendanceSubmission.id.desc()).all()

    for submission in submissions:
        raw_unit = (submission.unit_key or '').strip()
        unit_info = unit_option_map.get(raw_unit)
        if unit_info:
            unit_identifier = unit_info['unit_key']
            unit_display = unit_info['unit_name']
        else:
            raw_display = submission.unit_area or getattr(getattr(submission, 'user', None), 'unit_area', None) or ''
            unit_display = _resolve_unit_display(raw_display, unit_options, fallback_label='Chưa có đơn vị')
            unit_identifier = (
                raw_unit
                or getattr(getattr(submission, 'user', None), 'unit_key', None)
                or unit_display
            ).strip()
        if _is_system_unit(unit_display):
            continue
        if not unit_identifier:
            continue
        record = unit_map.setdefault(
            unit_identifier,
            {
                'unit_key': unit_identifier,
                'unit_name': unit_display,
                'member_count': 0,
                'submission_count': 0,
                'submitted': False,
                'latest_submission_at': None,
                'latest_submitter': '',
                'latest_note': '',
            },
        )
        record['submitted'] = True
        record['submission_count'] += 1
        submitted_at = submission.submitted_at or submission.created_at
        if submitted_at and (record['latest_submission_at'] is None or submitted_at > record['latest_submission_at']):
            record['latest_submission_at'] = submitted_at
            submitter = getattr(getattr(submission, 'user', None), 'fullname', None) or str(submission.user_id)
            if getattr(getattr(submission, 'user', None), 'username', '') == 'public_attendance':
                submitter = 'Điểm danh công khai'
            record['latest_submitter'] = submitter
            record['latest_note'] = (submission.note or '').strip()

    rows = sorted(unit_map.values(), key=lambda item: (item['unit_name'] or '').lower())
    checked_units = [row for row in rows if row['submitted']]
    pending_units = [row for row in rows if not row['submitted']]
    total_units = len(rows)
    checked_units_count = len(checked_units)
    pending_units_count = len(pending_units)
    coverage_percent = int(round((checked_units_count / total_units) * 100)) if total_units else 0

    return {
        'selected_slot': selected_slot,
        'total_units': total_units,
        'checked_units_count': checked_units_count,
        'pending_units_count': pending_units_count,
        'submission_count': len(submissions),
        'coverage_percent': coverage_percent,
        'checked_units': checked_units,
        'pending_units': pending_units,
    }


def _save_proof_file(file_storage):
    if not file_storage or not file_storage.filename:
        raise ValueError('Ảnh minh chứng là bắt buộc.')

    original_name = file_storage.filename
    safe_name = secure_filename(original_name)
    if not safe_name or '.' not in safe_name:
        raise ValueError('Tên file ảnh không hợp lệ.')

    extension = safe_name.rsplit('.', 1)[1].lower()
    if extension not in IMAGE_EXTENSIONS:
        raise ValueError('Chỉ chấp nhận ảnh JPG, JPEG, PNG hoặc WEBP.')

    relative_dir = os.path.join('attendance_proofs', datetime.now().strftime('%Y'), datetime.now().strftime('%m'))
    absolute_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], relative_dir)
    os.makedirs(absolute_dir, exist_ok=True)

    file_basename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_name}"
    absolute_path = os.path.join(absolute_dir, file_basename)
    file_storage.save(absolute_path)

    return os.path.join(relative_dir, file_basename), safe_name


def _remove_proof_file(relative_path):
    if not relative_path:
        return

    upload_root = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    proof_path = os.path.abspath(os.path.join(upload_root, relative_path))
    if not proof_path.startswith(upload_root + os.sep):
        return
    if os.path.exists(proof_path):
        os.remove(proof_path)


def _can_modify_submission(submission, can_manage):
    if not submission or not session.get('uid'):
        return False
    if can_manage:
        return True
    return submission.user_id == session.get('uid')


def _load_editable_submission(submission_id, can_manage):
    submission = db.session.get(AttendanceSubmission, submission_id) if submission_id else None
    if not submission:
        return None
    if not _can_modify_submission(submission, can_manage):
        return None
    return submission


@attendance_bp.route('/attendance')
def attendance_home():
    perms, role_name = _attendance_role_context()
    can_manage = _can_manage_attendance(perms, role_name)
    is_public_view = not session.get('uid')
    if session.get('uid') and not _can_view_attendance(perms, role_name):
        flash('Bạn không có quyền truy cập tính năng điểm danh.', 'danger')
        return redirect(url_for('admin_bp.index'))

    active_config, latest_config = _get_current_config()
    config_for_display = active_config or latest_config
    normalized_config = normalize_attendance_config(config_for_display) if config_for_display else None
    now = datetime.now()
    unit_options = _unit_category_options()
    unit_option_map = _build_unit_option_maps(unit_options)
    config_records = _build_attendance_config_list() if can_manage else []
    edit_config_id = request.args.get('edit_config_id', type=int) or 0
    editing_config = db.session.get(AttendanceConfig, edit_config_id) if can_manage and edit_config_id else None
    edit_submission_id = request.args.get('edit_submission_id', type=int) or 0
    editing_submission = _load_editable_submission(edit_submission_id, can_manage) if session.get('uid') and edit_submission_id else None
    form_config = editing_config
    form_config_payload = normalize_attendance_config(form_config) if form_config else None

    slot_rows = _build_slot_rows(active_config, now)
    selected_slot_key = (request.args.get('slot_key') or '').strip()
    monitor_slot_context = _build_monitor_slot_context(
        build_slots_for_date(now.date(), active_config) if active_config else [],
        now,
        selected_slot_key=selected_slot_key,
    )
    stats = {
        'completed': sum(1 for row in slot_rows if row['status'] == 'completed'),
        'available': sum(1 for row in slot_rows if row['status'] == 'available'),
        'upcoming': sum(1 for row in slot_rows if row['status'] == 'upcoming'),
        'missed': sum(1 for row in slot_rows if row['status'] == 'missed'),
    }

    own_recent_submissions = []
    if session.get('uid'):
        own_recent_submissions = AttendanceSubmission.query.filter_by(user_id=session['uid']).order_by(
            AttendanceSubmission.submitted_at.desc(),
            AttendanceSubmission.id.desc(),
        ).limit(12).all()
        stats['completed'] = sum(1 for submission in own_recent_submissions if submission.slot_date == now.date())

    can_submit = _can_submit_attendance(perms, role_name)
    admin_recent_submissions = []
    admin_summary = None
    unit_attendance = _build_unit_attendance_stats(active_config, monitor_slot_context['selected_slot'], unit_options) if can_manage else None
    if can_manage:
        admin_recent_submissions = AttendanceSubmission.query.order_by(
            AttendanceSubmission.submitted_at.desc(),
            AttendanceSubmission.id.desc(),
        ).limit(20).all()
        active_user_count = User.query.filter_by(is_active=True).count()
        today_query = AttendanceSubmission.query.filter_by(slot_date=now.date())
        if active_config:
            today_query = today_query.filter(AttendanceSubmission.config_id == active_config.id)
        admin_summary = {
            'active_user_count': active_user_count,
            'today_submission_count': today_query.count(),
            'config_status': 'Đang kích hoạt' if active_config else 'Chưa kích hoạt',
            'checked_units_count': unit_attendance['checked_units_count'] if unit_attendance else 0,
            'pending_units_count': unit_attendance['pending_units_count'] if unit_attendance else 0,
            'coverage_percent': unit_attendance['coverage_percent'] if unit_attendance else 0,
        }

    return render_template(
        'attendance.html',
        title='Điểm danh',
        active_config=active_config,
        latest_config=latest_config,
        normalized_config=normalized_config,
        editing_config=editing_config,
        editing_submission=editing_submission,
        form_config=form_config,
        form_config_payload=form_config_payload,
        config_records=config_records,
        config_summary=_format_config_summary(normalized_config),
        form_schedule_times_text='\n'.join((form_config_payload or {}).get('schedule_times', [])),
        form_active_weekdays=((form_config_payload or {}).get('active_weekdays') or list(range(7))),
        weekday_labels=[
            {'value': 0, 'label': 'Thứ 2'},
            {'value': 1, 'label': 'Thứ 3'},
            {'value': 2, 'label': 'Thứ 4'},
            {'value': 3, 'label': 'Thứ 5'},
            {'value': 4, 'label': 'Thứ 6'},
            {'value': 5, 'label': 'Thứ 7'},
            {'value': 6, 'label': 'Chủ nhật'},
        ],
        slot_rows=slot_rows,
        stats=stats,
        own_recent_submissions=own_recent_submissions,
        admin_recent_submissions=admin_recent_submissions,
        admin_summary=admin_summary,
        unit_attendance=unit_attendance,
        monitor_slot_context=monitor_slot_context,
        selected_slot_key=selected_slot_key,
        attendance_unit_options=_dedupe_unit_options(unit_option_map),
        default_attendance_unit_key=(
            (
                unit_option_map.get((session.get('unit_area_ref') or '').strip())
                or unit_option_map.get((session.get('unit_key') or '').strip())
                or unit_option_map.get((session.get('unit_area') or '').strip())
            ) or {}
        ).get('unit_key', ''),
        is_public_attendance=is_public_view,
        can_manage_attendance=can_manage,
        can_submit_attendance=can_submit,
        now=now,
    )


@attendance_bp.route('/diem-danh')
def public_attendance():
    active_config, latest_config = _get_current_config()
    config_for_display = active_config or latest_config
    normalized_config = normalize_attendance_config(config_for_display) if config_for_display else None
    now = datetime.now()
    unit_options = _unit_category_options()
    unit_option_map = _build_unit_option_maps(unit_options)
    slot_rows = _build_slot_rows(active_config, now)

    stats = {
        'completed': 0,
        'available': sum(1 for row in slot_rows if row['status'] == 'available'),
        'upcoming': sum(1 for row in slot_rows if row['status'] == 'upcoming'),
        'missed': sum(1 for row in slot_rows if row['status'] == 'missed'),
    }

    return render_template(
        'attendance_public.html',
        title='Điểm danh công khai',
        active_config=active_config,
        latest_config=latest_config,
        normalized_config=normalized_config,
        config_summary=_format_config_summary(normalized_config),
        slot_rows=slot_rows,
        stats=stats,
        attendance_unit_options=_dedupe_unit_options(unit_option_map),
        default_attendance_unit_key='',
        can_submit_attendance=True,
        now=now,
    )


@attendance_bp.route('/attendance/config', methods=['POST'])
def save_attendance_config():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    perms, role_name = _attendance_role_context()
    if not _can_manage_attendance(perms, role_name):
        flash('Bạn không có quyền cấu hình điểm danh.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    mode = (request.form.get('mode') or 'interval').strip().lower()
    if mode not in {'interval', 'schedule'}:
        flash('Chế độ điểm danh không hợp lệ.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    schedule_times = normalize_schedule_times(request.form.get('schedule_times'))
    interval_minutes = request.form.get('interval_minutes', type=int) or 0
    early_checkin_minutes = max(0, request.form.get('early_checkin_minutes', type=int) or 0)
    late_allow_minutes = max(0, request.form.get('late_allow_minutes', type=int) or 0)
    day_start_time = normalize_time_string(request.form.get('day_start_time'), '08:00')
    day_end_time = normalize_time_string(request.form.get('day_end_time'), '17:00')
    weekdays = normalize_weekdays(request.form.getlist('weekdays'))

    if mode == 'interval':
        if interval_minutes <= 0:
            flash('Chu kỳ tự động phải lớn hơn 0 phút.', 'danger')
            return redirect(url_for('attendance_bp.attendance_home'))
        start_time = parse_hhmm(day_start_time)
        end_time = parse_hhmm(day_end_time)
        if not start_time or not end_time or (end_time.hour, end_time.minute) < (start_time.hour, start_time.minute):
            flash('Khung giờ áp dụng không hợp lệ.', 'danger')
            return redirect(url_for('attendance_bp.attendance_home'))
    elif not schedule_times:
        flash('Bạn cần khai báo ít nhất một mốc giờ cố định.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    config_id = request.form.get('config_id', type=int) or 0
    is_new_config = not config_id
    config = db.session.get(AttendanceConfig, config_id) if config_id else None
    if config_id and not config:
        flash('Không tìm thấy cấu hình điểm danh cần cập nhật.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    if not config:
        config = AttendanceConfig(created_by=session['uid'])
        db.session.add(config)

    config.name = (request.form.get('name') or 'Điểm danh tự động').strip()
    config.mode = mode
    config.interval_minutes = interval_minutes or config.interval_minutes or 120
    config.day_start_time = day_start_time
    config.day_end_time = day_end_time
    config.schedule_times_json = json.dumps(schedule_times, ensure_ascii=False)
    config.active_weekdays_json = json.dumps(weekdays, ensure_ascii=False)
    config.early_checkin_minutes = early_checkin_minutes
    config.late_allow_minutes = late_allow_minutes
    config.is_active = bool(request.form.get('is_active'))
    config.note = (request.form.get('note') or '').strip()
    config.updated_by = session['uid']

    try:
        db.session.flush()
        if config.is_active:
            AttendanceConfig.query.filter(AttendanceConfig.id != config.id).update(
                {'is_active': False},
                synchronize_session=False,
            )
        db.session.commit()
        log_action(
            session['uid'],
            session['fullname'],
            'Tạo cấu hình điểm danh' if is_new_config else 'Cập nhật cấu hình điểm danh',
            'Điểm danh',
            config.name,
        )
        flash(
            'Đã tạo cấu hình điểm danh mới.' if is_new_config else 'Đã cập nhật cấu hình điểm danh.',
            'success',
        )
    except Exception as exc:
        db.session.rollback()
        flash(f'Lỗi khi lưu cấu hình: {exc}', 'danger')

    return redirect(url_for('attendance_bp.attendance_home'))


@attendance_bp.route('/attendance/config/<int:config_id>/delete', methods=['POST'])
def delete_attendance_config(config_id):
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    perms, role_name = _attendance_role_context()
    if not _can_manage_attendance(perms, role_name):
        flash('Bạn không có quyền xoá cấu hình điểm danh.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    config = db.session.get(AttendanceConfig, config_id)
    if not config:
        flash('Không tìm thấy cấu hình điểm danh cần xoá.', 'warning')
        return redirect(url_for('attendance_bp.attendance_home'))

    related_submissions = AttendanceSubmission.query.filter_by(config_id=config.id).all()
    config_name = config.name or f'Cấu hình #{config.id}'

    try:
        for submission in related_submissions:
            _remove_proof_file(submission.proof_path)
            db.session.delete(submission)
        db.session.delete(config)
        db.session.commit()
        log_action(
            session['uid'],
            session['fullname'],
            'Xoá cấu hình điểm danh',
            'Điểm danh',
            f'{config_name} ({len(related_submissions)} lượt điểm danh liên quan)',
        )
        flash('Đã xoá cấu hình điểm danh.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Không thể xoá cấu hình điểm danh: {exc}', 'danger')

    return redirect(url_for('attendance_bp.attendance_home'))


@attendance_bp.route('/attendance/submission/<int:submission_id>/update', methods=['POST'])
def update_attendance_submission(submission_id):
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    perms, role_name = _attendance_role_context()
    can_manage = _can_manage_attendance(perms, role_name)
    submission = _load_editable_submission(submission_id, can_manage)
    if not submission:
        flash('Bạn không có quyền chỉnh sửa lượt điểm danh này.', 'danger')
        return _attendance_home_redirect()

    unit_option_map = _build_unit_option_maps(_unit_category_options())
    selected_unit_key = (request.form.get('unit_key') or '').strip()
    selected_unit = unit_option_map.get(selected_unit_key)
    note = (request.form.get('note') or '').strip()
    replace_proof = bool(request.files.get('proof_image') and request.files.get('proof_image').filename)

    if not selected_unit:
        flash('Bạn cần chọn đơn vị hợp lệ để cập nhật.', 'danger')
        return _attendance_home_redirect(edit_submission_id=submission.id)

    duplicate_submission = AttendanceSubmission.query.filter(
        AttendanceSubmission.id != submission.id,
        AttendanceSubmission.config_id == submission.config_id,
        AttendanceSubmission.slot_key == submission.slot_key,
        AttendanceSubmission.unit_key == selected_unit['unit_key'],
    ).first()
    if duplicate_submission:
        flash('Đơn vị này đã có lượt điểm danh ở mốc đã chọn.', 'warning')
        return _attendance_home_redirect(edit_submission_id=submission.id)

    old_proof_path = submission.proof_path
    old_proof_filename = submission.proof_filename
    new_proof_path = ''

    try:
        if replace_proof:
            new_proof_path, new_proof_filename = _save_proof_file(request.files.get('proof_image'))
            submission.proof_path = new_proof_path
            submission.proof_filename = new_proof_filename
        submission.unit_key = selected_unit['unit_key']
        submission.unit_area = selected_unit['unit_name']
        submission.note = note
        submission.updated_at = datetime.now()
        db.session.commit()
        if replace_proof and old_proof_path and old_proof_path != submission.proof_path:
            _remove_proof_file(old_proof_path)
        log_action(
            session['uid'],
            session['fullname'],
            'Cập nhật lượt điểm danh',
            'Điểm danh',
            f"{submission.slot_label or submission.slot_key} - {selected_unit['unit_name']}",
        )
        flash('Đã cập nhật lượt điểm danh.', 'success')
    except Exception as exc:
        db.session.rollback()
        if new_proof_path:
            _remove_proof_file(new_proof_path)
        submission.proof_path = old_proof_path
        submission.proof_filename = old_proof_filename
        flash(f'Không thể cập nhật lượt điểm danh: {exc}', 'danger')

    return _attendance_home_redirect()


@attendance_bp.route('/attendance/submission/<int:submission_id>/delete', methods=['POST'])
def delete_attendance_submission(submission_id):
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    perms, role_name = _attendance_role_context()
    can_manage = _can_manage_attendance(perms, role_name)
    submission = _load_editable_submission(submission_id, can_manage)
    if not submission:
        flash('Bạn không có quyền xoá lượt điểm danh này.', 'danger')
        return _attendance_home_redirect()

    proof_path = submission.proof_path
    submission_label = submission.slot_label or submission.slot_key or f'#{submission.id}'
    submission_unit = submission.unit_area or submission.unit_key or 'Chưa có đơn vị'

    try:
        db.session.delete(submission)
        db.session.commit()
        _remove_proof_file(proof_path)
        log_action(
            session['uid'],
            session['fullname'],
            'Xoá lượt điểm danh',
            'Điểm danh',
            f'{submission_label} - {submission_unit}',
        )
        flash('Đã xoá lượt điểm danh.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Không thể xoá lượt điểm danh: {exc}', 'danger')

    return _attendance_home_redirect()


@attendance_bp.route('/attendance/submit', methods=['POST'])
@attendance_bp.route('/diem-danh/submit', methods=['POST'])
def submit_attendance():
    perms, role_name = _attendance_role_context()
    if not _can_submit_attendance(perms, role_name):
        flash('Bạn không có quyền điểm danh.', 'danger')
        return redirect(url_for(_attendance_return_endpoint()))

    active_config, _latest_config = _get_current_config()
    if not active_config:
        flash('Hệ thống chưa kích hoạt cấu hình điểm danh.', 'warning')
        return redirect(url_for(_attendance_return_endpoint()))

    slot_date_raw = (request.form.get('slot_date') or '').strip()
    slot_key = (request.form.get('slot_key') or '').strip()
    selected_unit_key = (request.form.get('unit_key') or '').strip()
    note = (request.form.get('note') or '').strip()
    unit_option_map = _build_unit_option_maps(_unit_category_options())
    selected_unit = unit_option_map.get(selected_unit_key)

    try:
        slot_date = date.fromisoformat(slot_date_raw)
    except ValueError:
        flash('Mốc điểm danh không hợp lệ.', 'danger')
        return redirect(url_for(_attendance_return_endpoint()))

    if not selected_unit:
        flash('Bạn cần chọn đơn vị từ danh mục đã cấu hình.', 'danger')
        return redirect(url_for(_attendance_return_endpoint()))

    slots = build_slots_for_date(slot_date, active_config)
    slot = next((item for item in slots if item['slot_key'] == slot_key), None)
    if not slot:
        flash('Không tìm thấy mốc điểm danh cần nộp.', 'danger')
        return redirect(url_for(_attendance_return_endpoint()))

    existing_submission = AttendanceSubmission.query.filter_by(
        config_id=active_config.id,
        slot_key=slot_key,
        unit_key=selected_unit['unit_key'],
    ).first()
    slot_status = resolve_slot_status(slot, submission=existing_submission, now=datetime.now())
    if existing_submission:
        flash('Đơn vị này đã được điểm danh ở mốc đã chọn.', 'info')
        return redirect(url_for(_attendance_return_endpoint()))
    if slot_status != 'available':
        flash('Mốc điểm danh này chưa mở hoặc đã quá hạn.', 'warning')
        return redirect(url_for(_attendance_return_endpoint()))

    try:
        submitter_user = db.session.get(User, session['uid']) if session.get('uid') else _get_public_submitter_user()
        proof_path, proof_filename = _save_proof_file(request.files.get('proof_image'))
        submission = AttendanceSubmission(
            config_id=active_config.id,
            user_id=submitter_user.id,
            unit_area=selected_unit['unit_name'],
            unit_key=selected_unit['unit_key'],
            slot_key=slot['slot_key'],
            slot_label=slot['slot_label'],
            slot_date=slot['slot_date'],
            due_at=slot['due_at'],
            window_start_at=slot['window_start_at'],
            window_end_at=slot['window_end_at'],
            proof_filename=proof_filename,
            proof_path=proof_path,
            note=note,
            submitted_at=datetime.now(),
        )
        db.session.add(submission)
        db.session.commit()
        log_action(
            session.get('uid', 0),
            session.get('fullname', 'Điểm danh công khai'),
            'Điểm danh thành công',
            'Điểm danh',
            f"{slot['slot_label']} - {selected_unit['unit_name']}",
        )
        flash('Điểm danh thành công.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Không thể lưu điểm danh: {exc}', 'danger')

    return redirect(url_for(_attendance_return_endpoint()))


@attendance_bp.route('/attendance/proofs/<int:submission_id>')
def attendance_proof(submission_id):
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    perms, role_name = _attendance_role_context()
    submission = db.session.get(AttendanceSubmission, submission_id)
    if not submission or not submission.proof_path:
        abort(404)

    can_manage = _can_manage_attendance(perms, role_name)
    if not can_manage and submission.user_id != session.get('uid'):
        abort(403)

    upload_root = os.path.abspath(current_app.config['UPLOAD_FOLDER'])
    proof_path = os.path.abspath(os.path.join(upload_root, submission.proof_path))
    if not proof_path.startswith(upload_root + os.sep) and proof_path != upload_root:
        abort(404)
    if not os.path.exists(proof_path):
        abort(404)

    mime_type, _encoding = mimetypes.guess_type(proof_path)
    return send_file(proof_path, mimetype=mime_type or 'application/octet-stream')
