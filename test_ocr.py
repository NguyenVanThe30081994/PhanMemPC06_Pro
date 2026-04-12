# Test OCR script
import io
from paddleocr import PaddleOCR

# Simple test
print("Testing PaddleOCR...")
ocr = PaddleOCR(lang='vi', use_gpu=False)
result = ocr.ocr('test.jpg')

print(f"Result: {result}")
print("Done!")
