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
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@convert_bp.route('/convert')
def index():
    return render_template('convert.html')

@convert_bp.route('/convert/process', methods=['POST'])
def process():
    if 'file' not in request.files:
        return jsonify({'error': 'Khong tim thay file tai len'}), 400
    
    file = request.files['file']
    convert_type = request.form.get('type', '')
    
    if file.filename == '':
        return jsonify({'error': 'Chua chon file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Dinh dang file khong duoc ho tro'}), 400
    
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
            return jsonify({'error': 'Chuc nang dang phat trien'}), 400
    except Exception as e:
        import traceback
        print("Error: " + str(e))
        traceback.print_exc()
        return jsonify({'error': 'Loi: ' + str(e)}), 500
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
    
    # Process image
    img = Image.open(filepath)
    
    if img.mode in ('RGBA', 'LA'):
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    
    # Resize for API limit
    max_size = 1500
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = tuple(int(dim * ratio) for dim in img.size)
        img = img.resize(new_size, Image.LANCZOS)
    
    # Save to buffer
    buffer = io.BytesIO()
    img.save(buffer, format='JPEG', quality=80)
    buffer.seek(0)
    
    # Call OCR API
    files = {'file': ('image.jpg', buffer, 'image/jpeg')}
    data = {
        'language': 'eng',
        'apikey': OCR_API_KEY,
        'isTable': 'true'
    }
    
    try:
        response = requests.post(
            'https://api.ocr.space/parse/image',
            files=files,
            data=data,
            timeout=30
        )
        result = response.json()
        
        if result.get('IsErroredOnProcessing'):
            return jsonify({'error': str(result.get('ErrorMessage', ['Loi OCR'])[0])}), 400
        
        parsed = result.get('ParsedResults', [])
        if not parsed:
            return jsonify({'error': 'Khong nhan dang duoc van ban'}), 400
        
        text = parsed[0].get('ParsedText', '')
    except Exception as e:
        print("OCR Error: " + str(e))
        return jsonify({'error': 'Loi OCR: ' + str(e)}), 500
    
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
        download_name='data.xlsx'
    )

def convert_image_to_word(filepath):
    """OCR Image to Word using OCR.space"""
    from docx import Document
    from PIL import Image
    
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
    img.save(buffer, format='JPEG', quality=80)
    buffer.seek(0)
    
    files = {'file': ('image.jpg', buffer, 'image/jpeg')}
    data = {
        'language': 'eng',
        'apikey': OCR_API_KEY
    }
    
    try:
        response = requests.post(
            'https://api.ocr.space/parse/image',
            files=files,
            data=data,
            timeout=30
        )
        result = response.json()
        
        if result.get('IsErroredOnProcessing'):
            return jsonify({'error': str(result.get('ErrorMessage', ['Loi OCR'])[0])}), 400
        
        parsed = result.get('ParsedResults', [])
        if not parsed:
            return jsonify({'error': 'Khong nhan dang duoc van ban'}), 400
        
        text = parsed[0].get('ParsedText', '')
    except Exception as e:
        print("OCR Error: " + str(e))
        return jsonify({'error': 'Loi OCR: ' + str(e)}), 500
    
    # Create Word
    doc = Document()
    doc.add_heading('Van ban OCR', 0)
    
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
        download_name='document.docx'
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
        download_name='output.pdf'
    )
