# Convert module - PDF & Image to Word
import os
import uuid
from flask import Blueprint, request, render_template, jsonify, send_file, current_app, flash, redirect, url_for
from werkzeug.utils import secure_filename
from ocr_engine import ocr_system

convert_bp = Blueprint('convert', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'bmp', 'tiff'}
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_upload_path(filename):
    unique_id = str(uuid.uuid4())[:8]
    safe_name = secure_filename(filename)
    return f"{unique_id}_{safe_name}"

@convert_bp.route('/convert')
def index():
    """Trang chủ chuyển đổi"""
    return render_template('convert.html')

@convert_bp.route('/convert/process', methods=['POST'])
def process():
    """Xử lý: PDF & Ảnh → Word"""
    if 'file' not in request.files:
        flash('Không tìm thấy file!', 'danger')
        return redirect(url_for('convert.index'))
    
    file = request.files['file']
    if file.filename == '':
        flash('Chưa chọn file!', 'warning')
        return redirect(url_for('convert.index'))
    
    if not allowed_file(file.filename):
        flash('Định dạng không hỗ trợ!', 'danger')
        return redirect(url_for('convert.index'))
    
    # Lưu file tạm
    filename = get_upload_path(file.filename)
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(input_path)
    
    try:
        # Chỉ chuyển sang Word
        result = ocr_system.full_convert(input_path, target_format='word')
        
        if result and os.path.exists(result):
            return send_file(
                result, 
                as_attachment=True, 
                download_name=os.path.basename(result),
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
        else:
            flash('Không thể chuyển đổi file này!', 'warning')
            
    except Exception as e:
        flash(f'Lỗi xử lý: {str(e)}', 'danger')
        
    finally:
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
        except: pass
    
    return redirect(url_for('convert.index'))

@convert_bp.route('/api/convert/status', methods=['GET'])
def status():
    """API kiểm tra trạng thái"""
    return jsonify({
        'status': 'success',
        'available': ocr_system.ocr_available,
        'message': ocr_system.status_message
    })
