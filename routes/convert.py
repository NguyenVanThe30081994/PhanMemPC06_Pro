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
import requests
from flask import Blueprint, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename

convert_bp = Blueprint('convert', __name__)

# Use PaddleOCR (lightweight OCR engine) - SET TO True AFTER INSTALLING
USE_PADDLE = True  # Enable by default

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
        return jsonify({'error': 'Khong tim thay file'}), 400
    
    file = request.files['file']
    convert_type = request.form.get('type', '')
    
    if file.filename == '':
        return jsonify({'error': 'Chua chon file'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'Dinh dang khong duoc ho tro'}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    try:
        if convert_type == 'img_excel':
            return ocr_to_excel(filepath)
        elif convert_type == 'img_word':
            return ocr_to_word(filepath)
        elif convert_type == 'img_pdf':
            return image_to_pdf(filepath)
        else:
            return jsonify({'error': 'Chuc nang khong ho tro'}), 400
    except Exception as e:
        return jsonify({'error': 'Loi: ' + str(e) }), 500
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass

def ocr_to_excel(filepath):
    """OCR to Excel using PaddleOCR or fallback"""
    from openpyxl import Workbook
    from PIL import Image
    
    # Try PaddleOCR first if available
    if USE_PADDLE:
        try:
            from paddleocr import PaddleOCR
            print("Initializing PaddleOCR...")
            ocr = PaddleOCR(use_angle_cls=True, lang='vi')
            print(f"Running OCR on: {filepath}")
            result = ocr.ocr(filepath, cls=True)
            print(f"OCR result: {result}")
            
            if not result or not result[0]:
                return jsonify({'error': 'Khong nhan duoc ket qua OCR'}), 400
            
            wb = Workbook()
            ws = wb.active
            
            for idx, line in enumerate(result[0], 1):
                if line and len(line) >= 2:
                    text = line[1][0]
                    ws.cell(row=idx, column=1, value=text)
            
            output = io.BytesIO()
            wb.save(output)
            output.seek(0)
            
            return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                       as_attachment=True, download_name='data.xlsx')
        except ImportError:
            print("PaddleOCR not installed")
            return jsonify({'error': 'PaddleOCR chua cai dat. Can chay: pip install paddlepaddle paddleocr'}), 500
        except Exception as e:
            print(f"PaddleOCR error: {e}")
            return jsonify({'error': 'Loi OCR: ' + str(e)}), 500
    
    # Fallback: simple PIL + basic text extraction
    img = Image.open(filepath)
    
    # Convert to grayscale for better OCR
    if img.mode != 'L':
        img = img.convert('L')
    
    # Resize if too large
    max_size = 2000
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        img = img.resize(tuple(int(d * ratio) for d in img.size), Image.LANCZOS)
    
    # Save temp
    temp_io = io.BytesIO()
    img.save(temp_io, format='PNG')
    temp_io.seek(0)
    
    # Return message - OCR requires setup
    return jsonify({
        'message': 'Chuc nang OCR can cai dat them. Lien he quan tri he thong.',
        'status': 'pending'
    }), 200

def ocr_to_word(filepath):
    """OCR to Word using PaddleOCR"""
    from docx import Document
    from PIL import Image
    
    if USE_PADDLE:
        try:
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(use_angle_cls=True, lang='vi')
            result = ocr.ocr(filepath, cls=True)
            
            doc = Document()
            doc.add_heading('Van ban', 0)
            
            for line in result[0]:
                text = line[1][0]
                doc.add_paragraph(text)
            
            output = io.BytesIO()
            doc.save(output)
            output.seek(0)
            
            return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                       as_attachment=True, download_name='document.docx')
        except:
            pass
    
    return jsonify({'message': 'Dang cho cai dat'}), 200

def image_to_pdf(filepath):
    """Convert Image to PDF"""
    from PIL import Image
    
    img = Image.open(filepath)
    
    if img.mode in ('RGBA', 'LA', 'P'):
        bg = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        if img.mode in ('RGBA', 'LA'):
            bg.paste(img, mask=img.split()[-1])
            img = bg
    elif img.mode != 'RGB':
        img = img.convert('RGB')
    
    output = io.BytesIO()
    img.save(output, format='PDF')
    output.seek(0)
    
    return send_file(output, mimetype='application/pdf', as_attachment=True, download_name='file.pdf')
