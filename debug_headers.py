from app import app
from models_reporting import FormTemplate
from pc06_excel_scanner import scan_excel_structure

with app.app_context():
    template = FormTemplate.query.order_by(FormTemplate.id.desc()).first()
    detected = scan_excel_structure(template.excel_template_blob)
    
    print("=== ALL HEADER ROWS DETECTED ===")
    print(detected.get('header_rows', []))
    
    print("\n=== DATA START ROW ===")
    print(detected.get('data_start_row'))
    
    print("\n=== HEADERS BY ROW ===")
    for row in sorted(detected.get('header_rows', []))[:15]:
        headers = detected.get('headers', {}).get(row, {})
        print(f"Row {row}: {list(headers.items())[:5]}")
