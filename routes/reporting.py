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
from openpyxl.utils import get_column_letter, column_index_from_string
from excel_renderer import format_excel_number
from models_reporting import db, ReportingPeriod, FormTemplate, FormVersion, FormField, ReportInstance, ReportAuditLog, ReportFieldValue, ReportAttachment, ReportSubmission, ReportValidationError, ReportWorkflowHistory
from sqlalchemy import or_, and_
from services.form_engine import FormEngine
from services.excel_formula_engine import ExcelFormulaEngine
from services.excel_recalc_service import ExcelRecalcService
from services.report_exporter import ReportExporter
from services.report_submission_service import ReportSubmissionService
from utils import log_action, render_auto_template as render_template
from models import User

reporting_bp = Blueprint('reporting_bp', __name__, url_prefix='/reporting')
form_engine = FormEngine()
submission_service = ReportSubmissionService()


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


def _load_authorized_submission(submission_id, write=False):
    if not session.get('uid'):
        return None, _report_access_denied('Unauthorized', 401)

    submission = ReportSubmission.query.get(submission_id)
    if not submission:
        return None, _report_access_denied('Bản nộp báo cáo không tồn tại', 404)

    _, is_admin, is_lead = _get_reporting_permissions()
    current_unit = _current_reporting_unit()
    if not (is_admin or is_lead) and (submission.reporting_unit or '') != current_unit:
        return None, _report_access_denied('Bạn không có quyền truy cập báo cáo của đơn vị khác.')

    if write and submission.status in {submission_service.STATUS_APPROVED, submission_service.STATUS_LOCKED, submission_service.STATUS_CANCELLED}:
        return None, _report_access_denied('Báo cáo này không còn cho phép chỉnh sửa.')

    return submission, None


def _refresh_report_calculations(instance):
    if not instance:
        return
    try:
        form_engine.calculate_fields(instance.id)
    except Exception as exc:
        print(f"[REPORTING] Skipped recalculation for report {instance.id}: {exc}")


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


def _parse_deadline_time(raw_value, fallback=None):
    raw = (raw_value or fallback or '').strip()
    if not raw:
        return None
    try:
        hour, minute = [int(part) for part in raw.split(':', 1)]
        return datetime.time(max(0, min(23, hour)), max(0, min(59, minute)))
    except Exception:
        return None


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

    report_type = (template.report_type or '').strip().lower()
    if report_type == 'daily' and ':' in rule_text:
        return {'time': rule_text}

    if report_type == 'periodic' and rule_text.isdigit():
        return {'day': int(rule_text)}

    return {}


def _format_schedule_summary(template):
    report_type = (template.report_type or '').strip().lower()
    frequency = (template.frequency or '').strip().lower()
    rule = _parse_deadline_rule(template)

    if not report_type:
        return "Chưa cấu hình loại báo cáo"

    if report_type == 'daily':
        return "Hàng ngày, hệ thống tự ghi nhận theo ngày hiện tại"

    if report_type == 'adhoc':
        deadline_raw = (rule.get('deadline') or '').strip()
        if deadline_raw:
            try:
                deadline_dt = datetime.datetime.strptime(deadline_raw, '%Y-%m-%dT%H:%M')
                return f"Đột xuất, hạn nộp {deadline_dt.strftime('%d/%m/%Y %H:%M')}"
            except Exception:
                pass
        return "Đột xuất, chưa cấu hình mốc thời gian"

    if report_type == 'periodic':
        if frequency == 'monthly':
            day = rule.get('day')
            return f"Định kỳ tháng, hạn trước hoặc bằng ngày {day} hằng tháng" if day else "Định kỳ tháng, chưa cấu hình ngày hạn"
        if frequency == 'quarterly':
            month = rule.get('month')
            day = rule.get('day')
            return f"Định kỳ quý, hạn trước hoặc bằng ngày {day} tháng thứ {month} của quý" if month and day else "Định kỳ quý, chưa cấu hình mốc hạn"
        if frequency == 'semiannual':
            month = rule.get('month')
            day = rule.get('day')
            return f"Định kỳ 6 tháng, hạn trước hoặc bằng ngày {day} tháng thứ {month} của kỳ 6 tháng" if month and day else "Định kỳ 6 tháng, chưa cấu hình mốc hạn"
        if frequency == 'yearly':
            month = rule.get('month')
            day = rule.get('day')
            return f"Định kỳ năm, hạn trước hoặc bằng ngày {day}/{month} hằng năm" if month and day else "Định kỳ năm, chưa cấu hình mốc hạn"
        return 'Định kỳ, chưa cấu hình loại chu kỳ'

    return "Chưa cấu hình loại báo cáo"


def _format_report_type_label(template):
    report_type = (template.report_type or '').strip().lower()
    if not report_type:
        return 'Chưa cấu hình'
    if report_type == 'daily':
        return 'Hàng ngày'
    if report_type == 'periodic':
        labels = {
            'monthly': 'Định kỳ tháng',
            'quarterly': 'Định kỳ quý',
            'semiannual': 'Định kỳ 6 tháng',
            'yearly': 'Định kỳ năm',
        }
        return labels.get((template.frequency or '').strip().lower(), 'Định kỳ')
    return 'Đột xuất'


def _slugify_field_code(text):
    normalized = unicodedata.normalize('NFKD', str(text or ''))
    ascii_text = normalized.encode('ascii', 'ignore').decode('utf-8')
    return re.sub(r'[-\s]+', '_', ascii_text).strip('_').lower()


