# -*- coding: utf-8 -*-
"""
V3 Metadata-Driven Reporting Architecture
Dựa trên Baocaoexel.md - 5 Module Architecture:
1. Template Importer - Đọc Excel, xử lý merged cells
2. Schema Builder - Sinh field definitions từ header phức tạp  
3. Report API - CRUD values, validation, audit
4. Permission Layer - RBAC theo đơn vị
5. Excel Renderer - Export giữ layout gốc
"""
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for, session, current_app
from models import db, ReportTemplateV3, ReportVersionV3, ReportSubmissionV3, ReportValueV3, ReportAuditV3, User
from datetime import datetime
import json
import os
import io

reports_v3_bp = Blueprint('reports_v3_bp', __name__)

# ==================== MODULE 1: TEMPLATE IMPORTER ====================
def _read_excel_matrix(worksheet):
    """Đọc worksheet thành ma trận 2D, xử lý merged cells"""
    from openpyxl.utils import get_column_letter
    
    # Lấy merged ranges
    merges = []
    for merge in worksheet.merged_cells.ranges:
        merges.append({
            'min_row': merge.min_row,
            'max_row': merge.max_row, 
            'min_col': merge.min_col,
            'max_col': merge.max_col
        })
    
    # Xây ma trận
    max_row = worksheet.max_row
    max_col = worksheet.max_column
    matrix = []
    
    for r in range(1, max_row + 1):
        row_data = []
        for c in range(1, max_col + 1):
            cell = worksheet.cell(row=r, column=c)
            row_data.append({
                'value': cell.value,
                'col': c,
                'row': r
            })
        matrix.append(row_data)
    
    return {'matrix': matrix, 'merges': merges, 'max_row': max_row, 'max_col': max_col}


def _propagate_merged_headers(matrix, merges, header_row_count):
    """Propagate giá trị ô góc trên-trái sang các ô phủ trong header"""
    # Tạo map cho merged ranges
    merge_map = {}
    for m in merges:
        key = f"{m['min_row']},{m['min_col']}"
        top_left_value = matrix[m['min_row']-1][m['min_col']-1]['value']
        for r in range(m['min_row']-1, m['max_row']):
            for c in range(m['min_col']-1, m['max_col']):
                merge_map[(r, c)] = top_left_value
    
    # Apply vào header rows
    for r in range(header_row_count):
        for c in range(len(matrix[r])):
            if (r, c) in merge_map:
                matrix[r][c]['value'] = merge_map[(r, c)]
    
    return matrix


# ==================== MODULE 2: SCHEMA BUILDER ====================
def _generate_field_code(header_path):
    """Sinh field_code ổn định từ header path"""
    import unicodedata
    import re
    
    # Kết nối path bằng __
    path_str = '__'.join(str(h) for h in header_path if h)
    
    # Unicode normalize, lower case
    normalized = unicodedata.normalize('NFKD', path_str)
    ascii_str = normalized.encode('ascii', 'ignore').decode('ascii')
    
    # Thay khoảng trắng bằng _, bỏ ký tự đặc biệt
    field_code = re.sub(r'[^a-z0-9_]', '_', ascii_str.lower())
    field_code = re.sub(r'_+', '_', field_code).strip('_')
    
    return field_code


def _build_schema(worksheet, header_row_count=3):
    """Build schema JSON từ Excel template"""
    data = _read_excel_matrix(worksheet)
    matrix = _propagate_merged_headers(data['matrix'], data['merges'], header_row_count)
    
    fields = []
    grid_header_tree = []
    
    # Header rows (0-indexed): 0 to header_row_count-1
    # Data rows: header_row_count onwards
    
    # Xây grid_header_tree cho UI
    for col_idx in range(len(matrix[0])):
        col_headers = []
        for row_idx in range(header_row_count):
            val = matrix[row_idx][col_idx]['value']
            col_headers.append(str(val) if val else '')
        grid_header_tree.append(col_headers)
    
    # Xây field definitions cho data columns
    data_start_row = header_row_count - 1  # 0-indexed
    
    for col_idx in range(len(matrix[0])):
        # Header path cho cột này
        header_path = [matrix[r][col_idx]['value'] for r in range(header_row_count)]
        
        # Bỏ cột trống
        if not any(header_path):
            continue
        
        field_code = _generate_field_code(header_path)
        
        # Detect data type từ first data row
        data_type = 'text'
        if data_start_row < len(matrix):
            first_value = matrix[data_start_row][col_idx]['value']
            if first_value is not None:
                if isinstance(first_value, (int, float)):
                    data_type = 'number'
                elif isinstance(first_value, str) and first_value.replace('.','',1).replace('-','',1).isdigit():
                    data_type = 'number'
        
        fields.append({
            'field_code': field_code,
            'header_path': header_path,
            'column_index': col_idx + 1,  # 1-indexed
            'data_type': data_type,
            'editable': True,
            'required': False
        })
    
    return {
        'schema_version': '1.0',
        'header_row_count': header_row_count,
        'fields': fields,
        'grid_header_tree': grid_header_tree
    }


