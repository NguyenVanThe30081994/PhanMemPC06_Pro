# PC06 Advanced OCR Engine
# Xử lý bảng phức tạp, PDF nhiều trang, và tiền xử lý ảnh

import os
import numpy as np
import pandas as pd

# Deferred imports - load only when needed
cv2 = None
fitz = None
Document = None

def _ensure_imports():
    """Lazy import các thư viện nặng"""
    global cv2, fitz, Document
    if cv2 is None:
        try:
            import cv2
        except ImportError:
            print("[OCR] Install opencv-python: pip install opencv-python")
    if fitz is None:
        try:
            import fitz
        except ImportError:
            print("[OCR] Install pymupdf: pip install pymupdf")
    if Document is None:
        try:
            from docx import Document
        except ImportError:
            print("[OCR] Install python-docx: pip install python-docx")

class PC06_Advanced_OCR:
    def __init__(self):
        self.ocr_available = False
        self.table_engine = None
        self.ocr_text = None
        
        # Load basic deps first
        try:
            import numpy as np
            import pandas as pd
        except ImportError as e:
            print(f"[OCR] Missing required library: {e}")
            print("[OCR] Install: pip install numpy pandas")
            return
            
        try:
            from paddleocr import PaddleOCR, PPStructure
            # OCR cho văn bản thuần túy
            self.ocr_text = PaddleOCR(use_angle_cls=True, lang='vi', show_log=False)
            # OCR cho cấu trúc bảng - PP-Structure
            self.table_engine = PPStructure(show_log=False, lang='vi', layout=True, table=True)
            self.ocr_available = True
            print("[OCR] PaddleOCR loaded successfully")
        except ImportError as e:
            print(f"[OCR] PaddleOCR not available: {e}")
            print("[OCR] Using fallback mode - Install: pip install paddlepaddle paddleocr")
            self.ocr_available = True
        except Exception as e:
            print(f"[OCR] Error loading OCR: {e}")

    def _fix_orientation(self, image):
        """Tình huống 1: Ảnh bị chụp nghiêng hoặc ngược"""
        _ensure_imports()
        if cv2 is None:
            return image
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image
            denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
            return denoised
        except:
            return image

    def process_image_to_excel(self, img_path, output_path):
        """Tình huống 2: Ảnh chứa bảng phức tạp, gộp ô"""
        if not self.ocr_available:
            return False
        
        _ensure_imports()
        if cv2 is None:
            print("[OCR] opencv-python not installed")
            return False
            
        try:
            img = cv2.imread(img_path)
            if img is None:
                print(f"[OCR] Cannot read image: {img_path}")
                return False
                
            # Sử dụng PP-Structure để nhận diện bảng
            result = self.table_engine(img)
            
            all_dfs = []
            for line in result:
                if line['type'] == 'table':
                    html_str = line['res']['html']
                    try:
                        df = pd.read_html(html_str)[0]
                        all_dfs.append(df)
                    except Exception as e:
                        print(f"[OCR] Error parsing table: {e}")
            
            if all_dfs:
                with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                    for i, df in enumerate(all_dfs):
                        sheet_name = f'Bang_{i+1}'
                        if len(sheet_name) > 31:
                            sheet_name = f'Sheet_{i+1}'
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
                return True
            return False
        except Exception as e:
            print(f"[OCR] Error processing image to Excel: {e}")
            return False

    def process_image_to_text(self, img_path):
        """Chuyển ảnh văn bản sang text"""
        if not self.ocr_available:
            return ""
        
        _ensure_imports()
        if cv2 is None:
            return ""
            
        try:
            img = cv2.imread(img_path)
            if img is None:
                return ""
            
            img = self._fix_orientation(img)
            
            if hasattr(self, 'ocr_text') and hasattr(self.ocr_text, 'ocr'):
                res = self.ocr_text.ocr(img, cls=True)
                if res and res[0]:
                    text_lines = []
                    for line in res[0]:
                        text_lines.append(line[1][0])
                    return '\n'.join(text_lines)
            return ""
        except Exception as e:
            print(f"[OCR] Error OCR text: {e}")
            return ""

    def _ensure_docx(self):
        """Ensure Document is imported"""
        global Document
        if Document is None:
            _ensure_imports()
        return Document is not None

    def process_pdf_to_word(self, pdf_path, output_word):
        """PDF hỗn hợp (text + scan) sang Word"""
        if not self.ocr_available:
            return False
        
        _ensure_imports()
        if fitz is None or Document is None:
            print("[OCR] pymupdf or python-docx not installed")
            return False
            
        try:
            doc = fitz.open(pdf_path)
            word_doc = Document()
            word_doc.add_heading('DỮ LIỆU TRÍCH XUẤT TỪ PDF - PC06', 0)

            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text().strip()

                if text:
                    word_doc.add_paragraph(f"--- Trang {page_num+1} (Dữ liệu gốc) ---")
                    word_doc.add_paragraph(text)
                else:
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
                    
                    word_doc.add_paragraph(f"--- Trang {page_num+1} (Dữ liệu OCR) ---")
                    try:
                        res = self.ocr_text.ocr(img_data, cls=True)
                        if res and res[0]:
                            for line in res[0]:
                                word_doc.add_paragraph(line[1][0])
                    except Exception as e:
                        word_doc.add_paragraph(f"[Lỗi OCR trang {page_num+1}]")
            
            word_doc.save(output_word)
            return True
        except Exception as e:
            print(f"[OCR] Error PDF to Word: {e}")
            return False

    def process_pdf_to_excel(self, pdf_path, output_path):
        """Chuyển PDF sang Excel"""
        if not self.ocr_available:
            return False
        
        _ensure_imports()
        if fitz is None:
            print("[OCR] pymupdf not installed")
            return False
            
        try:
            doc = fitz.open(pdf_path)
            all_page_dfs = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text().strip()
                
                if text:
                    continue
                
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
                
                try:
                    result = self.table_engine(img_data)
                    for line in result:
                        if line['type'] == 'table':
                            html_str = line['res']['html']
                            try:
                                df = pd.read_html(html_str)[0]
                                df['_page'] = page_num + 1
                                all_page_dfs.append(df)
                            except:
                                pass
                except Exception as e:
                    print(f"[OCR] Page {page_num} error: {e}")
            
            if all_page_dfs:
                with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
                    for i, df in enumerate(all_page_dfs):
                        df.to_excel(writer, sheet_name=f'Page_{i+1}', index=False)
                return True
            return False
        except Exception as e:
            print(f"[OCR] PDF to Excel error: {e}")
            return False

    def full_convert(self, input_file, target_format='word'):
        """Hàm tổng hợp tự động nhận diện định dạng"""
        if not self.ocr_available:
            print("[OCR] OCR engine not available")
            return None
            
        ext = os.path.splitext(input_file)[1].lower()
        
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        timestamp = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')
        
        if ext in ['.jpg', '.jpeg', '.png', '.bmp']:
            if target_format == 'excel':
                output_name = f"{base_name}_OCR_{timestamp}.xlsx"
                output_path = os.path.join('static/exports', output_name)
                success = self.process_image_to_excel(input_file, output_path)
                return output_path if success else None
            else:
                output_name = f"{base_name}_OCR_{timestamp}.docx"
                output_path = os.path.join('static/exports', output_name)
                
                text = self.process_image_to_text(input_file)
                if text:
                    _ensure_imports()
                    if Document:
                        doc = Document()
                        doc.add_heading('DỮ LIỆU OCR - PC06', 0)
                        for para in text.split('\n'):
                            if para.strip():
                                doc.add_paragraph(para)
                        doc.save(output_path)
                        return output_path
                return None
        
        elif ext == '.pdf':
            if target_format == 'excel':
                output_name = f"{base_name}_OCR_{timestamp}.xlsx"
                output_path = os.path.join('static/exports', output_name)
                success = self.process_pdf_to_excel(input_file, output_path)
                return output_path if success else None
            else:
                output_name = f"{base_name}_OCR_{timestamp}.docx"
                output_path = os.path.join('static/exports', output_name)
                success = self.process_pdf_to_word(input_file, output_path)
                return output_path if success else None
        
        return None


# Singleton instance
ocr_system = PC06_Advanced_OCR()
