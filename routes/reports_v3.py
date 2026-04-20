# -*- coding: utf-8 -*-
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, session, current_app
from models import db, ReportTemplateV3, ReportVersionV3, ReportSubmissionV3, ReportValueV3
from datetime import datetime
import json
import os
import io

reports_v3_bp = Blueprint('reports_v3_bp', __name__)

def _render_template(name, **kwargs):
    # Pass common variables
    kwargs['is_admin'] = session.get('is_admin')
    kwargs['fullname'] = session.get('fullname')
    kwargs['unit_area'] = session.get('unit_area')
    kwargs['phone'] = session.get('phone')
    return render_template(name, **kwargs)

@reports_v3_bp.route('/reports-v3/dashboard')
def dashboard():
    """Trang chủ quản lý biểu mẫu V3 (Dùng Luckysheet)"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
        
    templates = ReportTemplateV3.query.order_by(ReportTemplateV3.created_at.desc()).all()
    templates_data = []
    
    for t in templates:
        active_version = ReportVersionV3.query.filter_by(template_id=t.id, is_published=True).order_by(ReportVersionV3.created_at.desc()).first()
        version_count = ReportVersionV3.query.filter_by(template_id=t.id).count()
        templates_data.append({
            'template': t,
            'active_version': active_version,
            'version_count': version_count
        })
        
    return _render_template('reports_v3_dashboard.html', templates_data=templates_data)

@reports_v3_bp.route('/reports-v3/add', methods=['POST'])
def add_template():
    if not session.get('is_admin'):
        return jsonify({"error": "Unauthorized"}), 403

    file = request.files.get('template_excel')
    name = request.form.get('name', 'Báo cáo V3 Mới')

    if not file or not file.filename:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        file_content = file.read()
        
        # Tao Template
        template = ReportTemplateV3(
            name=name,
            created_by=session.get('fullname')
        )
        db.session.add(template)
        db.session.flush()

        # Tao Version
        new_version = ReportVersionV3(
            template_id=template.id,
            version_tag=datetime.now().strftime("%Y%m%d%H%M"),
            metadata_json=json.dumps({"input_range": [], "unit_column": "B"}, ensure_ascii=False),
            excel_file_blob=file_content,
            is_published=True
        )
        db.session.add(new_version)
        db.session.commit()

        return jsonify({"success": True, "template_id": template.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@reports_v3_bp.route('/reports-v3/config/<int:tid>')
def config_template(tid):
    """Màn hình Luckysheet cho Admin khoanh vùng nhập liệu"""
    if not session.get('is_admin'):
        return redirect(url_for('auth_bp.login'))
        
    template = db.session.get(ReportTemplateV3, tid)
    if not template:
        flash('Không tìm thấy biểu mẫu!', 'danger')
        return redirect(url_for('reports_v3_bp.dashboard'))
        
    version = ReportVersionV3.query.filter_by(template_id=tid, is_published=True).order_by(ReportVersionV3.created_at.desc()).first()
    if not version:
        flash('Chưa có file Excel!', 'warning')
        return redirect(url_for('reports_v3_bp.dashboard'))

    return _render_template('reports_v3_config.html', template=template, version=version)

@reports_v3_bp.route('/reports-v3/api/file/<int:vid>')
def get_version_file(vid):
    """API trả về file Excel thô để Luckyexcel parse ở Client"""
    from flask import send_file
    version = db.session.get(ReportVersionV3, vid)
    if not version or not version.excel_file_blob:
        return abort(404)
        
    return send_file(
        io.BytesIO(version.excel_file_blob),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='template.xlsx'
    )

@reports_v3_bp.route('/reports-v3/config/save/<int:tid>', methods=['POST'])
def config_save(tid):
    """Nhận JSON config vùng (ranges) từ Admin"""
    if not session.get('is_admin'):
        return jsonify({"error": "Unauthorized"}), 403
        
    data = request.json
    version = ReportVersionV3.query.filter_by(template_id=tid, is_published=True).order_by(ReportVersionV3.created_at.desc()).first()
    if not version:
        return jsonify({"error": "No version found"}), 404
        
    version.metadata_json = json.dumps(data, ensure_ascii=False)
    db.session.commit()
    return jsonify({"success": True})

@reports_v3_bp.route('/reports-v3/input/<int:tid>')
def input_form(tid):
    """Giao diện Cán bộ nhập liệu (Lock)"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
        
    template = db.session.get(ReportTemplateV3, tid)
    if not template:
        flash('Không tìm thấy biểu mẫu!', 'danger')
        return redirect(url_for('dashboard_bp.dashboard'))
        
    version = ReportVersionV3.query.filter_by(template_id=tid, is_published=True).order_by(ReportVersionV3.created_at.desc()).first()
    if not version:
        flash('Không có phiên bản nào!', 'danger')
        return redirect(url_for('dashboard_bp.dashboard'))
        
    # Lay config (input_range, unit_column)
    config = {}
    if version.metadata_json:
        try:
            config = json.loads(version.metadata_json)
        except:
            pass

    return _render_template('reports_v3_input.html', template=template, version=version, config=json.dumps(config))