def _normalize_header_text(text):
    normalized = unicodedata.normalize('NFKD', str(text or ''))
    ascii_text = normalized.encode('ascii', 'ignore').decode('utf-8').upper()
    ascii_text = re.sub(r'[^A-Z0-9]+', ' ', ascii_text)
    return ' '.join(ascii_text.split())


def _parse_row_list(raw_value):
    if raw_value is None:
        return []
    numbers = []
    for part in re.split(r'[\s,;]+', str(raw_value).strip()):
        if not part:
            continue
        try:
            numbers.append(int(part))
        except ValueError:
            continue
    return sorted(set(num for num in numbers if num > 0))


def _load_template_scan(excel_blob):
    from pc06_excel_scanner import scan_excel_structure
    return scan_excel_structure(excel_blob)


def _build_effective_structure(scan_result, manual_override=None):
    scan_result = dict(scan_result or {})
    manual_override = manual_override or {}
    structure = {
        'sheet_name': scan_result.get('sheet_name'),
        'used_range': scan_result.get('used_range'),
        'columns': scan_result.get('columns', []),
        'visible_columns': scan_result.get('visible_columns', scan_result.get('columns', [])),
        'hidden_columns': scan_result.get('hidden_columns', []),
        'merged_cells': scan_result.get('merged_cells', []),
        'headers': scan_result.get('headers', {}),
        'numeric_columns': scan_result.get('numeric_columns', []),
        'formulas': scan_result.get('formulas', {}),
        'title_rows': manual_override.get('title_rows', scan_result.get('title_rows', [])),
        'header_rows': manual_override.get('header_rows', scan_result.get('header_rows', [])),
        'helper_rows': manual_override.get('helper_rows', scan_result.get('helper_rows', [])),
        'summary_rows': manual_override.get('summary_rows', scan_result.get('summary_rows', [])),
        'data_start_row': int(manual_override.get('data_start_row') or scan_result.get('data_start_row') or 2),
        'unit_column': (manual_override.get('unit_column') or scan_result.get('unit_column') or 'B').strip().upper(),
    }
    return structure


def _update_version_structure_metadata(version, scan_result, manual_override=None):
    metadata = json.loads(version.metadata_json) if version.metadata_json else {}
    metadata['scan_result'] = scan_result or {}
    metadata['manual_override'] = manual_override or {}
    effective = _build_effective_structure(scan_result, manual_override)
    metadata['effective_structure'] = effective
    metadata['header_rows'] = max(effective.get('header_rows') or [1])
    metadata['data_start_row'] = effective.get('data_start_row', 2)
    metadata['scan_summary'] = {
        'sheet_name': effective.get('sheet_name'),
        'title_rows': effective.get('title_rows', []),
        'header_rows': effective.get('header_rows', []),
        'helper_rows': effective.get('helper_rows', []),
        'summary_rows': effective.get('summary_rows', []),
        'data_start_row': effective.get('data_start_row', 2),
        'unit_column': effective.get('unit_column', 'B'),
        'used_range': effective.get('used_range'),
        'status': 'parsed'
    }
    version.metadata_json = json.dumps(metadata, ensure_ascii=False)
    return metadata, effective


def _get_structure_header_text(structure, row_number, col_letter):
    c_idx = column_index_from_string(col_letter)
    for m in structure.get('merged_cells', []):
        m_r = m['row']
        m_rs = m.get('rowspan', 1)
        m_cs = column_index_from_string(m['col_start'])
        m_ce = column_index_from_string(m['col_end'])
        if m_r <= row_number < m_r + m_rs and m_cs <= c_idx <= m_ce:
            return str(m['value']).strip() if m['value'] else ""

    headers = structure.get('headers', {})
    row_key = row_number if row_number in headers else str(row_number)
    if row_key in headers and col_letter in headers[row_key]:
        val = headers[row_key][col_letter]
        return str(val).strip() if val else ""
    return ""


def _collect_detail_rows(worksheet, structure):
    data_start_row = int(structure.get('data_start_row') or 2)
    unit_col = structure.get('unit_column') or 'B'
    unit_col_idx = column_index_from_string(unit_col)
    detail_rows = []
    for row_idx in range(data_start_row, min(data_start_row + 60, worksheet.max_row + 1)):
        first_value = worksheet.cell(row=row_idx, column=1).value
        unit_value = worksheet.cell(row=row_idx, column=unit_col_idx).value
        unit_text = str(unit_value).strip().lower() if unit_value is not None else ''
        if not unit_text:
            continue
        if 'đơn vị' == unit_text or 'tên đơn vị' in unit_text:
            continue
        if any(token in unit_text for token in ('toàn tỉnh', 'tổng', 'cộng')):
            continue
        if isinstance(first_value, (int, float)) and len(unit_text) >= 2:
            detail_rows.append(row_idx)
    if not detail_rows:
        detail_rows = list(range(data_start_row, min(data_start_row + 24, worksheet.max_row + 1)))
    return detail_rows


def _detect_column_formula_mode(worksheet, detail_rows, col_letter):
    col_idx = column_index_from_string(col_letter)
    literal_found = False
    formula_found = False

    for row_idx in detail_rows[:24]:
        cell = worksheet.cell(row=row_idx, column=col_idx)
        cell_value = cell.value
        if cell_value is None or str(cell_value).strip() == '':
            continue
        if isinstance(cell_value, str) and cell_value.startswith('='):
            formula_found = True
        elif cell.data_type == 'f':
            formula_found = True
        else:
            literal_found = True
        if literal_found and formula_found:
            break

    if formula_found and not literal_found:
        return 'formula_only'
    if formula_found:
        return 'mixed'
    return 'literal_only'


