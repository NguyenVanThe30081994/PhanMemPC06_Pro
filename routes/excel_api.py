# -*- coding: utf-8 -*-
"""
Excel API - Nhan du lieu tu Luckysheet/Univer
"""
from flask import Blueprint, request, jsonify, session, redirect
from models import db, ReportConfig, ReportData
from datetime import datetime
import json
from utils import normalize_unit_name

excel_api = Blueprint('excel_api', __name__, url_prefix='/api/excel')


@excel_api.route('/import-luckysheet', methods=['POST'])
def import_luckysheet():
    # Check login
    if not session.get('uid'):
        return jsonify({'error': 'Chua dang nhap'}), 401
    
    try:
        data = request.get_json()
        
        # Validate data
        if not data or 'sheets' not in data:
            return jsonify({'error': 'Du lieu khong hop le'}), 400
        
        # Get first sheet
        sheets = data.get('sheets', [])
        if not sheets:
            return jsonify({'error': 'Sheet trong'}), 400
        
        sheet_data = sheets[0]
        rows = sheet_data.get('data', [])
        
        if not rows:
            return jsonify({'error': 'Du lieu trong'}), 400
        
        # Get config_id if provided
        config_id = data.get('config_id')
        form_config = None
        if config_id:
            form_config = ReportConfig.query.get(config_id)
        
        # Extract data based on structure
        submissions = []
        errors = []
        
        # First row is header
        headers = rows[0] if rows else []
        
        # Process data rows starting from row 1 (or configured start row)
        start_row = data.get('start_row', 1)
        
        for idx, row in enumerate(rows[start_row:], start=start_row):
            if not row:
                continue
            
            # Skip empty rows
            if all(cell is None for cell in row):
                continue
            
            # Try to extract unit name from first column
            unit_name = row[0] if row else None
            if not unit_name:
                continue
            
            unit_name = str(unit_name).strip()
            if not unit_name:
                continue
            
            # Use existing logic to find/create unit
            unit = normalize_unit_name(unit_name)
            if not unit:
                errors.append("Dong %d: Khong nhan dien duoc don vi '%s'" % (idx, unit_name))
                continue
            
            # Extract field values
            values = {}
            for col_idx, cell in enumerate(row[1:], 1):
                if cell is not None:
                    # Handle number formatting - keep as-is from JSON
                    values[str(col_idx)] = cell
            
            # Save submission
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


@excel_api.route('/preview-template/<int:config_id>', methods=['GET'])
def preview_template(config_id):
    if not session.get('uid'):
        return redirect('/login')
        
    try:
        config = ReportConfig.query.get(config_id)
        if not config:
            return jsonify({'error': 'Khong tim thay cau hinh'}), 404
        
        # Load template metadata
        metadata = json.loads(config.metadata) if config.metadata else {}
        
        return jsonify({
            'status': 'success',
            'template': metadata
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@excel_api.route('/preview')
def preview_page():
    if not session.get('uid'):
        return redirect('/login')
        
    from flask import render_template
    config_id = request.args.get('config_id', type=int)
    start_row = request.args.get('start_row', 1, type=int)
    return render_template('excel_preview.html', config_id=config_id, start_row=start_row)
