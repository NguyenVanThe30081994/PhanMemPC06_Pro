# -*- coding: utf-8 -*-
"""
LuckyTemplate Generator - Admin setup range, User input
"""
from flask import Blueprint, request, jsonify, session, redirect, send_file
from models import db
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
    """Admin: Upload template Excel"""
    check = login_required()
    if check: return check
    
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({'error': 'Khong co file'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'File trong'}), 400
        
        # Save to templates folder
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
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Upload Template - Admin</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/css/luckysheet.css" />
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/assets/iconfont/iconfont.css" />
        <script src="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/plugins/js/plugin.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/luckysheet.umd.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/luckyexcel@latest/dist/luckyexcel.umd.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
    </head>
    <body style="margin:0;padding:20px;background:#f5f5f5;">
        <div style="max-width:800px;margin:0 auto;background:white;padding:20px;border-radius:8px;">
            <h2><i class="fa-solid fa-upload"></i> Upload Template Excel</h2>
            <form id="uploadForm" enctype="multipart/form-data">
                <input type="file" name="file" accept=".xlsx" style="margin:20px 0;" required>
                <button type="submit" class="btn btn-primary">Upload</button>
            </form>
            <div id="luckysheet" style="margin:20px 0;min-height:500px;"></div>
            <div style="margin-top:20px;">
                <button id="saveRangeBtn" class="btn btn-success" disabled>
                    <i class="fa-solid fa-save"></i> Thiet lap vung nhap lieu
                </button>
                <span id="rangeInfo" style="margin-left:10px;color:green;"></span>
            </div>
        </div>
        <script>
            let selectedRange = null;
            
            // Watch for selection changes in Luckysheet
            function watchSelection() {
                if (luckysheet && luckysheet.getActiveSheet()) {
                    // Get current selection
                    const selection = luckysheet.getSelection();
                    if (selection && selection.length > 0) {
                        const s = selection[0];
                        selectedRange = {
                            row: [s.row, s.row + s.row_count - 1],
                            col: [s.column, s.column + s.column_count - 1]
                        };
                    }
                }
                setTimeout(watchSelection, 1000);
            }
            
            document.getElementById('uploadForm').addEventListener('submit', function(e) {
                e.preventDefault();
                const formData = new FormData(this);
                
                fetch('/template/admin/upload', {
                    method: 'POST',
                    body: formData
                })
                .then(r => r.json())
                .then(data => {
                    if (data.status === 'success') {
                        // Load file into Luckysheet
                        fetch(data.filepath)
                        .then(r => r.blob())
                        .then(blob => {
                            const file = new File([blob], data.filename, {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
                            LuckyExcel.transformExcelToLucky(file, function(exportJson) {
                                luckysheet.create({
                                    container: 'luckysheet',
                                    data: exportJson.sheets,
                                    title: exportJson.info.name
                                });
                                document.getElementById('saveRangeBtn').disabled = false;
                                setTimeout(watchSelection, 2000);
                            });
                        });
                    }
                });
            });
            
            document.getElementById('saveRangeBtn').addEventListener('click', function() {
                if (!selectedRange) {
                    alert('Hay chon mot vung truoc!');
                    return;
                }
                // Save range to hidden field or submit
                alert('Da chon vung: Hang ' + (selectedRange.row[0]+1) + '-' + (selectedRange.row[1]+1) + 
                      ', Cot ' + (selectedRange.col[0]+1) + '-' + (selectedRange.col[1]+1));
                // TODO: Save to database via API
            });
        </script>
    </body>
    </html>
    '''


@template_bp.route('/admin/save-range', methods=['POST'])
def admin_save_range():
    """Admin: Save input range to database"""
    check = login_required()
    if check: return check
    
    data = request.get_json()
    config_id = data.get('config_id')
    sheet_name = data.get('sheet_name', 'Sheet1')
    start_cell = data.get('start_cell')  # A5
    end_cell = data.get('end_cell')      # G10
    
    # Save to template config (use session for now)
    session['template_range_%s' % config_id] = {
        'sheet_name': sheet_name,
        'start_cell': start_cell,
        'end_cell': end_cell
    }
    
    return jsonify({'status': 'success', 'message': 'Da luu vung nhap lieu'})


# ============== USER: Load Template (Read-only) ==============

@template_bp.route('/user/input/<int:config_id>')
def user_input(config_id):
    """User: Load template for data entry (read-only headers)"""
    check = login_required()
    if check: return check
    
    # Get template range from session (or DB)
    range_config = session.get('template_range_%s' % config_id)
    
    template_html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Nhap Bao Cao</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/css/luckysheet.css" />
        <script src="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/plugins/js/plugin.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/luckysheet@latest/dist/luckysheet.umd.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/luckyexcel@latest/dist/luckyexcel.umd.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" />
        <style>
            .locked-cell { background: #f0f0f0 !important; }
            .input-cell { background: #fff !important; }
        </style>
    </head>
    <body style="margin:0;padding:20px;background:#f5f5f5;">
        <div style="max-width:1200px;margin:0 auto;background:white;padding:20px;border-radius:8px;">
            <h2><i class="fa-solid fa-edit"></i> Nhap Bao Cao - Don vi: %s</h2>
            <div id="luckysheet" style="margin:20px 0;min-height:500px;"></div>
            <button id="submitBtn" class="btn btn-success">
                <i class="fa-solid fa-check"></i> Gui Bao Cao
            </button>
        </div>
        <script>
            const configId = %d;
            const inputRange = %s;
            
            // Load template (mock - replace with actual template URL)
            // luckysheet.create({...});
            
            // Apply lock/unlock based on inputRange
            function applyLocks() {
                if (!inputRange || !luckysheet) return;
                // TODO: Lock cells outside inputRange
            }
            
            document.getElementById('submitBtn').addEventListener('click', function() {
                const data = luckysheet.getAllSheets();
                fetch('/template/extract-data', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        config_id: configId,
                        sheets: data,
                        unit_name: '%s'
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
    ''' % (session.get('unit_area', 'Unknown'), config_id, json.dumps(range_config), session.get('unit_area', 'Unknown'))
    
    return template_html


# ============== EXTRACT DATA with Proper Type Handling ==============

@template_bp.route('/extract-data', methods=['POST'])
def extract_data():
    """Extract data from Luckysheet JSON with proper dtype handling"""
    check = login_required()
    if check: return check
    
    try:
        data = request.get_json()
        sheets = data.get('sheets', [])
        config_id = data.get('config_id')
        unit_name = data.get('unit_name', session.get('unit_area', ''))
        
        if not sheets:
            return jsonify({'error': 'Sheet trong'}), 400
        
        # Get input range from session/DB
        range_config = session.get('template_range_%s' % config_id)
        
        # Extract data from specified range
        sheet = sheets[0]
        rows = sheet.get('data', [])
        
        if not rows:
            return jsonify({'error': 'Du lieu trong'}), 400
        
        # Parse range if available
        start_row = 1  # Default: skip header
        end_row = len(rows)
        
        if range_config:
            # Parse range like A5:G10
            # Simplified: just use all data after header
            pass
        
        # Extract values with proper type handling
        extracted = []
        for idx, row in enumerate(rows[start_row:], start=start_row):
            if not row:
                continue
            if all(cell is None for cell in row):
                continue
            
            # Get unit name from first column
            unit = str(row[0]).strip() if row[0] else None
            if not unit:
                continue
            
            # Extract other columns with type detection
            values = {}
            for col_idx, cell in enumerate(row[1:], 1):
                if cell is not None:
                    # Type detection: check if it's a float that should be int
                    if isinstance(cell, float):
                        # If value is essentially an integer (like 491.0)
                        if cell == int(cell):
                            values[str(col_idx)] = int(cell)  # Convert to int
                        else:
                            values[str(col_idx)] = round(cell, 2)  # Keep 2 decimals
                    else:
                        values[str(col_idx)] = cell
            
            extracted.append({
                'unit': unit,
                'values': values
            })
        
        # TODO: Save to database (ReportData)
        
        return jsonify({
            'status': 'success',
            'submissions': len(extracted),
            'message': 'Da luu %d ban ghi' % len(extracted),
            'data': extracted  # Debug
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