def _draft_fields_from_structure(excel_blob, structure):
    workbook = load_workbook(BytesIO(excel_blob), data_only=False)
    worksheet = workbook.active
    all_columns = structure.get('visible_columns', structure.get('columns', []))
    hidden_columns = set(structure.get('hidden_columns', []))
    header_rows = sorted(structure.get('header_rows', []))
    detail_rows = _collect_detail_rows(worksheet, structure)

    skip_columns = set()
    skip_keywords = {
        'STT', 'TT', 'SO TT', 'SO THU TU',
        'DON VI', 'TEN DON VI', 'TEN DON VI HANH CHINH', 'DON VI HANH CHINH'
    }
    skip_fragments = ['DON VI', 'HANH CHINH', 'DIA PHUONG', 'DIA BAN']

    for col_letter in all_columns:
        if col_letter in hidden_columns:
            continue
        normalized_chain = [
            _normalize_header_text(_get_structure_header_text(structure, row_idx, col_letter))
            for row_idx in header_rows
        ]
        normalized_chain = [item for item in normalized_chain if item]
        if any(item in skip_keywords for item in normalized_chain) or any(
            any(fragment in item for fragment in skip_fragments) for item in normalized_chain
        ):
            skip_columns.add(col_letter)

    drafts = []
    seen_codes = set()
    order = 1
    for col_letter in all_columns:
        if col_letter in hidden_columns or col_letter in skip_columns:
            continue
        parts = []
        for row_idx in header_rows:
            text = _get_structure_header_text(structure, row_idx, col_letter)
            if not text:
                continue
            text_str = str(text).strip()
            if text_str.startswith('='):
                continue
            if text_str and text_str not in parts:
                parts.append(text_str)
        if not parts:
            continue

        section = 'Thông tin chung' if len(parts) == 1 else ' / '.join(parts[:-1])
        field_name = parts[0] if len(parts) == 1 else parts[-1]
        field_code = _slugify_field_code(field_name) or f'col_{col_letter.lower()}'
        original_code = field_code
        counter = 1
        while field_code in seen_codes:
            field_code = f'{original_code}_{counter}'
            counter += 1
        seen_codes.add(field_code)

        is_numeric = col_letter in structure.get('numeric_columns', [])
        formula_mode = _detect_column_formula_mode(worksheet, detail_rows, col_letter)
        drafts.append({
            'field_code': field_code,
            'field_name': field_name,
            'field_type': 'number' if is_numeric else 'text',
            'data_type': 'number' if is_numeric else 'string',
            'is_calculated': formula_mode == 'formula_only',
            'is_readonly': formula_mode == 'formula_only',
            'display_order': order,
            'section': section,
            'excel_cell_ref': col_letter,
            'header_path': parts,
            'formula_mode': formula_mode,
        })
        order += 1

    return drafts


def _rebuild_fields_from_structure(version, excel_blob, structure):
    FormField.query.filter_by(version_id=version.id).delete(synchronize_session=False)
    drafts = _draft_fields_from_structure(excel_blob, structure)
    if drafts:
        db.session.add_all([
            FormField(
                version_id=version.id,
                field_code=item['field_code'],
                field_name=item['field_name'],
                field_type=item['field_type'],
                data_type=item['data_type'],
                is_required=False,
                is_readonly=item['is_readonly'],
                is_calculated=item['is_calculated'],
                display_order=item['display_order'],
                section=item['section'],
                excel_cell_ref=item['excel_cell_ref']
            )
            for item in drafts
        ])
    return drafts


