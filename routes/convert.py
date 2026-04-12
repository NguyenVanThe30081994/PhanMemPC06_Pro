# -*- coding: utf-8 -*-
import sys
import os

# Fix UTF-8 encoding
if sys.version_info[0] >= 3:
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)

import io
import time
from flask import Blueprint, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename

convert_bp = Blueprint('convert', __name__)

# Google Drive Configuration
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# Service Account JSON (upload your credentials file to hosting)
SERVICE_ACCOUNT_FILE = 'service_account.json'

# Folder IDs
INPUT_FOLDER_ID = '1VM-4I2AJUG7dEXzKkmaRWE33tJSCOa0K'  # PC06_Input
OUTPUT_FOLDER_ID = '12krphmrH8qH2vS6Y0b3hvcsxOugxZMJ2'  # PC06_Output

# Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_drive_service():
    """Get Google Drive service using Service Account"""
    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        service = build('drive', 'v3', credentials=credentials)
        return service
    except Exception as e:
        print(f"Drive service error: {e}")
        return None

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
        return jsonify({'error': 'Dinh dang khong ho tro'}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    try:
        if convert_type == 'img_excel':
            return convert_image_to_excel(filepath)
        elif convert_type == 'img_word':
            return convert_image_to_word(filepath)
        elif convert_type == 'img_pdf':
            return image_to_pdf(filepath)
        else:
            return jsonify({'error': 'Chuc nang khong ho tro'}), 400
    except Exception as e:
        return jsonify({'error': 'Loi: ' + str(e)}), 500
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass

def convert_image_to_excel(filepath):
    """Convert image to Excel via Google Drive OCR"""
    service = get_drive_service()
    if not service:
        return jsonify({'error': 'Loi ket noi Google Drive'}), 500
    
    try:
        # 1. Upload file to input folder
        file_metadata = {
            'name': os.path.basename(filepath),
            'parents': [INPUT_FOLDER_ID]
        }
        
        with open(filepath, 'rb') as f:
            file_content = f.read()
        
        from googleapiclient.http import MediaInMemoryUpload
        media = MediaInMemoryUpload(file_content, mimetype='application/octet-stream')
        
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        
        print(f"Uploaded file ID: {uploaded_file.get('id')}")
        
        # 2. Create Google Doc from image (OCR)
        doc_metadata = {
            'name': 'OCR_Result_' + str(int(time.time())),
            'parents': [OUTPUT_FOLDER_ID],
            'mimeType': 'application/vnd.google-apps.document'
        }
        
        # Copy to create document with OCR
        doc = service.files().copy(
            fileId=uploaded_file.get('id'),
            body=doc_metadata,
            convert=True
        ).execute()
        
        print(f"Created doc ID: {doc.get('id')}")
        
        # 3. Export to Word (can convert to xlsx later)
        export_mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        request_export = service.files().export_media(
            fileId=doc.get('id'),
            mimeType=export_mime
        )
        
        # Download
        output = io.BytesIO()
        downloader = MediaIoBaseDownload(output, request_export)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        # 4. Cleanup - delete temp files
        try:
            service.files().delete(fileId=uploaded_file.get('id')).execute()
            service.files().delete(fileId=doc.get('id')).execute()
        except:
            pass
        
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name='ket_qua.docx'
        )
        
    except Exception as e:
        print(f"Conversion error: {e}")
        return jsonify({'error': 'Loi chuyen doi: ' + str(e)}), 500

def convert_image_to_word(filepath):
    """Same as Excel - returns Word for now"""
    return convert_image_to_excel(filepath)

def image_to_pdf(filepath):
    """Convert Image to PDF using PIL"""
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
