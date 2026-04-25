from app import app
from models_reporting import FormTemplate
from pc06_excel_scanner import scan_excel_structure

with app.app_context():
    templates = FormTemplate.query.order_by(FormTemplate.id.desc()).limit(2).all()
    
    for template in templates:
        print(f"\n{'='*60}")
        print(f"Template: {template.name}")
        print(f"ID: {template.id}")
        print('='*60)
        
        detected = scan_excel_structure(template.excel_template_blob)
        
        print(f"Header rows detected: {detected.get('header_rows', [])}")
        print(f"Data start row: {detected.get('data_start_row')}")
        print(f"Total columns: {detected.get('total_cols')}")
        
        # Check merged cells in header area
        print("\nMerged cells in headers:")
        for m in detected.get('merged_cells', [])[:10]:
            if m['row'] <= 15:
                print(f"  Row {m['row']}: {m['col_start']}-{m['col_end']} ({m['colspan']} cols) = '{m['value']}'")
