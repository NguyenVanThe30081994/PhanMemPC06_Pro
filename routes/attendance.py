# -*- coding: utf-8 -*-
import json
import mimetypes
import os
import uuid
from datetime import date, datetime, timedelta

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
from models import AppRole, AttendanceConfig, AttendanceSubmission, User, db
from utils import (
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


def _build_slot_rows(config, user_id, current_time):
    if not config:
        return []
    today = current_time.date()
    today_slots = build_slots_for_date(today, config)
    if not today_slots:
        return []

    slot_keys = [slot['slot_key'] for slot in today_slots]
    submissions = AttendanceSubmission.query.filter(
        AttendanceSubmission.user_id == user_id,
        AttendanceSubmission.config_id == config.id,
        AttendanceSubmission.slot_key.in_(slot_keys),
    ).all()
    submission_map = {submission.slot_key: submission for submission in submissions}

    rows = []
    for slot in today_slots:
        submission = submission_map.get(slot['slot_key'])
        status = resolve_slot_status(slot, submission=submission, now=current_time)
        meta = STATUS_META.get(status, STATUS_META['upcoming'])
        row = dict(slot)
        row['submission'] = submission
        row['status'] = status
        row['status_label'] = meta['label']
        row['status_class'] = meta['class_name']
        rows.append(row)
    return rows


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


@attendance_bp.route('/attendance')
def attendance_home():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    perms, role_name = _attendance_role_context()
    if not _can_view_attendance(perms, role_name):
        flash('Bạn không có quyền truy cập tính năng điểm danh.', 'danger')
        return redirect(url_for('admin_bp.index'))

    active_config, latest_config = _get_current_config()
    config_for_display = active_config or latest_config
    normalized_config = normalize_attendance_config(config_for_display) if config_for_display else None
    now = datetime.now()

    slot_rows = _build_slot_rows(active_config, session['uid'], now)
    stats = {
        'completed': sum(1 for row in slot_rows if row['status'] == 'completed'),
        'available': sum(1 for row in slot_rows if row['status'] == 'available'),
        'upcoming': sum(1 for row in slot_rows if row['status'] == 'upcoming'),
        'missed': sum(1 for row in slot_rows if row['status'] == 'missed'),
    }

    own_recent_submissions = AttendanceSubmission.query.filter_by(user_id=session['uid']).order_by(
        AttendanceSubmission.submitted_at.desc(),
        AttendanceSubmission.id.desc(),
    ).limit(12).all()

    can_manage = _can_manage_attendance(perms, role_name)
    can_submit = _can_submit_attendance(perms, role_name)
    admin_recent_submissions = []
    admin_summary = None
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
        }

    return render_template(
        'attendance.html',
        title='Điểm danh',
        active_config=active_config,
        latest_config=latest_config,
        normalized_config=normalized_config,
        config_summary=_format_config_summary(normalized_config),
        schedule_times_text='\n'.join((normalized_config or {}).get('schedule_times', [])),
        active_weekdays=((normalized_config or {}).get('active_weekdays') or list(range(7))),
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
        can_manage_attendance=can_manage,
        can_submit_attendance=can_submit,
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

    config = AttendanceConfig.query.order_by(AttendanceConfig.id.desc()).first()
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
        db.session.commit()
        log_action(session['uid'], session['fullname'], 'Cập nhật cấu hình điểm danh', 'Điểm danh', config.name)
        flash('Đã lưu cấu hình điểm danh.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Lỗi khi lưu cấu hình: {exc}', 'danger')

    return redirect(url_for('attendance_bp.attendance_home'))


@attendance_bp.route('/attendance/submit', methods=['POST'])
def submit_attendance():
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    perms, role_name = _attendance_role_context()
    if not _can_submit_attendance(perms, role_name):
        flash('Bạn không có quyền điểm danh.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    active_config, _latest_config = _get_current_config()
    if not active_config:
        flash('Hệ thống chưa kích hoạt cấu hình điểm danh.', 'warning')
        return redirect(url_for('attendance_bp.attendance_home'))

    slot_date_raw = (request.form.get('slot_date') or '').strip()
    slot_key = (request.form.get('slot_key') or '').strip()
    note = (request.form.get('note') or '').strip()

    try:
        slot_date = date.fromisoformat(slot_date_raw)
    except ValueError:
        flash('Mốc điểm danh không hợp lệ.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    slots = build_slots_for_date(slot_date, active_config)
    slot = next((item for item in slots if item['slot_key'] == slot_key), None)
    if not slot:
        flash('Không tìm thấy mốc điểm danh cần nộp.', 'danger')
        return redirect(url_for('attendance_bp.attendance_home'))

    existing_submission = AttendanceSubmission.query.filter_by(
        config_id=active_config.id,
        user_id=session['uid'],
        slot_key=slot_key,
    ).first()
    slot_status = resolve_slot_status(slot, submission=existing_submission, now=datetime.now())
    if existing_submission:
        flash('Bạn đã điểm danh cho mốc này rồi.', 'info')
        return redirect(url_for('attendance_bp.attendance_home'))
    if slot_status != 'available':
        flash('Mốc điểm danh này chưa mở hoặc đã quá hạn.', 'warning')
        return redirect(url_for('attendance_bp.attendance_home'))

    try:
        proof_path, proof_filename = _save_proof_file(request.files.get('proof_image'))
        submission = AttendanceSubmission(
            config_id=active_config.id,
            user_id=session['uid'],
            unit_area=session.get('unit_area') or session.get('unit') or '',
            unit_key=session.get('unit_key') or '',
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
        log_action(session['uid'], session['fullname'], 'Điểm danh thành công', 'Điểm danh', f"{slot['slot_label']} - {session.get('unit', '')}")
        flash('Điểm danh thành công.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Không thể lưu điểm danh: {exc}', 'danger')

    return redirect(url_for('attendance_bp.attendance_home'))


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
