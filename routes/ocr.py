# OCR Routes for PC06
# API nhận file ảnh/PDF, xử lý OCR và trả về file Excel/Word

import os
import uuid
from flask import Blueprint, request, render_template, jsonify, send_file, current_app
from werkzeug.utils import secure_filename
from ocr_engine import ocr_system

ocr_bp = Blueprint('ocr_bp', __name__)

# Cấu hình upload
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'bmp', 'tiff'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_upload_path(filename):
    """Tạo đường dẫn upload duy nhất"""
    unique_id = str(uuid.uuid4())[:8]
    safe_name = secure_filename(filename)
    return f"{unique_id}_{safe_name}"

@ocr_bp.route('/ocr', methods=['GET'])
def ocr_index():
    """Trang chủ OCR"""
    return render_template('ocr.html')

@ocr_bp.route('/api/ocr/to-excel', methods=['POST'])
def ocr_to_excel():
    """API chuyển ảnh/PDF sang Excel (giữ định dạng bảng)"""
    if 'file' not in request.files:
        return jsonify({
            'status': 'error', 
            'message': 'Không tìm thấy file trong request'
        }), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({
            'status': 'error', 
            'message': 'Chưa chọn file'
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            'status': 'error', 
            'message': 'Định dạng không hỗ trợ. Chỉ chấp nhận: png, jpg, jpeg, pdf, bmp, tiff'
        }), 400

    # Lưu file tạm
    upload_folder = os.path.join(current_app.root_path, 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    
    filename = get_upload_path(file.filename)
    input_path = os.path.join(upload_folder, filename)
    file.save(input_path)

    # Xử lý OCR
    try:
        # Gọi OCR engine
        result_path = ocr_system.full_convert(input_path, target_format='excel')
        
        if result_path and os.path.exists(result_path):
            # Trả về đường dẫn download
            download_url = f"/static/exports/{os.path.basename(result_path)}"
            return jsonify({
                'status': 'success',
                'message': 'Chuyển đổi thành công',
                'download_url': download_url,
                'filename': os.path.basename(result_path)
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Không tìm thấy bảng trong file hoặc OCR chưa được cài đặt'
            }), 422
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Lỗi xử lý: {str(e)}'
        }), 500
    finally:
        # Xóa file input tạm sau khi xử lý
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
        except:
            pass

@ocr_bp.route('/api/ocr/to-word', methods=['POST'])
def ocr_to_word():
    """API chuyển ảnh/PDF sang Word (văn bản)"""
    if 'file' not in request.files:
        return jsonify({
            'status': 'error', 
            'message': 'Không tìm thấy file trong request'
        }), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({
            'status': 'error', 
            'message': 'Chưa chọn file'
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            'status': 'error', 
            'message': 'Định dạng không hỗ trợ'
        }), 400

    # Lưu file tạm
    upload_folder = os.path.join(current_app.root_path, 'uploads')
    os.makedirs(upload_folder, exist_ok=True)
    
    filename = get_upload_path(file.filename)
    input_path = os.path.join(upload_folder, filename)
    file.save(input_path)

    try:
        result_path = ocr_system.full_convert(input_path, target_format='word')
        
        if result_path and os.path.exists(result_path):
            download_url = f"/static/exports/{os.path.basename(result_path)}"
            return jsonify({
                'status': 'success',
                'message': 'Chuyển đổi thành công',
                'download_url': download_url,
                'filename': os.path.basename(result_path)
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Không thể chuyển đổi file này'
            }), 422
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Lỗi: {str(e)}'
        }), 500
    finally:
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
        except:
            pass

@ocr_bp.route('/api/ocr/status', methods=['GET'])
def ocr_status():
    """API kiểm tra trạng thái OCR"""
    return jsonify({
        'status': 'success',
        'available': ocr_system.ocr_available,
        'engine': 'PaddleOCR' if ocr_system.ocr_available else 'None',
        'supported_formats': list(ALLOWED_EXTENSIONS)
    })
