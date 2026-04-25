from app import app
from models_reporting import FormTemplate
from pc06_excel_scanner import scan_excel_structure
from openpyxl.utils import column_index_from_string

with app.app_context():
    template = FormTemplate.query.order_by(FormTemplate.id.desc()).first()
    detected = scan_excel_structure(template.excel_template_blob)
    
    print("=== MERGED CELLS ===")
    for m in detected.get('merged_cells', []):
        if m['row'] >= 8:  # Header rows
            print(f"Row {m['row']}: {m['col_start']}-{m['col_end']} ({m['colspan']} cols) = '{m['value']}'")
    
    print("\n=== COLUMNS TO SCAN ===")
    # Chỉ lấy các cột nằm trong vùng merge của header
    cols_in_merge = set()
    for m in detected.get('merged_cells', []):
        if m['row'] >= 8 and m.get('colspan', 1) > 1:  # Multi-column merge
            start_idx = column_index_from_string(m['col_start'])
            end_idx = column_index_from_string(m['col_end'])
            for i in range(start_idx, end_idx + 1):
                from openpyxl.utils import get_column_letter
                cols_in_merge.add(get_column_letter(i))
    
    print("Columns in merged headers:", sorted(cols_in_merge))
