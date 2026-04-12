import os
import io
from flask import Blueprint, request, jsonify, send_file, render_template, session
from werkzeug.utils import secure_filename

# Lazy imports - only load when needed
# This prevents app crash if libraries aren't installed on hosting

convert_bp = Blueprint('convert', __name__)

def _get_ocr_reader():
    """Lazy load OCR reader"""
    import easyocr
    global _ocr_reader
    if _ocr_reader is None:
        try:
            _ocr_reader = easyocr.Reader(['vi', 'en'], gpu=False)
        except Exception as e:
            print(f"Error initializing OCR: {e}")
            _ocr_reader = easyocr.Reader(['en'], gpu=False)
    return _ocr_reader

_ocr_reader = None

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
    """Handle file conversion"""
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
            return convert_image_to_excel(filepath)
        elif convert_type == 'pdf_excel':
            return convert_pdf_to_excel(filepath)
        elif convert_type == 'pdf_word':
            return convert_pdf_to_word(filepath)
        elif convert_type == 'img_word':
            return convert_image_to_word(filepath)
        elif convert_type == 'img_pdf':
            return convert_image_to_pdf(filepath)
        else:
            return jsonify({'error': 'Loại chuyển đổi không hợp lệ'}), 400
    except Exception as e:
        print(f"Conversion error: {e}")
        return jsonify({'error': f'Lỗi xử lý: {str(e)}'}), 500
    finally:
        # Clean up uploaded file
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass

def convert_image_to_excel(filepath):
    """Convert table in image to Excel"""
    try:
        # Lazy imports
        import cv2
        from openpyxl import Workbook
        
        # Read image
        img = cv2.imread(filepath)
        if img is None:
            return jsonify({'error': 'Không thể đọc file ảnh'}), 400
        
        # Get OCR reader
        reader = _get_ocr_reader()
        
        # Perform OCR
        results = reader.readtext(filepath)
        
        # Extract text with position
        data = []
        for (bbox, text, prob) in results:
            if text.strip():
                # bbox is [[x1,y1], [x2,y1], [x2,y2], [x1,y2]]
                x = bbox[0][0]
                y = bbox[0][1]
                data.append({'text': text.strip(), 'x': x, 'y': y})
        
        if not data:
            return jsonify({'error': 'Không nhận dạng được văn bản trong ảnh'}), 400
        
        # Group by rows (using Y coordinate)
        # Sort by Y, then by X
        data.sort(key=lambda k: (round(k['y'] / 20), k['x']))
        
        # Simple row detection based on Y coordinate
        rows = []
        current_row = []
        current_y = None
        threshold = 20  # Y threshold for same row
        
        for item in data:
            if current_y is None:
                current_y = item['y']
                current_row.append(item['text'])
            elif abs(item['y'] - current_y) <= threshold:
                current_row.append(item['text'])
            else:
                rows.append(current_row)
                current_row = [item['text']]
                current_y = item['y']
        
        if current_row:
            rows.append(current_row)
        
        # Create Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "Bảng dữ liệu"
        
        for row_idx, row_data in enumerate(rows, 1):
            for col_idx, cell_data in enumerate(row_data, 1):
                ws.cell(row=row_idx, column=col_idx, value=cell_data)
        
        # Save to buffer
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='bang_du_lieu.xlsx'
        )
        
    except Exception as e:
        print(f"Image to Excel error: {e}")
        return jsonify({'error': f'Lỗi chuyển đổi ảnh sang Excel: {str(e)}'}), 500

def convert_pdf_to_excel(filepath):
    """Extract tables from PDF to Excel"""
    try:
        # Lazy imports
        import pdfplumber
        from openpyxl import Workbook
        
        tables_data = []
        
        with pdfplumber.open(filepath) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        if table:
                            tables_data.append({
                                'page': page_num,
                                'table': table
                            })
        
        if not tables_data:
            return jsonify({'error': 'Không tìm thấy bảng trong PDF. Đảm bảo PDF có dạng bảng (table)'}), 400
        
        # Create Excel
        wb = Workbook()
        ws = wb.active
        ws.title = "Bảng dữ liệu"
        
        row_count = 1
        for idx, data in enumerate(tables_data):
            # Add page header
            ws.cell(row=row_count, column=1, value=f"Trang {data['page']}")
            row_count += 1
            
            for row in data['table']:
                for col_idx, cell in enumerate(row, 1):
                    ws.cell(row=row_count, column=col_idx, value=cell if cell else "")
                row_count += 1
            
            row_count += 1  # Empty row between tables
        
        # Save to buffer
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='bang_tu_pdf.xlsx'
        )
        
    except Exception as e:
        print(f"PDF to Excel error: {e}")
        return jsonify({'error': f'Lỗi chuyển đổi PDF sang Excel: {str(e)}'}), 500

def convert_pdf_to_word(filepath):
    """Convert PDF to Word"""
    try:
        # Lazy import
        import pdf2docx
        
        # Use pdf2docx
        doc = pdf2docx.Document(filepath)
        
        # Save to buffer
        output = io.BytesIO()
        doc.save(output)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name='tai_lieu.docx'
        )
        
    except Exception as e:
        print(f"PDF to Word error: {e}")
        return jsonify({'error': f'Lỗi chuyển đổi PDF sang Word: {str(e)}'}), 500

def convert_image_to_word(filepath):
    """OCR image to Word document"""
    try:
        # Lazy imports
        from docx import Document
        
        # Get OCR reader
        reader = _get_ocr_reader()
        
        # Perform OCR
        results = reader.readtext(filepath)
        
        if not results:
            return jsonify({'error': 'Không nhận dạng được văn bản trong ảnh'}), 400
        
        # Create Word document
        doc = Document()
        doc.add_heading('Văn bản nhận dạng từ ảnh', 0)
        
        # Group by paragraphs (based on Y position)
        paragraphs = []
        current_para = []
        current_y = None
        threshold = 30
        
        for (bbox, text, prob) in results:
            if text.strip():
                x = bbox[0][0]
                y = bbox[0][1]
                
                if current_y is None:
                    current_y = y
                    current_para.append(text.strip())
                elif abs(y - current_y) <= threshold:
                    current_para.append(' ' + text.strip())
                else:
                    paragraphs.append(' '.join(current_para))
                    current_para = [text.strip()]
                    current_y = y
        
        if current_para:
            paragraphs.append(' '.join(current_para))
        
        # Add paragraphs to document
        for para in paragraphs:
            if para.strip():
                doc.add_paragraph(para.strip())
        
        # Save to buffer
        output = io.BytesIO()
        doc.save(output)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name='van_ban.docx'
        )
        
    except Exception as e:
        print(f"Image to Word error: {e}")
        return jsonify({'error': f'Lỗi chuyển đổi ảnh sang Word: {str(e)}'}), 500

def convert_image_to_pdf(filepath):
    """Convert image to PDF"""
    try:
        # Lazy imports
        from PIL import Image
        import img2pdf
        
        # Read image to verify it's valid
        img = Image.open(filepath)
        
        # Convert to RGB if needed (for PNG with transparency)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Create white background
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
        
        # Save image to temporary buffer for img2pdf
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='JPEG', quality=95)
        img_buffer.seek(0)
        
        # Convert to PDF
        pdf_bytes = img2pdf.convert(img_buffer.read())
        
        # Save to output buffer
        output = io.BytesIO(pdf_bytes)
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