def _build_structure_preview(excel_blob, structure, max_rows=22, max_cols=12):
    workbook = load_workbook(BytesIO(excel_blob), data_only=False)
    worksheet = workbook.active
    effective_max_row = min(worksheet.max_row or 1, max_rows)
    effective_max_col = min(worksheet.max_column or 1, max_cols)
    row_role_map = {}
    for role_name in ('title', 'header', 'helper', 'summary'):
        for row_idx in structure.get(f'{role_name}_rows', []):
            row_role_map[row_idx] = role_name

    preview_rows = []
    for row_idx in range(1, effective_max_row + 1):
        cells = []
        for col_idx in range(1, effective_max_col + 1):
            value = worksheet.cell(row=row_idx, column=col_idx).value
            cells.append('' if value is None else str(value).replace('\n', ' '))
        row_role = row_role_map.get(row_idx, 'data' if row_idx >= int(structure.get('data_start_row') or 2) else '')
        preview_rows.append({
            'row_index': row_idx,
            'role': row_role,
            'cells': cells
        })
    return {
        'sheet_name': worksheet.title,
        'col_letters': [get_column_letter(idx) for idx in range(1, effective_max_col + 1)],
        'rows': preview_rows
    }


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
    configured_templates = FormTemplate.query.filter(FormTemplate.report_type.isnot(None)).count()

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
        configured_templates=configured_templates,
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

    template_entries = []
    for template in templates:
        department_name = (template.department or '').strip()
        if not department_name or department_name.lower() == 'chưa phân đội':
            continue

        try:
            current_context = form_engine.get_reporting_context(template) if template.report_type else None
        except Exception:
            current_context = None

        deadline_dt = current_context.get('deadline') if current_context else None
        deadline_label = deadline_dt.strftime('%d/%m/%Y %H:%M') if deadline_dt else _format_schedule_summary(template)
        period_label = current_context.get('name') if current_context else None
        report_type_label = _format_report_type_label(template)
        schedule_label = _format_schedule_summary(template)

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
            report_type=None,
            frequency=None,
            deadline_rule=None,
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
            'sections': [],
            'scan_summary': {
                'field_count': 0,
                'status': 'pending'
            }
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

        # 3. Tự động scan cấu trúc và sinh field nháp
        try:
            detected = _load_template_scan(excel_blob)
            metadata, effective = _update_version_structure_metadata(version, detected, manual_override={})
            drafts = _rebuild_fields_from_structure(version, excel_blob, effective)
            metadata['scan_summary']['field_count'] = len(drafts)
            if not drafts:
                metadata['scan_summary']['status'] = 'empty'
                metadata['scan_summary']['message'] = 'Không sinh được trường nào từ cấu trúc biểu mẫu.'
            version.metadata_json = json.dumps(metadata, ensure_ascii=False)

        except Exception as parse_e:
            import traceback
            traceback.print_exc()
            print(f"Lỗi parse excel fields: {parse_e}")
            current_metadata = json.loads(version.metadata_json) if version.metadata_json else metadata
            current_metadata.setdefault('scan_summary', {})
            current_metadata['scan_summary']['status'] = 'error'
            current_metadata['scan_summary']['message'] = str(parse_e)
            version.metadata_json = json.dumps(current_metadata, ensure_ascii=False)

        submission_service.ensure_version_config(template, version, force=True)
        db.session.commit()

        flash(f'Tạo thành công biểu mẫu: {template_name}', 'success')
        return redirect(url_for('reporting_bp.template_structure', template_id=template.id, first_setup=1))

    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi xử lý file: {str(e)}', 'danger')
        return redirect(url_for('reporting_bp.index'))


@reporting_bp.route('/template/<int:template_id>/workspace')
def template_workspace(template_id):
    """Legacy entrypoint: workspace view was removed in favor of the template list."""
    flash('Không còn giao diện nội bộ biểu mẫu. Vui lòng thao tác trực tiếp từ danh sách biểu mẫu.', 'info')
    return redirect(url_for('reporting_bp.index'))


@reporting_bp.route('/form/<int:template_id>')
def select_period(template_id):
    """Điểm vào báo cáo: chuyển thẳng sang form của chu kỳ hiện tại."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    if session.get('is_admin'):
        flash('Tài khoản quản trị không nhập liệu trực tiếp. Vui lòng dùng tài khoản đơn vị để nhập báo cáo.', 'warning')
        return redirect(url_for('reporting_bp.index'))

    return redirect(url_for('reporting_bp.fill_form_direct', template_id=template_id))


@reporting_bp.route('/form/<int:template_id>/edit')
def fill_form_direct(template_id):
    """Trang nhập liệu trực tiếp trên phần mềm."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    if session.get('is_admin'):
        flash('Tài khoản quản trị không nhập liệu trực tiếp. Vui lòng dùng tài khoản đơn vị để nhập báo cáo.', 'warning')
        return redirect(url_for('reporting_bp.index'))

    user_id = session.get('uid')
    user_unit = session.get('unit_area', session.get('unit', ''))
    template = FormTemplate.query.get_or_404(template_id)
    report_type = (template.report_type or '').strip().lower()
    if report_type not in {'adhoc', 'daily', 'periodic'}:
        flash('Biểu mẫu chưa được cấu hình loại báo cáo.', 'warning')
        return redirect(url_for('reporting_bp.index'))

    instance = form_engine.create_report_instance_for_context(
        template_id=template_id,
        user_id=user_id,
        org_unit=user_unit
    )
    _refresh_report_calculations(instance)
    report_data = form_engine.get_report_data(instance.id)
    version = submission_service.get_published_version(template_id)
    config = submission_service.ensure_version_config(instance.template, version)
    report_context = form_engine.get_reporting_context(template)

    return render_template(
        'reporting/fill_form.html',
        report_data=report_data,
        instance=instance,
        template_id=template_id,
        period=instance.period,
        report_context=report_context,
        template_config=config
    )


@reporting_bp.route('/form/<int:template_id>/period/<int:period_id>')
def fill_form(template_id, period_id):
    """Legacy route: redirect sang form trực tiếp."""
    return redirect(url_for('reporting_bp.fill_form_direct', template_id=template_id))


@reporting_bp.route('/form/<int:template_id>/period/<int:period_id>/desktop')
def fill_form_desktop(template_id, period_id):
    """Giao diện Excel-like chỉ dùng để xem báo cáo, không dùng nhập liệu."""
    flash('Giao diện Excel-like chỉ còn dùng cho màn hình xem báo cáo.', 'info')
    return redirect(url_for('reporting_bp.fill_form', template_id=template_id, period_id=period_id))


