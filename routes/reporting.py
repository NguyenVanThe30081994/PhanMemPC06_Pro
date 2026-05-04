# -*- coding: utf-8 -*-
"""
Routes cho hệ thống nhập liệu báo cáo mới
API endpoints và UI pages
"""
from flask import Blueprint, request, session, redirect, url_for, jsonify, flash, make_response, g
import calendar
import json
import datetime
import re
import unicodedata
from io import BytesIO
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from excel_renderer import format_excel_number
from models_reporting import db, ReportingPeriod, FormTemplate, FormVersion, FormField, ReportInstance, ReportAuditLog
from sqlalchemy import or_
from services.form_engine import FormEngine
from services.excel_formula_engine import ExcelFormulaEngine
from services.excel_recalc_service import ExcelRecalcService
from services.report_exporter import ReportExporter
from utils import log_action, render_auto_template as render_template
from models import User

reporting_bp = Blueprint('reporting_bp', __name__, url_prefix='/reporting')
form_engine = FormEngine()


def _get_reporting_permissions():
    """Resolve reporting-related permissions from the current session role."""
    perms = {}
    role_id = session.get('role_id')
    if role_id:
        from models import AppRole
        role = db.session.get(AppRole, role_id)
        if role and role.perms:
            try:
                perms = json.loads(role.perms)
            except Exception:
                perms = {}

    is_admin = bool(session.get('is_admin'))
    is_lead = is_admin or bool(
        perms.get('p_stat_lead') or
        perms.get('p_input_lead') or
        perms.get('p_form_lead')
    )
    return perms, is_admin, is_lead


def _current_reporting_unit():
    return session.get('unit_area', session.get('unit', ''))


def _report_access_denied(message='Bạn không có quyền truy cập báo cáo này.', status_code=403):
    return jsonify({'success': False, 'message': message}), status_code


def _load_authorized_report_instance(instance_id, write=False):
    if not session.get('uid'):
        return None, _report_access_denied('Unauthorized', 401)

    instance = ReportInstance.query.get(instance_id)
    if not instance:
        return None, _report_access_denied('Report instance không tồn tại', 404)

    _, is_admin, _ = _get_reporting_permissions()
    if not is_admin and (instance.org_unit or '') != _current_reporting_unit():
        return None, _report_access_denied()

    if write and getattr(instance.period, 'is_locked', False):
        return None, _report_access_denied('Kỳ báo cáo này đã bị khóa.')

    return instance, None


def _resolve_field_cell_ref(field, worksheet, target_row, exporter):
    cell_ref = str(field.excel_cell_ref or '').strip()
    if not cell_ref:
        return None
    if re.match(r'^[A-Za-z]+$', cell_ref):
        if not target_row:
            return None
        cell_ref = f"{cell_ref}{target_row}"
    return exporter._resolve_target_cell(worksheet, cell_ref)


def _build_excel_like_rows(instance):
    if not instance.template.excel_template_blob:
        raise ValueError('Biểu mẫu chưa có file Excel gốc để hiển thị dạng bảng.')

    exporter = ReportExporter()
    workbook_bytes = exporter.build_workbook_bytes(
        instance.id,
        protect_cells=False,
        recalculate=ExcelRecalcService.is_available()
    )
    wb_formula = load_workbook(BytesIO(workbook_bytes), data_only=False)
    wb_values = load_workbook(BytesIO(workbook_bytes), data_only=True)
    ws = wb_formula.active
    ws_values = wb_values[ws.title] if ws.title in wb_values.sheetnames else wb_values.active
    evaluator = None if ExcelRecalcService.is_available() else ExcelFormulaEngine(wb_formula)
    target_row = exporter._find_target_row(ws, instance.org_unit)

    fields = FormField.query.filter_by(version_id=instance.version_id).order_by(FormField.display_order).all()
    report_values = {fv.field_code: fv.value for fv in instance.field_values}

    merged_map = {}
    covered_cells = set()
    for merged_range in ws.merged_cells.ranges:
        min_col, min_row, max_col, max_row = merged_range.bounds
        top_left = (min_row, min_col)
        merged_map[top_left] = {
            'rowspan': max_row - min_row + 1,
            'colspan': max_col - min_col + 1,
        }
        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                if (r, c) != top_left:
                    covered_cells.add((r, c))

    max_row = min(ws.max_row or 1, 300)
    max_col = min(ws.max_column or 1, 100)

    col_widths = []
    col_letters = []
    for col_idx in range(1, max_col + 1):
        letter = get_column_letter(col_idx)
        col_letters.append(letter)
        width = ws.column_dimensions[letter].width
        px = int((width or 8.43) * 7.5)
        col_widths.append(max(px, 28))

    def _extract_color(color_obj):
        if color_obj and color_obj.type == 'rgb' and color_obj.rgb:
            rgb = str(color_obj.rgb)[-6:]
            if rgb != '000000':
                return f"#{rgb}"
        return None

    def _border_css(border):
        if not border:
            return ''
        parts = []
        for side, css_side in [('left', 'border-left'), ('right', 'border-right'),
                                ('top', 'border-top'), ('bottom', 'border-bottom')]:
            edge = getattr(border, side, None)
            if edge and edge.style and edge.style != 'none':
                weight = {'thin': '1px', 'medium': '2px', 'thick': '3px',
                          'hair': '1px', 'dotted': '1px', 'dashed': '1px',
                          'double': '3px'}.get(edge.style, '1px')
                style = 'double' if edge.style == 'double' else (
                    'dotted' if edge.style in ('dotted', 'hair') else (
                    'dashed' if edge.style == 'dashed' else 'solid'))
                color = '#000'
                if edge.color and edge.color.type == 'rgb' and edge.color.rgb:
                    color = f"#{str(edge.color.rgb)[-6:]}"
                parts.append(f"{css_side}:{weight} {style} {color};")
        return ''.join(parts)

    coord_field_map = {}
    for field in fields:
        rules = json.loads(field.validation_rules_json) if field.validation_rules_json else {}
        coord = _resolve_field_cell_ref(field, ws, target_row, exporter)
        if not coord:
            continue
        coord_field_map[coord] = {
            'field': field,
            'hidden': bool(rules.get('hidden', False)),
        }

    rows = []
    for r in range(1, max_row + 1):
        row_cells = []
        for c in range(1, max_col + 1):
            if (r, c) in covered_cells:
                continue

            cell = ws.cell(row=r, column=c)
            value_cell = ws_values.cell(row=r, column=c)
            merge_info = merged_map.get((r, c), {'rowspan': 1, 'colspan': 1})
            font = cell.font
            fill = cell.fill
            alignment = cell.alignment
            border = cell.border
            coord = cell.coordinate
            binding = coord_field_map.get(coord)
            field = binding['field'] if binding else None
            is_hidden = bool(binding and binding.get('hidden'))
            can_edit = bool(
                field and
                not is_hidden and
                not field.is_readonly and
                not field.is_calculated and
                instance.status in ('draft', 'returned')
            )

            bg_color = None
            if fill and fill.fill_type and fill.fgColor:
                bg_color = _extract_color(fill.fgColor)

            font_color = None
            if font and font.color:
                font_color = _extract_color(font.color)

            if field and field.field_code in report_values:
                raw_value = report_values.get(field.field_code)
            else:
                if value_cell.value is not None:
                    raw_value = value_cell.value
                elif isinstance(cell.value, str) and cell.value.startswith('=') and evaluator:
                    try:
                        raw_value = evaluator.evaluate_cell(ws, cell.coordinate)
                    except Exception:
                        raw_value = ''
                else:
                    raw_value = cell.value

            display_source = raw_value
            if field and display_source not in (None, '') and (field.field_type == 'number' or field.data_type in ('integer', 'decimal')):
                try:
                    display_source = float(str(display_source).replace(',', ''))
                except Exception:
                    pass
            display_value = format_excel_number(display_source, cell.number_format)

            font_size = int(font.sz) if font and font.sz else 11
            h_align = (alignment.horizontal if alignment and alignment.horizontal else None)
            v_align = (alignment.vertical if alignment and alignment.vertical else 'center')
            wrap = bool(alignment and alignment.wrap_text)
            border_style = _border_css(border)
            is_numeric = bool(field and (field.field_type == 'number' or field.data_type in ('integer', 'decimal')))

            row_cells.append({
                'coord': coord,
                'field_code': field.field_code if field else '',
                'field_type': field.field_type if field else 'text',
                'is_input': can_edit,
                'raw_value': '' if raw_value is None else str(raw_value),
                'display_value': display_value,
                'value': display_value,
                'rowspan': merge_info['rowspan'],
                'colspan': merge_info['colspan'],
                'bold': bool(font and font.bold),
                'italic': bool(font and font.italic),
                'underline': bool(font and font.underline),
                'font_size': font_size,
                'font_color': font_color,
                'align': h_align or 'left',
                'valign': v_align,
                'bg_color': bg_color,
                'wrap_text': wrap,
                'border_style': border_style,
                'col_idx': c,
                'is_numeric': is_numeric,
            })

        raw_height = ws.row_dimensions[r].height
        rows.append({
            'height_px': max(int(raw_height * 1.0), 16) if raw_height else 20,
            'cells': row_cells,
        })

    unresolved_fields = [
        field for field in fields
        if field.excel_cell_ref and not _resolve_field_cell_ref(field, ws, target_row, exporter)
    ]

    return {
        'sheet_title': ws.title,
        'rows': rows,
        'col_widths': col_widths,
        'col_letters': col_letters,
        'target_row': target_row,
        'unresolved_fields': unresolved_fields,
        'recalc_mode': 'libreoffice' if ExcelRecalcService.is_available() else 'fallback',
    }


