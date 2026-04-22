# -*- coding: utf-8 -*-
"""
Template Generator - LuckySheet integration for V2 template setup
"""
from flask import Blueprint, request, jsonify, session, redirect
from models import db, ReportTemplateV2, ReportVersionV2, ReportSubmissionV2, ReportValueV2
from datetime import datetime
import json
import os

template_bp = Blueprint('template_bp', __name__, url_prefix='/template')


def login_required():
    if not session.get('uid'):
        return redirect('/login')
    return None


# ============== ADMIN: Upload & Setup Range ==============

@template_bp.route('/admin/upload', methods=['GET', 'POST'])
def admin_upload():
    check = login_required()
    if check: return check
    
    if not session.get('is_admin'):
        return jsonify({'error': 'Chi admin duoc phep'}), 403
    
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({'error': 'No file'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'Empty file'}), 400
        
        from flask import current_app
        template_dir = os.path.join(current_app.root_path, 'templates_files')
        os.makedirs(template_dir, exist_ok=True)
        
        filename = 'template_%d_%s' % (session.get('uid'), file.filename)
        filepath = os.path.join(template_dir, filename)
        file.save(filepath)
        
        return jsonify({
            'status': 'success',
            'filepath': '/templates_files/%s' % filename,
            'filename': file.filename
        })
    
    # Return HTML with LuckySheet
    return '''<!DOCTYPE html>
<html>
<head>
    <title>Setup Template - Admin</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/css/luckysheet.css" />
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/assets/iconfont/iconfont.css" />
    <script src="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/plugins/js/plugin.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/luckysheet.umd.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/luckyexcel@latest/dist/luckyexcel.umd.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
    <style>
        body { margin: 0; padding: 20px; background: #f5f5f5; font-family: 'Segoe UI', sans-serif; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .btn { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; margin: 5px; }
        .btn-primary { background: #2196F3; color: white; }
        .btn-success { background: #4CAF50; color: white; }
        .btn:disabled { background: #ccc; cursor: not-allowed; }
        h2 { margin-top: 0; color: #333; }
        .upload-section { padding: 15px; background: #f9f9f9; border-radius: 4px; margin-bottom: 15px; }
        .luckysheet-container { min-height: 500px; border: 1px solid #ddd; border-radius: 4px; }
        #rangeInfo { margin-left: 10px; color: green; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h2><i class="fa-solid fa-upload"></i> Cai dat Mau V2 - LuckySheet</h2>
        
        <div class="upload-section">
            <label>Chon file Excel:</label>
            <input type="file" id="excelFile" accept=".xlsx" />
            <button id="uploadBtn" class="btn btn-primary">
                <i class="fa-solid fa-upload"></i> Tai len
            </button>
        </div>
        
        <div id="luckysheet" class="luckysheet-container"></div>
        
        <div style="margin-top: 15px;">
            <button id="saveRangeBtn" class="btn btn-success" disabled>
                <i class="fa-solid fa-save"></i> Luu vung nhap lieu
            </button>
            <span id="rangeInfo"></span>
        </div>
    </div>
    
    <script>
        let selectedRange = null;
        let loadedFile = null;
        
        // Load file when selected
        document.getElementById('excelFile').addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (!file) return;
            
            document.getElementById('uploadBtn').disabled = true;
            document.getElementById('uploadBtn').innerHTML = 'Dang tai...';
            
            LuckyExcel.transformExcelToLucky(file, function(exportJson) {
                luckysheet.create({
                    container: 'luckysheet',
                    data: exportJson.sheets,
                    title: exportJson.info.name
                });
                loadedFile = file.name;
                document.getElementById('saveRangeBtn').disabled = false;
                document.getElementById('uploadBtn').disabled = false;
                document.getElementById('uploadBtn').innerHTML = 'Tai len';
            }, function(error) {
                alert('Loi: ' + error.message);
                document.getElementById('uploadBtn').disabled = false;
            });
        });
        
        // Watch for selection
        setInterval(function() {
            try {
                const sheet = luckysheet.getActiveSheet();
                if (sheet && sheet.data) {
                    const selection = luckysheet.getSelection();
                    if (selection && selection.length > 0) {
                        const s = selection[0];
                        selectedRange = 'Row ' + (s.row + 1) + '-' + (s.row + s.row_count) + 
                                     ', Col ' + (s.column + 1) + '-' + (s.column + s.column_count);
                        document.getElementById('rangeInfo').textContent = selectedRange;
                    }
                }
            } catch(e) {}
        }, 1000);
        
        // Save range
        document.getElementById('saveRangeBtn').addEventListener('click', function() {
            if (!selectedRange) {
                alert('Chon mot vung truoc!');
                return;
            }
            
            // Get all data from LuckySheet
            const allData = luckysheet.getAllSheets();
            
            // Save via API
            fetch('/template/save-config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    filename: loadedFile,
                    range: selectedRange,
                    data: allData
                })
            })
            .then(r => r.json())
            .then(data => {
                alert(data.message);
                if (data.status === 'success') {
                    window.close();
                }
            });
        });
    </script>
</body>
</html>'''


