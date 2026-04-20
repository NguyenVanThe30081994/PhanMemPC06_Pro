# -*- coding: utf-8 -*-
"""
Excel API - Nhan du lieu tu Luckysheet/Univer
"""
from flask import Blueprint, request, jsonify, session, redirect
from models import db, ReportConfig, ReportData
from datetime import datetime
import json
import os
from utils import normalize_unit_name

excel_api = Blueprint('excel_api', __name__, url_prefix='/api/excel')


@excel_api.route('/upload-template', methods=['POST'])
def upload_template():
    """Upload template Excel - use Luckysheet to parse"""
    if not session.get('uid'):
        return redirect('/login')
    
    # Check if file in request
    if 'file' not in request.files:
        return jsonify({'error': 'Khong co file'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'File trong'}), 400
    
    # Save file to temp directory
    from flask import current_app
    temp_dir = os.path.join(current_app.root_path, 'tmp')
    os.makedirs(temp_dir, exist_ok=True)
    
    filepath = os.path.join(temp_dir, 'temp_' + str(session.get('uid')) + '.xlsx')
    file.save(filepath)
    
    return jsonify({
        'status': 'success',
        'filepath': filepath,
        'message': 'File uploaded'
    })


@excel_api.route('/import-luckysheet', methods=['POST'])
def import_luckysheet():
    if not session.get('uid'):
        return jsonify({'error': 'Chua dang nhap'}), 401
    
    try:
        data = request.get_json()
        
        if not data or 'sheets' not in data:
            return jsonify({'error': 'Du lieu khong hop le'}), 400
        
        sheets = data.get('sheets', [])
        if not sheets:
            return jsonify({'error': 'Sheet trong'}), 400
        
        sheet_data = sheets[0]
        rows = sheet_data.get('data', [])
        
        if not rows:
            return jsonify({'error': 'Du lieu trong'}), 400
        
        config_id = data.get('config_id')
        submissions = []
        errors = []
        
        start_row = data.get('start_row', 1)
        
        for idx, row in enumerate(rows[start_row:], start=start_row):
            if not row:
                continue
            
            if all(cell is None for cell in row):
                continue
            
            unit_name = row[0] if row else None
            if not unit_name:
                continue
            
            unit_name = str(unit_name).strip()
            if not unit_name:
                continue
            
            unit = normalize_unit_name(unit_name)
            if not unit:
                errors.append("Dong %d: Khong nhan dien duoc don vi" % idx)
                continue
            
            values = {}
            for col_idx, cell in enumerate(row[1:], 1):
                if cell is not None:
                    values[str(col_idx)] = cell
            
            submission = ReportData(
                report_config_id=config_id,
                unit_name=unit,
                values=json.dumps(values, ensure_ascii=False),
                submitted_by=session.get('uid'),
                submitted_at=datetime.now()
            )
            db.session.add(submission)
            submissions.append(unit)
        
        db.session.commit()
        
        return jsonify({
            'status': 'success',
            'submissions': len(submissions),
            'errors': errors,
            'message': 'Da luu %d ban ghi' % len(submissions)
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@excel_api.route('/preview')
def preview_page():
    if not session.get('uid'):
        return redirect('/login')
        
    from flask import render_template
    config_id = request.args.get('config_id', type=int)
    start_row = request.args.get('start_row', 1, type=int)
    return render_template('excel_preview.html', config_id=config_id, start_row=start_row)
