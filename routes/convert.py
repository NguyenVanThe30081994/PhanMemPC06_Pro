# -*- coding: utf-8 -*-
import sys
import os

# Fix UTF-8 encoding
if sys.version_info[0] >= 3:
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)

import io
import json
import base64
import requests
from flask import Blueprint, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename

convert_bp = Blueprint('convert', __name__)

# Google Apps Script Web App URL
GAS_URL = "https://script.google.com/macros/s/AKfycbzcQ2dRkfFrrQ5Hjohrz6DGkjvalSmlqTZBRDtSQoIs8X7ivQCDgadtUPw_GJlqTvR5/exec"

# Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads')
CONVERT_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tmp', 'convert')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(CONVERT_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@convert_bp.route('/convert')
def index():
    """Render convert page"""
    return render_template('convert.html')

@convert_bp.route('/convert/process', methods=['POST'])
def process():
    """Handle file conversion using Google Drive API"""
    if 'file' not in request.files:
        return jsonify({'error': 'Không tìm thấy file tải lên'}), 400
    
    file = request.files['file']
    convert_type = request.form.get('type', '')
    
    if file.filename == '':
        return jsonify({'error': 'Chưa chọn file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Định dạng file không được hỗ trợ. Chỉ chấp nhận: JPG, PNG, PDF'}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    try:
        if convert_type == 'img_excel':
            return convert_using_gas(filepath, 'excel')
        elif convert_type == 'pdf_excel':
            return convert_using_gas(filepath, 'excel')
        elif convert_type == 'pdf_word':
            return convert_using_gas(filepath, 'word')
        elif convert_type == 'img_word':
            return convert_using_gas(filepath, 'word')
        elif convert_type == 'img_pdf':
            return convert_image_to_pdf_simple(filepath)
        else:
            return jsonify({'error': 'Loại chuyển đổi không hợp lệ'}), 400
    except Exception as e:
        print(f"Conversion error: {e}")
        return jsonify({'error': f'Lỗi xử lý: {str(e)}'}), 500
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass

def convert_using_gas(filepath, target_type):
    """Convert file using Google Apps Script (Google Drive OCR)"""
    try:
        # Determine mime type from file extension
        ext = filepath.rsplit('.', 1)[1].lower()
        if ext in ['jpg', 'jpeg']:
            mime_type = 'image/jpeg'
        elif ext == 'png':
            mime_type = 'image/png'
        elif ext == 'pdf':
            mime_type = 'application/pdf'
        else:
            mime_type = 'application/octet-stream'
        
        # Read and encode file
        with open(filepath, 'rb') as f:
            file_data = base64.b64encode(f.read()).decode('utf-8')
        
        # Prepare payload for GAS
        payload = {
            'base64': file_data,
            'fileName': os.path.basename(filepath),
            'mimeType': mime_type,
            'target': target_type
        }
        
        # Send to Google Apps Script
        response = requests.post(GAS_URL, json=payload, timeout=60)
        result = response.json()
        
        print(f"GAS Response: {result}")
        
        # Check for errors
        if result.get('status') == 'error':
            return jsonify({'error': result.get('message', 'Lỗi chuyển đổi')}), 400
        
        # Decode returned file
        if not result.get('fileData'):
            return jsonify({'error': 'Không nhận được file chuyển đổi'}), 400
        
        file_bytes = base64.b64decode(result['fileData'])
        
        # Determine output filename and mimetype
        if target_type == 'excel':
            output_filename = 'bang_du_lieu.xlsx'
            output_mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else:
            output_filename = 'tai_lieu.docx'
            output_mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        
        output = io.BytesIO(file_bytes)
        output.seek(0)
        
        return send_file(
            output,
            mimetype=output_mime,
            as_attachment=True,
            download_name=output_filename
        )
        
    except Exception as e:
        print(f"Google Drive conversion error: {e}")
        return jsonify({'error': f'Lỗi chuyển đổi: {str(e)}'}), 500

def convert_image_to_pdf_simple(filepath):
    """Convert image to PDF using PIL"""
    try:
        from PIL import Image
        
        img = Image.open(filepath)
        
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
                img = background
            else:
                img = img.convert('RGB')
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        output = io.BytesIO()
        img.save(output, format='PDF')
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='chuyen_doi.pdf'
        )
        
    except Exception as e:
        print(f"Image to PDF error: {e}")
        return jsonify({'error': f'Lỗi chuyển đổi ảnh sang PDF: {str(e)}'}), 500
