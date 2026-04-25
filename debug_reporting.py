from app import app
from models_reporting import FormTemplate
from pc06_excel_scanner import scan_excel_structure
from openpyxl.utils import column_index_from_string

with app.app_context():
    template = FormTemplate.query.order_by(FormTemplate.id.desc()).first()
    detected = scan_excel_structure(template.excel_template_blob)
    header_rows_list = detected.get('header_rows', [1])
    total_cols = detected.get('total_cols', 10)
    
    real_header_rows = []
    for r in sorted(header_rows_list):
        is_title = False
        for m in detected.get('merged_cells', []):
            if m['row'] == r and m.get('colspan', 1) >= total_cols * 0.5:
                is_title = True
                break
        if not is_title:
            real_header_rows.append(r)
            
    if real_header_rows:
        contiguous = [real_header_rows[-1]]
        for i in range(len(real_header_rows)-2, -1, -1):
            if real_header_rows[i+1] - real_header_rows[i] <= 2:
                contiguous.insert(0, real_header_rows[i])
            else:
                break
        real_header_rows = contiguous
    else:
        real_header_rows = header_rows_list[-2:] if len(header_rows_list) >= 2 else header_rows_list

    print("Real header rows:", real_header_rows)
    
    def get_header_text_for_cell(r, c_letter):
        c_idx = column_index_from_string(c_letter)
        for m in detected.get('merged_cells', []):
            m_r = m['row']
            m_rs = m.get('rowspan', 1)
            m_cs = column_index_from_string(m['col_start'])
            m_ce = column_index_from_string(m['col_end'])
            if m_r <= r < m_r + m_rs and m_cs <= c_idx <= m_ce:
                return str(m['value']).strip() if m['value'] else ""
        
        headers = detected.get('headers', {})
        if r in headers and c_letter in headers[r]:
            val = headers[r][c_letter]
            return str(val).strip() if val else ""
        return ""

    for col in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']:
        parts = []
        for r in real_header_rows:
            text = get_header_text_for_cell(r, col)
            if text and text not in parts:
                parts.append(text)
        print(f"Col {col}: parts={parts} -> section={parts[0] if len(parts) > 1 else 'Thông tin chung'}, name={' - '.join(parts)}")
