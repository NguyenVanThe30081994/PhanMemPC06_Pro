# -*- coding: utf-8 -*-
"""
excel_renderer.py
-----------------
Shared utility: renders an openpyxl worksheet as a faithful HTML <table>,
preserving merged cells (colspan/rowspan), cell styles, and optionally
filling in submitted data values.

Used by:
  - V1 Stats page  (render header rows + append unit data rows)
  - V2 Render page (render full template, turn input-marker cells into <input>)
"""

import io
import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles.fills import PatternFill
from markupsafe import Markup
import unicodedata


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fmt_val(val):
    """
    Format value for display: 
    - Removes floating point noise (e.g., 3441.6000000000004 -> 3441.6)
    - Shows integers as integers (e.g., 525.0 -> 525)
    """
    if val is None or val == '':
        return ''
    if isinstance(val, (int, float)):
        try:
            fval = round(float(val), 10)
            if fval == int(fval):
                return str(int(fval))
            return "{:.10f}".format(fval).rstrip('0').rstrip('.')
        except:
            return str(val)
    return str(val).strip()


def _normalize_nfc(value):
    """Normalize string to NFC form for consistent comparison."""
    return unicodedata.normalize('NFC', str(value)) if value is not None else ""


def _safe_color(color_obj):
    """Return a 6-char hex string or None from an openpyxl Color object."""
    try:
        if not color_obj:
            return None
        # RGB type
        if color_obj.type == 'rgb' and color_obj.rgb:
            rgb = str(color_obj.rgb).upper()
            # Handle 8-char ARGB (common in Excel)
            if len(rgb) == 8:
                # If it's 00000000 or FFFFFFFF, it's usually default/no-fill
                if rgb in ('00000000', 'FFFFFFFF'):
                    return None
                return rgb[2:]
            return rgb
        # Theme type
        if color_obj.type == 'theme' and color_obj.theme is not None:
            return f"THEME_{color_obj.theme}"
    except Exception:
        pass
    return None


def is_input_cell(cell):
    """
    Broadened detection: Any cell with a non-white background is likely an input marker.
    """
    try:
        fill = cell.fill
        if not fill or fill.patternType is None: return False
        
        c = fill.start_color
        if not c: return False
        
        # 1. Match by Theme (Aggressive)
        if c.type == 'theme' and c.theme is not None:
            if c.theme > 0: return True
            if c.theme == 0 and (c.tint and abs(c.tint) > 0.01): return True

        # 2. Match by RGB
        if hasattr(c, 'rgb') and c.rgb:
            rgb = str(c.rgb).upper()
            rgb_6 = rgb[-6:] if len(rgb) >= 6 else rgb
            if rgb_6 not in ['FFFFFF', '000000', '00000000']:
                return True
    except:
        pass
    return False


def _cell_css(cell):
    """Generate inline CSS for a cell based on its openpyxl style."""
    css = []
    
    # 1. Background color - Only apply if patternType is present and not default
    if cell.fill and cell.fill.patternType and cell.fill.patternType != 'none':
        color = _safe_color(cell.fill.start_color)
        if color and not color.startswith("THEME_"):
            # Skip common default backgrounds that cause "black/white" issues
            if color not in ('FFFFFF', '000000'):
                css.append(f"background-color:#{color};")

    # 2. Font styles
    f = cell.font
    if f:
        if f.bold: css.append("font-weight:bold;")
        if f.italic: css.append("font-style:italic;")
        if f.color and f.color.rgb and isinstance(f.color.rgb, str):
            c = str(f.color.rgb)
            if len(c) == 8: css.append(f"color:#{c[2:]};")
        if f.sz: css.append(f"font-size:{f.sz}pt;")

    # 3. Alignment
    a = cell.alignment
    if a:
        if a.horizontal: css.append(f"text-align:{a.horizontal};")
        if a.vertical: css.append(f"vertical-align:{a.vertical};")
        if a.wrapText: css.append("white-space:normal;")
        else: css.append("white-space:nowrap;")

    return "".join(css)


def _build_merge_lookup(ws):
    """Return (spans, shadows) dicts to handle merged cells in HTML."""
    spans = {}  # (r, c) -> (rowspan, colspan)
    shadows = set() # (r, c) that are covered by a merge
    for mr in ws.merged_cells.ranges:
        s_row, s_col, e_row, e_col = mr.min_row, mr.min_col, mr.max_row, mr.max_col
        spans[(s_row, s_col)] = (e_row - s_row + 1, e_col - s_col + 1)
        for r in range(s_row, e_row + 1):
            for c in range(s_col, e_col + 1):
                if r == s_row and c == s_col: continue
                shadows.add((r, c))
    return spans, shadows


def _col_widths_px(ws):
    """Estimate column widths in pixels."""
    widths = []
    for i in range(1, ws.max_column + 1):
        letter = get_column_letter(i)
        w = ws.column_dimensions[letter].width or 8.43
        widths.append(max(int(w * 7), 45))
    return widths


