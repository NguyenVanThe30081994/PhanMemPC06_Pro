# -*- coding: utf-8 -*-
"""
Routes cho hệ thống nhập liệu báo cáo mới
API endpoints và UI pages
"""
from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, flash, send_file
import json
from models_reporting import db, ReportingPeriod, FormTemplate, FormVersion, FormField, ReportInstance, ReportAuditLog
from services.form_engine import FormEngine
from utils import log_action

reporting_bp = Blueprint('reporting_bp', __name__, url_prefix='/reporting')
form_engine = FormEngine()


# ==================== UI PAGES ====================

@reporting_bp.route('/')
def index():
    """Trang chủ hệ thống báo cáo"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    
    # Lấy danh sách templates
    templates = FormTemplate.query.filter_by(is_active=True).all()
    
    # Lấy kỳ báo cáo hiện tại
    periods = ReportingPeriod.query.filter_by(is_locked=False).order_by(ReportingPeriod.start_date.desc()).limit(5).all()
    
    # Lấy báo cáo của user
    user_unit = session.get('unit_area', session.get('unit', ''))
    my_reports = ReportInstance.query.filter_by(
        org_unit=user_unit
    ).order_by(ReportInstance.updated_at.desc()).limit(10).all()
    
    return render_template('reporting/index.html',
                         templates=templates,
                         periods=periods,
                         my_reports=my_reports)


@reporting_bp.route('/form/<int:template_id>')
def select_period(template_id):
    """Chọn kỳ báo cáo"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    if session.get('is_admin'):
        flash('Tài khoản quản trị không nhập liệu trực tiếp. Vui lòng dùng tài khoản đơn vị để nhập báo cáo.', 'warning')
        return redirect(url_for('reporting_bp.index'))
    
    template = FormTemplate.query.get_or_404(template_id)
    periods = ReportingPeriod.query.filter_by(is_locked=False).order_by(ReportingPeriod.start_date.desc()).all()
    
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


@reporting_bp.route('/dashboard')
def dashboard():
    """Dashboard tổng hợp"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    
    # Lấy thống kê
    from models import User, AppRole
    import json
    
    role = db.session.get(AppRole, session.get('role_id')) if session.get('role_id') else None
    perms = json.loads(role.perms) if role and role.perms else {}
    is_lead = perms.get('p_stat_lead') or session.get('is_admin')
    user_unit = session.get('unit_area', session.get('unit', ''))
    
    # Lấy tất cả đơn vị
    all_units_query = db.session.query(User.unit_area).distinct()
    if not is_lead:
        all_units_query = all_units_query.filter(User.unit_area == user_unit)
    
    all_units = [u[0] for u in all_units_query.all() if u[0] and u[0] != 'Hệ thống']
    
    # Lấy kỳ hiện tại
    current_period = ReportingPeriod.query.filter_by(is_locked=False).order_by(ReportingPeriod.start_date.desc()).first()
    
    # Thống kê tiến độ
    stats = {}
    if current_period:
        templates = FormTemplate.query.filter_by(is_active=True).all()
        
        for template in templates:
            total_units = len(all_units)
            submitted = ReportInstance.query.filter_by(
                template_id=template.id,
                period_id=current_period.id,
                status='submitted'
            ).count()
            
            stats[template.code] = {
                'name': template.name,
                'total': total_units,
                'submitted': submitted,
                'percent': round((submitted / total_units * 100) if total_units > 0 else 0, 1)
            }
    
    return render_template('reporting/dashboard.html',
                          stats=stats,
                          current_period=current_period,
                          is_lead=is_lead)


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
    return render_template('reporting/history.html', logs=logs)


@reporting_bp.route('/template/<int:template_id>/preview')
def preview_template(template_id):
    """Xem trực tiếp biểu mẫu trên web"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))

    template = FormTemplate.query.get_or_404(template_id)
    version = FormVersion.query.filter_by(
        template_id=template_id,
        is_published=True
    ).order_by(FormVersion.created_at.desc()).first()

    if not version:
        flash('Mẫu biểu chưa có phiên bản published.', 'warning')
        return redirect(url_for('reporting_bp.index'))

    schema = form_engine.get_form_schema(version.id)
    return render_template('reporting/preview_template.html', template=template, version=version, schema=schema)


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
    """API: Xuất báo cáo ra Excel"""
    try:
        from services.report_exporter import ReportExporter
        exporter = ReportExporter()

        instance = ReportInstance.query.get_or_404(instance_id)
        if not session.get('is_admin'):
            user_unit = session.get('unit_area', session.get('unit', ''))
            if instance.org_unit != user_unit:
                return jsonify({'success': False, 'message': 'Forbidden'}), 403

        file_path = exporter.export_to_excel(instance_id)
        return send_file(file_path, as_attachment=True, download_name=f'report_{instance_id}.xlsx')
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