@template_bp.route('/save-config', methods=['POST'])
def save_config():
    check = login_required()
    if check: return check
    
    if not session.get('is_admin'):
        return jsonify({'error': 'Admin only'}), 403
    
    try:
        data = request.get_json()
        filename = data.get('filename')
        range_info = data.get('range')
        sheet_data = data.get('data')
        
        # Save template - use session for now (in production, save to DB)
        template_key = 'v2_template_%s' % session.get('uid')
        session[template_key] = {
            'filename': filename,
            'range': range_info,
            'data': sheet_data[0] if sheet_data else {}
        }
        
        return jsonify({
            'status': 'success',
            'message': 'Template saved'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============== USER: Input with LuckySheet ==============

@template_bp.route('/user/input/<int:config_id>')
def user_input(config_id):
    check = login_required()
    if check: return check
    
    # Get user's unit
    user_unit = session.get('unit_area', '')
    
    # Get template from session
    template_key = 'v2_template_%s' % config_id
    template_data = session.get(template_key)
    
    if not template_data:
        return '''<!DOCTYPE html>
<html>
<head>
    <title>Error</title>
</head>
<body style="padding:20px;text-align:center;">
    <h2>Chua co template</h2>
    <p>Lien he admin de cau hinh mau truoc</p>
</body>
</html>'''
    
    # Return HTML for user input (read-only headers, editable data area)
    return '''<!DOCTYPE html>
<html>
<head>
    <title>Nhap Bao cao</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/css/luckysheet.css" />
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/assets/iconfont/iconfont.css" />
    <script src="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/plugins/js/plugin.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/luckysheet.umd.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/luckyexcel@latest/dist/luckyexcel.umd.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
    <style>
        body { margin: 0; padding: 20px; background: #f5f5f5; font-family: 'Segoe UI', sans-serif; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }
        .btn { padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
        .btn-success { background: #4CAF50; color: white; }
        h2 { margin-top: 0; color: #333; }
    </style>
</head>
<body>
    <div class="container">
        <h2><i class="fa-solid fa-edit"></i> Nhap Bao cao - Don vi: %s</h2>
        <div id="luckysheet" style="min-height:500px;border:1px solid #ddd;"></div>
        <button id="submitBtn" class="btn btn-success">
            <i class="fa-solid fa-check"></i> Gui Bao cao
        </button>
    </div>
    <script>
        const configId = %d;
        
        // Load template
        fetch('/template/get-template/%d' % configId)
        .then(r => r.json())
        .then(data => {
            if (data.template) {
                luckysheet.create({
                    container: 'luckysheet',
                    data: [data.template],
                    title: 'Bao cao'
                });
            }
        });
        
        document.getElementById('submitBtn').addEventListener('click', function() {
            const allData = luckysheet.getAllSheets();
            fetch('/template/user/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    config_id: configId,
                    unit_name: '%s',
                    data: allData
                })
            })
            .then(r => r.json())
            .then(data => {
                alert(data.message);
                if (data.status === 'success') window.close();
            });
        });
    </script>
</body>
</html>
''' % (user_unit, config_id, config_id, user_unit)


@template_bp.route('/get-template/<int:config_id>')
def get_template(config_id):
    check = login_required()
    if check: return check
    
    template_key = 'v2_template_%s' % config_id
    template_data = session.get(template_key)
    
    if not template_data:
        return jsonify({'error': 'No template'}), 404
    
    return jsonify({'template': template_data.get('data', {})})


@template_bp.route('/user/save', methods=['POST'])
def user_save():
    check = login_required()
    if check: return check
    
    try:
        data = request.get_json()
        config_id = data.get('config_id')
        unit_name = data.get('unit_name', session.get('unit_area', ''))
        sheet_data = data.get('data', [])
        
        if not sheet_data:
            return jsonify({'error': 'No data'}), 400
        
        # Extract data - handle int vs decimal
        rows = sheet_data[0].get('data', [])
        submissions = []
        
        for idx, row in enumerate(rows[1:], 1):  # Skip header
            if not row or all(c is None for c in row):
                continue
            
            unit = str(row[0]).strip() if row[0] else None
            if not unit:
                continue
            
            # Only allow user's unit to edit their own
            if unit != unit_name and not session.get('is_admin'):
                continue
            
            # Extract values with type handling
            values = {}
            for col_idx, cell in enumerate(row[1:], 1):
                if cell is not None:
                    if isinstance(cell, float):
                        if cell == int(cell):
                            values[str(col_idx)] = int(cell)
                        else:
                            values[str(col_idx)] = round(cell, 2)
                    else:
                        values[str(col_idx)] = cell
            
            submissions.append({
                'unit': unit,
                'values': values
            })
        
        # Save to session (in production, save to DB)
        save_key = 'submissions_%d_%s' % (config_id, unit_name)
        session[save_key] = submissions
        
        return jsonify({
            'status': 'success',
            'message': 'Da luu %d ban ghi' % len(submissions)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