@reporting_bp.route('/submission/<int:submission_id>')
def view_submission(submission_id):
    """Xem chi tiết một lần nộp báo cáo Excel."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    submission, denied = _load_authorized_submission(submission_id)
    if denied:
        flash('Bạn không có quyền xem báo cáo này.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    try:
        detail = submission_service.get_submission_detail(submission_id)
        preview_bytes = submission_service.read_submission_file_bytes(submission, prefer_processed=True)
        preview_context = submission_service.build_preview_context(preview_bytes)
    except Exception as exc:
        flash(f'Không thể hiển thị chi tiết báo cáo: {exc}', 'danger')
        return redirect(url_for('reporting_bp.index'))

    return render_template(
        'reporting/submission_detail.html',
        detail=detail,
        preview_context=preview_context,
        can_submit=submission.status in {submission_service.STATUS_DRAFT, submission_service.STATUS_RETURNED},
        can_review=session.get('is_admin'),
        can_approve=session.get('is_admin'),
    )


@reporting_bp.route('/submission/<int:submission_id>/workflow/<action>', methods=['POST'])
def submission_workflow(submission_id, action):
    """Workflow cho lần nộp báo cáo."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    submission, denied = _load_authorized_submission(submission_id, write=True)
    if denied:
        flash('Bạn không có quyền thao tác báo cáo này.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    _, is_admin, is_lead = _get_reporting_permissions()
    actor_id = session.get('uid')
    comment = (request.form.get('comment') or '').strip() or None

    if action != 'submit' and not (is_admin or is_lead):
        flash('Bạn không có quyền thực hiện thao tác workflow này.', 'danger')
        return redirect(url_for('reporting_bp.view_submission', submission_id=submission_id))

    try:
        submission_service.transition_submission(submission.id, action, actor_id, comment=comment)
        flash('Đã cập nhật trạng thái báo cáo.', 'success')
    except Exception as exc:
        db.session.rollback()
        flash(f'Lỗi workflow: {exc}', 'danger')
    return redirect(url_for('reporting_bp.view_submission', submission_id=submission_id))


@reporting_bp.route('/submission/<int:submission_id>/download/<kind>')
def download_submission_file(submission_id, kind):
    """Tải file gốc, file lỗi hoặc file đã xử lý."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    submission, denied = _load_authorized_submission(submission_id)
    if denied:
        flash('Bạn không có quyền tải file này.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    file_map = {
        'original': submission.original_file_path,
        'processed': submission.processed_file_path,
        'error': submission.error_file_path,
    }
    file_path = file_map.get(kind)
    if not file_path:
        flash('Không có file tương ứng để tải xuống.', 'warning')
        return redirect(url_for('reporting_bp.view_submission', submission_id=submission_id))

    try:
        file_bytes = BytesIO(open(file_path, 'rb').read())
        file_bytes.seek(0)
        safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', submission.original_filename or f'submission_{submission.id}.xlsx').strip('_') or f'submission_{submission.id}.xlsx'
        prefix = {'original': 'original', 'processed': 'processed', 'error': 'errors'}.get(kind, kind)
        response = make_response(file_bytes.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename="{prefix}_{safe_name}"'
        return response
    except Exception as exc:
        flash(f'Lỗi tải file: {exc}', 'danger')
        return redirect(url_for('reporting_bp.view_submission', submission_id=submission_id))


@reporting_bp.route('/report/<int:instance_id>')
def view_report(instance_id):
    """Xem báo cáo (readonly)"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    instance, denied = _load_authorized_report_instance(instance_id)
    if denied:
        flash('Bạn không có quyền xem báo cáo của đơn vị khác.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    _refresh_report_calculations(instance)
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

        _refresh_report_calculations(instance)
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
    if not template.report_type:
        flash('Biểu mẫu chưa được cấu hình loại báo cáo.', 'warning')
        return redirect(url_for('reporting_bp.index'))

    period = form_engine.resolve_internal_period(template_id)
    context = form_engine.get_reporting_context(template)

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
    deadline_dt = context.get('deadline')
    report_type = (template.report_type or '').strip().lower()
    
    for unit in all_units:
        report = submitted_units_map.get(unit)
        if report:
            submitted_at = report.submitted_at or report.updated_at
            if report_type == 'daily':
                status_group = 'Đã báo cáo'
                status_detail = 'Đã báo cáo hôm nay'
            else:
                is_late = bool(deadline_dt and submitted_at and submitted_at > deadline_dt)
                status_group = 'Đã nộp'
                status_detail = 'Đã nộp (Quá hạn)' if is_late else 'Đã nộp (Đúng hạn)'

            stats_list.append({
                'unit': unit,
                'status_group': status_group,
                'status_detail': status_detail,
                'report_id': report.id,
                'updated_at': submitted_at
            })
        else:
            if report_type == 'daily':
                status_group = 'Chưa báo cáo'
                status_detail = 'Chưa báo cáo hôm nay'
            else:
                is_late_now = bool(deadline_dt and now > deadline_dt)
                status_group = 'Chưa nộp'
                status_detail = 'Chưa nộp (Quá hạn)' if is_late_now else 'Chưa nộp'

            stats_list.append({
                'unit': unit,
                'status_group': status_group,
                'status_detail': status_detail,
                'report_id': None,
                'updated_at': None
            })
            
    # Tính toán tổng quan
    total = len(stats_list)
    submitted = sum(1 for s in stats_list if s['status_group'] in {'Đã nộp', 'Đã báo cáo'})
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
                           report_context=context,
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


@reporting_bp.route('/template/<int:template_id>/download')
def download_template(template_id):
    """Tải file Excel mẫu gốc."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    template = FormTemplate.query.get_or_404(template_id)
    if not template.excel_template_blob:
        flash('Biểu mẫu chưa có file Excel gốc để tải xuống.', 'warning')
        return redirect(url_for('reporting_bp.index'))

    safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', template.name or 'template').strip('_') or 'template'
    filename = f"{safe_name}.xlsx"
    file_bytes = bytes(template.excel_template_blob)
    response = make_response(file_bytes)
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.headers['Content-Length'] = str(len(file_bytes))
    return response


@reporting_bp.route('/template/<int:template_id>/structure', methods=['GET', 'POST'])
def template_structure(template_id):
    """Thiết lập cấu trúc quét header trước khi thiết lập nhập liệu."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    _, is_admin, is_lead = _get_reporting_permissions()
    if not (is_admin or is_lead):
        flash('Bạn không có quyền chỉnh cấu trúc biểu mẫu.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    template = FormTemplate.query.get_or_404(template_id)
    version = FormVersion.query.filter_by(
        template_id=template_id,
        is_published=True
    ).order_by(FormVersion.created_at.desc()).first()
    if not version or not template.excel_template_blob:
        flash('Biểu mẫu chưa sẵn sàng để chỉnh cấu trúc.', 'warning')
        return redirect(url_for('reporting_bp.index'))

    metadata = json.loads(version.metadata_json) if version.metadata_json else {}
    scan_result = metadata.get('scan_result') or _load_template_scan(template.excel_template_blob)
    manual_override = metadata.get('manual_override') or {}

    if request.method == 'POST':
        try:
            manual_override = {
                'title_rows': _parse_row_list(request.form.get('title_rows')),
                'header_rows': _parse_row_list(request.form.get('header_rows')),
                'helper_rows': _parse_row_list(request.form.get('helper_rows')),
                'summary_rows': _parse_row_list(request.form.get('summary_rows')),
                'data_start_row': int(request.form.get('data_start_row') or 0),
                'unit_column': (request.form.get('unit_column') or 'B').strip().upper(),
            }

            if not manual_override['header_rows']:
                raise ValueError('Phải xác định ít nhất một dòng header.')
            expected_header_span = list(range(min(manual_override['header_rows']), max(manual_override['header_rows']) + 1))
            if manual_override['header_rows'] != expected_header_span:
                raise ValueError('Các dòng header phải liền nhau.')
            if manual_override['data_start_row'] <= max(manual_override['header_rows']):
                raise ValueError('Dòng bắt đầu dữ liệu phải nằm sau toàn bộ header.')
            if not re.match(r'^[A-Z]+$', manual_override['unit_column']):
                raise ValueError('Cột đơn vị không hợp lệ.')
            if set(manual_override['header_rows']) & set(manual_override['title_rows']):
                raise ValueError('Một dòng không thể vừa là tiêu đề vừa là header.')
            if set(manual_override['header_rows']) & set(manual_override['summary_rows']):
                raise ValueError('Một dòng không thể vừa là header vừa là dòng tổng.')

            metadata, effective = _update_version_structure_metadata(version, scan_result, manual_override)
            drafts = _rebuild_fields_from_structure(version, template.excel_template_blob, effective)
            if not drafts:
                raise ValueError('Sau khi chỉnh cấu trúc, hệ thống không sinh được trường nào.')
            metadata['scan_summary']['field_count'] = len(drafts)
            version.metadata_json = json.dumps(metadata, ensure_ascii=False)
            submission_service.ensure_version_config(template, version, force=True)
            db.session.commit()
            flash('Đã cập nhật cấu trúc header và sinh lại các trường.', 'success')
            return redirect(url_for('reporting_bp.field_settings', template_id=template_id, first_setup=request.args.get('first_setup')))
        except Exception as exc:
            db.session.rollback()
            flash(f'Lỗi lưu cấu trúc: {exc}', 'danger')

    effective_structure = _build_effective_structure(scan_result, manual_override)
    preview = _build_structure_preview(template.excel_template_blob, effective_structure)
    field_drafts = _draft_fields_from_structure(template.excel_template_blob, effective_structure)

    return render_template(
        'reporting/template_structure.html',
        template=template,
        version=version,
        preview=preview,
        structure=effective_structure,
        field_drafts=field_drafts,
        scan_summary=metadata.get('scan_summary', {}),
        first_setup=request.args.get('first_setup') == '1'
    )


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
    metadata = json.loads(version.metadata_json) if version.metadata_json else {}
    scan_summary = metadata.get('scan_summary', {})
    
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
        schedule_summary=_format_schedule_summary(template),
        total_fields=len(fields),
        scan_summary=scan_summary,
        first_setup=request.args.get('first_setup') == '1'
    )


@reporting_bp.route('/template/<int:template_id>/config', methods=['GET', 'POST'])
def template_config(template_id):
    """Cấu hình loại báo cáo, hệ thống tự suy ra chu kỳ hiện tại."""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    _, is_admin, is_lead = _get_reporting_permissions()
    if not (is_admin or is_lead):
        flash('Bạn không có quyền cấu hình biểu mẫu.', 'danger')
        return redirect(url_for('reporting_bp.index'))

    template = FormTemplate.query.get_or_404(template_id)

    if request.method == 'POST':
        try:
            template_name = (request.form.get('name') or '').strip()
            report_type = (request.form.get('report_type') or '').strip().lower()
            frequency = None
            deadline_rule = None

            if not template_name:
                raise ValueError('Tên báo cáo không được để trống.')
            if report_type not in {'adhoc', 'daily', 'periodic'}:
                raise ValueError('Quản trị phải chọn loại báo cáo trước khi lưu cấu hình.')

            if report_type == 'adhoc':
                deadline_value = (request.form.get('adhoc_deadline') or '').strip()
                if not deadline_value:
                    raise ValueError('Báo cáo đột xuất phải có mốc thời gian cố định.')
                try:
                    datetime.datetime.strptime(deadline_value, '%Y-%m-%dT%H:%M')
                except Exception:
                    raise ValueError('Mốc thời gian của báo cáo đột xuất không hợp lệ.')
                deadline_rule = json.dumps({'deadline': deadline_value}, ensure_ascii=False, separators=(',', ':'))
            elif report_type == 'periodic':
                frequency = (request.form.get('frequency') or '').strip().lower()
                if frequency not in {'monthly', 'quarterly', 'semiannual', 'yearly'}:
                    raise ValueError('Phải chọn một loại định kỳ: tháng, quý, 6 tháng hoặc năm.')
                if frequency == 'monthly':
                    day = request.form.get('monthly_deadline_day', type=int)
                    if not day or day < 1 or day > 31:
                        raise ValueError('Báo cáo tháng phải có ngày hạn từ 1 đến 31.')
                    deadline_rule = json.dumps({'day': day}, ensure_ascii=False, separators=(',', ':'))
                elif frequency == 'quarterly':
                    month = request.form.get('quarterly_deadline_month', type=int)
                    day = request.form.get('quarterly_deadline_day', type=int)
                    if not month or month < 1 or month > 3:
                        raise ValueError('Báo cáo quý phải chọn tháng thứ 1, 2 hoặc 3 của quý.')
                    if not day or day < 1 or day > 31:
                        raise ValueError('Báo cáo quý phải có ngày hạn từ 1 đến 31.')
                    deadline_rule = json.dumps({'month': month, 'day': day}, ensure_ascii=False, separators=(',', ':'))
                elif frequency == 'semiannual':
                    month = request.form.get('semiannual_deadline_month', type=int)
                    day = request.form.get('semiannual_deadline_day', type=int)
                    if not month or month < 1 or month > 6:
                        raise ValueError('Báo cáo 6 tháng phải chọn tháng thứ 1 đến 6 của chu kỳ.')
                    if not day or day < 1 or day > 31:
                        raise ValueError('Báo cáo 6 tháng phải có ngày hạn từ 1 đến 31.')
                    deadline_rule = json.dumps({'month': month, 'day': day}, ensure_ascii=False, separators=(',', ':'))
                elif frequency == 'yearly':
                    month = request.form.get('yearly_deadline_month', type=int)
                    day = request.form.get('yearly_deadline_day', type=int)
                    if not month or month < 1 or month > 12:
                        raise ValueError('Báo cáo năm phải chọn tháng hạn từ 1 đến 12.')
                    if not day or day < 1 or day > 31:
                        raise ValueError('Báo cáo năm phải có ngày hạn từ 1 đến 31.')
                    deadline_rule = json.dumps({'month': month, 'day': day}, ensure_ascii=False, separators=(',', ':'))

            template.name = template_name
            template.report_type = report_type
            template.frequency = frequency
            template.deadline_rule = deadline_rule
            db.session.commit()
            flash('Đã cập nhật cấu hình reporting.', 'success')
            return redirect(url_for('reporting_bp.template_config', template_id=template_id))
        except PermissionError as exc:
            db.session.rollback()
            flash(str(exc), 'danger')
        except Exception as exc:
            db.session.rollback()
            flash(f'Lỗi lưu cấu hình: {exc}', 'danger')

    return render_template(
        'reporting/template_config.html',
        template=template,
        schedule_summary=_format_schedule_summary(template),
        deadline_config=_parse_deadline_rule(template),
        is_reporting_admin=is_admin,
        first_setup=request.args.get('first_setup') == '1'
    )


@reporting_bp.route('/template/<int:template_id>/periods', methods=['GET', 'POST'])
def template_periods(template_id):
    """Legacy page: merged into template configuration."""
    return redirect(url_for('reporting_bp.template_config', template_id=template_id))

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
        _refresh_report_calculations(instance)
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

        _refresh_report_calculations(instance)
        output, filename = exporter.export_to_excel_bytes(instance_id)
        file_bytes = output.getvalue()

        response = make_response(file_bytes)
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Length'] = str(len(file_bytes))
        return response
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@reporting_bp.route('/api/report-submissions/upload', methods=['POST'])
def api_upload_report_submission():
    """API upload báo cáo Excel theo phương án submission-centric."""
    if not session.get('uid'):
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    if session.get('is_admin'):
        return jsonify({'success': False, 'message': 'Tài khoản quản trị không nộp báo cáo trực tiếp'}), 403

    template_id = request.form.get('template_id', type=int)
    period_id = request.form.get('period_id', type=int)
    excel_file = request.files.get('file')
    if not template_id or not period_id or not excel_file:
        return jsonify({'success': False, 'message': 'Thiếu template, chu kỳ dữ liệu hoặc file upload'}), 400

    try:
        submission = submission_service.create_submission(
            template_id=template_id,
            period_id=period_id,
            user_id=session.get('uid'),
            reporting_unit=_current_reporting_unit(),
            uploaded_file=excel_file
        )
        return jsonify({
            'success': True,
            'submission_id': submission.id,
            'status': submission.status,
            'total_rows': submission.total_rows,
            'valid_rows': submission.valid_rows,
            'invalid_rows': submission.invalid_rows,
            'warnings': submission.warning_count,
        })
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(exc)}), 400