# ==================== MODULE 3: REPORT API ====================
def _render_template(name, **kwargs):
    kwargs['is_admin'] = session.get('is_admin')
    kwargs['fullname'] = session.get('fullname')
    kwargs['unit_area'] = session.get('unit_area')
    return render_template(name, **kwargs)


@reports_v3_bp.route('/reports-v3/dashboard')
def dashboard():
    """Trang chủ quản lý biểu mẫu V3"""
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
    """Upload template + auto-parse thành schema"""
    if not session.get('is_admin'):
        return jsonify({"error": "Unauthorized"}), 403

    file = request.files.get('template_excel')
    name = request.form.get('name', 'Báo cáo V3 Mới')
    header_rows = int(request.form.get('header_rows', 3))

    if not file or not file.filename:
        return jsonify({"error": "No file uploaded"}), 400

    try:
        import openpyxl
        file_content = file.read()
        
        # Parse template thành schema
        wb = openpyxl.load_workbook(io.BytesIO(file_content))
        ws = wb.active
        schema = _build_schema(ws, header_rows)
        
        # Tạo Template
        template = ReportTemplateV3(
            name=name,
            created_by=session.get('fullname')
        )
        db.session.add(template)
        db.session.flush()

        # Tạo Version với schema
        new_version = ReportVersionV3(
            template_id=template.id,
            version_tag=datetime.now().strftime("%Y%m%d%H%M"),
            metadata_json=json.dumps(schema, ensure_ascii=False),
            excel_file_blob=file_content,
            is_published=True
        )
        db.session.add(new_version)
        db.session.commit()

        return jsonify({"success": True, "template_id": template.id})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"V3 add error: {e}")
        return jsonify({"error": str(e)}), 500


@reports_v3_bp.route('/reports-v3/config/<int:tid>')
def config_template(tid):
    """Xem/chỉnh sửa schema"""
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


# ==================== MODULE 4: PERMISSION LAYER ====================
def _check_unit_permission(user_unit, data_unit):
    """Kiểm tra quyền theo đơn vị"""
    if not user_unit or not data_unit:
        return False
    return user_unit.lower() == data_unit.lower()


@reports_v3_bp.route('/reports-v3/api/file/<int:vid>')
def get_version_file(vid):
    """API trả về file Excel thô"""
    if not session.get('uid'):
        return jsonify({"error": "Unauthorized"}), 401
        
    version = db.session.get(ReportVersionV3, vid)
    if not version or not version.excel_file_blob:
        return jsonify({"error": "Not found"}), 404
    
    from flask import send_file
    return send_file(
        io.BytesIO(version.excel_file_blob),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='template.xlsx'
    )


@reports_v3_bp.route('/reports-v3/config/save/<int:tid>', methods=['POST'])
def config_save(tid):
    """Lưu schema config"""
    if not session.get('is_admin'):
        return jsonify({"error": "Unauthorized"}), 403
    
    data = request.json
    version = ReportVersionV3.query.filter_by(template_id=tid, is_published=True).order_by(ReportVersionV3.created_at.desc()).first()
    if not version:
        return jsonify({"error": "No version found"}), 404
    
    version.metadata_json = json.dumps(data, ensure_ascii=False)
    db.session.commit()
    return jsonify({"success": True})


# ==================== MODULE 5: EXCEL RENDERER ====================
def _export_with_data(version, submissions):
    """Export Excel giữ nguyên layout template + merge data"""
    import openpyxl
    
    wb = openpyxl.load_workbook(io.BytesIO(version.excel_file_blob))
    ws = wb.active
    
    # Merge submission data
    for sub in submissions:
        for val in sub.values:
            key = str(val.cell_key or '').strip()
            if '!' in key:
                _, coord = key.split('!', 1)
            else:
                coord = key
            try:
                ws[coord].value = val.value
            except:
                pass
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