def _parse_deadline_time(raw_value, fallback='17:00'):
    raw = (raw_value or fallback or '17:00').strip()
    try:
        hour, minute = [int(part) for part in raw.split(':', 1)]
        return datetime.time(max(0, min(23, hour)), max(0, min(59, minute)))
    except Exception:
        return datetime.time(17, 0)


def _safe_date_in_month(year, month, day):
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, max(1, min(int(day), last_day)))


def _parse_deadline_rule(template):
    rule_text = (template.deadline_rule or '').strip()
    if not rule_text:
        return {}

    if rule_text.startswith('{'):
        try:
            return json.loads(rule_text)
        except Exception:
            return {}

    report_type = (template.report_type or 'adhoc').strip().lower()
    if report_type == 'daily' and ':' in rule_text:
        return {'time': rule_text}

    if report_type == 'periodic' and rule_text.isdigit():
        return {'offset_days': int(rule_text), 'time': '17:00'}

    return {}


def _format_schedule_summary(template):
    report_type = (template.report_type or 'adhoc').strip().lower()
    frequency = (template.frequency or '').strip().lower()
    rule = _parse_deadline_rule(template)

    if report_type == 'daily':
        return f"Hàng ngày, hạn nộp {rule.get('time', '17:00')}"

    if report_type == 'periodic':
        if frequency == 'weekly':
            weekday_map = {
                0: 'Thứ hai', 1: 'Thứ ba', 2: 'Thứ tư', 3: 'Thứ năm',
                4: 'Thứ sáu', 5: 'Thứ bảy', 6: 'Chủ nhật'
            }
            weekday = int(rule.get('weekday', 0))
            return f"Hàng tuần, hạn nộp {weekday_map.get(weekday, 'Thứ hai')} {rule.get('time', '17:00')}"
        if frequency == 'monthly':
            return f"Hàng tháng, hạn nộp ngày {rule.get('day', 5)} lúc {rule.get('time', '17:00')}"
        if frequency == 'quarterly':
            return (
                f"Hàng quý, hạn nộp tháng {rule.get('month', 1)} trong quý "
                f"ngày {rule.get('day', 5)} lúc {rule.get('time', '17:00')}"
            )
        if frequency == 'yearly':
            return (
                f"Hàng năm, hạn nộp ngày {rule.get('day', 15)}/{rule.get('month', 1)} "
                f"lúc {rule.get('time', '17:00')}"
            )
        if 'offset_days' in rule:
            return f"Định kỳ, hạn nộp sau {rule['offset_days']} ngày"
        return "Định kỳ, chưa cấu hình hạn nộp"

    return "Đột xuất, hạn nộp khai báo theo từng kỳ"


def _format_report_type_label(template):
    report_type = (template.report_type or 'adhoc').strip().lower()
    if report_type == 'daily':
        return 'Hàng ngày'
    if report_type == 'periodic':
        return 'Định kỳ'
    return 'Đột xuất'


