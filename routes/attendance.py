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
TASK_STATUS_META = {
    'inactive': {'label': 'Tạm dừng', 'class_name': 'secondary'},
    'unassigned': {'label': 'Chưa gán', 'class_name': 'warning'},
    'not_today': {'label': 'Không áp dụng hôm nay', 'class_name': 'secondary'},
    'completed': STATUS_META['completed'],
    'available': STATUS_META['available'],
    'upcoming': STATUS_META['upcoming'],
    'missed': STATUS_META['missed'],
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
        return False
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


def _attendance_role_options():
    return AppRole.query.order_by(AppRole.name.asc(), AppRole.id.asc()).all()


def _attendance_target_type(config):
    target_type = (getattr(config, 'target_type', None) or 'role').strip().lower()
    return target_type if target_type in {'role', 'unit'} else 'role'


def _attendance_primary_time(config):
    normalized = normalize_attendance_config(config)
    if normalized['schedule_times']:
        return normalized['schedule_times'][0]
    return normalized['day_start_time']


def _attendance_time_summary(config):
    normalized = normalize_attendance_config(config)
    start_time = normalized['day_start_time']
    end_time = normalized['day_end_time']
    interval_minutes = max(1, normalized['interval_minutes'])
    late_allow_minutes = max(0, normalized['late_allow_minutes'])

    summary = f"{start_time}-{end_time}"
    if start_time == end_time:
        summary = start_time
    return f"{summary} · {interval_minutes}p/lần · báo danh {late_allow_minutes}p"


def _resolve_user_unit_option(unit_option_map, user=None):
    candidates = [
        session.get('unit_key'),
        getattr(user, 'unit_key', None),
        session.get('unit_area_ref'),
        session.get('unit_area'),
        getattr(user, 'unit_area', None),
    ]
    for raw_candidate in candidates:
        candidate = (raw_candidate or '').strip()
        if not candidate:
            continue
        if candidate in unit_option_map:
            return unit_option_map[candidate]
        derived_key = extract_unit_key(candidate)
        if derived_key and derived_key in unit_option_map:
            return unit_option_map[derived_key]
    return None


def _attendance_scope_label(config, role_map, unit_option_map):
    if _attendance_target_type(config) == 'unit':
        unit_key = (getattr(config, 'target_unit_key', None) or '').strip()
        unit_option = unit_option_map.get(unit_key)
        return unit_option['unit_name'] if unit_option else (unit_key or 'Chưa chọn đơn vị')
    role = role_map.get(getattr(config, 'target_role_id', None) or 0)
    return getattr(role, 'name', None) or 'Chưa chọn vai trò'


def _attendance_config_applies_to_user(config, user, user_unit_option):
    if not config or not getattr(config, 'is_active', False) or not user:
        return False
    if _attendance_target_type(config) == 'unit':
        target_unit_key = (getattr(config, 'target_unit_key', None) or '').strip()
        return bool(target_unit_key and user_unit_option and user_unit_option['unit_key'] == target_unit_key)
    return bool(getattr(config, 'target_role_id', None) and user.role_id == config.target_role_id)


def _attendance_submission_for_task(config, slot, user=None, user_unit_option=None):
    if not config or not slot:
        return None
    query = AttendanceSubmission.query.filter_by(config_id=config.id, slot_key=slot['slot_key'])
    if _attendance_target_type(config) == 'unit':
        target_unit_key = (getattr(config, 'target_unit_key', None) or '').strip()
        if not target_unit_key:
            return None
        return query.filter_by(unit_key=target_unit_key).order_by(
            AttendanceSubmission.submitted_at.desc(),
            AttendanceSubmission.id.desc(),
        ).first()
    if not user:
        return None
    return query.filter_by(user_id=user.id).order_by(
        AttendanceSubmission.submitted_at.desc(),
        AttendanceSubmission.id.desc(),
    ).first()


def _attendance_slot_submissions(config, slots, user=None, user_unit_option=None):
    if not config or not slots:
        return {}
    slot_keys = [slot['slot_key'] for slot in slots]
    query = AttendanceSubmission.query.filter(
        AttendanceSubmission.config_id == config.id,
        AttendanceSubmission.slot_key.in_(slot_keys),
    )
    if _attendance_target_type(config) == 'unit':
        target_unit_key = (getattr(config, 'target_unit_key', None) or '').strip()
        if not target_unit_key:
            return {}
        query = query.filter_by(unit_key=target_unit_key)
    elif user:
        query = query.filter_by(user_id=user.id)
    submissions = query.order_by(AttendanceSubmission.submitted_at.desc(), AttendanceSubmission.id.desc()).all()
    output = {}
    for submission in submissions:
        output.setdefault(submission.slot_key, submission)
    return output


def _attendance_task_state(config, now, user=None, user_unit_option=None):
    if not config or not getattr(config, 'is_active', False):
        return 'inactive', None, None, None
    if _attendance_target_type(config) == 'unit':
        has_target = bool((getattr(config, 'target_unit_key', None) or '').strip())
    else:
        has_target = bool(getattr(config, 'target_role_id', None))
    if not has_target:
        return 'unassigned', None, None, None

    slots = build_slots_for_date(now.date(), config)
    if not slots:
        return 'not_today', None, None, None

    submissions_by_slot = _attendance_slot_submissions(config, slots, user=user, user_unit_option=user_unit_option)
    latest_submission = None
    latest_submission_time = None
    latest_missed_slot = None
    next_upcoming_slot = None

    for slot in slots:
        submission = submissions_by_slot.get(slot['slot_key'])
        if submission:
            submitted_at = submission.submitted_at or submission.created_at
            if submitted_at and (latest_submission_time is None or submitted_at > latest_submission_time):
                latest_submission = submission
                latest_submission_time = submitted_at
        status_key = resolve_slot_status(slot, submission=submission, now=now)
        if status_key == 'available' and not submission:
            return 'available', slot, submission, latest_submission
        if status_key == 'upcoming' and next_upcoming_slot is None:
            next_upcoming_slot = slot
        if status_key == 'missed' and not submission:
            latest_missed_slot = slot

    if next_upcoming_slot is not None:
        return 'upcoming', next_upcoming_slot, submissions_by_slot.get(next_upcoming_slot['slot_key']), latest_submission
    if latest_missed_slot is not None:
        return 'missed', latest_missed_slot, submissions_by_slot.get(latest_missed_slot['slot_key']), latest_submission
    return 'completed', slots[-1], submissions_by_slot.get(slots[-1]['slot_key']), latest_submission


def _attendance_progress_for_task(config, slots):
    if not config or not slots:
        return {'submitted_count': 0, 'expected_count': 0}
    slot_keys = [slot['slot_key'] for slot in slots]
    query = AttendanceSubmission.query.filter(
        AttendanceSubmission.config_id == config.id,
        AttendanceSubmission.slot_key.in_(slot_keys),
        AttendanceSubmission.slot_date == slots[0]['slot_date'],
    )
    if _attendance_target_type(config) == 'unit':
        target_unit_key = (getattr(config, 'target_unit_key', None) or '').strip()
        if not target_unit_key:
            return {'submitted_count': 0, 'expected_count': 0}
        return {
            'submitted_count': query.filter_by(unit_key=target_unit_key).count(),
            'expected_count': len(slots),
        }
    target_role_id = getattr(config, 'target_role_id', None) or 0
    role_user_count = User.query.filter_by(is_active=True, role_id=target_role_id).count() if target_role_id else 0
    expected_count = role_user_count * len(slots)
    submitted_count = query.count()
    if expected_count:
        submitted_count = min(submitted_count, expected_count)
    return {
        'submitted_count': submitted_count,
        'expected_count': expected_count,
    }


def _build_attendance_task_rows(configs, now, role_map, unit_option_map, current_user=None, user_unit_option=None, include_all=False):
    rows = []
    for config in configs:
        slots = build_slots_for_date(now.date(), config) if getattr(config, 'is_active', False) else []
        status_key, slot, submission, latest_submission = _attendance_task_state(
            config,
            now,
            user=current_user,
            user_unit_option=user_unit_option,
        )
        progress = _attendance_progress_for_task(config, slots) if include_all else {'submitted_count': 0, 'expected_count': 0}
        rows.append({
            'id': config.id,
            'name': (config.name or 'Nhiệm vụ điểm danh').strip(),
            'time_text': _attendance_time_summary(config),
            'target_type': _attendance_target_type(config),
            'scope_label': _attendance_scope_label(config, role_map, unit_option_map),
            'status_key': status_key,
            'status_label': TASK_STATUS_META[status_key]['label'],
            'status_class': TASK_STATUS_META[status_key]['class_name'],
            'slot': slot,
            'submission': submission or latest_submission,
            'progress': progress,
            'is_active': bool(config.is_active),
        })
    return rows


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
    if not session.get('uid'):
        return public_attendance()

    perms, role_name = _attendance_role_context()
    can_manage = _can_manage_attendance(perms, role_name)
    if not _can_view_attendance(perms, role_name):
        flash('Bạn không có quyền truy cập tính năng điểm danh.', 'danger')
        return redirect(url_for('admin_bp.index'))

    now = datetime.now()
    current_user = db.session.get(User, session['uid'])
    role_options = _attendance_role_options()
    role_map = {role.id: role for role in role_options}
    unit_options = _unit_category_options()
    unit_option_map = _build_unit_option_maps(unit_options)
    unit_list = _dedupe_unit_options(unit_option_map)
    user_unit_option = _resolve_user_unit_option(unit_option_map, current_user)
    configs = AttendanceConfig.query.order_by(
        AttendanceConfig.is_active.desc(),
        AttendanceConfig.updated_at.desc(),
        AttendanceConfig.id.desc(),
    ).all()
    edit_config_id = request.args.get('edit_config_id', type=int) or 0
    editing_config = db.session.get(AttendanceConfig, edit_config_id) if can_manage and edit_config_id else None
    form_config = editing_config
    form_config_payload = normalize_attendance_config(form_config) if form_config else None
    manager_task_rows = _build_attendance_task_rows(
        configs,
        now,
        role_map,
        unit_option_map,
        current_user=current_user,
        user_unit_option=user_unit_option,
        include_all=True,
    )
    applicable_configs = [
        config for config in configs
        if _attendance_config_applies_to_user(config, current_user, user_unit_option)
    ]
    my_task_rows = _build_attendance_task_rows(
        applicable_configs,
        now,
        role_map,
        unit_option_map,
        current_user=current_user,
        user_unit_option=user_unit_option,
        include_all=False,
    )
    can_submit = _can_submit_attendance(perms, role_name)
    selected_task_id = editing_config.id if editing_config else (manager_task_rows[0]['id'] if manager_task_rows else None)
    sidebar_submenu_items = [
        {
            'label': 'Danh sách',
            'href': url_for('attendance_bp.attendance_home') + '#attendance-task-list',
            'active': True,
        },
    ]
    if can_manage:
        sidebar_submenu_items.append({
            'label': 'Tạo mới',
            'href': url_for('attendance_bp.attendance_home') + '#attendance-task-form',
            'active': False,
        })
    for row in manager_task_rows[:8]:
        sidebar_submenu_items.append({
            'label': row['name'],
            'href': url_for('attendance_bp.attendance_home', edit_config_id=row['id']) + f"#attendance-config-{row['id']}",
            'active': row['id'] == selected_task_id,
        })

    return render_template(
        'attendance.html',
        title='Điểm danh',
        editing_config=editing_config,
        form_config=form_config,
        form_config_payload=form_config_payload,
        start_time_value=(form_config_payload or {}).get('day_start_time', '08:00'),
        end_time_value=(form_config_payload or {}).get('day_end_time', '10:00'),
        interval_minutes_value=(form_config_payload or {}).get('interval_minutes', 30),
        late_allow_minutes_value=(form_config_payload or {}).get('late_allow_minutes', 15),
        role_options=role_options,
        unit_options=unit_list,
        selected_target_type=_attendance_target_type(form_config) if form_config else 'role',
        selected_role_id=getattr(form_config, 'target_role_id', None) if form_config else None,
        selected_unit_key=(getattr(form_config, 'target_unit_key', None) or '') if form_config else '',
        manager_task_rows=manager_task_rows,
        my_task_rows=my_task_rows,
        current_user_unit_label=(user_unit_option or {}).get('unit_name', getattr(current_user, 'unit_area', '') or 'Chưa xác định'),
        can_manage_attendance=can_manage,
        can_submit_attendance=can_submit,
        sidebar_submenu_parent='attendance',
        sidebar_submenu_title='Điểm danh',
        sidebar_submenu_items=sidebar_submenu_items,
        now=now,
    )


@attendance_bp.route('/diem-danh')
def public_attendance():
    return render_template(
        'attendance_public.html',
        title='Điểm danh công khai',
        login_url=url_for('auth_bp.login'),
    )


@attendance_bp.route('/attendance/config', methods=['POST'])
def save_attendance_config():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    perms, role_name = _attendance_role_context()
    if not _can_manage_attendance(perms, role_name):
        flash('Bạn không có quyền cấu hình điểm danh.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    target_type = (request.form.get('target_type') or 'role').strip().lower()
    if target_type not in {'role', 'unit'}:
        flash('Đối tượng điểm danh không hợp lệ.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    start_time = normalize_time_string(request.form.get('day_start_time'), '')
    end_time = normalize_time_string(request.form.get('day_end_time'), '')
    interval_minutes = max(1, request.form.get('interval_minutes', type=int) or 0)
    late_allow_minutes = max(0, request.form.get('late_allow_minutes', type=int) or 0)
    start_time_obj = parse_hhmm(start_time)
    end_time_obj = parse_hhmm(end_time)
    if not start_time_obj or not end_time_obj:
        flash('Bạn cần nhập thời gian bắt đầu và kết thúc hợp lệ.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))
    if (end_time_obj.hour, end_time_obj.minute) < (start_time_obj.hour, start_time_obj.minute):
        flash('Thời gian kết thúc phải sau hoặc bằng thời gian bắt đầu.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))
    if interval_minutes <= 0:
        flash('Tần suất lặp lại phải lớn hơn 0 phút.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    unit_option_map = _build_unit_option_maps(_unit_category_options())
    target_role_id = request.form.get('target_role_id', type=int) or None
    target_unit_key = (request.form.get('target_unit_key') or '').strip()
    if target_type == 'role' and not target_role_id:
        flash('Bạn cần chọn vai trò áp dụng.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))
    if target_type == 'unit' and target_unit_key not in unit_option_map:
        flash('Bạn cần chọn đơn vị áp dụng.', 'danger')
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
    config.mode = 'interval'
    config.interval_minutes = interval_minutes
    config.day_start_time = start_time
    config.day_end_time = end_time
    config.schedule_times_json = json.dumps([], ensure_ascii=False)
    config.active_weekdays_json = json.dumps(list(range(7)), ensure_ascii=False)
    config.early_checkin_minutes = 0
    config.late_allow_minutes = late_allow_minutes
    config.is_active = bool(request.form.get('is_active'))
    config.note = ''
    config.target_type = target_type
    config.target_role_id = target_role_id if target_type == 'role' else None
    config.target_unit_key = target_unit_key if target_type == 'unit' else None
    config.updated_by = session['uid']

    try:
        db.session.commit()
        log_action(
            session['uid'],
            session['fullname'],
            'Tạo nhiệm vụ điểm danh' if is_new_config else 'Cập nhật nhiệm vụ điểm danh',
            'Điểm danh',
            config.name,
        )
        flash(
            'Đã tạo nhiệm vụ điểm danh.' if is_new_config else 'Đã cập nhật nhiệm vụ điểm danh.',
            'success',
        )
    except Exception as exc:
        db.session.rollback()
        flash(f'Lỗi khi lưu nhiệm vụ điểm danh: {exc}', 'danger')

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
    if not session.get('uid'):
        flash('Bạn cần đăng nhập để điểm danh.', 'warning')
        return redirect(url_for('auth_bp.login'))

    perms, role_name = _attendance_role_context()
    if not _can_submit_attendance(perms, role_name):
        flash('Bạn không có quyền điểm danh.', 'danger')
        return redirect(url_for(_attendance_return_endpoint()))

    config_id = request.form.get('config_id', type=int) or 0
    config = db.session.get(AttendanceConfig, config_id)
    if not config or not config.is_active:
        flash('Không tìm thấy nhiệm vụ điểm danh đang hoạt động.', 'warning')
        return redirect(url_for(_attendance_return_endpoint()))

    slot_date_raw = (request.form.get('slot_date') or '').strip()
    slot_key = (request.form.get('slot_key') or '').strip()
    current_user = db.session.get(User, session['uid'])
    unit_option_map = _build_unit_option_maps(_unit_category_options())
    user_unit_option = _resolve_user_unit_option(unit_option_map, current_user)

    try:
        slot_date = date.fromisoformat(slot_date_raw)
    except ValueError:
        flash('Mốc điểm danh không hợp lệ.', 'danger')
        return redirect(url_for(_attendance_return_endpoint()))

    if _attendance_target_type(config) == 'unit':
        target_unit_key = (getattr(config, 'target_unit_key', None) or '').strip()
        if not user_unit_option or user_unit_option['unit_key'] != target_unit_key:
            flash('Tài khoản của bạn không thuộc đơn vị được giao điểm danh này.', 'danger')
            return redirect(url_for(_attendance_return_endpoint()))
    elif current_user.role_id != config.target_role_id:
        flash('Tài khoản của bạn không thuộc vai trò được giao điểm danh này.', 'danger')
        return redirect(url_for(_attendance_return_endpoint()))

    slots = build_slots_for_date(slot_date, config)
    slot = next((item for item in slots if item['slot_key'] == slot_key), None)
    if not slot:
        flash('Không tìm thấy thời điểm điểm danh cần nộp.', 'danger')
        return redirect(url_for(_attendance_return_endpoint()))

    existing_submission = _attendance_submission_for_task(
        config,
        slot,
        user=current_user,
        user_unit_option=user_unit_option,
    )
    slot_status = resolve_slot_status(slot, submission=existing_submission, now=datetime.now())
    if existing_submission:
        flash('Nhiệm vụ này đã được điểm danh.', 'info')
        return redirect(url_for(_attendance_return_endpoint()))
    if slot_status != 'available':
        flash('Chưa đến giờ điểm danh hoặc đã quá hạn.', 'warning')
        return redirect(url_for(_attendance_return_endpoint()))

    try:
        submission = AttendanceSubmission(
            config_id=config.id,
            user_id=current_user.id,
            unit_area=(user_unit_option or {}).get('unit_name', current_user.unit_area or ''),
            unit_key=(user_unit_option or {}).get('unit_key', current_user.unit_key or ''),
            slot_key=slot['slot_key'],
            slot_label=slot['slot_label'],
            slot_date=slot['slot_date'],
            due_at=slot['due_at'],
            window_start_at=slot['window_start_at'],
            window_end_at=slot['window_end_at'],
            proof_filename='',
            proof_path='',
            note='',
            submitted_at=datetime.now(),
        )
        db.session.add(submission)
        db.session.commit()
        log_action(
            session['uid'],
            session['fullname'],
            'Điểm danh thành công',
            'Điểm danh',
            f"{config.name} - {slot['slot_time']}",
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