@reporting_bp.route('/api/report-submissions/<int:submission_id>', methods=['GET'])
def api_get_submission(submission_id):
    """API lấy thông tin một lần nộp báo cáo."""
    try:
        submission, denied = _load_authorized_submission(submission_id)
        if denied:
            return denied
        detail = submission_service.get_submission_detail(submission_id)
        return jsonify({
            'success': True,
            'data': {
                'submission': {
                    'id': detail['submission'].id,
                    'status': detail['submission'].status,
                    'reporting_unit': detail['submission'].reporting_unit,
                    'period_id': detail['submission'].period_id,
                    'total_rows': detail['submission'].total_rows,
                    'valid_rows': detail['submission'].valid_rows,
                    'invalid_rows': detail['submission'].invalid_rows,
                    'warning_count': detail['submission'].warning_count,
                },
                'errors': [
                    {
                        'sheet_name': err.sheet_name,
                        'cell_address': err.cell_address,
                        'error_code': err.error_code,
                        'error_message': err.error_message,
                        'severity': err.severity,
                    } for err in detail['errors']
                ],
            }
        })
    except Exception as exc:
        return jsonify({'success': False, 'message': str(exc)}), 500


@reporting_bp.route('/api/report-submissions/<int:submission_id>/errors', methods=['GET'])
def api_get_submission_errors(submission_id):
    """API lấy danh sách lỗi import."""
    try:
        submission, denied = _load_authorized_submission(submission_id)
        if denied:
            return denied
        errors = ReportValidationError.query.filter_by(submission_id=submission.id).all()
        return jsonify({
            'success': True,
            'data': [
                {
                    'sheet_name': err.sheet_name,
                    'section_code': err.section_code,
                    'row_index': err.row_index,
                    'column_index': err.column_index,
                    'cell_address': err.cell_address,
                    'field_code': err.field_code,
                    'error_code': err.error_code,
                    'error_message': err.error_message,
                    'severity': err.severity,
                } for err in errors
            ]
        })
    except Exception as exc:
        return jsonify({'success': False, 'message': str(exc)}), 500


