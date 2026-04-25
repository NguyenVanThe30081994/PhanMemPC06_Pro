# -*- coding: utf-8 -*-
"""
Routes cho hệ thống nhập liệu báo cáo mới
API endpoints và UI pages
"""
from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, flash, send_file, make_response
import calendar
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
    unit_stats = db.session.query(
        ReportInstance.org_unit,
        func.count(ReportInstance.id).label('count')
    ).filter_by(status='submitted').group_by(ReportInstance.org_unit).all()

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
    """Trang chủ hệ thống báo cáo - chỉ hiển thị danh sách mẫu biểu"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    templates = FormTemplate.query.filter_by(is_active=True).order_by(FormTemplate.name.asc()).all()
    
    from models import CategoryGroup
    category_groups = CategoryGroup.query.filter_by(is_active=True).all()

    return render_template('reporting/index.html', templates=templates, category_groups=category_groups)

@reporting_bp.route('/api/category/<int:group_id>/items')
def api_get_category_items(group_id):
    from models import CategoryItem
    items = CategoryItem.query.filter_by(group_id=group_id, is_active=True).order_by(CategoryItem.sort_order).all()
    return jsonify([{'id': item.id, 'name': item.name} for item in items])


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
            import re
            import unicodedata
            
            def slugify(text):
                text = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode('utf-8')
                return re.sub(r'[-\s]+', '_', text).strip('_').lower()

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

            # Tạo field dựa trên kết quả scan - Xử lý gom nhóm Section như MVP
            fields = []
            order = 1
            all_columns = detected.get('columns', [])
            total_cols = detected.get('total_cols', len(all_columns))
            
            # Detect real header rows smartly: stop when hitting data row
            header_candidates = []
            for row in range(1, min(20, detected.get('original_max_row', 50) + 1)):
                # Check if this row looks like data
                numeric_count = 0
                for col_letter in all_columns:
                    headers = detected.get('headers', {})
                    cell_val = headers.get(row, {}).get(col_letter)
                    # Note: we need raw cell values. If not in headers, maybe it's purely numeric.
                    # Actually, a better way is to just use detected.get('header_rows') but filter out titles!
            
            # Lọc bỏ các dòng title (chứa ô gộp chiếm phần lớn chiều rộng bảng)
            real_header_rows = []
            for r in sorted(detected.get('header_rows', [])):
                is_title = False
                for m in detected.get('merged_cells', []):
                    if m['row'] == r and m.get('colspan', 1) >= total_cols * 0.5:
                        is_title = True
                        break
                if not is_title:
                    real_header_rows.append(r)
            
            # Chỉ lấy block header cuối cùng sát với data (bỏ qua các dòng trống ở giữa nếu có)
            if real_header_rows:
                contiguous = [real_header_rows[-1]]
                for i in range(len(real_header_rows)-2, -1, -1):
                    if real_header_rows[i+1] - real_header_rows[i] <= 2:
                        contiguous.insert(0, real_header_rows[i])
                    else:
                        break
                real_header_rows = contiguous
            
            for col_letter in all_columns:
                parts = []
                for r in real_header_rows:
                    text = get_header_text_for_cell(r, col_letter)
                    if text and text not in parts:
                        parts.append(text)
                
                # Loại bỏ các đoạn trùng lặp hoặc chứa nhau (vd: "Đo đạc lập bản đồ địa chính" và "Đo đạc lập bản đồ địa chính (ha)")
                clean_parts = []
                for p in parts:
                    if p and not any(p in cp or cp in p for cp in clean_parts):
                        clean_parts.append(p)
                if not clean_parts:
                    clean_parts = parts
                
                if clean_parts:
                    if len(clean_parts) > 1:
                        section = " || ".join(clean_parts[:-1])
                        field_name = clean_parts[-1]
                    else:
                        section = 'Thông tin chung'
                        field_name = clean_parts[0]
                else:
                    field_name = f"Cột {col_letter}"
                    section = 'Thông tin chung'
                    
                field_code = slugify(field_name) or f"col_{col_letter}"

                # Tránh trùng lặp code
                original_code = field_code
                counter = 1
                while any(f.field_code == field_code for f in fields):
                    field_code = f"{original_code}_{counter}"
                    counter += 1
                    
                # Phân tích kiểu dữ liệu từ MVP scanner
                data_type = 'number' if col_letter in detected.get('numeric_columns', []) else 'string'
                is_formula = col_letter in detected.get('formulas', {})

                field = FormField(
                    version_id=version.id,
                    field_code=field_code,
                    field_name=field_name,
                    field_type='text',
                    data_type=data_type,
                    is_required=False,
                    display_order=order,
                    section=section,
                    excel_cell_ref=col_letter
                )
                
                # Nếu là cột công thức, thì mặc định không bắt buộc
                if is_formula:
                    field.is_required = False
                    
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
    _, is_admin, is_lead = _get_reporting_permissions()
    if not (is_admin or is_lead):
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
        section_path = field.section or 'Thông tin chung'
        parts = section_path.split(' || ')
        
        current_level = grouped_fields
        for part in parts:
            if part not in current_level:
                current_level[part] = {'_fields': [], '_subgroups': {}}
            current_level = current_level[part]
            current_level = current_level['_subgroups']
            
        # Put the field in the last part's _fields list
        # We need to navigate to the exact part again to append to _fields
        curr = grouped_fields
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                curr[part]['_fields'].append(field)
            else:
                curr = curr[part]['_subgroups']

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
    if not session.get('is_admin'):
        flash('Bạn không có quyền cấu hình biểu mẫu.', 'danger')
        return redirect(url_for('reporting_bp.template_workspace', template_id=template_id))

    template = FormTemplate.query.get_or_404(template_id)

    if request.method == 'POST':
        report_type = (request.form.get('report_type') or 'adhoc').strip().lower()
        frequency = None
        deadline_rule = None

        try:
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

            template.report_type = report_type
            template.frequency = frequency
            template.deadline_rule = deadline_rule
            db.session.commit()
            flash('Đã cập nhật cấu hình reporting.', 'success')
            return redirect(url_for('reporting_bp.template_workspace', template_id=template_id))
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
        return redirect(url_for('reporting_bp.template_workspace', template_id=template_id))

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
        
        log_action(user_id, session.get('fullname', 'Unknown'), 'Lưu nháp báo cáo', 'Reporting', f'Report ID: {instance_id}')
        
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
            log_action(user_id, session.get('fullname', 'Unknown'), 'Nộp báo cáo', 'Reporting', f'Report ID: {instance_id}')
        
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
