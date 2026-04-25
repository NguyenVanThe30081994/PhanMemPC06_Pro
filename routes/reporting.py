# -*- coding: utf-8 -*-
"""
Routes cho hệ thống nhập liệu báo cáo mới
API endpoints và UI pages
"""
from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, flash, send_file, make_response
import json
import datetime
from io import BytesIO
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from excel_renderer import format_excel_number
from models_reporting import db, ReportingPeriod, FormTemplate, FormVersion, FormField, ReportInstance, ReportAuditLog
from sqlalchemy import or_
from services.form_engine import FormEngine
from utils import log_action

reporting_bp = Blueprint('reporting_bp', __name__, url_prefix='/reporting')
form_engine = FormEngine()


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

    # Thống kê theo đơn vị
    from sqlalchemy import func
    unit_stats = db.session.query(
        ReportInstance.org_unit,
        func.count(ReportInstance.id).label('count')
    ).filter_by(status='submitted').group_by(ReportInstance.org_unit).all()

    return render_template(
        'reporting/dashboard.html',
        total_templates=total_templates,
        active_templates=active_templates,
        total_periods=total_periods,
        active_periods=active_periods,
        total_reports=total_reports,
        submitted_reports=submitted_reports,
        draft_reports=draft_reports,
        unit_stats=unit_stats
    )

@reporting_bp.route('/')
def index():
    """Trang chủ hệ thống báo cáo - chỉ hiển thị danh sách mẫu biểu"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    templates = FormTemplate.query.filter_by(is_active=True).order_by(FormTemplate.name.asc()).all()

    return render_template('reporting/index.html', templates=templates)


@reporting_bp.route('/template/<int:template_id>/workspace')
def template_workspace(template_id):
    """Không gian làm việc theo từng biểu mẫu"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    template = FormTemplate.query.get_or_404(template_id)
    periods = ReportingPeriod.query.filter_by(is_locked=False).order_by(ReportingPeriod.start_date.desc()).all()

    user_unit = session.get('unit_area', session.get('unit', ''))
    report_query = ReportInstance.query.filter_by(template_id=template_id)
    if not session.get('is_admin'):
        report_query = report_query.filter(ReportInstance.org_unit == user_unit)

    reports = report_query.order_by(ReportInstance.updated_at.desc()).limit(20).all()
    latest_report = reports[0] if reports else None

    return render_template(
        'reporting/template_workspace.html',
        template=template,
        periods=periods,
        reports=reports,
        latest_report=latest_report
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


@reporting_bp.route('/report/<int:instance_id>')
def view_report(instance_id):
    """Xem báo cáo (readonly)"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    
    report_data = form_engine.get_report_data(instance_id)
    instance = ReportInstance.query.get_or_404(instance_id)

    if not session.get('is_admin'):
        user_unit = session.get('unit_area', session.get('unit', ''))
        if instance.org_unit != user_unit:
            flash('Bạn không có quyền xem báo cáo của đơn vị khác.', 'danger')
            return redirect(url_for('reporting_bp.index'))
    
    return render_template('reporting/view_report.html',
                          report_data=report_data,
                          instance=instance)


@reporting_bp.route('/report/<int:instance_id>/export')
def export_report(instance_id):
    """Xuất báo cáo Excel cho người dùng giao diện web"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    try:
        from services.report_exporter import ReportExporter
        exporter = ReportExporter()

        instance = ReportInstance.query.get_or_404(instance_id)
        if not session.get('is_admin'):
            user_unit = session.get('unit_area', session.get('unit', ''))
            if instance.org_unit != user_unit:
                flash('Bạn không có quyền xuất báo cáo của đơn vị khác.', 'danger')
                return redirect(url_for('reporting_bp.index'))

        output, filename = exporter.export_to_excel_bytes(instance_id)
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
    if not (session.get('is_admin') or session.get('is_lead')):
        flash('Bạn không có quyền truy cập chức năng này.', 'danger')
        return redirect(url_for('reporting_bp.template_workspace', template_id=template_id))

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
        return redirect(url_for('reporting_bp.template_workspace', template_id=template_id))

    # Lấy tất cả đơn vị
    from models import User
    user_unit = session.get('unit_area', session.get('unit', ''))
    all_units_query = db.session.query(User.unit_area).distinct()
    if not session.get('is_admin'):
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
                           summary=summary)

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
    instance_ids = [row.id for row in reports]
    
    if not instance_ids:
        return render_template('reporting/history.html', logs=[], reports=[], template=template)

    logs = ReportAuditLog.query.filter(
        ReportAuditLog.entity_type == 'report_instance',
        ReportAuditLog.entity_id.in_(instance_ids)
    ).order_by(ReportAuditLog.timestamp.desc()).limit(300).all()

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
    if not session.get('is_admin'):
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

    grouped_fields = {}
    hidden_field_codes = set()
    for field in fields:
        section_name = field.section or 'Khác'
        grouped_fields.setdefault(section_name, []).append(field)

        rules = json.loads(field.validation_rules_json) if field.validation_rules_json else {}
        if rules.get('hidden'):
            hidden_field_codes.add(field.field_code)

    return render_template(
        'reporting/field_settings.html',
        template=template,
        version=version,
        grouped_fields=grouped_fields,
        hidden_field_codes=hidden_field_codes
    )


# Tạm thời disable route template_config và template_periods
# Sẽ bật lại sau khi migration hoàn tất (cột report_type, frequency, deadline_rule được thêm)

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
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@reporting_bp.route('/api/reports/<int:instance_id>', methods=['GET'])
def api_get_report(instance_id):
    """API: Lấy dữ liệu báo cáo"""
    try:
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
        result = form_engine.save_draft(instance_id, field_values, user_id)
        
        # Calculate fields
        form_engine.calculate_fields(instance_id)
        
        log_action('Báo cáo', 'Lưu nháp', f'Report ID: {instance_id}')
        
        return jsonify(result)
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
        result = form_engine.submit_report(instance_id, user_id)
        
        if result['success']:
            log_action('Báo cáo', 'Nộp báo cáo', f'Report ID: {instance_id}')
        
        return jsonify(result)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@reporting_bp.route('/api/reports/<int:instance_id>/validate', methods=['POST'])
def api_validate_report(instance_id):
    """API: Validate dữ liệu"""
    try:
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

        instance = ReportInstance.query.get_or_404(instance_id)
        if not session.get('is_admin'):
            user_unit = session.get('unit_area', session.get('unit', ''))
            if instance.org_unit != user_unit:
                return jsonify({'success': False, 'message': 'Forbidden'}), 403

        output, filename = exporter.export_to_excel_bytes(instance_id)
        file_bytes = output.getvalue()

        response = make_response(file_bytes)
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        response.headers['Content-Length'] = str(len(file_bytes))
        return response
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