def _row_height_px(ws, r):
    """Estimate row height in pixels."""
    h = ws.row_dimensions[r].height or 15
    return int(h * 1.33)


def render_range_to_html(ws, start_row, end_row,
                         input_marker_hex='FFE0F2FE',
                         existing_values=None,
                         editable=True,
                         min_col=1, max_col=None):
    """
    Render rows [start_row .. end_row] (1-indexed, inclusive) of `ws`
    as an HTML <tbody> fragment.
    """
    if existing_values is None:
        existing_values = {}
    if max_col is None:
        max_col = ws.max_column

    spans, shadows = _build_merge_lookup(ws)
    html = []
    input_keys = []

    for r in range(start_row, end_row + 1):
        if ws.row_dimensions[r].hidden:
            continue
        rh = _row_height_px(ws, r)
        html.append(f'<tr style="height:{rh}px">')

        for c in range(min_col, max_col + 1):
            if (r, c) in shadows:
                continue

            cell = ws.cell(row=r, column=c)
            rowspan, colspan = spans.get((r, c), (1, 1))
            css = _cell_css(cell)

            is_input = is_input_cell(cell)
            coord = cell.coordinate
            rs_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ''
            cs_attr = f' colspan="{colspan}"' if colspan > 1 else ''
            base_style = 'padding:3px 6px;border:1px solid #d1d5db;overflow:hidden;box-sizing:border-box;'
            if is_input:
                base_style += 'background-color:#e0f2fe;'

            full_css = f'{base_style}{css}'
            td_open = f'<td{rs_attr}{cs_attr} style="{full_css}">'

            if is_input:
                val = existing_values.get(coord, '')
                safe_val = str(val).replace('"', '&quot;')
                input_keys.append(coord)
                td_inner = (
                    f'<input type="text" class="grid-input" '
                    f'data-key="{coord}" data-coord="{coord}" '
                    f'value="{safe_val}" onchange="markDirty()" '
                    f'style="width:100%;height:100%;border:none;'
                    f'background:transparent;padding:2px;font-size:inherit;">'
                )
            else:
                raw_val = cell.value
                if isinstance(raw_val, str) and raw_val.startswith('='):
                    raw_val = ''
                display = _fmt_val(raw_val)
                td_inner = display

            html.append(f'{td_open}{td_inner}</td>')
        html.append('</tr>')

    return {
        'tbody_html': '\n'.join(html),
        'input_keys': input_keys,
    }


def build_stats_table_html(file_blob, config, submissions):
    """
    For V1 Stats: render the Excel file's header section faithfully,
    then append one data row per unit below the headers.
    """
    if not file_blob:
        return Markup('<p class="text-muted">Không có file Excel gốc.</p>')

    try:
        # Load workbook 2 lần:
        # wb_formula: để lấy định dạng, merged cells (data_only=False)
        # wb_values: để lấy giá trị hiển thị/kết quả công thức (data_only=True)
        wb_formula = openpyxl.load_workbook(io.BytesIO(file_blob), data_only=False)
        wb_values = openpyxl.load_workbook(io.BytesIO(file_blob), data_only=True)
        ws = wb_formula.active
        ws_values = wb_values.active
    except Exception as e:
        return Markup(f'<p class="text-danger">Lỗi đọc file Excel: {e}</p>')

    header_start = config.header_start or 1
    header_rows = config.header_rows or 1
    header_end = header_start + header_rows - 1

    from pc06_excel_engine import ExcelEngineV2
    regions = ExcelEngineV2._detect_active_regions(wb, ws)
    r_box = regions["report"]
    min_col, min_row, max_col, max_row = r_box[0], r_box[1], r_box[2], r_box[3]
    render_start_row = min(header_start, min_row)

    import json
    try: fields = json.loads(config.config_json or '[]')
    except: fields = []

    unit_map = {sub.get('unit'): sub for sub in submissions}
    unit_map_lower = {str(k).strip().lower(): v for k, v in unit_map.items() if k}
    unit_names_lower = sorted(list(unit_map_lower.keys()), key=len, reverse=True)

    spans, shadows = _build_merge_lookup(ws)
    col_widths = []
    for i in range(min_col, max_col + 1):
        letter = get_column_letter(i)
        w = ws.column_dimensions[letter].width or 8.43
        col_widths.append(max(int(w * 7), 45))

    col_parts = ['<colgroup>']
    for w in col_widths: col_parts.append(f'<col style="width:{w}px">')
    col_parts.append('</colgroup>')

    rows_html = []
    from utils import is_unit_match
    for r in range(render_start_row, max_row + 1):
        if ws.row_dimensions[r].hidden: continue
        
        matched_sub = None
        for name in unit_names_lower:
            found_match = False
            for c_check in range(min_col, max_col + 1):
                cell_v = ws.cell(row=r, column=c_check).value
                if cell_v and is_unit_match(name, str(cell_v)):
                    found_match = True
                    break
            if found_match:
                matched_sub = unit_map_lower[name]
                break
        
        rh = _row_height_px(ws, r)
        rows_html.append(f'<tr style="height:{rh}px">')

        for c in range(min_col, max_col + 1):
            if (r, c) in shadows: continue
            cell = ws.cell(row=r, column=c)
            cell_values = ws_values.cell(row=r, column=c)
            rowspan, colspan = spans.get((r, c), (1, 1))
            css = _cell_css(cell)
            val = cell_values.value # Ưu tiên giá trị hiển thị từ wb_values
            if matched_sub and r > header_end:
                is_field = any(f['idx'] == c for f in fields)
                if is_field: val = matched_sub['values'].get(str(c), '')
            
            display = _fmt_val(val)
            rs_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ''
            cs_attr = f' colspan="{colspan}"' if colspan > 1 else ''
            base_td = 'padding:3px 6px;border:1px solid #d1d5db;overflow:hidden;'
            if r > header_end: base_td += 'text-align:center;'
            rows_html.append(f'<td{rs_attr}{cs_attr} style="{base_td}{css}">{display}</td>')
        rows_html.append('</tr>')

    html = (
        '<div class="excel-wrapper" style="overflow:auto;max-height:80vh;">'
        '<table class="excel-render-table" style="border-collapse:collapse;font-size:12px;">'
        + ''.join(col_parts) + '<tbody>' + ''.join(rows_html) + '</tbody></table></div>'
    )
    return Markup(html)


