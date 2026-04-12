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

# OCR.space API Key
OCR_API_KEY = "K81408611188957"

# Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@convert_bp.route('/convert')
def index():
    return render_template('convert.html')

@convert_bp.route('/convert/process', methods=['POST'])
def process():
    if 'file' not in request.files:
        return jsonify({'error': 'Không tìm thấy file tải lên'}), 400
    
    file = request.files['file']
    convert_type = request.form.get('type', '')
    
    if file.filename == '':
        return jsonify({'error': 'Chưa chọn file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Định dạng file không được hỗ trợ'}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    try:
        if convert_type == 'img_excel':
            return convert_image_to_excel(filepath)
        elif convert_type == 'img_word':
            return convert_image_to_word(filepath)
        elif convert_type == 'img_pdf':
            return convert_image_to_pdf(filepath)
        else:
            return jsonify({'error': 'Chức năng đang phát triển'}), 400
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass

def convert_image_to_excel(filepath):
    """OCR Image to Excel using OCR.space"""
    from openpyxl import Workbook
    from PIL import Image
    import PIL
    
    # Compress image if too large
    img = Image.open(filepath)
    if img.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    
    # Resize if needed (max 1500px for free API)
    max_size = 1500
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = tuple(int(dim * ratio) for dim in img.size)
        img = img.resize(new_size, Image.LANCZOS)
    
    # Save compressed
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=80, optimize=True)
    buffer.seek(0)
    
    # Call OCR.space API
    files = {'file': ('image.jpg', buffer, 'image/jpeg')}
    data = {
        'language': 'eng',
        'apikey': OCR_API_KEY,
        'isTable': 'true',
        'OCREngine': '2'
    }
    
    response = requests.post(
        'https://api.ocr.space/parse/image',
        files=files,
        data=data,
        timeout=30
    )
    
    result = response.json()
    
    if result.get('IsErroredOnProcessing'):
        return jsonify({'error': str(result.get('ErrorMessage', ['Lỗi OCR'])[0])}), 400
    
    parsed = result.get('ParsedResults', [])
    if not parsed:
        return jsonify({'error': 'Không nhận dạng được văn bản'}), 400
    
    text = parsed[0].get('ParsedText', '')
    
    # Create Excel
    wb = Workbook()
    ws = wb.active
    
    lines = text.split('\n')
    for row_idx, line in enumerate(lines, 1):
        if line.strip():
            cells = line.split('\t') if '\t' in line else line.split()
            for col_idx, cell in enumerate(cells, 1):
                ws.cell(row=row_idx, column=col_idx, value=cell.strip())
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='bang_du_lieu.xlsx'
    )

def convert_image_to_word(filepath):
    """OCR Image to Word using OCR.space"""
    from docx import Document
    from PIL import Image
    
    # Compress image
    img = Image.open(filepath)
    if img.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    
    max_size = 1500
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = tuple(int(dim * ratio) for dim in img.size)
        img = img.resize(new_size, Image.LANCZOS)
    
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=80, optimize=True)
    buffer.seek(0)
    
    # Call OCR API
    files = {'file': ('image.jpg', buffer, 'image/jpeg')}
    data = {
        'language': 'eng',
        'apikey': OCR_API_KEY,
        'OCREngine': '2'
    }
    
    response = requests.post(
        'https://api.ocr.space/parse/image',
        files=files,
        data=data,
        timeout=30
    )
    
    result = response.json()
    
    if result.get('IsErroredOnProcessing'):
        return jsonify({'error': str(result.get('ErrorMessage', ['Lỗi OCR'])[0])}), 400
    
    parsed = result.get('ParsedResults', [])
    if not parsed:
        return jsonify({'error': 'Không nhận dạng được văn bản'}), 400
    
    text = parsed[0].get('ParsedText', '')
    
    # Create Word
    doc = Document()
    doc.add_heading('Văn bản OCR', 0)
    
    for line in text.split('\n'):
        if line.strip():
            doc.add_paragraph(line.strip())
    
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name='van_ban.docx'
    )

def convert_image_to_pdf(filepath):
    """Convert Image to PDF using PIL"""
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
