# PC06 OCR Engine - Chỉ 2 chức năng:
# 1. PDF có text → Word (giữ nguyên format)
# 2. Ảnh → Word (OCR Tiếng Việt)

import os
import requests

Document = None
fitz = None

def _ensure_imports():
    global Document, fitz
    if Document is None:
        try:
            from docx import Document
        except: pass
    if fitz is None:
        try:
            import fitz
        except: pass

# OCR.space API
OCR_API_KEY = "K81408611188957"
OCR_API_URL = "https://api.ocr.space/ocr"

class PC06_OCR_API:
    def __init__(self):
        self.ocr_available = True
        self.status_message = "OCR - Ready (PDF & Ảnh → Word)"
        print(f"[OCR] {self.status_message}")
    
    def process_image_to_word(self, img_path, output_path):
        """Ảnh → Word (OCR Tiếng Việt)"""
        try:
            with open(img_path, "rb") as f:
                img_data = f.read()
            
            files = {"filename": ("image.png", img_data, "image/png")}
            data = {
                "apikey": OCR_API_KEY,
                "language": "vie",
                "isTable": "true",
                "detectOrientation": "true"
            }
            
            response = requests.post(OCR_API_URL, files=files, data=data, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("IsErroredOnProcessing") == False:
                    parsed = result.get("ParsedResults", [])
                    if parsed:
                        _ensure_imports()
                        if Document:
                            word_doc = Document()
                            word_doc.add_heading("OCR - PC06", 0)
                            
                            for p in parsed:
                                text = p.get("ParsedText", "")
                                if text.strip():
                                    for line in text.strip().split("\n"):
                                        if line.strip():
                                            word_doc.add_paragraph(line.strip())
                            
                            word_doc.save(output_path)
                            return True
            return False
        except Exception as e:
            print(f"[OCR] Error: {e}", flush=True)
            return False
    
    def process_pdf_to_word(self, pdf_path, output_path):
        """PDF có text → Word (giữ nguyên format)"""
        _ensure_imports()
        if fitz is None or Document is None:
            return False
        
        try:
            doc = fitz.open(pdf_path)
            word_doc = Document()
            word_doc.add_heading("CHUYỂN ĐỔI TỪ PDF - PC06", 0)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text().strip()
                
                if text:
                    word_doc.add_paragraph(f"--- Trang {page_num+1} ---")
                    for line in text.split("\n"):
                        if line.strip():
                            word_doc.add_paragraph(line.strip())
                else:
                    word_doc.add_paragraph(f"--- Trang {page_num+1} (PDF scan) ---")
            
            word_doc.save(output_path)
            return True
        except Exception as e:
            print(f"[OCR] Error: {e}", flush=True)
            return False
    
    def full_convert(self, input_file, target_format="word"):
        """PDF & Ảnh → Word"""
        import pandas as pd
        
        try:
            ext = os.path.splitext(input_file)[1].lower()
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
            
            os.makedirs("static/exports", exist_ok=True)
            
            if ext == ".pdf":
                output_path = f"static/exports/{base_name}_{timestamp}.docx"
                success = self.process_pdf_to_word(input_file, output_path)
                return output_path if success else None
            
            elif ext in [".jpg", ".jpeg", ".png", ".bmp", ".tiff"]:
                output_path = f"static/exports/{base_name}_{timestamp}.docx"
                success = self.process_image_to_word(input_file, output_path)
                return output_path if success else None
            
            return None
        except Exception as e:
            print(f"[OCR] Error: {e}", flush=True)
            return None

# Singleton
try:
    ocr_system = PC06_OCR_API()
except Exception as e:
    ocr_system = type("obj", (object,), {
        "ocr_available": False,
        "status_message": f"Error: {e}"
    })()