@reporting_bp.route('/api/report-submissions/<int:submission_id>/history', methods=['GET'])
def api_get_submission_history(submission_id):
    """API lấy lịch sử workflow."""
    try:
        submission, denied = _load_authorized_submission(submission_id)
        if denied:
            return denied
        history = ReportWorkflowHistory.query.filter_by(submission_id=submission.id).order_by(
            ReportWorkflowHistory.acted_at.desc()
        ).all()
        return jsonify({
            'success': True,
            'data': [
                {
                    'from_status': item.from_status,
                    'to_status': item.to_status,
                    'action': item.action,
                    'comment': item.comment,
                    'actor_id': item.actor_id,
                    'acted_at': item.acted_at.isoformat() if item.acted_at else None,
                } for item in history
            ]
        })
    except Exception as exc:
        return jsonify({'success': False, 'message': str(exc)}), 500


@reporting_bp.route('/api/report-submissions/<int:submission_id>/submit', methods=['POST'])
def api_submit_submission(submission_id):
    """API gửi báo cáo đã upload."""
    try:
        submission, denied = _load_authorized_submission(submission_id, write=True)
        if denied:
            return denied
        submission_service.transition_submission(submission.id, 'submit', session.get('uid'))
        return jsonify({'success': True, 'message': 'Đã gửi báo cáo'})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(exc)}), 400


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
        version_ids = [row.id for row in FormVersion.query.filter_by(template_id=template.id).all()]
        instance_ids = [
            row.id for row in ReportInstance.query.filter_by(template_id=template.id).all()
        ]

        field_value_ids = []
        if instance_ids:
            field_value_ids = [
                row.id for row in ReportFieldValue.query.filter(ReportFieldValue.instance_id.in_(instance_ids)).all()
            ]

            attachments = ReportAttachment.query.filter(ReportAttachment.instance_id.in_(instance_ids)).all()
            for attachment in attachments:
                file_path = (attachment.file_path or '').strip()
                if file_path:
                    try:
                        import os
                        if os.path.exists(file_path):
                            os.remove(file_path)
                    except Exception:
                        pass

            audit_filters = [
                and_(ReportAuditLog.entity_type == 'report_instance', ReportAuditLog.entity_id.in_(instance_ids))
            ]
            if field_value_ids:
                audit_filters.append(
                    and_(ReportAuditLog.entity_type == 'field_value', ReportAuditLog.entity_id.in_(field_value_ids))
                )
            ReportAuditLog.query.filter(or_(*audit_filters)).delete(synchronize_session=False)
            ReportAttachment.query.filter(ReportAttachment.instance_id.in_(instance_ids)).delete(synchronize_session=False)
            ReportFieldValue.query.filter(ReportFieldValue.instance_id.in_(instance_ids)).delete(synchronize_session=False)
            ReportInstance.query.filter(ReportInstance.id.in_(instance_ids)).delete(synchronize_session=False)

        ReportingPeriod.query.filter_by(template_id=template.id).delete(synchronize_session=False)

        if version_ids:
            FormField.query.filter(FormField.version_id.in_(version_ids)).delete(synchronize_session=False)
            FormVersion.query.filter(FormVersion.id.in_(version_ids)).delete(synchronize_session=False)

        db.session.delete(template)
        db.session.commit()
        
        flash(f'Đã xóa biểu mẫu {template.name} thành công', 'success')
        return redirect(url_for('reporting_bp.index'))
    except Exception as e:
        db.session.rollback()
        flash(f'Lỗi khi xóa: {str(e)}', 'danger')
        return redirect(url_for('reporting_bp.index'))
