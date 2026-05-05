# -*- coding: utf-8 -*-
import html
import json
import os
import unicodedata
from copy import copy
from datetime import date, datetime

import openpyxl
from openpyxl.styles import PatternFill
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.cell import range_boundaries


def normalize_code(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("đ", "d").replace("Đ", "D").lower().strip()
    text = "".join(ch if ch.isalnum() else "_" for ch in text)
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")


def safe_filename(value):
    text = unicodedata.normalize("NFKD", str(value or "report"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace(" ", "_")
    return "".join(ch for ch in text if ch.isalnum() or ch in "_-.")


def _load_workbook(file_path):
    try:
        return openpyxl.load_workbook(file_path, rich_text=True, data_only=False)
    except Exception:
        return openpyxl.load_workbook(file_path, data_only=False)


def _safe_color(color_obj):
    try:
        if not color_obj:
            return None
        if color_obj.type == "rgb" and color_obj.rgb:
            rgb = str(color_obj.rgb).upper()
            if len(rgb) == 8:
                rgb = rgb[2:]
            if rgb in {"FFFFFF", "000000", "00000000"}:
                return None
            return rgb[-6:]
        if color_obj.type == "theme" and color_obj.theme is not None:
            return f"THEME_{color_obj.theme}"
    except Exception:
        return None
    return None


def is_input_cell(cell):
    try:
        fill = cell.fill
        if not fill or fill.patternType is None:
            return False
        color = _safe_color(fill.start_color)
        if not color:
            return False
        if color.startswith("THEME_"):
            return True
        return color not in {"FFFFFF", "000000"}
    except Exception:
        return False


def format_excel_number(value, number_format):
    if value is None or value == "":
        return ""
    if not isinstance(value, (int, float)):
        return str(value).strip()
    if not number_format:
        return str(int(value)) if float(value).is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
    fmt = str(number_format).lower().strip()
    try:
        if "%" in fmt:
            decimals = 0
            if "." in fmt:
                decimals = len(fmt.split(".")[1].split("%")[0])
            return f"{value * 100:.{decimals}f}%"
        if "#,##0" in fmt or "," in fmt:
            decimals = 0
            if "." in fmt:
                decimals = len(fmt.split(".")[1])
            result = f"{value:,.{decimals}f}"
            return result.rstrip("0").rstrip(".") if decimals == 0 else result
        if "0" in fmt:
            if "." in fmt:
                decimals = len(fmt.split(".")[1])
                return f"{value:.{decimals}f}"
            return str(int(round(value)))
    except Exception:
        pass
    return str(int(value)) if float(value).is_integer() else str(value)


def _extract_styles(cell):
    styles = []
    if cell.fill and cell.fill.patternType and cell.fill.patternType != "none":
        color = _safe_color(cell.fill.start_color)
        if color and not color.startswith("THEME_") and color not in {"FFFFFF", "000000"}:
            styles.append(f"background-color:#{color};")
    f = cell.font
    if f:
        if f.bold:
            styles.append("font-weight:bold;")
        if f.italic:
            styles.append("font-style:italic;")
        if f.sz:
            styles.append(f"font-size:{f.sz}pt;")
        if f.color and getattr(f.color, "rgb", None):
            rgb = str(f.color.rgb)
            if len(rgb) == 8:
                styles.append(f"color:#{rgb[2:]};")
    a = cell.alignment
    if a:
        if a.horizontal:
            styles.append(f"text-align:{a.horizontal};")
        if a.vertical:
            styles.append(f"vertical-align:{a.vertical};")
        styles.append("white-space:normal;" if a.wrapText else "white-space:nowrap;")
    return "".join(styles)


def _active_bounds(ws):
    dim = ws.calculate_dimension()
    min_col, min_row, max_col, max_row = range_boundaries(dim)
    for merge in ws.merged_cells.ranges:
        min_col = min(min_col, merge.min_col)
        min_row = min(min_row, merge.min_row)
        max_col = max(max_col, merge.max_col)
        max_row = max(max_row, merge.max_row)
    return min_col, min_row, max_col, max_row


def _merge_lookup(ws):
    spans = {}
    shadows = set()
    anchor_by_coord = {}
    for merge in ws.merged_cells.ranges:
        r1, c1, r2, c2 = merge.min_row, merge.min_col, merge.max_row, merge.max_col
        spans[(r1, c1)] = (r2 - r1 + 1, c2 - c1 + 1)
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                if r == r1 and c == c1:
                    anchor_by_coord[(r, c)] = (r1, c1)
                    continue
                shadows.add((r, c))
                anchor_by_coord[(r, c)] = (r1, c1)
    return spans, shadows, anchor_by_coord


def _anchor_value(ws, r, c, anchor_by_coord):
    ar, ac = anchor_by_coord.get((r, c), (r, c))
    return ws.cell(row=ar, column=ac).value


def _resolve_header_range(min_row, max_row, header_rows=2, header_start_row=None, header_end_row=None):
    start_row = int(header_start_row or min_row or 1)
    if header_end_row:
        end_row = int(header_end_row)
    else:
        end_row = start_row + max(int(header_rows or 1), 1) - 1
    if end_row < start_row:
        end_row = start_row
    if max_row < start_row:
        start_row = max_row
    if max_row < end_row:
        end_row = max_row
    return max(1, start_row), max(1, end_row)


def _resolve_column_range(min_col, max_col, start_column=None, end_column=None):
    start_col = min_col
    end_col = max_col
    if start_column:
        try:
            start_col = column_index_from_string(str(start_column).strip().upper())
        except Exception:
            start_col = min_col
    if end_column:
        try:
            end_col = column_index_from_string(str(end_column).strip().upper())
        except Exception:
            end_col = max_col
    start_col = max(min_col, start_col)
    end_col = min(max_col, end_col)
    if end_col < start_col:
        end_col = start_col
    return start_col, end_col


def _suggest_hidden_field(field):
    label = normalize_code(field.get("field_name") or field.get("path_code") or "")
    if not label:
        return False
    hidden_markers = {
        "stt",
        "so_thu_tu",
        "thu_tu",
        "don_vi",
        "ten_don_vi",
        "ma_don_vi",
    }
    return any(marker in label for marker in hidden_markers)


def parse_workbook(
    file_path,
    header_rows=2,
    data_start_row=3,
    header_start_row=None,
    header_end_row=None,
    data_end_row=None,
    total_start_row=None,
    total_end_row=None,
    start_column=None,
    end_column=None,
):
    wb = _load_workbook(file_path)
    metadata = {"sheets": [], "parser_version": "1.0"}

    for order, ws in enumerate(wb.worksheets):
        min_col, min_row, max_col, max_row = _active_bounds(ws)
        resolved_min_col, resolved_max_col = _resolve_column_range(
            min_col,
            max_col,
            start_column=start_column,
            end_column=end_column,
        )
        spans, shadows, anchors = _merge_lookup(ws)
        resolved_header_start, resolved_header_end = _resolve_header_range(
            min_row,
            max_row,
            header_rows=header_rows,
            header_start_row=header_start_row,
            header_end_row=header_end_row,
        )
        resolved_data_start = max(1, int(data_start_row or (resolved_header_end + 1)))
        resolved_data_end = min(max_row, int(data_end_row or max_row))
        if resolved_data_end < resolved_data_start:
            resolved_data_end = resolved_data_start
        resolved_total_start = int(total_start_row or 0)
        resolved_total_end = int(total_end_row or 0)
        if resolved_total_start:
            resolved_total_start = min(max_row, max(1, resolved_total_start))
        if resolved_total_end:
            resolved_total_end = min(max_row, max(resolved_total_start or 1, resolved_total_end))
        display_end_row = max(resolved_header_end, resolved_data_end, resolved_total_end or 0)
        header_rows_meta = []
        field_lookup = {}
        fields = []
        used_codes = {}

        for r in range(resolved_header_start, resolved_header_end + 1):
            row_meta = {"row": r, "cells": []}
            for c in range(resolved_min_col, resolved_max_col + 1):
                if (r, c) in shadows:
                    continue
                cell = ws.cell(row=r, column=c)
                value = _anchor_value(ws, r, c, anchors)
                if value is None or str(value).strip() == "":
                    continue
                rowspan, colspan = spans.get((r, c), (1, 1))
                row_meta["cells"].append({
                    "label": str(value),
                    "row": r,
                    "col": c,
                    "rowspan": rowspan,
                    "colspan": colspan,
                    "coord": cell.coordinate,
                })
            header_rows_meta.append(row_meta)

        for c in range(resolved_min_col, resolved_max_col + 1):
            path_labels = []
            for r in range(resolved_header_start, resolved_header_end + 1):
                value = _anchor_value(ws, r, c, anchors)
                if value is not None and str(value).strip():
                    path_labels.append(str(value).strip())
            leaf_label = path_labels[-1] if path_labels else get_column_letter(c)
            base_code = normalize_code(leaf_label) or get_column_letter(c).lower()
            count = used_codes.get(base_code, 0)
            field_code = base_code if count == 0 else f"{base_code}_{get_column_letter(c).lower()}"
            used_codes[base_code] = count + 1
            inferred_type = "text"
            for r in range(data_start_row, max_row + 1):
                if ws.row_dimensions[r].hidden:
                    continue
                sample = ws.cell(row=r, column=c).value
                if sample in (None, ""):
                    continue
                if isinstance(sample, (int, float)):
                    inferred_type = "number"
                    break
                if isinstance(sample, (datetime, date)):
                    inferred_type = "date"
                    break
            field = {
                "field_code": field_code,
                "field_name": leaf_label,
                "column_index": c,
                "column_letter": get_column_letter(c),
                "data_type": inferred_type,
                "input_mode": "text",
                "is_required": False,
                "is_visible": True,
                "is_editable": True,
                "default_value": "",
                "validation_rule": "",
                "dictionary_source": "",
                "formula_expression": "",
                "aggregation_type": "",
                "display_order": c - min_col + 1,
                "path_code": " > ".join(path_labels) if path_labels else get_column_letter(c),
            }
            fields.append(field)
            field_lookup[c] = field_code

        input_cells = []
        for r in range(resolved_data_start, resolved_data_end + 1):
            if ws.row_dimensions[r].hidden:
                continue
            for c in range(resolved_min_col, resolved_max_col + 1):
                cell = ws.cell(row=r, column=c)
                if is_input_cell(cell):
                    input_cells.append({
                        "sheet_name": ws.title,
                        "cell_address": cell.coordinate,
                        "row_index": r,
                        "column_index": c,
                        "field_code": field_lookup.get(c),
                    })

        if not input_cells:
            for r in range(resolved_data_start, resolved_data_end + 1):
                if ws.row_dimensions[r].hidden:
                    continue
                for c in range(resolved_min_col, resolved_max_col + 1):
                    cell = ws.cell(row=r, column=c)
                    if (r, c) in shadows:
                        continue
                    if cell.value in (None, ""):
                        input_cells.append({
                            "sheet_name": ws.title,
                            "cell_address": cell.coordinate,
                            "row_index": r,
                            "column_index": c,
                            "field_code": field_lookup.get(c),
                        })

        editable_columns = {cell["column_index"] for cell in input_cells if cell.get("column_index")}
        for field in fields:
            is_input_column = field["column_index"] in editable_columns
            field["is_visible"] = not _suggest_hidden_field(field)
            field["is_editable"] = is_input_column

        metadata["sheets"].append({
            "sheet_name": ws.title,
            "order_index": order,
            "min_row": min_row,
            "min_col": resolved_min_col,
            "max_row": display_end_row,
            "max_col": resolved_max_col,
            "header_start_row": resolved_header_start,
            "header_end_row": resolved_header_end,
            "header_rows": max(0, resolved_header_end - resolved_header_start + 1),
            "data_start_row": resolved_data_start,
            "data_end_row": resolved_data_end,
            "unit_start_row": resolved_data_start,
            "unit_end_row": resolved_data_end,
            "total_start_row": resolved_total_start,
            "total_end_row": resolved_total_end,
            "start_column": get_column_letter(resolved_min_col),
            "end_column": get_column_letter(resolved_max_col),
            "merges": [str(m) for m in ws.merged_cells.ranges],
            "hidden_rows": [idx for idx in range(min_row, display_end_row + 1) if ws.row_dimensions[idx].hidden],
            "hidden_cols": [get_column_letter(i) for i in range(resolved_min_col, resolved_max_col + 1) if ws.column_dimensions[get_column_letter(i)].hidden],
            "header_rows_meta": header_rows_meta,
            "fields": fields,
            "field_lookup": field_lookup,
            "input_cells": input_cells,
        })

    return metadata


def render_sheet_html(ws, editable_values=None, field_lookup=None, editable=True, start_row=None, end_row=None, min_col=None, max_col=None):
    editable_values = editable_values or {}
    field_lookup = field_lookup or {}
    active_min_col, active_min_row, active_max_col, active_max_row = _active_bounds(ws)
    min_col = max(active_min_col, min_col or active_min_col)
    max_col = min(active_max_col, max_col or active_max_col)
    min_row = max(active_min_row, start_row or active_min_row)
    max_row = min(active_max_row, end_row or active_max_row)
    spans, shadows, anchors = _merge_lookup(ws)
    html_rows = []

    for r in range(min_row, max_row + 1):
        if ws.row_dimensions[r].hidden:
            continue
        row_height = ws.row_dimensions[r].height or 15
        html_rows.append(f'<tr style="height:{int(row_height * 1.33)}px">')
        for c in range(min_col, max_col + 1):
            if (r, c) in shadows:
                continue
            cell = ws.cell(row=r, column=c)
            rowspan, colspan = spans.get((r, c), (1, 1))
            coord = cell.coordinate
            value = editable_values.get(coord, cell.value)
            if value is None:
                value = ""
            if cell.data_type == "f" and coord not in editable_values:
                value = cell.value or ""
            if isinstance(value, (datetime, date)):
                display = value.strftime("%d/%m/%Y")
            elif isinstance(value, (int, float)):
                display = format_excel_number(value, cell.number_format)
            else:
                display = str(value)
            css = _extract_styles(cell)
            field_meta = field_lookup.get(c, {})
            if isinstance(field_meta, dict):
                field_code = field_meta.get("code", "")
                field_label = field_meta.get("label", "")
            else:
                field_code = field_meta or ""
                field_label = ""
            is_input = editable and is_input_cell(cell)
            attrs = [f'data-cell="{coord}"']
            if field_code:
                attrs.append(f'data-field-code="{field_code}"')
            if field_label:
                attrs.append(f'data-field-label="{html.escape(field_label, quote=True)}"')
                attrs.append(f'title="{html.escape(field_label, quote=True)}"')
            if is_input:
                attrs.append('contenteditable="true"')
                attrs.append('spellcheck="false"')
            td_class = "report-cell"
            if is_input:
                td_class += " report-input"
            rs_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ""
            cs_attr = f' colspan="{colspan}"' if colspan > 1 else ""
            html_rows.append(
                f'<td class="{td_class}" {rs_attr}{cs_attr} style="padding:4px 6px;border:1px solid #d1d5db;overflow:hidden;box-sizing:border-box;{css}" {" ".join(attrs)}>{html.escape(display)}</td>'
            )
        html_rows.append("</tr>")

    return "\n".join(html_rows)


def write_workbook_copy(template_path, output_path, values_by_sheet):
    wb = _load_workbook(template_path)
    for ws in wb.worksheets:
        sheet_values = values_by_sheet.get(ws.title, {})
        for cell_address, value in sheet_values.items():
            ws[cell_address] = value
    wb.save(output_path)
    return output_path