@reports_v3_bp.route('/reports-v3/input/<int:tid>')
def input_form(tid):
    """Giao diện nhập liệu"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    
    template = db.session.get(ReportTemplateV3, tid)
    if not template:
        flash('Không tìm thấy biểu mẫu!', 'danger')
        return redirect(url_for('reports_v3_bp.dashboard'))
    
    version = ReportVersionV3.query.filter_by(template_id=tid, is_published=True).order_by(ReportVersionV3.created_at.desc()).first()
    if not version:
        flash('Không có phiên bản!', 'danger')
        return redirect(url_for('reports_v3_bp.dashboard'))
    
    # Parse schema
    schema = {}
    if version.metadata_json:
        try:
            schema = json.loads(version.metadata_json)
        except:
            pass

    return _render_template('reports_v3_input.html', template=template, version=version, config=json.dumps(schema))


@reports_v3_bp.route('/reports-v3/export/<int:tid>')
def export_report(tid):
    """Export báo cáo với dữ liệu đã nhập"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    
    template = db.session.get(ReportTemplateV3, tid)
    if not template:
        return "Not found", 404
    
    version = ReportVersionV3.query.filter_by(template_id=tid, is_published=True).order_by(ReportVersionV3.created_at.desc()).first()
    if not version or not version.excel_file_blob:
        return "No data", 404
    
    # Get all submissions for this version
    subs = ReportSubmissionV3.query.filter_by(version_id=version.id).all()
    
    # Export with merged data
    content = _export_with_data(version, subs)
    
    filename = f"BaoCao_{template.name}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    from flask import Response
    return Response(content, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")



    return jsonify({'success': True, 'message': 'Đã lưu báo cáo'})

@reports_v3_bp.route('/reports-v3/submit', methods=['POST'])
def submit_data():
    """Submit dữ liệu nhập liệu V3 với permission check và audit"""
    if not session.get('uid'):
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json or {}
    template_id = data.get('template_id')
    values = data.get('values', {})  # { "r_c": value }

    if not template_id:
        return jsonify({'success': False, 'message': 'Thiếu template_id'}), 400

    template = db.session.get(ReportTemplateV3, template_id)
    if not template:
        return jsonify({'success': False, 'message': 'Template không tồn tại'}), 404

    version = ReportVersionV3.query.filter_by(template_id=template_id, is_published=True).order_by(ReportVersionV3.created_at.desc()).first()
    if not version:
        return jsonify({'success': False, 'message': 'Không có phiên bản published'}), 404

    user_unit = session.get('unit_area', '').lower()
    if not user_unit:
        return jsonify({'success': False, 'message': 'Không xác định đơn vị'}), 403

    # Check permission: chỉ submit cho đơn vị của mình
    # Tạo submission mới hoặc update existing
    submission = ReportSubmissionV3.query.filter_by(
        version_id=version.id,
        user_id=session.get('uid'),
        org_unit=user_unit
    ).first()

    if not submission:
        submission = ReportSubmissionV3(
            version_id=version.id,
            user_id=session.get('uid'),
            org_unit=user_unit,
            period_name=datetime.now().strftime("%Y-%m-%d"),
            status='draft'
        )
        db.session.add(submission)
        db.session.flush()

    # Xóa values cũ và audit
    old_values = {f"{v.cell_r}_{v.cell_c}": v.value for v in submission.values}
    ReportValueV3.query.filter_by(submission_id=submission.id).delete()
    db.session.commit()

    # Thêm values mới
    for key, value in values.items():
        if '_' in key:
            r, c = map(int, key.split('_'))
            new_val = ReportValueV3(
                submission_id=submission.id,
                cell_r=r,
                cell_c=c,
                value=str(value) if value else ''
            )
            db.session.add(new_val)

            # Audit nếu có thay đổi
            old_val = old_values.get(key, '')
            if old_val != str(value):
                audit = ReportAuditV3(
                    submission_id=submission.id,
                    user_id=session.get('uid'),
                    cell_r=r,
                    cell_c=c,
                    old_value=old_val,
                    new_value=str(value) if value else ''
                )
                db.session.add(audit)

    submission.status = 'submitted'
    submission.updated_at = datetime.now()
    db.session.commit()

    return jsonify({'success': True, 'message': 'Đã lưu báo cáo'})
