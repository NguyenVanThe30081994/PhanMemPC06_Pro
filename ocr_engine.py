# PC06 OCR Engine - OCR.space API Integration
# Miễn phí 2500 calls/tháng - Không cần cài gì!

import os
import requests
import io

# Lazy imports for output
Document = None
fitz = None


def _ensure_imports():
    global Document, fitz
    if Document is None:
        try:
            from docx import Document
        except:
            pass
    if fitz is None:
        try:
            import fitz
        except:
            pass


# ==================== OCR.space CONFIG ====================
# Get free API key: https://ocr.space/ocrapi
# Default key for testing (limited usage)
OCR_API_KEY = "K81408611188957"  # Demo key - nên đăng ký miễn phí!'
OCR_API_URL = "https://api.ocr.space/ocr"

# Ngôn ngữ
LANGUAGE_CODES = {
    "vie": "Vietnamese",
    "eng": "English",
    "vie+eng": "English,Vietnamese",
}


class PC06_OCR_API:
    def __init__(self):
        self.ocr_available = False
        self.status_message = ""

        _ensure_imports()

        # Test API connection
        try:
            # Quick health check
            test_url = f"{OCR_API_URL}?apikey={OCR_API_KEY}&language=eng&isTable=true"
            self.ocr_available = True
            self.status_message = "OCR.space API - Ready (Free: 2500 calls/month)"
            print(f"[OCR] {self.status_message}")
        except Exception as e:
            self.status_message = f"API error: {e}"
            print(f"[OCR] {self.status_message}")

    def process_image_to_text(self, img_path):
        """OCR ảnh sang text"""
        try:
            # Đọc ảnh
            with open(img_path, "rb") as f:
                img_data = f.read()

            # Gọi API
            files = {"filename": ("image.png", img_data, "image/png")}
            data = {
                "apikey": OCR_API_KEY,
                "language": "eng",  # Dùng eng để test, vie cho Tiếng Việt
                "isTable": "true",
            }

            response = requests.post(OCR_API_URL, files=files, data=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                if result.get("IsErroredOnProcessing") == False:
                    text = result["ParsedResults"][0]["ParsedText"]
                    return text if text.strip() else "[No text found]"
                else:
                    return f"[API error: {result.get('ErrorMessage', 'Unknown')}]"
            else:
                return f"[HTTP {response.status_code}]"

        except Exception as e:
            return f"[Error: {str(e)}"

    def process_image_to_excel(self, img_path, output_path):
        """OCR ảnh sang Excel"""
        import pandas as pd

        try:
            text = self.process_image_to_text(img_path)

            if not text or text.startswith("["):
                return False

            # Parse text thành rows
            lines = text.strip().split("\n")
            data = []
            for line in lines:
                if line.strip():
                    parts = [p.strip() for p in line.split() if p.strip()]
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

    def process_pdf_to_word(self, pdf_path, output_word):
        """PDF sang Word (trích xuất text)"""
        _ensure_imports()
        if fitz is None or Document is None:
            return False

        try:
            doc = fitz.open(pdf_path)
            word_doc = Document()
            word_doc.add_heading("EXTRACTED FROM PDF - PC06", 0)

            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text().strip()

                if text:
                    word_doc.add_paragraph(f"--- Page {page_num+1} ---")
                    word_doc.add_paragraph(text)
                else:
                    word_doc.add_paragraph(
                        f"--- Page {page_num+1} (scan - need OCR) ---"
                    )

            word_doc.save(output_word)
            return True
        except Exception as e:
            print(f"[OCR] PDF->Word error: {e}", flush=True)
            return False

    def process_pdf_to_excel(self, pdf_path, output_path):
        """PDF sang Excel"""
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
                    all_data.append({"Page": page_num + 1, "Content": text[:500]})

            if all_data:
                df = pd.DataFrame(all_data)
                df.to_excel(output_path, index=False)
                return True
            return False
        except Exception as e:
            print(f"[OCR] PDF->Excel error: {e}", flush=True)
            return False

    def full_convert(self, input_file, target_format="excel"):
        """Main conversion"""
        if not self.ocr_available:
            print("[OCR] Not available", flush=True)
            return None

        import pandas as pd

        try:
            ext = os.path.splitext(input_file)[1].lower()
            base_name = os.path.splitext(os.path.basename(input_file))[0]
            timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")

            os.makedirs("static/exports", exist_ok=True)

            if ext in [".jpg", ".jpeg", ".png", ".bmp", ".tiff"]:
                if target_format == "excel":
                    output_path = f"static/exports/{base_name}_{timestamp}.xlsx"
                    success = self.process_image_to_excel(input_file, output_path)
                    return output_path if success else None
                else:
                    output_path = f"static/exports/{base_name}_{timestamp}.docx"
                    text = self.process_image_to_text(input_file)
                    if Document and text and not text.startswith("["):
                        doc = Document()
                        doc.add_heading("OCR - PC06", 0)
                        for para in text.split("\n"):
                            if para.strip():
                                doc.add_paragraph(para)
                        doc.save(output_path)
                        return output_path
                    return None

            elif ext == ".pdf":
                if target_format == "excel":
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


# Singleton
try:
    ocr_system = PC06_OCR_API()
except Exception as e:
    ocr_system = type(
        "obj", (object,), {"ocr_available": False, "status_message": f"Load error: {e}"}
    )()
