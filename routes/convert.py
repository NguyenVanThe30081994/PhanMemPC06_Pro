# -*- coding: utf-8 -*-
import sys
import os
import logging
from datetime import datetime

# Setup logging
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'convert.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

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

# Service Account JSON
possible_paths = [
    'service_account.json',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'service_account.json'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'service_account.json'),
]

SERVICE_ACCOUNT_FILE = None
for path in possible_paths:
    if os.path.exists(path):
        SERVICE_ACCOUNT_FILE = path
        break

if not SERVICE_ACCOUNT_FILE:
    SERVICE_ACCOUNT_FILE = 'service_account.json'

logger.info(f"Service account file: {SERVICE_ACCOUNT_FILE}")

# Folder IDs
INPUT_FOLDER_ID = '1VM-4I2AJUG7dEXzKkmaRWE33tJSCOa0K'
OUTPUT_FOLDER_ID = '12krphmrH8qH2vS6Y0b3hvcsxOugxZMJ2'

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_drive_service():
    """Get Google Drive service using Service Account"""
    try:
        logger.info("Starting Google Drive connection...")
        
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            logger.error(f"Service account file NOT FOUND at: {SERVICE_ACCOUNT_FILE}")
            logger.error(f"Current dir: {os.getcwd()}")
            logger.error(f"Files in dir: {os.listdir('.')}")
            return None
        
        logger.info(f"Loading credentials from: {SERVICE_ACCOUNT_FILE}")
        
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=['https://www.googleapis.com/auth/drive.file']
        )
        
        logger.info(f"Credentials loaded for email: {credentials.service_account_email}")
        
        service = build('drive', 'v3', credentials=credentials)
        
        # Test connection
        about = service.about().get(fields="user").execute()
        logger.info(f"Connected! User: {about.get('user')}")
        
        return service
    except Exception as e:
        logger.error(f"DRIVE SERVICE ERROR: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return None

@convert_bp.route('/convert')
def index():
    return render_template('convert.html')

@convert_bp.route('/convert/process', methods=['POST'])
def process():
    logger.info("=== START CONVERSION ===")
    
    if 'file' not in request.files:
        logger.error("No file in request")
        return jsonify({'error': 'Khong tim thay file'}), 400
    
    file = request.files['file']
    convert_type = request.form.get('type', '')
    
    logger.info(f"Convert type: {convert_type}, File: {file.filename}")
    
    if file.filename == '':
        logger.error("Empty filename")
        return jsonify({'error': 'Chua chon file'}), 400
    
    if not allowed_file(file.filename):
        logger.error(f"Invalid file type: {file.filename}")
        return jsonify({'error': 'Dinh dang khong ho tro'}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    logger.info(f"File saved to: {filepath}")
    
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
        logger.error(f"CONVERSION ERROR: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Loi: ' + str(e)}), 500
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info("Temp file deleted")
            except:
                pass

def convert_image_to_excel(filepath):
    """Convert image to Excel via Google Drive OCR"""
    logger.info("Starting convert_image_to_excel")
    
    service = get_drive_service()
    if not service:
        logger.error("Failed to get drive service")
        return jsonify({'error': 'Loi ket noi Google Drive'}), 500
    
    try:
        # 1. Upload file
        logger.info("Step 1: Uploading file to Google Drive...")
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
        
        logger.info(f"Uploaded file ID: {uploaded_file.get('id')}")
        
        # 2. Create Google Doc with OCR
        logger.info("Step 2: Creating Google Doc (OCR)...")
        doc_metadata = {
            'name': 'OCR_Result_' + str(int(time.time())),
            'parents': [OUTPUT_FOLDER_ID],
            'mimeType': 'application/vnd.google-apps.document'
        }
        
        doc = service.files().copy(
            fileId=uploaded_file.get('id'),
            body=doc_metadata,
            convert=True
        ).execute()
        
        logger.info(f"Created doc ID: {doc.get('id')}")
        
        # 3. Export to Word
        logger.info("Step 3: Exporting to Word...")
        export_mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        request_export = service.files().export_media(
            fileId=doc.get('id'),
            mimeType=export_mime
        )
        
        output = io.BytesIO()
        downloader = MediaIoBaseDownload(output, request_export)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        logger.info("Download complete")
        
        # 4. Cleanup
        logger.info("Step 4: Cleaning up...")
        try:
            service.files().delete(fileId=uploaded_file.get('id')).execute()
            service.files().delete(fileId=doc.get('id')).execute()
            logger.info("Cleanup done")
        except:
            pass
        
        output.seek(0)
        
        logger.info("=== CONVERSION SUCCESS ===")
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name='ket_qua.docx'
        )
        
    except Exception as e:
        logger.error(f"Conversion failed: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Loi chuyen doi: ' + str(e)}), 500

def convert_image_to_word(filepath):
    logger.info("convert_image_to_word called - using same as excel")
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
