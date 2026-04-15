# PC06 OCR Engine - Safe version for hosting
# Handles errors gracefully

import os
import sys

# Lazy imports
cv2 = None
fitz = None
Document = None
pytesseract = None

def _ensure_imports():
    global cv2, fitz, Document, pytesseract
    try:
        if cv2 is None:
            import cv2
    except: pass
    try:
        if fitz is None:
            import fitz
    except: pass
    try:
        if Document is None:
            from docx import Document
    except: pass
    try:
        if pytesseract is None:
            import pytesseract
    except: pass

def get_tesseract_path():
    """Find Tesseract on server"""
    import subprocess
    
    # Common paths
    paths = [
        '/usr/bin/tesseract',
        '/usr/local/bin/tesseract',
        '/opt/bin/tesseract',
    ]
    
    for p in paths:
        if os.path.exists(p):
            return p
    
    # Try which
    try:
        result = subprocess.run(['which', 'tesseract'], 
                         capture_output=True, text=True, timeout=3)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except: pass
    
    return None

TESSERACT_LANG = 'vie+eng'
TESSERACT_CONFIG = '--oem 3 --psm 6'

class PC06_Tesseract_OCR:
    def __init__(self):
        self.ocr_available = False
        self.status_message = "Initializing..."
        
        try:
            _ensure_imports()
            
            if pytesseract is None:
                self.status_message = "pytesseract not installed"
                return
            
            # Find Tesseract
            tess_path = get_tesseract_path()
            
            if tess_path and os.path.exists(tess_path):
                try:
                    pytesseract.pytesseract.tesseract_cmd = tess_path
                    version = pytesseract.get_tesseract_version()
                    self.ocr_available = True
                    self.status_message = f"OK - Tesseract {version}"
                except Exception as e:
                    self.status_message = f"Tesseract error: {e}"
            else:
                # Try from PATH
                try:
                    version = pytesseract.get_tesseract_version()
                    self.ocr_available = True
                    self.status_message = "OK - Tesseract from PATH"
                except Exception as e:
                    self.status_message = f"Tesseract not found: {e}"
                    
        except Exception as e:
            self.status_message = f"Init error: {e}"
    
    def preprocess_image(self, img_path):
        """Preprocess image"""
        _ensure_imports()
        if cv2 is None:
            return None
        try:
            img = cv2.imread(img_path)
            if img is None:
                return None
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            thresh = cv2.adaptiveThreshold(blurred, 255, 
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
            return thresh
        except:
            return None
    
    def process_image_to_excel(self, img_path, output_path):
        """Convert image to Excel"""
        _ensure_imports()
        import pandas as pd
        
        if pytesseract is None:
            return False
        
        try:
            processed_img = self.preprocess_image(img_path)
            if processed_img is None:
                return False
            
            text = pytesseract.image_to_string(
                processed_img, 
                lang=TESSERACT_LANG,
                config=TESSERACT_CONFIG
            )
            
            if not text.strip():
                return False
            
            lines = text.strip().split('\n')
            data = []
            for line in lines:
                if line.strip():
                    parts = [p for p in line.split() if p.strip()]
                    if parts:
                        data.append(parts)
            
            if data:
                df = pd.DataFrame(data)
                if not df.empty:
                    df.to_excel(output_path, index=False, header=False)
                    return True
            return False
        except Exception as e:
            print(f"[OCR] Excel error: {e}", flush=True)
            return False
    
    def process_image_to_text(self, img_path):
        """Convert image to text"""
        _ensure_imports()
        
        if pytesseract is None:
            return "[pytesseract not installed]"
        
        try:
            processed_img = self.preprocess_image(img_path)
            if processed_img is None:
                return "[Cannot read image]"
            
            text = pytesseract.image_to_string(
                processed_img,
                lang=TESSERACT_LANG,
                config=TESSERACT_CONFIG
            )
            
            return text.strip() if text.strip() else "[No text detected]"
        except Exception as e:
            return f"[Error: {e}]"
    
    def process_pdf_to_word(self, pdf_path, output_word):
        """PDF to Word"""
        _ensure_imports()
        if fitz is None or Document is None:
            return False
        
        try:
            doc = fitz.open(pdf_path)
            word_doc = Document()
            word_doc.add_heading('EXTRACTED FROM PDF - PC06', 0)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text().strip()
                
                if text:
                    word_doc.add_paragraph(f"--- Page {page_num+1} ---")
                    word_doc.add_paragraph(text)
                else:
                    word_doc.add_paragraph(f"--- Page {page_num+1} (scan) ---")
            
            word_doc.save(output_word)
            return True
        except Exception as e:
            print(f"[OCR] PDF->Word error: {e}", flush=True)
            return False
    
    def process_pdf_to_excel(self, pdf_path, output_path):
        """PDF to Excel"""
        _ensure_imports()
        if fitz is None:
            return False
        
        try:
            import pandas as pd
            doc = fitz.open(pdf_path)
            
            all_data = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text().strip()
                if text:
                    all_data.append({'Page': page_num+1, 'Content': text[:500]})
            
            if all_data:
                df = pd.DataFrame(all_data)
                df.to_excel(output_path, index=False)
                return True
            return False
        except Exception as e:
            print(f"[OCR] PDF->Excel error: {e}", flush=True)
            return False
    
    def full_convert(self, input_file, target_format='excel'):
        """Main conversion function"""
        if not self.ocr_available:
            print("[OCR] Not available", flush=True)
            return None
        
        import pandas as pd
        
        try:
            ext = os.path.splitext(input_file)[1].lower()
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
            
            os.makedirs('static/exports', exist_ok=True)
            
            if ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']:
                if target_format == 'excel':
                    output_path = f"static/exports/{base_name}_{timestamp}.xlsx"
                    success = self.process_image_to_excel(input_file, output_path)
                    return output_path if success else None
                else:
                    output_path = f"static/exports/{base_name}_{timestamp}.docx"
                    text = self.process_image_to_text(input_file)
                    if Document and text:
                        doc = Document()
                        doc.add_heading('OCR - PC06', 0)
                        for para in text.split('\n'):
                            if para.strip():
                                doc.add_paragraph(para)
                        doc.save(output_path)
                        return output_path
                    return None
            
            elif ext == '.pdf':
                if target_format == 'excel':
                    output_path = f"static/exports/{base_name}_{timestamp}.xlsx"
                    success = self.process_pdf_to_excel(input_file, output_path)
                    return output_path if success else None
                else:
                    output_path = f"static/exports/{base_name}_{timestamp}.docx"
                    success = self.process_pdf_to_word(input_file, output_path)
                    return output_path if success else None
            
            return None
        except Exception as e:
            print(f"[OCR] Convert error: {e}", flush=True)
            return None

# Singleton - with try/except to prevent crash
try:
    ocr_system = PC06_Tesseract_OCR()
except Exception as e:
    ocr_system = type('obj', (object,), {
        'ocr_available': False,
        'status_message': f'Load error: {e}'
    })()
