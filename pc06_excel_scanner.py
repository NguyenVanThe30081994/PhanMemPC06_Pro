# -*- coding: utf-8 -*-
# Excel Scanner for V2 Reports
# Uses raw values from Excel - no conversion to avoid float precision errors
import io
import openpyxl
from openpyxl.utils import get_column_letter, column_index_from_string, range_boundaries


def _is_blank(value):
    return value is None or str(value).strip() == ''


def _is_formula_text(value):
    return isinstance(value, str) and value.strip().startswith('=')


def _is_text_like(value):
    if _is_blank(value) or _is_formula_text(value):
        return False
    return isinstance(value, str)


def _is_numeric_like(value):
    if _is_blank(value):
        return False
    return isinstance(value, (int, float))


def _load_workbook_utf8(buffer, **kwargs):
    """Load workbook with UTF-8 encoding support"""
    kwargs.setdefault('read_only', False)
    kwargs.setdefault('keep_vba', True)
    # Try with rich_text for better UTF-8 handling
    try:
        return openpyxl.load_workbook(buffer, rich_text=True, **kwargs)
    except:
        return openpyxl.load_workbook(buffer, **kwargs)


def scan_excel_structure(excel_blob):
    """
    Quét cấu trúc file Excel và trả về gợi ý cấu hình.
    Chỉ quét vùng có dữ liệu thực tế (used range), không quét vùng trắng.
    """
    wb = _load_workbook_utf8(io.BytesIO(excel_blob))
    ws = wb.active
    
    # Tìm vùng thực tế có dữ liệu (used range)
    # Thay vì dùng max_row/max_column (có thể bao gồm vùng trắng), 
    # ta tìm last row/col có dữ liệu
    used_min_row = ws.min_row
    used_max_row = ws.max_row
    used_min_col = ws.min_column
    used_max_col = ws.max_column
    
    # Nếu worksheet có nhiều dòng trống ở cuối, tìn lại
    # Duyệt từ cuối ngược lên để tìm dòng có dữ liệu
    if used_max_row > used_min_row:
        for row in range(used_max_row, used_min_row, -1):
            has_data = False
            for col in range(used_min_col, used_max_col + 1):
                cell_val = ws.cell(row, col).value
                if cell_val is not None and str(cell_val).strip() != '':
                    has_data = True
                    break
            if has_data:
                used_max_row = row
                break
            else:
                used_max_row = row - 1  # Giảm max_row nếu dòng trống
    
    # Tương tự cho cột
    if used_max_col > used_min_col:
        for col in range(used_max_col, used_min_col, -1):
            has_data = False
            for row in range(used_min_row, used_max_row + 1):
                cell_val = ws.cell(row, col).value
                if cell_val is not None and str(cell_val).strip() != '':
                    has_data = True
                    break
            if has_data:
                used_max_col = col
                break
            else:
                used_max_col = col - 1
    
    used_width = max(1, used_max_col - used_min_col + 1)
    result = {
        'total_rows': used_max_row,
        'total_cols': used_max_col,
        'columns': [],  # ['A', 'B', 'C', ...]
        'header_rows': [],
        'data_start_row': 4,  # Default
        'headers': {},  # {row: {col: value}}
        'merged_cells': [],
        'numeric_columns': [],
        'formulas': {},  # {col_letter: formula_type}
        'original_max_row': ws.max_row,  # Lưu lại để debug
        'original_max_col': ws.max_column,
    }
    
    # Get columns (chỉ vùng có dữ liệu)
    for col in range(used_min_col, used_max_col + 1):
        result['columns'].append(get_column_letter(col))
    
    # Scan merged cells
    for merged_range in ws.merged_cells.ranges:
        min_col, min_row, max_col, max_row = range_boundaries(str(merged_range))
        result['merged_cells'].append({
            'range': str(merged_range),
            'row': min_row,
            'col_start': get_column_letter(min_col),
            'col_end': get_column_letter(max_col),
            'colspan': max_col - min_col + 1,
            'rowspan': max_row - min_row + 1,
            'value': ws.cell(min_row, min_col).value
        })
    
    merged_by_row = {}
    for merged in result['merged_cells']:
        merged_by_row.setdefault(merged['row'], []).append(merged)

    # Detect header rows with relaxed heuristics:
    # - keep rows containing labels/merged section headers
    # - stop at the first row that clearly looks like data
    header_candidates = []
    detected_data_row = None
    scan_limit = min(used_max_row, used_min_row + 39)
    for row in range(used_min_row, scan_limit + 1):
        row_values = [ws.cell(row, col).value for col in range(used_min_col, used_max_col + 1)]
        non_empty = [value for value in row_values if not _is_blank(value)]
        if not non_empty:
            continue

        text_like_count = sum(1 for value in non_empty if _is_text_like(value))
        numeric_like_count = sum(1 for value in non_empty if _is_numeric_like(value))
        formula_like_count = sum(1 for value in non_empty if _is_formula_text(value))
        merged_headers = merged_by_row.get(row, [])
        dominant_merge = any(m.get('colspan', 1) >= max(3, int(used_width * 0.45)) for m in merged_headers)
        first_cell = ws.cell(row, used_min_col).value
        numeric_ratio = numeric_like_count / max(1, len(non_empty))

        looks_like_data = (
            numeric_like_count >= 2
            and numeric_ratio >= 0.35
            and text_like_count <= max(2, len(non_empty) // 3)
        ) or (
            header_candidates
            and _is_numeric_like(first_cell)
            and numeric_like_count >= 2
            and text_like_count <= 2
            and formula_like_count <= 2
        )

        if header_candidates and looks_like_data:
            detected_data_row = row
            break

        if text_like_count > 0 or dominant_merge:
            header_candidates.append(row)
            continue

        if header_candidates and numeric_like_count > 0:
            detected_data_row = row
            break

    result['header_rows'] = header_candidates
    if detected_data_row:
        result['data_start_row'] = detected_data_row
    elif header_candidates:
        cursor = max(header_candidates) + 1
        while cursor <= used_max_row:
            row_values = [ws.cell(cursor, col).value for col in range(used_min_col, used_max_col + 1)]
            if any(not _is_blank(value) for value in row_values):
                result['data_start_row'] = cursor
                break
            cursor += 1

    # Scan headers - use raw value directly, don't convert
    for row in header_candidates:
        result['headers'][row] = {}
        for col in range(used_min_col, used_max_col + 1):
            cell_val = ws.cell(row, col).value
            if cell_val:
                # Use raw value - don't convert to avoid float precision issues
                result['headers'][row][get_column_letter(col)] = cell_val

    # Detect numeric columns
    data_row = result['data_start_row']
    if data_row <= ws.max_row:
        numeric_cols = set()
        sample_rows = [
            row for row in range(data_row, min(data_row + 8, used_max_row + 1))
            if any(not _is_blank(ws.cell(row, col).value) for col in range(used_min_col, used_max_col + 1))
        ]
        
        for col in range(used_min_col, used_max_col + 1):
            all_numeric = True
            for row in sample_rows:
                cell_val = ws.cell(row, col).value
                if cell_val is not None and cell_val != '':
                    if not isinstance(cell_val, (int, float)):
                        if isinstance(cell_val, str) and cell_val.startswith('='):
                            continue
                        all_numeric = False
                        break
            if all_numeric:
                numeric_cols.add(get_column_letter(col))
        
        result['numeric_columns'] = list(numeric_cols)
    
    # Detect formulas
    formula_cols = {}
    if data_row <= ws.max_row:
        for col in range(used_min_col, used_max_col + 1):
            cell = ws.cell(data_row, col)
            if cell.data_type == 'f':
                formula = str(cell.value)
                if 'SUM' in formula.upper():
                    formula_cols[get_column_letter(col)] = 'SUM'
                elif 'AVG' in formula.upper():
                    formula_cols[get_column_letter(col)] = 'AVG'
                elif '/' in formula and '%' not in formula.upper():
                    formula_cols[get_column_letter(col)] = 'RATIO'
                else:
                    formula_cols[get_column_letter(col)] = 'CUSTOM'
    
    result['formulas'] = formula_cols
    
    return result
