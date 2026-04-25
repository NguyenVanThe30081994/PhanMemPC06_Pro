from app import app
from models_reporting import FormTemplate
from pc06_excel_scanner import scan_excel_structure
from openpyxl.utils import column_index_from_string, get_column_letter

with app.app_context():
    template = FormTemplate.query.order_by(FormTemplate.id.desc()).first()
    detected = scan_excel_structure(template.excel_template_blob)
    
    real_header_rows = [8, 9, 10]  # Giả sử đã lọc
    
    # Tìm các cột trong merge multi-column
    cols_in_data_groups = set()
    for m in detected.get('merged_cells', []):
        if m['row'] in real_header_rows and m.get('colspan', 1) > 1:
            start_idx = column_index_from_string(m['col_start'])
            end_idx = column_index_from_string(m['col_end'])
            for i in range(start_idx, end_idx + 1):
                cols_in_data_groups.add(get_column_letter(i))
    
    print("Columns in multi-column merges:", sorted(cols_in_data_groups))
    print("\nColumn A in list?", 'A' in cols_in_data_groups)
    print("Column B in list?", 'B' in cols_in_data_groups)
    print("Column C in list?", 'C' in cols_in_data_groups)