def _compute_period_deadline(template, start_date, end_date, explicit_deadline=None):
    report_type = (template.report_type or 'adhoc').strip().lower()
    frequency = (template.frequency or '').strip().lower()
    rule = _parse_deadline_rule(template)

    if report_type == 'adhoc':
        if explicit_deadline is None:
            raise ValueError('Báo cáo đột xuất phải có hạn nộp cụ thể.')
        return explicit_deadline

    if report_type == 'daily':
        return datetime.datetime.combine(end_date, _parse_deadline_time(rule.get('time')))

    if report_type != 'periodic':
        return None

    time_value = _parse_deadline_time(rule.get('time'))

    if 'offset_days' in rule:
        target_date = end_date + datetime.timedelta(days=int(rule['offset_days']))
        return datetime.datetime.combine(target_date, time_value)

    if frequency == 'weekly':
        weekday = max(0, min(6, int(rule.get('weekday', 0))))
        days_ahead = (weekday - end_date.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        target_date = end_date + datetime.timedelta(days=days_ahead)
        return datetime.datetime.combine(target_date, time_value)

    if frequency == 'monthly':
        next_month = end_date.month + 1
        target_year = end_date.year
        if next_month > 12:
            next_month = 1
            target_year += 1
        target_date = _safe_date_in_month(target_year, next_month, int(rule.get('day', 5)))
        return datetime.datetime.combine(target_date, time_value)

    if frequency == 'quarterly':
        current_quarter = ((end_date.month - 1) // 3) + 1
        next_quarter_start_month = current_quarter * 3 + 1
        target_year = end_date.year
        if next_quarter_start_month > 12:
            next_quarter_start_month = 1
            target_year += 1
        month_in_quarter = max(1, min(3, int(rule.get('month', 1))))
        target_month = next_quarter_start_month + month_in_quarter - 1
        target_date = _safe_date_in_month(target_year, target_month, int(rule.get('day', 5)))
        return datetime.datetime.combine(target_date, time_value)

    if frequency == 'yearly':
        target_year = end_date.year + 1
        target_month = max(1, min(12, int(rule.get('month', 1))))
        target_date = _safe_date_in_month(target_year, target_month, int(rule.get('day', 15)))
        return datetime.datetime.combine(target_date, time_value)

    return None


def _slugify_field_code(text):
    normalized = unicodedata.normalize('NFKD', str(text or ''))
    ascii_text = normalized.encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[-\s]+', '_', ascii_text).strip('_').lower()


def _normalize_header_text(text):
    normalized = unicodedata.normalize('NFKD', str(text or ''))
    ascii_text = normalized.encode('ascii', 'ignore').decode('utf-8').upper()
    ascii_text = re.sub(r'[^A-Z0-9]+', ' ', ascii_text)
    return ' '.join(ascii_text.split())


def _user_display_label(user, fallback=''):
    if user:
        return (user.fullname or user.username or fallback or '').strip()
    return (fallback or '').strip()


def _attach_report_display_names(reports):
    user_ids = sorted({report.user_id for report in reports if getattr(report, 'user_id', None)})
    user_map = {}
    if user_ids:
        user_map = {user.id: user for user in User.query.filter(User.id.in_(user_ids)).all()}

    for report in reports:
        report.display_owner_name = _user_display_label(
            user_map.get(report.user_id),
            fallback=report.org_unit or 'Không xác định'
        )
    return reports


def _attach_log_display_names(logs):
    user_ids = sorted({log.user_id for log in logs if getattr(log, 'user_id', None)})
    user_map = {}
    if user_ids:
        user_map = {user.id: user for user in User.query.filter(User.id.in_(user_ids)).all()}

    for log in logs:
        fallback = log.org_unit or '-'
        log.display_org_name = _user_display_label(user_map.get(log.user_id), fallback=fallback) or fallback
    return logs


# ==================== UI PAGES ====================

@reporting_bp.route('/dashboard')
def dashboard():
    """Dashboard thống kê tổng quan"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    if not session.get('is_admin'):
        flash('Bạn không có quyền truy cập trang này.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    # Thống kê biểu mẫu
    total_templates = FormTemplate.query.count()
    active_templates = FormTemplate.query.filter_by(is_active=True).count()

    # Thống kê kỳ báo cáo
    total_periods = ReportingPeriod.query.count()
    active_periods = ReportingPeriod.query.filter_by(is_locked=False).count()

    # Thống kê báo cáo đã nộp
    total_reports = ReportInstance.query.count()
    submitted_reports = ReportInstance.query.filter_by(status='submitted').count()
    draft_reports = ReportInstance.query.filter_by(status='draft').count()

    # Thống kê theo đơn vị (đã nộp)
    from sqlalchemy import func
    unit_label = func.coalesce(User.fullname, User.username, ReportInstance.org_unit, 'Không xác định')
    unit_stats = db.session.query(
        unit_label.label('unit_name'),
        func.count(ReportInstance.id).label('count')
    ).outerjoin(User, User.id == ReportInstance.user_id).filter(
        ReportInstance.status == 'submitted'
    ).group_by(unit_label).order_by(func.count(ReportInstance.id).desc(), unit_label.asc()).all()

    # Thống kê số lượng báo cáo (biểu mẫu) cần làm theo đội nghiệp vụ
    department_stats = db.session.query(
        FormTemplate.department,
        func.count(FormTemplate.id).label('count')
    ).filter_by(is_active=True).group_by(FormTemplate.department).all()

    return render_template(
        'reporting/dashboard.html',
        total_templates=total_templates,
        active_templates=active_templates,
        total_periods=total_periods,
        active_periods=active_periods,
        total_reports=total_reports,
        submitted_reports=submitted_reports,
        draft_reports=draft_reports,
        unit_stats=unit_stats,
        department_stats=department_stats
    )

@reporting_bp.route('/')
def index():
    """Trang chủ hệ thống báo cáo - danh sách biểu mẫu tối giản theo vai trò."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    _, is_admin, is_lead = _get_reporting_permissions()
    templates = FormTemplate.query.filter_by(is_active=True).order_by(FormTemplate.name.asc()).all()
    open_periods = ReportingPeriod.query.filter(
        ReportingPeriod.template_id.isnot(None),
        ReportingPeriod.is_locked.is_(False)
    ).all()

    period_map = {}
    for period in open_periods:
        if not period.template_id:
            continue
        current = period_map.get(period.template_id)
        period_deadline = period.deadline or datetime.datetime.max
        current_deadline = (current.deadline if current and current.deadline else datetime.datetime.max)
        if current is None or period_deadline < current_deadline:
            period_map[period.template_id] = period

    template_entries = []
    for template in templates:
        department_name = (template.department or '').strip()
        if not department_name or department_name.lower() == 'chưa phân đội':
            continue

        current_period = period_map.get(template.id)
        deadline_dt = current_period.deadline if current_period else None
        deadline_label = deadline_dt.strftime('%d/%m/%Y %H:%M') if deadline_dt else _format_schedule_summary(template)
        period_label = current_period.name if current_period else None
        report_type_label = _format_report_type_label(template)
        schedule_label = f"Hạn nộp {deadline_label}" if deadline_dt else deadline_label

        entry = {
            'template': template,
            'deadline_dt': deadline_dt,
            'deadline_label': deadline_label,
            'schedule_label': schedule_label,
            'period_label': period_label,
            'department_name': department_name,
            'report_type_label': report_type_label
        }
        template_entries.append(entry)

    template_entries = sorted(
        template_entries,
        key=lambda entry: (
            entry['deadline_dt'] is None,
            entry['deadline_dt'] or datetime.datetime.max,
            entry['department_name'].lower(),
            entry['template'].name.lower()
        )
    )

    return render_template(
        'reporting/index.html',
        template_entries=template_entries,
        total_templates=len(template_entries),
        is_reporting_admin=is_admin,
        is_reporting_lead=is_lead
    )

@reporting_bp.route('/template/upload', methods=['POST'])
def template_upload():
    """Tải file Excel lên để tạo biểu mẫu mới"""
    if not session.get('uid'):
        flash('Vui lòng đăng nhập', 'danger')
        return redirect(url_for('auth_bp.login'))
    
    _, is_admin, is_lead = _get_reporting_permissions()
    if not (is_admin or is_lead):
        flash('Bạn không có quyền thực hiện chức năng này', 'danger')
        return redirect(url_for('reporting_bp.index'))

    if 'excel_file' not in request.files:
        flash('Không tìm thấy file tải lên', 'danger')
        return redirect(url_for('reporting_bp.index'))

    file = request.files['excel_file']
    if file.filename == '':
        flash('File trống', 'danger')
        return redirect(url_for('reporting_bp.index'))

    if not file.filename.endswith(('.xls', '.xlsx')):
        flash('Chỉ hỗ trợ file Excel (.xls, .xlsx)', 'danger')
        return redirect(url_for('reporting_bp.index'))

    department = request.form.get('department', '').strip()
    template_name = request.form.get('name', '').strip()
    
    if not template_name:
        template_name = file.filename.rsplit('.', 1)[0]

    try:
        import uuid
        excel_blob = file.read()
        
        # 1. Tạo Template mới
        code = f"TMP_{uuid.uuid4().hex[:8].upper()}"
        template = FormTemplate(
            code=code,
            name=template_name,
            department=department,
            excel_template_blob=excel_blob,
            is_active=True,
            created_by=session.get('uid')
        )
        db.session.add(template)
        db.session.flush()

        # 2. Tạo FormVersion rỗng
        metadata = {
            'title': template_name,
            'header_rows': 1,
            'data_start_row': 2,
            'sections': []
        }
        
        version = FormVersion(
            template_id=template.id,
            version_number='v1.0',
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            is_published=True,
            effective_from=datetime.date.today(),
            created_by=session.get('uid')
        )
        db.session.add(version)
        db.session.flush()

            # 3. Tự động parse các trường (FormField) từ Excel sử dụng thuật toán MVP
        try:
            from pc06_excel_scanner import scan_excel_structure
            from openpyxl.utils import column_index_from_string

            detected = scan_excel_structure(excel_blob)
            
            # Cập nhật metadata
            header_rows_list = detected.get('header_rows', [1])
            metadata['header_rows'] = max(header_rows_list) if header_rows_list else 1
            metadata['data_start_row'] = detected.get('data_start_row', 2)
            version.metadata_json = json.dumps(metadata, ensure_ascii=False)
            
            # Helper function để lấy nội dung text cho 1 ô (xử lý gộp ô)
            def get_header_text_for_cell(r, c_letter):
                c_idx = column_index_from_string(c_letter)
                for m in detected.get('merged_cells', []):
                    m_r = m['row']
                    m_rs = m.get('rowspan', 1)
                    m_cs = column_index_from_string(m['col_start'])
                    m_ce = column_index_from_string(m['col_end'])
                    if m_r <= r < m_r + m_rs and m_cs <= c_idx <= m_ce:
                        return str(m['value']).strip() if m['value'] else ""
                
                headers = detected.get('headers', {})
                if r in headers and c_letter in headers[r]:
                    val = headers[r][c_letter]
                    return str(val).strip() if val else ""
                return ""

            # Tạo field với logic linh hoạt cho mọi biểu mẫu
            fields = []
            order = 1
            all_columns = detected.get('visible_columns', detected.get('columns', []))
            hidden_columns = set(detected.get('hidden_columns', []))
            total_cols = detected.get('total_cols', len(all_columns))
            
            def is_title_row(row_number):
                row_parts = []
                dominant_merge = None
                for m in detected.get('merged_cells', []):
                    if m['row'] == row_number and m.get('colspan', 1) >= max(4, int(total_cols * 0.8)):
                        dominant_merge = m
                        break

                for col_letter in all_columns:
                    text = get_header_text_for_cell(row_number, col_letter)
                    text_str = str(text).strip() if text else ""
                    if text_str and text_str not in row_parts:
                        row_parts.append(text_str)

                return bool(dominant_merge and len(row_parts) <= 1)

            # Lọc bỏ các dòng title tổng quát, giữ lại các hàng header nhóm/cột thực tế
            real_header_rows = []
            for r in sorted(detected.get('header_rows', [])):
                if not is_title_row(r):
                    real_header_rows.append(r)

            if not real_header_rows:
                real_header_rows = sorted(detected.get('header_rows', []))

            # Tìm các cột cần BỎ QUA (STT, đơn vị, tên đơn vị...)
            skip_columns = set()
            skip_keywords = {
                'STT', 'TT', 'SO TT', 'SO THU TU',
                'DON VI', 'TEN DON VI', 'TEN DON VI HANH CHINH', 'DON VI HANH CHINH'
            }
            skip_fragments = ['DON VI', 'HANH CHINH', 'DIA PHUONG', 'DIA BAN']
            
            for col_letter in all_columns:
                if col_letter in hidden_columns:
                    continue
                # Kiểm tra TẤT CẢ các dòng header
                should_skip = False
                for r in real_header_rows:
                    normalized_text = _normalize_header_text(get_header_text_for_cell(r, col_letter))
                    if normalized_text in skip_keywords or any(fragment in normalized_text for fragment in skip_fragments):
                        should_skip = True
                        break
                if should_skip:
                    skip_columns.add(col_letter)
            
            # Quét tất cả các cột (trừ cột skip)
            for col_letter in all_columns:
                if col_letter in hidden_columns:
                    continue
                if col_letter in skip_columns:
                    continue
                
                parts = []
                for r in real_header_rows:
                    text = get_header_text_for_cell(r, col_letter)
                    # Bỏ qua công thức và giá trị số
                    if text:
                        text_str = str(text).strip()
                        # Bỏ qua nếu là công thức hoặc số
                        if text_str.startswith('=') or (isinstance(text, (int, float))):
                            continue
                        if text_str and text_str not in parts:
                            parts.append(text_str)
                
                # Nếu không có header hợp lệ thì bỏ qua
                if not parts:
                    continue

                is_formula = col_letter in detected.get('formulas', {})
                if is_formula:
                    continue
                
                # Logic linh hoạt:
                # - Nếu chỉ có 1 header: section = "Thông tin chung", field = header đó
                # - Nếu có >= 2 headers: section = header gần cuối, field = header cuối
                if len(parts) == 1:
                    section = 'Thông tin chung'
                    field_name = parts[0]
                elif len(parts) >= 2:
                    section = ' / '.join(parts[:-1])
                    field_name = parts[-1]  # Dòng header cuối cùng
                else:
                    continue
                    
                field_code = _slugify_field_code(field_name) or f"col_{col_letter.lower()}"

                # Tránh trùng lặp code
                original_code = field_code
                counter = 1
                while any(f.field_code == field_code for f in fields):
                    field_code = f"{original_code}_{counter}"
                    counter += 1
                    
                # Phân tích kiểu dữ liệu từ MVP scanner
                is_numeric = col_letter in detected.get('numeric_columns', [])
                data_type = 'number' if is_numeric else 'string'

                field = FormField(
                    version_id=version.id,
                    field_code=field_code,
                    field_name=field_name,
                    field_type='number' if is_numeric else 'text',
                    data_type=data_type,
                    is_required=False,
                    display_order=order,
                    section=section,
                    excel_cell_ref=col_letter
                )
                    
                fields.append(field)
                order += 1

            if fields:
                db.session.add_all(fields)
            
        except Exception as parse_e:
            import traceback
            traceback.print_exc()
            print(f"Lỗi parse excel fields: {parse_e}")
            pass

        db.session.commit()

        flash(f'Tạo thành công biểu mẫu: {template_name}', 'success')
        return redirect(url_for('reporting_bp.index'))

    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi xử lý file: {str(e)}', 'danger')
        return redirect(url_for('reporting_bp.index'))


@reporting_bp.route('/template/<int:template_id>/workspace')
def template_workspace(template_id):
    """Không gian làm việc theo từng biểu mẫu"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    _, is_admin, is_lead = _get_reporting_permissions()
    template = FormTemplate.query.get_or_404(template_id)
    periods = ReportingPeriod.query.filter(
        or_(ReportingPeriod.template_id == template_id, ReportingPeriod.template_id == None)
    ).order_by(ReportingPeriod.start_date.desc()).all()

    user_unit = session.get('unit_area', session.get('unit', ''))
    report_query = ReportInstance.query.filter_by(template_id=template_id)
    if not is_admin:
        report_query = report_query.filter(ReportInstance.org_unit == user_unit)

    reports = report_query.order_by(ReportInstance.updated_at.desc()).limit(20).all()
    _attach_report_display_names(reports)
    latest_report = reports[0] if reports else None

    return render_template(
        'reporting/template_workspace.html',
        template=template,
        periods=periods,
        reports=reports,
        latest_report=latest_report,
        active_period_count=sum(1 for period in periods if not period.is_locked),
        schedule_summary=_format_schedule_summary(template),
        is_reporting_admin=is_admin,
        is_reporting_lead=is_lead
    )


@reporting_bp.route('/form/<int:template_id>')
def select_period(template_id):
    """Chọn kỳ báo cáo"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    if session.get('is_admin'):
        flash('Tài khoản quản trị không nhập liệu trực tiếp. Vui lòng dùng tài khoản đơn vị để nhập báo cáo.', 'warning')
        return redirect(url_for('reporting_bp.index'))
    
    template = FormTemplate.query.get_or_404(template_id)
    periods = ReportingPeriod.query.filter(
        or_(ReportingPeriod.template_id == template_id, ReportingPeriod.template_id == None),
        ReportingPeriod.is_locked == False
    ).order_by(ReportingPeriod.start_date.desc()).all()
    
    return render_template('reporting/select_period.html',
                          template=template,
                          periods=periods)


@reporting_bp.route('/form/<int:template_id>/period/<int:period_id>')
def fill_form(template_id, period_id):
    """Trang nhập liệu"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    if session.get('is_admin'):
        flash('Tài khoản quản trị không nhập liệu trực tiếp. Vui lòng dùng tài khoản đơn vị để nhập báo cáo.', 'warning')
        return redirect(url_for('reporting_bp.index'))
    
    user_id = session.get('uid')
    user_unit = session.get('unit_area', session.get('unit', ''))
    
    # Tạo hoặc lấy report instance
    instance = form_engine.create_report_instance(
        template_id=template_id,
        period_id=period_id,
        user_id=user_id,
        org_unit=user_unit
    )
    
    # Lấy dữ liệu
    report_data = form_engine.get_report_data(instance.id)
    
    return render_template('reporting/fill_form.html',
                          report_data=report_data,
                          instance=instance,
                          template_id=template_id)


@reporting_bp.route('/form/<int:template_id>/period/<int:period_id>/desktop')
def fill_form_desktop(template_id, period_id):
    """Giao diện Excel-like chỉ dùng để xem báo cáo, không dùng nhập liệu."""
    flash('Giao diện Excel-like chỉ còn dùng cho màn hình xem báo cáo.', 'info')
    return redirect(url_for('reporting_bp.fill_form', template_id=template_id, period_id=period_id))


@reporting_bp.route('/report/<int:instance_id>')
def view_report(instance_id):
    """Xem báo cáo (readonly)"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    instance, denied = _load_authorized_report_instance(instance_id)
    if denied:
        flash('Bạn không có quyền xem báo cáo của đơn vị khác.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    report_data = form_engine.get_report_data(instance.id)
    excel_context = None
    if instance.template.excel_template_blob:
        try:
            excel_context = _build_excel_like_rows(instance)
        except Exception as exc:
            flash(f'Không thể dựng giao diện Excel từ biểu mẫu: {exc}', 'warning')
    
    return render_template('reporting/view_report.html',
                          report_data=report_data,
                          instance=instance,
                          excel_context=excel_context)


@reporting_bp.route('/report/<int:instance_id>/export')
def export_report(instance_id):
    """Xuất báo cáo Excel cho người dùng giao diện web"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    try:
        from services.report_exporter import ReportExporter
        exporter = ReportExporter()

        instance, denied = _load_authorized_report_instance(instance_id)
        if denied:
            flash('Bạn không có quyền xuất báo cáo của đơn vị khác.', 'danger')
            return redirect(url_for('reporting_bp.index'))

        output, filename = exporter.export_to_excel_bytes(instance.id)
        file_bytes = output.getvalue()

        response = make_response(file_bytes)
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Length'] = str(len(file_bytes))
        return response
    except Exception as e:
        flash(f'Lỗi xuất Excel: {e}', 'danger')
        return redirect(url_for('reporting_bp.view_report', instance_id=instance_id))





@reporting_bp.route('/template/<int:template_id>/statistics')
def template_statistics(template_id):
    """Thống kê tiến độ nộp báo cáo của các đơn vị"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    _, is_admin, is_lead = _get_reporting_permissions()
    if not (is_admin or is_lead):
        flash('Bạn không có quyền truy cập chức năng này.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    template = FormTemplate.query.get_or_404(template_id)
    
    # Lấy kỳ báo cáo gần nhất của biểu mẫu
    period = ReportingPeriod.query.filter(
        or_(ReportingPeriod.template_id == template_id, ReportingPeriod.template_id == None),
        ReportingPeriod.is_locked == False
    ).order_by(ReportingPeriod.start_date.desc()).first()
    
    if not period:
        period = ReportingPeriod.query.filter(
            or_(ReportingPeriod.template_id == template_id, ReportingPeriod.template_id == None)
        ).order_by(ReportingPeriod.start_date.desc()).first()
        
    if not period:
        flash('Chưa có kỳ báo cáo nào được tạo.', 'warning')
        return redirect(url_for('reporting_bp.index'))

    # Lấy tất cả đơn vị
    from models import User
    user_unit = session.get('unit_area', session.get('unit', ''))
    all_units_query = db.session.query(User.unit_area).distinct()
    if not is_admin:
        all_units_query = all_units_query.filter(User.unit_area == user_unit)
    
    all_units = [u[0] for u in all_units_query.all() if u[0] and u[0] != 'Hệ thống']

    # Lấy các báo cáo đã nộp
    submitted_reports = ReportInstance.query.filter_by(
        template_id=template_id,
        period_id=period.id,
        status='submitted'
    ).all()
    
    submitted_units_map = {r.org_unit: r for r in submitted_reports}
    
    stats_list = []
    now = datetime.datetime.now()
    deadline_dt = period.deadline  # datetime
    deadline_date = period.end_date # date fallback
    
    for unit in all_units:
        report = submitted_units_map.get(unit)
        if report:
            is_late = False
            if deadline_dt:
                if report.updated_at > deadline_dt:
                    is_late = True
            elif deadline_date and report.updated_at.date() > deadline_date:
                is_late = True
            
            stats_list.append({
                'unit': unit,
                'status_group': 'Đã nộp',
                'status_detail': 'Đã nộp (Quá hạn)' if is_late else 'Đã nộp (Đúng hạn)',
                'report_id': report.id,
                'updated_at': report.updated_at
            })
        else:
            is_late_now = False
            if deadline_dt:
                if now > deadline_dt:
                    is_late_now = True
            elif deadline_date and now.date() > deadline_date:
                is_late_now = True
                
            stats_list.append({
                'unit': unit,
                'status_group': 'Chưa nộp',
                'status_detail': 'Chưa nộp (Quá hạn)' if is_late_now else 'Chưa nộp',
                'report_id': None,
                'updated_at': None
            })
            
    # Tính toán tổng quan
    total = len(stats_list)
    submitted = sum(1 for s in stats_list if s['status_group'] == 'Đã nộp')
    not_submitted = total - submitted
    on_time = sum(1 for s in stats_list if s['status_detail'] == 'Đã nộp (Đúng hạn)')
    late = sum(1 for s in stats_list if 'Quá hạn' in s['status_detail'])

    summary = {
        'total': total,
        'submitted': submitted,
        'not_submitted': not_submitted,
        'on_time': on_time,
        'late': late,
        'percent': round((submitted/total*100) if total > 0 else 0, 1)
    }

    return render_template('reporting/template_statistics.html', 
                           template=template, 
                           period=period, 
                           stats_list=stats_list,
                           summary=summary,
                           schedule_summary=_format_schedule_summary(template))

@reporting_bp.route('/history')
def history():
    """Lịch sử thao tác báo cáo"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    query = ReportAuditLog.query.order_by(ReportAuditLog.timestamp.desc())
    if not session.get('is_admin'):
        user_unit = session.get('unit_area', session.get('unit', ''))
        query = query.filter(ReportAuditLog.org_unit == user_unit)

    logs = query.limit(200).all()
    _attach_log_display_names(logs)
    return render_template('reporting/history.html', logs=logs, reports=[], template=None)


@reporting_bp.route('/template/<int:template_id>/history')
def template_history(template_id):
    """Lịch sử thao tác theo từng biểu mẫu"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    template = FormTemplate.query.get_or_404(template_id)

    instance_query = ReportInstance.query.filter_by(template_id=template_id)
    if not session.get('is_admin'):
        user_unit = session.get('unit_area', session.get('unit', ''))
        instance_query = instance_query.filter(ReportInstance.org_unit == user_unit)

    reports = instance_query.order_by(ReportInstance.updated_at.desc()).all()
    _attach_report_display_names(reports)
    instance_ids = [row.id for row in reports]
    
    if not instance_ids:
        return render_template('reporting/history.html', logs=[], reports=[], template=template)

    logs = ReportAuditLog.query.filter(
        ReportAuditLog.entity_type == 'report_instance',
        ReportAuditLog.entity_id.in_(instance_ids)
    ).order_by(ReportAuditLog.timestamp.desc()).limit(300).all()
    _attach_log_display_names(logs)

    return render_template('reporting/history.html', logs=logs, reports=reports, template=template)


@reporting_bp.route('/template/<int:template_id>/preview')
def preview_template(template_id):
    """Xem trực tiếp biểu mẫu Excel trên web"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    template = FormTemplate.query.get_or_404(template_id)

    if not template.excel_template_blob:
        flash('Mẫu biểu chưa có file Excel gốc để xem trực quan.', 'warning')
        return redirect(url_for('reporting_bp.index'))

    try:
        wb_formula = load_workbook(BytesIO(template.excel_template_blob), data_only=False)
        wb_values = load_workbook(BytesIO(template.excel_template_blob), data_only=True)
        ws = wb_formula.active
        ws_values = wb_values[ws.title] if ws.title in wb_values.sheetnames else wb_values.active

        merged_map = {}
        covered_cells = set()
        for merged_range in ws.merged_cells.ranges:
            min_col, min_row, max_col, max_row = merged_range.bounds
            top_left = (min_row, min_col)
            merged_map[top_left] = {
                'rowspan': max_row - min_row + 1,
                'colspan': max_col - min_col + 1,
            }
            for r in range(min_row, max_row + 1):
                for c in range(min_col, max_col + 1):
                    if (r, c) != top_left:
                        covered_cells.add((r, c))

        max_row = min(ws.max_row or 1, 120)
        max_col = min(ws.max_column or 1, 40)

        # Tính chiều rộng cột
        col_widths = []
        col_letters = []
        for col_idx in range(1, max_col + 1):
            letter = get_column_letter(col_idx)
            col_letters.append(letter)
            width = ws.column_dimensions[letter].width
            px = int((width or 8.43) * 7.5)  # Excel chuẩn: 1 char ≈ 7.5px
            col_widths.append(max(px, 28))

        # Helper: trích xuất màu từ openpyxl Color object
        def _extract_color(color_obj):
            if color_obj and color_obj.type == 'rgb' and color_obj.rgb:
                rgb = str(color_obj.rgb)[-6:]
                if rgb != '000000':
                    return f"#{rgb}"
            return None

        # Helper: build CSS border cho 1 cell
        def _border_css(border):
            if not border:
                return ''
            parts = []
            for side, css_side in [('left', 'border-left'), ('right', 'border-right'),
                                    ('top', 'border-top'), ('bottom', 'border-bottom')]:
                edge = getattr(border, side, None)
                if edge and edge.style and edge.style != 'none':
                    weight = {'thin': '1px', 'medium': '2px', 'thick': '3px',
                              'hair': '1px', 'dotted': '1px', 'dashed': '1px',
                              'double': '3px'}.get(edge.style, '1px')
                    style = 'double' if edge.style == 'double' else (
                        'dotted' if edge.style in ('dotted', 'hair') else (
                        'dashed' if edge.style == 'dashed' else 'solid'))
                    color = '#000'
                    if edge.color and edge.color.type == 'rgb' and edge.color.rgb:
                        color = f"#{str(edge.color.rgb)[-6:]}"
                    parts.append(f"{css_side}:{weight} {style} {color};")
            return ''.join(parts)

        rows = []
        for r in range(1, max_row + 1):
            row_cells = []
            for c in range(1, max_col + 1):
                if (r, c) in covered_cells:
                    continue

                cell = ws.cell(row=r, column=c)
                cell_value_obj = ws_values.cell(row=r, column=c)
                merge_info = merged_map.get((r, c), {'rowspan': 1, 'colspan': 1})

                font = cell.font
                fill = cell.fill
                alignment = cell.alignment
                border = cell.border

                # Background color
                bg_color = None
                if fill and fill.fill_type and fill.fgColor:
                    bg_color = _extract_color(fill.fgColor)

                # Font color
                font_color = None
                if font and font.color:
                    font_color = _extract_color(font.color)

                # Display value
                raw_value = cell_value_obj.value
                if raw_value is None and isinstance(cell.value, str) and cell.value.startswith('='):
                    display_value = ''
                else:
                    display_value = format_excel_number(raw_value, cell.number_format)

                # Font size: Excel default = 11pt
                font_size = int(font.sz) if font and font.sz else 11

                # Alignment
                h_align = (alignment.horizontal if alignment and alignment.horizontal else None)
                v_align = (alignment.vertical if alignment and alignment.vertical else 'center')
                wrap = bool(alignment and alignment.wrap_text)

                # Border CSS
                border_style = _border_css(border)

                row_cells.append({
                    'value': display_value,
                    'rowspan': merge_info['rowspan'],
                    'colspan': merge_info['colspan'],
                    'bold': bool(font and font.bold),
                    'italic': bool(font and font.italic),
                    'underline': bool(font and font.underline),
                    'font_size': font_size,
                    'font_color': font_color,
                    'align': h_align or 'left',
                    'valign': v_align,
                    'bg_color': bg_color,
                    'wrap_text': wrap,
                    'border_style': border_style,
                    'col_idx': c,
                })

            # Chiều cao dòng: Excel default = 15pt ≈ 20px, dùng tỉ lệ 1:1 cho compact
            raw_height = ws.row_dimensions[r].height
            if raw_height:
                height_px = max(int(raw_height * 1.0), 16)  # tối thiểu 16px
            else:
                height_px = 20  # default Excel ≈ 20px
            rows.append({'height_px': height_px, 'cells': row_cells})

        return render_template(
            'reporting/preview_template.html',
            template=template,
            sheet_title=ws.title,
            rows=rows,
            col_widths=col_widths,
            col_letters=col_letters
        )
    except Exception as e:
        flash(f'Không thể hiển thị preview Excel: {e}', 'danger')
        return redirect(url_for('reporting_bp.index'))


@reporting_bp.route('/template/<int:template_id>/field-settings', methods=['GET', 'POST'])
def field_settings(template_id):
    """Admin: Thiết lập cột được nhập liệu"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    _, is_admin, is_lead = _get_reporting_permissions()
    if not (is_admin or is_lead):
        flash('Bạn không có quyền truy cập chức năng này.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    template = FormTemplate.query.get_or_404(template_id)
    version = FormVersion.query.filter_by(
        template_id=template_id,
        is_published=True
    ).order_by(FormVersion.created_at.desc()).first()

    if not version:
        flash('Mẫu biểu chưa có phiên bản published.', 'warning')
        return redirect(url_for('reporting_bp.index'))

    fields = FormField.query.filter_by(version_id=version.id).order_by(FormField.display_order).all()

    if request.method == 'POST':
        editable_codes = set(request.form.getlist('editable_fields'))
        hidden_codes = set(request.form.getlist('hidden_fields'))

        updated = 0
        for field in fields:
            if field.is_calculated:
                # calculated fields remain readonly
                field.is_readonly = True
            else:
                new_readonly = field.field_code not in editable_codes
                if field.is_readonly != new_readonly:
                    field.is_readonly = new_readonly
                    updated += 1

            validation_data = json.loads(field.validation_rules_json) if field.validation_rules_json else {}
            new_hidden = field.field_code in hidden_codes
            if bool(validation_data.get('hidden', False)) != new_hidden:
                validation_data['hidden'] = new_hidden
                field.validation_rules_json = json.dumps(validation_data, ensure_ascii=False)
                updated += 1

        db.session.commit()
        flash(f'Đã cập nhật thiết lập cho {updated} trường.', 'success')
        return redirect(url_for('reporting_bp.field_settings', template_id=template_id))

    # Simple flat grouping like MVP
    grouped_fields = {}
    hidden_field_codes = set()
    
    for field in fields:
        section_name = field.section or 'Thông tin chung'
        grouped_fields.setdefault(section_name, []).append(field)

        rules = json.loads(field.validation_rules_json) if field.validation_rules_json else {}
        if rules.get('hidden'):
            hidden_field_codes.add(field.field_code)

    return render_template(
        'reporting/field_settings.html',
        template=template,
        version=version,
        grouped_fields=grouped_fields,
        hidden_field_codes=hidden_field_codes,
        schedule_summary=_format_schedule_summary(template)
    )


@reporting_bp.route('/template/<int:template_id>/config', methods=['GET', 'POST'])
def template_config(template_id):
    """Admin: cấu hình loại báo cáo và quy tắc hạn nộp."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    _, is_admin, is_lead = _get_reporting_permissions()
    if not (is_admin or is_lead):
        flash('Bạn không có quyền cấu hình biểu mẫu.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    template = FormTemplate.query.get_or_404(template_id)

    if request.method == 'POST':
        template_name = (request.form.get('name') or '').strip()
        report_type = (request.form.get('report_type') or 'adhoc').strip().lower()
        frequency = None
        deadline_rule = None

        try:
            if not template_name:
                raise ValueError('Tên báo cáo không được để trống.')

            if report_type == 'daily':
                deadline_rule = json.dumps(
                    {'time': request.form.get('daily_time', '17:00')},
                    ensure_ascii=False,
                    separators=(',', ':')
                )
            elif report_type == 'periodic':
                frequency = (request.form.get('frequency') or 'monthly').strip().lower()
                time_value = request.form.get('periodic_time', '17:00')

                if frequency == 'weekly':
                    deadline_rule = json.dumps(
                        {'weekday': int(request.form.get('weekly_weekday', 0)), 'time': time_value},
                        ensure_ascii=False,
                        separators=(',', ':')
                    )
                elif frequency == 'monthly':
                    deadline_rule = json.dumps(
                        {'day': int(request.form.get('monthly_day', 5)), 'time': time_value},
                        ensure_ascii=False,
                        separators=(',', ':')
                    )
                elif frequency == 'quarterly':
                    deadline_rule = json.dumps(
                        {
                            'month': int(request.form.get('quarterly_month', 1)),
                            'day': int(request.form.get('quarterly_day', 5)),
                            'time': time_value
                        },
                        ensure_ascii=False,
                        separators=(',', ':')
                    )
                elif frequency == 'yearly':
                    deadline_rule = json.dumps(
                        {
                            'month': int(request.form.get('yearly_month', 1)),
                            'day': int(request.form.get('yearly_day', 15)),
                            'time': time_value
                        },
                        ensure_ascii=False,
                        separators=(',', ':')
                    )
                else:
                    raise ValueError('Tần suất báo cáo không hợp lệ.')

            template.name = template_name
            template.report_type = report_type
            template.frequency = frequency
            template.deadline_rule = deadline_rule
            db.session.commit()
            flash('Đã cập nhật cấu hình reporting.', 'success')
            return redirect(url_for('reporting_bp.index'))
        except Exception as exc:
            db.session.rollback()
            flash(f'Lỗi lưu cấu hình: {exc}', 'danger')

    return render_template(
        'reporting/template_config.html',
        template=template,
        schedule_summary=_format_schedule_summary(template),
        deadline_config=_parse_deadline_rule(template)
    )


@reporting_bp.route('/template/<int:template_id>/periods', methods=['GET', 'POST'])
def template_periods(template_id):
    """Admin: tạo và quản lý các kỳ báo cáo của biểu mẫu."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    if not session.get('is_admin'):
        flash('Bạn không có quyền quản lý kỳ báo cáo.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    template = FormTemplate.query.get_or_404(template_id)
    report_type = (template.report_type or 'adhoc').strip().lower()

    if request.method == 'POST':
        code = (request.form.get('code') or '').strip()
        name = (request.form.get('name') or '').strip()

        if ReportingPeriod.query.filter_by(code=code).first():
            flash('Mã kỳ báo cáo đã tồn tại.', 'warning')
            return redirect(url_for('reporting_bp.template_periods', template_id=template_id))

        try:
            start_date = datetime.datetime.strptime(request.form.get('start_date', ''), '%Y-%m-%d').date()
            end_date = datetime.datetime.strptime(request.form.get('end_date', ''), '%Y-%m-%d').date()
            if end_date < start_date:
                raise ValueError('Ngày kết thúc phải lớn hơn hoặc bằng ngày bắt đầu.')

            explicit_deadline = None
            if report_type == 'adhoc':
                deadline_raw = request.form.get('deadline', '')
                explicit_deadline = datetime.datetime.strptime(deadline_raw, '%Y-%m-%dT%H:%M')

            deadline = _compute_period_deadline(template, start_date, end_date, explicit_deadline)
            period_type = 'adhoc' if report_type == 'adhoc' else (template.frequency or report_type or 'custom')

            period = ReportingPeriod(
                template_id=template.id,
                code=code,
                name=name,
                period_type=period_type,
                is_adhoc=(report_type == 'adhoc'),
                start_date=start_date,
                end_date=end_date,
                deadline=deadline,
                is_locked=False,
                created_by=session.get('uid')
            )
            db.session.add(period)
            db.session.commit()
            flash('Đã tạo kỳ báo cáo mới.', 'success')
            return redirect(url_for('reporting_bp.template_periods', template_id=template_id))
        except Exception as exc:
            db.session.rollback()
            flash(f'Không thể tạo kỳ báo cáo: {exc}', 'danger')

    periods = ReportingPeriod.query.filter(
        or_(ReportingPeriod.template_id == template.id, ReportingPeriod.template_id == None)
    ).order_by(ReportingPeriod.start_date.desc()).all()
    return render_template(
        'reporting/template_periods.html',
        template=template,
        periods=periods,
        schedule_summary=_format_schedule_summary(template),
        deadline_config=_parse_deadline_rule(template)
    )

# ==================== API ENDPOINTS ====================

@reporting_bp.route('/api/templates', methods=['GET'])
def api_list_templates():
    """API: Danh sách mẫu biểu"""
    templates = FormTemplate.query.filter_by(is_active=True).all()
    return jsonify({
        'success': True,
        'data': [{
            'id': t.id,
            'code': t.code,
            'name': t.name,
            'description': t.description,
            'category': t.category
        } for t in templates]
    })


@reporting_bp.route('/api/templates/<int:template_id>/schema', methods=['GET'])
def api_get_schema(template_id):
    """API: Lấy schema form"""
    try:
        # Lấy version published mới nhất
        version = FormVersion.query.filter_by(
            template_id=template_id,
            is_published=True
        ).order_by(FormVersion.created_at.desc()).first()
        
        if not version:
            return jsonify({'success': False, 'message': 'Template chưa có version'}), 404
        
        schema = form_engine.get_form_schema(version.id)
        return jsonify({'success': True, 'data': schema})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@reporting_bp.route('/api/reports', methods=['POST'])
def api_create_report():
    """API: Tạo báo cáo mới"""
    if not session.get('uid'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Tài khoản quản trị không nhập liệu trực tiếp'}), 403
    
    data = request.get_json()
    template_id = data.get('template_id')
    period_id = data.get('period_id')
    
    try:
        user_id = session.get('uid')
        user_unit = session.get('unit_area', session.get('unit', ''))
        
        instance = form_engine.create_report_instance(
            template_id=template_id,
            period_id=period_id,
            user_id=user_id,
            org_unit=user_unit
        )
        
        return jsonify({
            'success': True,
            'data': {'instance_id': instance.id}
        })
    except PermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@reporting_bp.route('/api/reports/<int:instance_id>', methods=['GET'])
def api_get_report(instance_id):
    """API: Lấy dữ liệu báo cáo"""
    try:
        instance, denied = _load_authorized_report_instance(instance_id)
        if denied:
            return denied
        report_data = form_engine.get_report_data(instance_id)
        return jsonify({'success': True, 'data': report_data})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@reporting_bp.route('/api/reports/<int:instance_id>/draft', methods=['PUT'])
def api_save_draft(instance_id):
    """API: Lưu nháp"""
    if not session.get('uid'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Tài khoản quản trị không nhập liệu trực tiếp'}), 403
    
    data = request.get_json()
    field_values = data.get('values', {})
    
    try:
        user_id = session.get('uid')
        user_unit = _current_reporting_unit()
        result = form_engine.save_draft(instance_id, field_values, user_id, user_unit=user_unit, is_admin=False)
        
        # Calculate fields
        form_engine.calculate_fields(instance_id)
        
        log_action(user_id, session.get('fullname', 'Unknown'), 'Lưu nháp báo cáo', 'Reporting', f'Report ID: {instance_id}')
        
        return jsonify(result)
    except PermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@reporting_bp.route('/api/reports/<int:instance_id>/submit', methods=['POST'])
def api_submit_report(instance_id):
    """API: Submit báo cáo"""
    if not session.get('uid'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Tài khoản quản trị không nhập liệu trực tiếp'}), 403
    
    try:
        user_id = session.get('uid')
        user_unit = _current_reporting_unit()
        result = form_engine.submit_report(instance_id, user_id, user_unit=user_unit, is_admin=False)
        
        if result['success']:
            log_action(user_id, session.get('fullname', 'Unknown'), 'Nộp báo cáo', 'Reporting', f'Report ID: {instance_id}')
        
        return jsonify(result)
    except PermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@reporting_bp.route('/api/reports/<int:instance_id>/validate', methods=['POST'])
def api_validate_report(instance_id):
    """API: Validate dữ liệu"""
    try:
        instance, denied = _load_authorized_report_instance(instance_id)
        if denied:
            return denied
        validation = form_engine.validate_report(instance_id)
        return jsonify({'success': True, 'data': validation})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@reporting_bp.route('/api/reports/<int:instance_id>/export', methods=['GET'])
def api_export_report(instance_id):
    """API: Xuất báo cáo ra Excel (dành cho tích hợp)"""
    if not session.get('uid'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    try:
        from services.report_exporter import ReportExporter
        exporter = ReportExporter()

        instance, denied = _load_authorized_report_instance(instance_id)
        if denied:
            return denied

        output, filename = exporter.export_to_excel_bytes(instance_id)
        file_bytes = output.getvalue()

        response = make_response(file_bytes)
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Length'] = str(len(file_bytes))
        return response
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@reporting_bp.route('/template/<int:template_id>/delete', methods=['POST'])
def template_delete(template_id):
    """Xóa biểu mẫu"""
    if not session.get('uid'):
        return jsonify({'success': False, 'message': 'Vui lòng đăng nhập'}), 401
    
    _, is_admin, is_lead = _get_reporting_permissions()
    if not is_admin:
        return jsonify({'success': False, 'message': 'Chỉ quản trị viên mới được xóa biểu mẫu'}), 403

    template = db.session.get(FormTemplate, template_id)
    if not template:
        return jsonify({'success': False, 'message': 'Không tìm thấy biểu mẫu'}), 404

    try:
        versions = FormVersion.query.filter_by(template_id=template.id).all()
        for v in versions:
            FormField.query.filter_by(version_id=v.id).delete()
            db.session.delete(v)
            
        periods = ReportingPeriod.query.filter_by(template_id=template.id).all()
        for p in periods:
            instances = ReportInstance.query.filter_by(period_id=p.id).all()
            for instance in instances:
                ReportAuditLog.query.filter_by(instance_id=instance.id).delete()
                db.session.delete(instance)
            db.session.delete(p)
            
        db.session.delete(template)
        db.session.commit()
        
        flash(f'Đã xóa biểu mẫu {template.name} thành công', 'success')
        return redirect(url_for('reporting_bp.index'))
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa: {str(e)}', 'danger')
        return redirect(url_for('reporting_bp.index'))