def build_v2_stats_table_html(file_blob, metadata, all_values):
    """For V2 Stats: render the full Excel template structure."""
    if not file_blob: return Markup('<p class="text-muted">Không có file Excel gốc.</p>')
    try:
        wb_formula = openpyxl.load_workbook(io.BytesIO(file_blob), data_only=False)
        wb_values = openpyxl.load_workbook(io.BytesIO(file_blob), data_only=True)
    except Exception as e:
        return Markup(f'<p class="text-danger">Lỗi đọc file Excel: {e}</p>')

    wb = wb_formula

    sheets_html = []
    from pc06_excel_engine import ExcelEngineV2
    for ws in wb.worksheets:
        ws_values = wb_values[ws.title] if ws.title in wb_values.sheetnames else ws
        sheet_meta = next((s for s in metadata.get('sheets', []) if s['name'] == ws.title), None)
        if sheet_meta:
            region = sheet_meta.get('activeRenderRegion', {})
            min_row, min_col, max_row = region.get('r1', 1), region.get('c1', 1), region.get('r2', ws.max_row)
            max_col = max(region.get('c2', ws.max_column), ws.max_column)
        else:
            max_row, max_col = ExcelEngineV2._get_true_max_row_col(wb, ws)
            min_row, min_col = 1, 1

        spans_all, shadows_all = _build_merge_lookup(ws)
        spans = {k: v for k, v in spans_all.items() if min_row <= k[0] <= max_row and min_col <= k[1] <= max_col}
        shadows = shadows_all

        col_widths = []
        for i in range(min_col, max_col + 1):
            letter = get_column_letter(i)
            w = ws.column_dimensions[letter].width or 8.43
            col_widths.append(max(int(w * 7), 45))

        colgroup = '<colgroup>' + ''.join(f'<col style="width:{w}px">' for w in col_widths) + '</colgroup>'
        rows_html = []
        for r in range(min_row, max_row + 1):
            if ws.row_dimensions[r].hidden: continue
            rh = _row_height_px(ws, r)
            rows_html.append(f'<tr style="height:{rh}px">')
            for c in range(min_col, max_col + 1):
                if (r, c) in shadows: continue
                cell = ws.cell(row=r, column=c)
                cell_values = ws_values.cell(row=r, column=c)
                rowspan, colspan = spans.get((r, c), (1, 1))
                css = _cell_css(cell)
                coord = cell.coordinate
                full_key = f"{ws.title}!{coord}"
                val = all_values.get(full_key, all_values.get(coord))
                if val is None:
                    val = cell_values.value if cell_values.value is not None else ''
                display = _fmt_val(val)
                rs_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ''
                cs_attr = f' colspan="{colspan}"' if colspan > 1 else ''
                base_td = 'padding:3px 6px;border:1px solid #d1d5db;overflow:hidden;'
                rows_html.append(f'<td{rs_attr}{cs_attr} style="{base_td}{css}">{display}</td>')
            rows_html.append('</tr>')

        sheet_title_html = f'<h6 class="fw-bold mt-4 mb-2"><i class="fa-solid fa-layer-group me-2"></i>Sheet: {ws.title}</h6>'
        sheet_table = (
            f'<div class="excel-wrapper mb-4" style="overflow:auto;max-height:80vh;border:1px solid #eee;border-radius:8px;">'
            f'<table class="excel-render-table" style="border-collapse:collapse;font-size:12px;width:max-content;">'
            f'{colgroup}<tbody>{"".join(rows_html)}</tbody></table></div>'
        )
        sheets_html.append(sheet_title_html + sheet_table)
    return Markup(''.join(sheets_html))
