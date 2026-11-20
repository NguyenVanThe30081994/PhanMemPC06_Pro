# -*- coding: utf-8 -*-
"""
Dịch vụ nhận diện & nhập danh sách theo dõi hồ sơ / chỉ tiêu hàng ngày
từ file Excel (.xlsx), CSV/văn bản dán bảng, hoặc ảnh chụp bảng (OCR / Vision AI).

Hỗ trợ tự động phân loại 5 phân hệ nghiệp vụ PC06:
- tam_tru: Danh sách hồ sơ đăng ký tạm trú (10 cột, có Ngày nộp, Ngày hẹn trả, Đơn vị xử lý)
- thuong_tru: Danh sách hồ sơ đăng ký thường trú (7 cột, không có Ngày hẹn trả, Địa bàn tiếp nhận)
- ct10: Thống kê phiếu xác minh CT10 (header 2 tầng Lập phiếu / Trả lời / Quá hạn)
- tich_hop: Biểu chỉ tiêu kích hoạt ĐDĐT mức 2 & tích hợp giấy tờ (sheet tổng hợp 43 cột hoặc từng giấy tờ)
- lam_sach: Chỉ tiêu làm sạch dữ liệu dân cư theo đơn vị
- khac: Bảng hồ sơ / theo dõi tổng quát khác
"""

import base64
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime

import openpyxl
from openpyxl.utils import get_column_letter

from category_helpers import canonicalize_category_value, resolve_category_display
from models import Unit
from utils import extract_unit_key, remove_accents

DOSSIER_TAB_DEFS = [
    {"key": "tam_tru", "label": "Tạm trú", "short": "Tạm trú"},
    {"key": "thuong_tru", "label": "Thường trú", "short": "Thường trú"},
    {"key": "ct10", "label": "Phiếu XM CT10", "short": "XM CT10"},
    {"key": "tich_hop", "label": "Tích hợp giấy tờ", "short": "Tích hợp"},
    {"key": "lam_sach", "label": "Làm sạch dữ liệu", "short": "Làm sạch"},
    {"key": "khac", "label": "Hồ sơ khác", "short": "Khác"},
]

DOSSIER_TAB_LABELS = {item["key"]: item["label"] for item in DOSSIER_TAB_DEFS}
VALID_TABS = {item["key"] for item in DOSSIER_TAB_DEFS}

DEFAULT_DOSSIER_LOAI_DEFS = [
    {"key": "can-cuoc", "label": "Căn cước"},
    {"key": "cu-tru", "label": "Cư trú"},
    {"key": "dinh-danh", "label": "Định danh VNeID"},
    {"key": "xac-thuc", "label": "Xác thực ĐA06"},
    {"key": "khac", "label": "Hồ sơ khác"},
]


def _load_bound_dossier_defs(field_code, defaults, include_inactive=False):
    """Đọc danh mục Phân hệ / Loại hồ sơ từ Quản trị danh mục tập trung (fallback về mặc định nếu ngoài app context)."""
    try:
        from flask import has_app_context
        if not has_app_context():
            return [dict(item) for item in defaults]
        from category_helpers import ensure_unified_category_catalog, get_bound_group, slugify_code
        from models import CategoryItem
        grp = get_bound_group("dossiers", field_code)
        if not grp:
            ensure_unified_category_catalog(commit=True)
            grp = get_bound_group("dossiers", field_code)
        if not grp:
            return [dict(item) for item in defaults]
        q = CategoryItem.query.filter_by(group_id=grp.id)
        if not include_inactive:
            q = q.filter_by(is_active=True)
        items = q.order_by(CategoryItem.sort_order.asc(), CategoryItem.id.asc()).all()
        if not items:
            return [] if not include_inactive else [dict(item) for item in defaults]
        out = []
        seen_keys = set()
        for it in items:
            key = (it.code or slugify_code(it.name or "") or str(it.id)).strip()
            lbl = (it.name or it.code or "").strip()
            if not key or not lbl or key in seen_keys:
                continue
            seen_keys.add(key)
            out.append({
                "key": key,
                "label": lbl,
                "short": lbl[:24],
                "is_active": bool(it.is_active),
                "item_id": it.id,
            })
        return out
    except Exception:
        return [dict(item) for item in defaults]


def get_dossier_tab_defs(include_inactive=False):
    return _load_bound_dossier_defs("category_tab", DOSSIER_TAB_DEFS, include_inactive=include_inactive)


def get_dossier_tab_labels():
    defs = get_dossier_tab_defs(include_inactive=True)
    labels = dict(DOSSIER_TAB_LABELS)
    for item in defs:
        labels[item["key"]] = item["label"]
    return labels


def get_valid_dossier_tabs():
    tabs = set(VALID_TABS)
    for item in get_dossier_tab_defs(include_inactive=True):
        if item.get("key"):
            tabs.add(item["key"])
    return tabs


def get_dossier_loai_defs(include_inactive=False):
    return _load_bound_dossier_defs("loai", DEFAULT_DOSSIER_LOAI_DEFS, include_inactive=include_inactive)


def get_dossier_loai_labels():
    defs = get_dossier_loai_defs(include_inactive=True)
    labels = {item["key"]: item["label"] for item in DEFAULT_DOSSIER_LOAI_DEFS}
    for item in defs:
        labels[item["key"]] = item["label"]
    return labels

_STOP_ROW_TOKENS = {
    "tong",
    "tong cong",
    "cong hoa",
    "thong ke",
    "1 thong ke",
    "2 thong ke",
    "ghi chu",
    "nguon",
}

_PROVINCE_TOTAL_TOKENS = {
    "tong",
    "tong cong",
    "toan tinh",
    "tinh tuyen quang",
    "cong an tinh",
    "cong an tinh tuyen quang",
    "ca tinh",
}


def _norm_vn(text):
    """Chuẩn hóa chuỗi tiếng Việt: bỏ dấu (kể cả đ/Đ -> d), viết thường, gom khoảng trắng."""
    if text is None:
        return ""
    raw = str(text).replace("đ", "d").replace("Đ", "D")
    s = remove_accents(raw).replace("đ", "d").replace("Đ", "D").lower()
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_key(text):
    return re.sub(r"[^a-z0-9]+", "", _norm_vn(text))


def _cell_str(val):
    if val is None:
        return ""
    if isinstance(val, datetime):
        if val.hour or val.minute:
            return val.strftime("%H:%M %d/%m/%Y")
        return val.strftime("%d/%m/%Y")
    if isinstance(val, date):
        return val.strftime("%d/%m/%Y")
    s = str(val).strip()
    if s.lower() in ("none", "nan", "nat"):
        return ""
    return s


def _parse_vn_date(val):
    """Parse linh hoạt các định dạng ngày trong biểu mẫu CSDLQG / ảnh chụp / Excel."""
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s or s in ("--", "-", "N/A", "null", "None"):
        return None

    # Dạng ISO YYYY-MM-DD hoặc YYYY/MM/DD
    m_iso = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", s)
    if m_iso:
        y, mo, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        try:
            return date(y, mo, d)
        except ValueError:
            pass

    # Dạng dd/mm/yyyy hoặc dd-mm-yyyy hoặc dd.mm.yyyy (hoặc có HH:MM phía trước/sau)
    m_vn = re.search(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", s)
    if m_vn:
        d, mo, y = int(m_vn.group(1)), int(m_vn.group(2)), int(m_vn.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d)
        except ValueError:
            pass
    return None


def _extract_report_date(texts, filename=""):
    """Tìm ngày báo cáo mới nhất trong tiêu đề biểu mẫu hoặc tên file."""
    candidates = []
    combined = " | ".join([t for t in texts if t] + [filename or ""])
    # Dạng 01-18.11.2026 -> lấy ngày kết thúc 18/11/2026
    for m in re.finditer(r"\d{1,2}\s*[-–]\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", combined):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            candidates.append(date(y, mo, d))
        except ValueError:
            pass
    for m in re.finditer(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", combined):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            candidates.append(date(y, mo, d))
        except ValueError:
            pass
    if candidates:
        return max(candidates)
    return date.today()


def _parse_number(val):
    """Đọc số nguyên/thực từ Excel hoặc chuỗi OCR Việt Nam (dấu chấm ngàn / dấu phẩy)."""
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        if isinstance(val, float) and val != val:  # NaN
            return None
        return float(val)
    s = str(val).strip().replace("\xa0", " ")
    if not s or s in ("--", "-", "N/A"):
        return None
    is_pct = "%" in s
    s = s.replace("%", "").strip()
    # Chuẩn hóa chữ O bị OCR nhầm 0 khi chuỗi toàn số/ký tự ngăn cách
    if re.fullmatch(r"[0-9.,\sOo]+", s):
        s = s.replace("O", "0").replace("o", "0")
    s = re.sub(r"\s+", "", s)

    # Nếu có dạng 1.416 hoặc 34.253 (chấm ngăn ngàn 3 chữ số ở cuối)
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s) and not is_pct:
        s = s.replace(".", "")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+", s) and not is_pct:
        s = s.replace(",", "")
    else:
        s = s.replace(",", ".")

    try:
        num = float(s)
        return num / 100.0 if is_pct else num
    except ValueError:
        return None


def _parse_int(val, default=0):
    num = _parse_number(val)
    if num is None:
        return default
    return int(round(num))


def _format_pct(val):
    if val is None or val == "":
        return ""
    if isinstance(val, str) and "%" in val:
        num = _parse_number(val)
        return f"{num * 100:.1f}%" if num is not None else val.strip()
    num = _parse_number(val)
    if num is None:
        return ""
    pct = num * 100.0 if 0 <= abs(num) <= 1.0001 else num
    return f"{pct:.1f}%"


def _is_stop_or_summary_text(text):
    norm = _norm_vn(text)
    if not norm:
        return False
    norm_alpha = re.sub(r"[:.;]+$", "", norm).strip()
    if norm_alpha in _STOP_ROW_TOKENS:
        return True
    if norm_alpha.startswith("tong cong") or norm_alpha == "tong":
        return True
    if norm_alpha.startswith("thong ke tong hop") or norm_alpha.startswith("1. thong ke") or norm_alpha.startswith("2. thong ke"):
        return True
    return False


def _is_province_or_total_unit(text):
    norm = _norm_vn(text)
    if not norm:
        return True
    if norm in _PROVINCE_TOTAL_TOKENS:
        return True
    if norm.startswith("tong ") or norm.startswith("tinh tuyen quang") or norm.startswith("toan tinh"):
        return True
    return False


def build_unit_matcher():
    """Tạo bộ đối sánh tên đơn vị nhanh từ bảng Unit (ưu tiên Công an Xã/Phường cho hồ sơ CSDLQG)."""
    units = Unit.query.filter(Unit.is_active.is_(True)).all()
    by_exact = {}
    by_geo_key = {}

    for u in units:
        code = (u.code or "").strip()
        name = (u.name or "").strip()
        if not name and not code:
            continue
        if code:
            by_exact[code.lower()] = u
        if name:
            by_exact[_norm_vn(name)] = u
        geo = extract_unit_key(name or code)
        if geo:
            by_geo_key.setdefault(geo, []).append(u)

    def resolve(raw_unit_name):
        raw = _cell_str(raw_unit_name)
        if not raw:
            return {"unit_area": "", "unit_code": "", "unit_key": "", "unit_label": "", "matched": False}
        norm = _norm_vn(raw)
        if norm in by_exact:
            u = by_exact[norm]
            return {
                "unit_area": raw,
                "unit_code": u.code,
                "unit_key": extract_unit_key(u.name or u.code),
                "unit_label": u.name,
                "matched": True,
            }
        geo = extract_unit_key(raw)
        candidates = by_geo_key.get(geo, []) if geo else []
        if candidates:
            prefer_ubnd = "ubnd" in norm
            chosen = None
            for cand in candidates:
                c_code = (cand.code or "").lower()
                c_norm = _norm_vn(cand.name or "")
                if prefer_ubnd and ("ubnd" in c_code or "ubnd" in c_norm):
                    chosen = cand
                    break
                if not prefer_ubnd and (c_code.startswith("cax_") or "cong an" in c_norm):
                    chosen = cand
                    break
            chosen = chosen or candidates[0]
            return {
                "unit_area": raw,
                "unit_code": chosen.code,
                "unit_key": extract_unit_key(chosen.name or raw) or geo,
                "unit_label": chosen.name,
                "matched": True,
            }
        # Fallback fuzzy suffix match (vd OCR thiếu chữ "Xã"/"Phường")
        if geo and len(geo) >= 4:
            for gkey, cand_list in by_geo_key.items():
                if gkey.endswith(geo) or geo.endswith(gkey):
                    chosen = next(
                        (c for c in cand_list if (c.code or "").lower().startswith("cax_") or "cong an" in _norm_vn(c.name or "")),
                        cand_list[0],
                    )
                    return {
                        "unit_area": raw,
                        "unit_code": chosen.code,
                        "unit_key": extract_unit_key(chosen.name or raw),
                        "unit_label": chosen.name,
                        "matched": True,
                    }
        return {
            "unit_area": raw,
            "unit_code": "",
            "unit_key": geo,
            "unit_label": raw,
            "matched": False,
        }

    return resolve


def get_user_dossier_identity(user):
    """Lấy tập định danh đơn vị chuẩn của user để phân quyền xem và tích hoàn thành."""
    if not user:
        return {"unit_code": "", "unit_key": "", "unit_name": "", "area_variants": set()}

    unit_obj = getattr(user, "unit", None)
    raw_code = (getattr(unit_obj, "code", None) or getattr(user, "unit_key", None) or "").strip()
    raw_name = (getattr(unit_obj, "name", None) or "").strip()

    raw_area = (getattr(user, "unit_area", None) or "").strip()
    if raw_area.lower().startswith("category_item:"):
        resolved_area = resolve_category_display(raw_area, [], fallback_label="").get("display_name", "")
        if not resolved_area or resolved_area.lower().startswith("category_item:"):
            from models import CategoryItem, db
            try:
                cid = int(raw_area.split(":", 1)[1])
                cat = db.session.get(CategoryItem, cid)
                resolved_area = (cat.name or "").strip() if cat else ""
            except Exception:
                resolved_area = ""
        area_label = resolved_area
    else:
        area_label = raw_area

    unit_name = raw_name or area_label or getattr(user, "fullname", "") or getattr(user, "username", "")
    geo_key = extract_unit_key(raw_name or area_label or raw_code)
    variants = {v for v in (raw_name, area_label, raw_area, raw_code) if v}
    if raw_name:
        stripped = re.sub(r"^(?:công an|ubnd)\s+", "", raw_name, flags=re.IGNORECASE).strip()
        if stripped:
            variants.add(stripped)
    return {
        "unit_code": raw_code,
        "unit_key": geo_key,
        "unit_name": unit_name,
        "area_variants": variants,
    }


def _extract_sheet_col_widths(ws, max_col=None):
    """Đọc độ rộng cột thực tế (đơn vị ký tự Excel) từ ws.column_dimensions."""
    max_c = min(max_col or ws.max_column or 0, 60)
    widths = []
    for c in range(1, max_c + 1):
        cd = ws.column_dimensions.get(get_column_letter(c))
        w = getattr(cd, "width", None) if cd else None
        try:
            num_w = float(w) if w is not None else None
        except (TypeError, ValueError):
            num_w = None
        widths.append(round(num_w, 2) if (num_w and num_w > 0) else None)
    return widths


def _sheet_to_grid(ws):
    """Đọc worksheet openpyxl thành ma trận 2D có giải merged cells ở vùng tiêu đề."""
    max_r = min(ws.max_row or 0, 2000)
    max_c = min(ws.max_column or 0, 60)
    grid = []
    for r in range(1, max_r + 1):
        row_vals = []
        for c in range(1, max_c + 1):
            row_vals.append(_cell_str(ws.cell(r, c).value))
        grid.append(row_vals)

    # Propagate merged cell values ở vùng đầu bảng (20 dòng đầu) để tách header 2 tầng chính xác
    for m_range in list(ws.merged_cells.ranges):
        if m_range.min_row > 20 or m_range.min_row > max_r:
            continue
        top_val = _cell_str(ws.cell(m_range.min_row, m_range.min_col).value)
        if not top_val:
            continue
        for r in range(m_range.min_row, min(m_range.max_row, max_r) + 1):
            for c in range(m_range.min_col, min(m_range.max_col, max_c) + 1):
                if not grid[r - 1][c - 1]:
                    grid[r - 1][c - 1] = top_val

    # Cắt bỏ dòng trống hoàn toàn ở cuối & cột trống hoàn toàn bên phải
    while grid and not any(grid[-1]):
        grid.pop()
    return grid


def _text_to_grid(raw_text):
    """Chuyển CSV / TSV / văn bản bảng (Zalo/Excel paste) thành ma trận 2D."""
    text = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []

    sample = "\n".join(lines[:15])
    if "\t" in sample:
        reader = csv.reader(io.StringIO(text), delimiter="\t")
        return [[c.strip() for c in row] for row in reader if any(c.strip() for c in row)]

    pipe_count = sum(1 for ln in lines[:10] if ln.count("|") >= 2)
    if pipe_count >= 2:
        grid = []
        for ln in lines:
            stripped = ln.strip().strip("|")
            if re.fullmatch(r"[-:\s|]+", stripped):
                continue
            row = [c.strip() for c in stripped.split("|")]
            if any(row):
                grid.append(row)
        return grid

    semicolon_count = sum(ln.count(";") for ln in lines[:10])
    comma_count = sum(ln.count(",") for ln in lines[:10])
    if semicolon_count > 0 or comma_count >= 2 * min(len(lines), 5):
        delim = ";" if semicolon_count > comma_count else ","
        reader = csv.reader(io.StringIO(text), delimiter=delim)
        return [[c.strip() for c in row] for row in reader if any(c.strip() for c in row)]

    # Fallback tách theo >=2 khoảng trắng liên tiếp (copy bảng thẳng từ PDF/Terminal)
    grid = []
    for ln in lines:
        parts = [p.strip() for p in re.split(r"\s{2,}", ln.strip()) if p.strip()]
        if parts:
            grid.append(parts)
    return grid


def _cluster_ocr_boxes_to_grid(boxes):
    """Chuyển danh sách box {text, x, y, w, h} (tọa độ top-down 0..1) thành bảng 2D."""
    if not boxes:
        return []
    heights = sorted([b["h"] for b in boxes if b.get("h", 0) > 0])
    med_h = heights[len(heights) // 2] if heights else 0.02
    row_tol = max(med_h * 0.6, 0.008)

    sorted_boxes = sorted(boxes, key=lambda b: (b["y"] + b["h"] / 2.0, b["x"]))
    row_groups = []
    for box in sorted_boxes:
        cy = box["y"] + box["h"] / 2.0
        placed = False
        for grp in row_groups:
            if abs(cy - grp["cy"]) <= row_tol:
                grp["items"].append(box)
                n = len(grp["items"])
                grp["cy"] = (grp["cy"] * (n - 1) + cy) / n
                placed = True
                break
        if not placed:
            row_groups.append({"cy": cy, "items": [box]})

    # Gom các đoạn chữ gần nhau trên cùng dòng (cùng 1 ô)
    merged_rows = []
    for grp in row_groups:
        items = sorted(grp["items"], key=lambda b: b["x"])
        cells = []
        for it in items:
            if cells:
                prev = cells[-1]
                gap = it["x"] - (prev["x"] + prev["w"])
                if gap <= max(med_h * 0.9, 0.012):
                    prev["text"] = f"{prev['text']} {it['text']}".strip()
                    prev["w"] = max(prev["x"] + prev["w"], it["x"] + it["w"]) - prev["x"]
                    continue
            cells.append(dict(it))
        merged_rows.append(cells)

    # Tìm các hàng giống bảng (có >= 3 ô) để định vị trục cột theo X-interval overlap
    table_rows = [r for r in merged_rows if len(r) >= 3]
    if not table_rows:
        return [[c["text"] for c in r] for r in merged_rows]

    # Sắp xếp ưu tiên các ô ngắn (thường là dữ liệu số/mã) hoặc phân cụm theo giao nhau khoảng X
    all_cells = [c for r in table_rows for c in r]
    # Xây dựng các cột từ những hàng có nhiều ô nhất (đại diện tốt nhất cho số cột thật)
    max_cells_row = max(len(r) for r in table_rows)
    anchor_rows = [r for r in table_rows if len(r) >= max(3, max_cells_row - 1)]
    col_intervals = []
    for r in anchor_rows:
        for idx, c in enumerate(r):
            c_l, c_r = c["x"], c["x"] + max(c["w"], 0.015)
            # Tìm cột đã có khớp nhất theo overlap hoặc khoảng cách nhỏ hơn col_tol
            best_col = None
            best_score = -1e9
            for ci, col in enumerate(col_intervals):
                overlap = min(c_r, col["r"]) - max(c_l, col["l"])
                center_dist = abs((c_l + c_r) / 2.0 - (col["l"] + col["r"]) / 2.0)
                if overlap > 0 or center_dist <= 0.025:
                    score = overlap - center_dist * 0.2
                    if score > best_score:
                        best_score = score
                        best_col = ci
            if best_col is None:
                col_intervals.append({"l": c_l, "r": c_r})
            else:
                # Chỉ mở rộng nhẹ để giữ ranh giới cột sạch
                col_intervals[best_col]["l"] = min(col_intervals[best_col]["l"], c_l)
                col_intervals[best_col]["r"] = max(col_intervals[best_col]["r"], c_r)

    col_intervals.sort(key=lambda iv: (iv["l"] + iv["r"]) / 2.0)
    col_centers = [(iv["l"] + iv["r"]) / 2.0 for iv in col_intervals]
    n_cols = len(col_intervals)

    def _match_col(cell_box):
        c_l, c_r = cell_box["x"], cell_box["x"] + max(cell_box["w"], 0.01)
        c_mid = (c_l + c_r) / 2.0
        best_i = 0
        best_metric = -1e9
        for idx, iv in enumerate(col_intervals):
            overlap = min(c_r, iv["r"]) - max(c_l, iv["l"])
            dist = abs(col_centers[idx] - c_mid)
            metric = (overlap * 5.0 if overlap > 0 else 0.0) - dist
            if metric > best_metric:
                best_metric = metric
                best_i = idx
        return best_i

    grid = []
    for r in merged_rows:
        if len(r) == 1 and n_cols >= 3:
            grid.append([r[0]["text"]] + [""] * (n_cols - 1))
            continue
        row_out = [""] * n_cols
        for c in r:
            best_idx = _match_col(c)
            row_out[best_idx] = (f"{row_out[best_idx]} {c['text']}".strip()) if row_out[best_idx] else c["text"]
        if any(row_out):
            grid.append(row_out)

    # Cắt bỏ các cột hoàn toàn rỗng trên mọi hàng & tách header gộp "STT Đơn vị" nếu cột trái rỗng
    if grid:
        non_empty_cols = [c_i for c_i in range(n_cols) if any(c_i < len(r) and r[c_i] for r in grid)]
        if non_empty_cols:
            grid = [[r[c_i] if c_i < len(r) else "" for c_i in non_empty_cols] for r in grid]
        for r_i, row in enumerate(grid[:6]):
            for c_i in range(1, len(row)):
                if not grid[r_i][c_i - 1] and re.match(r"^STT\s+(.+)$", row[c_i], flags=re.IGNORECASE):
                    m = re.match(r"^(STT)\s+(.+)$", row[c_i], flags=re.IGNORECASE)
                    grid[r_i][c_i - 1] = m.group(1)
                    grid[r_i][c_i] = m.group(2).strip()
    return grid


def _ocr_via_gemini_vision(file_bytes, ext, api_key):
    """Nhận diện bảng từ ảnh bằng Gemini Vision REST API (không cần SDK ngoài)."""
    import requests

    mime_map = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime_type = mime_map.get(ext.lower(), "image/png")
    b64_img = base64.b64encode(file_bytes).decode("ascii")
    prompt = (
        "Hãy trích xuất CHÍNH XÁC toàn bộ bảng số liệu/hồ sơ trong ảnh thành JSON hợp lệ.\n"
        "Trả về DUY NHẤT một JSON object theo mẫu:\n"
        "{\n"
        '  "title": "tiêu đề phía trên bảng nếu có",\n'
        '  "report_date": "dd/mm/yyyy nếu thấy ngày số liệu",\n'
        '  "headers": ["tên cột 1", "tên cột 2", ...],\n'
        '  "subheaders": ["tên cột con tầng 2 nếu bảng có 2 tầng tiêu đề, nếu không để []"],\n'
        '  "rows": [["giá trị ô 1", "giá trị ô 2", ...]]\n'
        "}\n"
        "Giữ nguyên đầy đủ dấu tiếng Việt, số hồ sơ (vd G01...), tên đơn vị (Phường/Xã...), và các con số. "
        "Không bỏ sót dòng dữ liệu. Nếu có 2 tầng tiêu đề, giữ nguyên độ dài khớp số cột với từng dòng trong rows."
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": b64_img}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    models_to_try = [os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash"), "gemini-2.0-flash"]
    last_err = None
    for model_name in models_to_try:
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
                params={"key": api_key},
                json=payload,
                timeout=35,
            )
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}: {resp.text[:180]}"
                continue
            data = resp.json()
            raw_txt = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            if raw_txt.startswith("```"):
                raw_txt = re.sub(r"^```[a-zA-Z]*\n?", "", raw_txt)
                raw_txt = re.sub(r"\n?```$", "", raw_txt).strip()
            parsed = json.loads(raw_txt)
            grid = []
            title = _cell_str(parsed.get("title"))
            rep_date = _cell_str(parsed.get("report_date"))
            headers = [_cell_str(h) for h in (parsed.get("headers") or [])]
            subheaders = [_cell_str(h) for h in (parsed.get("subheaders") or [])]
            rows = parsed.get("rows") or []
            ncols = max([len(headers), len(subheaders)] + [len(r) for r in rows] + [1])
            if title or rep_date:
                title_row = [f"{title} {rep_date}".strip()] + [""] * (ncols - 1)
                grid.append(title_row)
            if headers:
                grid.append(headers + [""] * (ncols - len(headers)))
            if any(subheaders):
                grid.append(subheaders + [""] * (ncols - len(subheaders)))
            for r in rows:
                row_vals = [_cell_str(c) for c in (r if isinstance(r, list) else [])]
                if any(row_vals):
                    grid.append(row_vals + [""] * (ncols - len(row_vals)))
            if grid:
                return grid, "gemini_vision", None
        except Exception as exc:
            last_err = str(exc)
    return None, "gemini_vision", last_err


def _ocr_via_apple_vision(img_path):
    """Dùng macOS Vision framework nhận diện chữ tiếng Việt + tọa độ dòng/cột."""
    swift_code = r'''
import Foundation
import Vision
import AppKit

let args = CommandLine.arguments
guard args.count >= 2 else { exit(1) }
let url = URL(fileURLWithPath: args[1])
guard let image = NSImage(contentsOf: url),
      let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    exit(2)
}
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = true
req.recognitionLanguages = ["vi-VN", "en-US"]
let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
try handler.perform([req])
var output: [[String: Any]] = []
for obs in req.results ?? [] {
    guard let top = obs.topCandidates(1).first else { continue }
    let box = obs.boundingBox
    output.append([
        "text": top.string,
        "x": box.origin.x,
        "y": 1.0 - (box.origin.y + box.size.height),
        "w": box.size.width,
        "h": box.size.height
    ])
}
let data = try JSONSerialization.data(withJSONObject: output, options: [])
if let str = String(data: data, encoding: .utf8) {
    print(str)
}
'''
    proc = subprocess.run(
        ["/usr/bin/swift", "-", img_path],
        input=swift_code,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(proc.stderr.strip() or "Apple Vision failed")
    boxes = json.loads(proc.stdout.strip())
    return _cluster_ocr_boxes_to_grid(boxes), "apple_vision"


def _ocr_via_tesseract(img_path):
    """Dùng Tesseract CLI TSV để dựng lại tọa độ bảng."""
    tess_bin = shutil.which("tesseract")
    if not tess_bin:
        raise RuntimeError("tesseract not installed")

    langs_proc = subprocess.run([tess_bin, "--list-langs"], capture_output=True, text=True, timeout=5)
    avail = langs_proc.stdout + langs_proc.stderr
    lang = "vie+eng" if "vie" in avail else "eng"

    from PIL import Image
    with Image.open(img_path) as im:
        width, height = im.size or (1000, 1000)

    proc = subprocess.run(
        [tess_bin, img_path, "stdout", "-l", lang, "--psm", "6", "tsv"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "tesseract error")

    boxes = []
    reader = csv.DictReader(io.StringIO(proc.stdout), delimiter="\t")
    for row in reader:
        txt = (row.get("text") or "").strip()
        if not txt:
            continue
        try:
            left = float(row["left"]) / max(width, 1)
            top = float(row["top"]) / max(height, 1)
            w = float(row["width"]) / max(width, 1)
            h = float(row["height"]) / max(height, 1)
        except Exception:
            continue
        boxes.append({"text": txt, "x": left, "y": top, "w": w, "h": h})
    return _cluster_ocr_boxes_to_grid(boxes), f"tesseract:{lang}"


def extract_image_table_grid(file_bytes, ext=".png"):
    """Trích xuất ma trận bảng từ file ảnh bằng công cụ tốt nhất sẵn có."""
    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if api_key:
        grid, engine, err = _ocr_via_gemini_vision(file_bytes, ext, api_key)
        if grid:
            return grid, engine, None

    suffix = ext if ext.startswith(".") else f".{ext}"
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as fh:
            fh.write(file_bytes)

        if sys.platform == "darwin" and os.path.exists("/usr/bin/swift"):
            try:
                grid, engine = _ocr_via_apple_vision(tmp_path)
                if grid:
                    return grid, engine, None
            except Exception:
                pass

        if shutil.which("tesseract"):
            try:
                grid, engine = _ocr_via_tesseract(tmp_path)
                if grid:
                    return grid, engine, None
            except Exception as exc:
                return [], "ocr_error", f"Lỗi đọc ảnh OCR: {exc}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    return (
        [],
        "ocr_unavailable",
        "Máy chủ chưa bật Gemini AI (GEMINI_API_KEY) hoặc Tesseract OCR. Bạn hãy chụp rõ bảng rồi dán trực tiếp nội dung bảng hoặc tải file .xlsx/.csv.",
    )


def _col_letter_from_index(idx):
    """Chuyển index cột 0-based -> A, B, ..., Z, AA."""
    n = int(idx) + 1
    out = []
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out.append(chr(65 + rem))
    return "".join(reversed(out))


_BANNER_NOISE_PREFIXES = (
    "cong hoa xa hoi",
    "doc lap - tu do",
    "doc lap tu do",
    "bo cong an",
    "cong an tinh",
    "cuc canh sat",
    "phong canh sat",
    "tu ngay",
    "den ngay",
)

_BANNER_TITLE_HINTS = (
    "danh sach",
    "thong ke",
    "bao cao",
    "bieu chi tieu",
    "chi tieu",
    "tam tru",
    "thuong tru",
    "ct10",
    "tich hop",
    "lam sach",
    "ho so",
)

_SUBHEADER_HINTS = (
    "ngay nop",
    "ngay tiep nhan",
    "ngay hen tra",
    "han tra",
    "han giai quyet",
    "tong",
    "hoan thanh",
    "cho tra loi",
    "cho xac nhan",
    "da tich hop",
    "tu choi",
    "ty le",
    "da kich hoat",
    "da duoc cap",
    "da lam sach",
    "con ton",
    "chua xu ly",
    "don vi",
    "dia ban",
    "trang thai",
    "ho ten",
    "so ho so",
    "ma ho so",
    "thu tuc",
)

_DOSSIER_ALL_KEYWORDS = [
    "stt",
    "so ho so",
    "ma ho so",
    "so/ma ho so",
    "ma tiep nhan",
    "so bien nhan",
    "thu tuc",
    "ho va ten",
    "ho ten",
    "cong dan",
    "chu ho",
    "ngay nop",
    "ngay tiep nhan",
    "ngay hen tra",
    "han tra",
    "han giai quyet",
    "han xu ly",
    "tinh dung han",
    "can bo",
    "don vi",
    "dia ban",
    "trang thai",
    "tinh trang",
    "ghi chu",
    "lap phieu",
    "tra loi",
    "qua han",
    "cho xac nhan",
    "da tich hop",
    "dinh danh",
    "ty le",
    "lam sach",
]


def _is_guide_numbering_row(row):
    """Nhận diện hàng đánh số cột kiểu (1) | (2) | (3) hoặc 1 | 2 | 3 dưới dòng tiêu đề."""
    non_empty = [c.strip() for c in (row or []) if c and str(c).strip()]
    if len(non_empty) < 3:
        return False
    guide_hits = sum(
        1
        for c in non_empty
        if re.fullmatch(r"\(?\s*\d{1,2}\s*\)?", c) or re.fullmatch(r"[A-Za-z]", c)
    )
    return guide_hits / len(non_empty) >= 0.7


def _looks_like_data_row(row):
    """Kiểm tra một hàng có mang dấu hiệu hàng dữ liệu (số HS G01., ngày dd/mm/yyyy, số ĐT/CCCD)."""
    joined = " | ".join(_cell_str(c) for c in (row or []) if _cell_str(c))
    if not joined:
        return False
    if re.search(r"\b[A-Z]\d{2}[A-Z0-9.\-/]{4,}\b", joined):
        return True
    if re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", joined):
        return True
    return False


def _pick_table_title(banner_lines):
    """Chọn nhãn tiêu đề chính có ý nghĩa nhất trong các dòng banner phía trên bảng."""
    clean_lines = []
    for row in banner_lines:
        parts = [c for c in row if c]
        if not parts:
            continue
        text = " ".join(dict.fromkeys(parts)).strip()
        norm = _norm_vn(text)
        if not norm or any(norm.startswith(p) for p in _BANNER_NOISE_PREFIXES):
            continue
        clean_lines.append((text, norm))
    for text, norm in clean_lines:
        if any(h in norm for h in _BANNER_TITLE_HINTS):
            return text[:240]
    if clean_lines:
        return max(clean_lines, key=lambda x: len(x[0]))[0][:240]
    return ""


def _extract_table_structure(grid, keywords, max_scan=25, step_up_if_merged=False):
    """Quét tìm vị trí tiêu đề cột, gộp tiêu đề 2 tầng (nếu có), bỏ qua dòng đánh số cột và trích nhãn tiêu đề."""
    if not grid:
        return 0, 0, [], [], ""

    best_idx = 0
    best_score = -1e9
    scan_limit = min(len(grid), max_scan)
    for i in range(scan_limit):
        row = grid[i]
        non_empty = [c for c in row if _cell_str(c)]
        if len(non_empty) < 2:
            continue
        norm_cells = [_norm_vn(c) for c in non_empty]
        joined = " | ".join(norm_cells)
        kw_hits = sum(1 for kw in keywords if kw in joined)
        # Ưu tiên hàng có nhiều tiêu đề ngắn (không phải hàng dữ liệu G01 / ngày)
        short_headers = sum(1 for nc in norm_cells if len(nc) <= 45)
        score = kw_hits * 3.0 + min(len(non_empty), 10) * 0.25 + short_headers * 0.1
        if _looks_like_data_row(row):
            score -= 8.0
        if _is_guide_numbering_row(row):
            score -= 10.0
        if kw_hits > 0 and len(non_empty) >= 3 and score > best_score:
            best_score = score
            best_idx = i

    if best_score <= 0:
        # Fallback chọn hàng đầu tiên có >=3 ô chữ giống tiêu đề
        for i in range(scan_limit):
            non_empty = [c for c in grid[i] if _cell_str(c)]
            if len(non_empty) >= 3 and not _looks_like_data_row(grid[i]) and not _is_guide_numbering_row(grid[i]):
                best_idx = i
                break

    if step_up_if_merged and best_idx > 0:
        prev_row = grid[best_idx - 1]
        prev_norm = " | ".join(_norm_vn(c) for c in prev_row if c)
        curr_norm = " | ".join(_norm_vn(c) for c in grid[best_idx] if c)
        if any(k in prev_norm for k in ("stt", "don vi", "dia ban", "ho so")) and any(
            k in curr_norm
            for k in ("cho xac nhan", "da tich hop", "ty le", "hoan thanh", "cho tra loi", "da kich hoat", "ngay nop", "hen tra")
        ):
            best_idx -= 1

    tier1 = grid[best_idx] if best_idx < len(grid) else []
    next_row = grid[best_idx + 1] if best_idx + 1 < len(grid) else []

    has_tier2 = False
    if next_row and not _looks_like_data_row(next_row) and not _is_guide_numbering_row(next_row):
        next_non_empty = [c for c in next_row if _cell_str(c)]
        next_joined = " | ".join(_norm_vn(c) for c in next_non_empty)
        sub_hits = sum(1 for tok in _SUBHEADER_HINTS if tok in next_joined)
        # Kiểm tra header tầng 1 có ô lặp (do merge ngang propagate) hay nhiều sub-header
        has_horizontal_repeats = any(
            _cell_str(tier1[k]) and k + 1 < len(tier1) and _cell_str(tier1[k]) == _cell_str(tier1[k + 1])
            for k in range(len(tier1) - 1)
        )
        if next_non_empty and (sub_hits >= 2 or (has_horizontal_repeats and len(next_non_empty) >= 2)):
            has_tier2 = True

    tier2 = next_row if has_tier2 else []
    data_start = best_idx + (2 if has_tier2 else 1)
    while data_start < len(grid) and (not any(grid[data_start]) or _is_guide_numbering_row(grid[data_start])):
        data_start += 1

    ncols = max([len(tier1), len(tier2)] + [len(r) for r in grid[data_start:data_start + 5]] + [1])
    while ncols > 1 and not any(
        _cell_str(r[ncols - 1] if ncols - 1 < len(r) else "")
        for r in ([tier1, tier2] + grid[data_start:data_start + 5])
        if r
    ):
        ncols -= 1
    raw_tier1 = [_cell_str(tier1[c] if c < len(tier1) else "") for c in range(ncols)]
    raw_tier2 = [_cell_str(tier2[c] if c < len(tier2) else "") for c in range(ncols)] if has_tier2 else []
    raw_header_rows = [raw_tier1, raw_tier2] if has_tier2 and any(raw_tier2) else ([raw_tier1] if any(raw_tier1) else [])

    eff_headers = []
    full_headers = []
    for c_idx in range(ncols):
        h1 = raw_tier1[c_idx]
        h2 = raw_tier2[c_idx] if raw_tier2 else ""
        n1, n2 = _norm_vn(h1), _norm_vn(h2)
        if h2 and n2 != n1:
            eff_headers.append(h2)
            full_headers.append(f"{h1} - {h2}" if h1 else h2)
        else:
            eff_headers.append(h1 or h2)
            full_headers.append(h1 or h2)

    table_title = _pick_table_title(grid[:best_idx])
    return best_idx, data_start, eff_headers, full_headers, table_title


def _extract_raw_header_rows(grid, hdr_idx, data_start, ncols=None):
    """Lấy đúng các dòng tiêu đề gốc từ bảng (không đổi chữ, không thêm bớt cột)."""
    if not grid or hdr_idx >= len(grid):
        return [], []
    tier1 = grid[hdr_idx]
    has_tier2 = (data_start - hdr_idx) >= 2 and hdr_idx + 1 < len(grid)
    tier2 = grid[hdr_idx + 1] if has_tier2 else []
    if ncols is None:
        ncols = max([len(tier1), len(tier2)] + [len(r) for r in grid[data_start:data_start + 5]] + [1])
        while ncols > 1 and not any(
            _cell_str(r[ncols - 1] if ncols - 1 < len(r) else "")
            for r in ([tier1, tier2] + grid[data_start:data_start + 5])
            if r
        ):
            ncols -= 1
    r1 = [_cell_str(tier1[c] if c < len(tier1) else "") for c in range(ncols)]
    rows = [r1]
    if has_tier2:
        r2 = [_cell_str(tier2[c] if c < len(tier2) else "") for c in range(ncols)]
        if any(r2):
            rows.append(r2)
    flat = []
    for c in range(ncols):
        h1 = r1[c]
        h2 = rows[1][c] if len(rows) > 1 else ""
        if h2 and _norm_vn(h2) != _norm_vn(h1):
            flat.append(f"{h1} - {h2}" if h1 and h1 != r1[c - 1] else h2 if not h1 else f"{h1} - {h2}")
            if c > 0 and h1 and h1 == r1[c - 1]:
                flat[-1] = h2
        else:
            flat.append(h1 or h2 or f"Cột {c + 1}")
    return rows, flat


def _find_header_row_idx(grid, keywords, max_scan=25, step_up_if_merged=False):
    hdr_idx, _, _, _, _ = _extract_table_structure(
        grid, keywords, max_scan=max_scan, step_up_if_merged=step_up_if_merged
    )
    return hdr_idx


def detect_dossier_category(grid, filename="", sheet_name="", override_tab=""):
    """Tự động nhận diện 1 trong 5 phân hệ biểu mẫu + khac (quét nhãn tiêu đề & cấu trúc cột đến dòng 25)."""
    if override_tab and override_tab in get_valid_dossier_tabs():
        return override_tab

    hdr_idx, data_start, eff_headers, full_headers, table_title = _extract_table_structure(
        grid, _DOSSIER_ALL_KEYWORDS, max_scan=25
    )
    banner_rows_text = " ".join(" ".join(r) for r in grid[: max(hdr_idx, 1)])
    meta_text = _norm_vn(" ".join([filename or "", sheet_name or "", table_title or "", banner_rows_text]))
    header_joined = _norm_vn(" | ".join(full_headers + eff_headers))
    sample_data_text = _norm_vn(" ".join(" ".join(r) for r in grid[data_start : data_start + 8]))
    combined_top = f"{meta_text} | {header_joined}".strip()

    # 1. Phiếu xác minh CT10
    if (
        "ct10" in combined_top
        or ("lap phieu xac minh" in header_joined and "tra loi xac minh" in header_joined)
        or ("hoan thanh lap phieu" in header_joined and "qua han chua tra loi" in header_joined)
    ):
        return "ct10"

    # 2. Nhận diện Tạm trú vs Thường trú theo nhãn tiêu đề + cấu trúc cột thực tế
    has_dossier_id = bool(
        re.search(r"\b(?:so ho so|ma ho so|so/ma ho so|ma tiep nhan|so bien nhan|so hs|ma hs)\b", header_joined)
    ) or "g01." in sample_data_text or "g01." in combined_top

    has_tam_tru_title = bool(re.search(r"\btam tru\b", meta_text) and not re.search(r"\bthuong tru\b", meta_text))
    has_thuong_tru_title = bool(re.search(r"\bthuong tru\b", meta_text) and not re.search(r"\btam tru\b", meta_text))
    has_hen_tra_col = bool(
        re.search(r"\b(?:ngay hen tra|hen tra|han tra ket qua|han tra|han giai quyet|han xu ly|tinh dung han)\b", header_joined)
    )
    has_ngay_nop_col = bool(re.search(r"\b(?:ngay nop|thoi gian nop|ngay gui)\b", header_joined))
    has_dia_ban_col = bool(re.search(r"\bdia ban tiep nhan\b", header_joined))
    has_don_vi_xl_col = bool(re.search(r"\b(?:don vi xu ly|don vi giai quyet)\b", header_joined))

    if has_tam_tru_title:
        return "tam_tru"
    if has_thuong_tru_title and not has_hen_tra_col:
        return "thuong_tru"

    if has_dossier_id or any(k in header_joined for k in ["thu tuc", "ngay tiep nhan", "ngay nop"]):
        if has_hen_tra_col or (has_ngay_nop_col and has_don_vi_xl_col) or "tam tru" in sample_data_text:
            return "tam_tru"
        if has_dia_ban_col or "thuong tru" in sample_data_text:
            return "thuong_tru"
        if has_ngay_nop_col and not has_dia_ban_col:
            return "tam_tru"

    # 3. Làm sạch dữ liệu dân cư
    if any(
        tok in combined_top
        for tok in [
            "lam sach du lieu",
            "lam sach dan cu",
            "lam sach",
            "lech thong tin",
            "sai cau truc",
            "doi soat du lieu dan cu",
        ]
    ):
        return "lam_sach"

    # 4. Tích hợp giấy tờ / ĐDĐT
    if any(
        tok in combined_top
        for tok in [
            "tich hop giay to",
            "kich hoat dinh danh",
            "dinh danh dien tu",
            "dddt muc 2",
            "giay khai sinh",
            "so suc khoe",
            "thue bao di dong",
            "van bang chung chi",
            "qsd dat",
            "ly lich tu phap",
            "ho chieu",
            "giay phep lai xe",
            "giay dang ky xe",
            "cho xac nhan",
            "da tich hop",
            "tu choi xac nhan",
        ]
    ):
        return "tich_hop"

    if has_dia_ban_col:
        return "thuong_tru"
    if has_hen_tra_col or (has_ngay_nop_col and ("don vi" in header_joined or "trang thai" in header_joined)):
        return "tam_tru"

    return "khac"


def _map_columns(headers, spec_map, extra_full_headers=None):
    """Ánh xạ tên cột -> chỉ số (ưu tiên khớp chính xác toàn chuỗi trước, rồi mới khớp cụm dài -> ngắn)."""
    resolved = {}
    used_indices = set()
    primary_norms = [_norm_vn(h) for h in headers]
    full_norms = [_norm_vn(h) for h in (extra_full_headers or headers)]

    for field, patterns in spec_map:
        found_idx = None
        # Vòng 1: Khớp chính xác tiêu đề cột
        for pat in patterns:
            for idx, (nh, fh) in enumerate(zip(primary_norms, full_norms)):
                if idx in used_indices:
                    continue
                if nh == pat or fh == pat:
                    found_idx = idx
                    break
            if found_idx is not None:
                break
        # Vòng 2: Khớp từ khóa con (ưu tiên cụm dài nhất)
        if found_idx is None:
            for pat in sorted(patterns, key=len, reverse=True):
                for idx, (nh, fh) in enumerate(zip(primary_norms, full_norms)):
                    if idx in used_indices:
                        continue
                    if (nh and pat in nh) or (fh and pat in fh):
                        found_idx = idx
                        break
                if found_idx is not None:
                    break
        if found_idx is not None:
            resolved[field] = found_idx
            used_indices.add(found_idx)
    return resolved


def _infer_missing_dossier_columns(grid, data_start, col_map, resolve_unit):
    """Bổ sung cột còn thiếu bằng cách quét mẫu dữ liệu nếu tiêu đề Excel viết tắt/khác lạ."""
    sample_rows = [r for r in grid[data_start : data_start + 12] if any(r) and not _is_stop_or_summary_text(_col_val(r, 0))]
    if not sample_rows:
        return col_map
    used = set(col_map.values())
    ncols = max((len(r) for r in sample_rows), default=0)

    if "so_ho_so" not in col_map:
        best_c, best_hits = None, 0
        for c in range(ncols):
            if c in used or c == col_map.get("stt"):
                continue
            hits = sum(
                1 for r in sample_rows
                if re.search(r"\b[A-Z]\d{2}[A-Z0-9.\-/]{4,}\b", _col_val(r, c))
            )
            if hits > best_hits:
                best_hits = hits
                best_c = c
        if best_c is not None and best_hits >= 1:
            col_map["so_ho_so"] = best_c
            used.add(best_c)

    if "unit_name" not in col_map:
        best_c, best_hits = None, 0
        for c in range(ncols):
            if c in used or c == col_map.get("stt"):
                continue
            hits = 0
            for r in sample_rows:
                val = _col_val(r, c)
                if not val:
                    continue
                if resolve_unit(val).get("matched") or any(
                    tok in _norm_vn(val) for tok in ("phuong ", "xa ", "thi tran ", "cong an ", "ubnd ")
                ):
                    hits += 1
            if hits > best_hits:
                best_hits = hits
                best_c = c
        if best_c is not None and best_hits >= 1:
            col_map["unit_name"] = best_c
            used.add(best_c)

    return col_map


_FIELD_VI_LABELS = {
    "stt": "STT",
    "so_ho_so": "Số hồ sơ",
    "thu_tuc": "Thủ tục",
    "cong_dan": "Công dân / Chủ hộ",
    "ngay_nop": "Ngày nộp",
    "ngay_tiep_nhan": "Ngày tiếp nhận",
    "han_tra": "Ngày hẹn trả",
    "tinh_dung_han": "Tính đúng hạn",
    "can_bo": "Cán bộ tiếp nhận",
    "unit_name": "Đơn vị xử lý",
    "trang_thai_nguon": "Trạng thái",
}


def _build_column_mapping_summary(headers, col_map):
    """Tạo danh sách ánh xạ nhãn tiêu đề Excel -> trường dữ liệu chuẩn để hiển thị kiểm chứng."""
    summary = []
    for field, c_idx in sorted(col_map.items(), key=lambda kv: kv[1]):
        raw_hdr = _cell_str(headers[c_idx] if c_idx < len(headers) else "") or f"Cột {_col_letter_from_index(c_idx)}"
        summary.append({
            "field": field,
            "field_label": _FIELD_VI_LABELS.get(field, field),
            "col_index": c_idx,
            "col_letter": _col_letter_from_index(c_idx),
            "excel_header": raw_hdr,
        })
    return summary


def _collect_custom_fields(row, headers, mapped_indices):
    """Lưu giữ các cột bổ sung ngoài bộ trường cố định (vd Họ tên, CCCD, Ghi chú...) kèm đúng nhãn tiêu đề."""
    extras = []
    for idx, hdr in enumerate(headers):
        if idx in mapped_indices:
            continue
        lbl = _cell_str(hdr)
        val = _col_val(row, idx)
        if lbl and val:
            extras.append({"label": lbl, "value": val})
    return extras


def _estimate_column_char_width(col_idx, header_text, grid, data_start, field_name=None):
    """Ước lượng độ rộng tự nhiên khi file thiếu metadata column_dimensions (CSV/ảnh/sheet mặc định)."""
    hdr_len = len(_cell_str(header_text))
    lengths = [hdr_len]
    for row in grid[data_start : data_start + 80]:
        if col_idx < len(row):
            val = _cell_str(row[col_idx])
            if val:
                lengths.append(len(val))
    lengths.sort()
    p85 = lengths[int(len(lengths) * 0.85)] if lengths else hdr_len
    est = max(hdr_len + 3.0, p85 + 4.0)
    if field_name == "stt":
        return min(max(est, 6.0), 12.0)
    if field_name in ("ngay_nop", "ngay_tiep_nhan", "han_tra", "tinh_dung_han"):
        return min(max(est, 16.0), 22.0)
    if field_name == "so_ho_so":
        return min(max(est, 26.0), 34.0)
    if field_name == "thu_tuc":
        return min(max(est, 42.0), 76.0)
    return min(max(est, 12.0), 42.0)


def _compute_column_width_metrics(grid, data_start, exact_headers, col_map=None, excel_col_widths=None):
    """Tính danh sách độ rộng gốc và tỉ lệ % các cột để UI dựng lại bảng cân đối theo file Excel."""
    ncols = len(exact_headers or [])
    if ncols <= 0:
        return [], []
    col_to_field = {c_idx: fname for fname, c_idx in (col_map or {}).items()}
    raw_widths = []
    for c_idx in range(ncols):
        w = excel_col_widths[c_idx] if (excel_col_widths and c_idx < len(excel_col_widths)) else None
        if isinstance(w, (int, float)) and w > 0:
            raw_widths.append(round(float(w), 2))
        else:
            raw_widths.append(
                round(
                    _estimate_column_char_width(
                        c_idx, exact_headers[c_idx], grid, data_start, col_to_field.get(c_idx)
                    ),
                    2,
                )
            )
    total = sum(raw_widths) or 1.0
    ratios = [round(w * 100.0 / total, 2) for w in raw_widths]
    return raw_widths, ratios


def _attach_scan_layout_meta(
    scan_meta,
    grid,
    data_start,
    raw_hdr_rows,
    exact_hdr_labels,
    eff_headers,
    col_map,
    table_title,
):
    """Đồng bộ nhãn tiêu đề bảng, ánh xạ cột và tỉ lệ độ rộng Excel vào scan_meta."""
    excel_widths = scan_meta.get("excel_col_widths") if isinstance(scan_meta, dict) else None
    col_widths, col_ratios = _compute_column_width_metrics(
        grid,
        data_start,
        exact_hdr_labels or eff_headers,
        col_map=col_map,
        excel_col_widths=excel_widths,
    )
    if isinstance(scan_meta, dict):
        scan_meta["table_title"] = table_title or _cell_str(grid[0][0] if grid and grid[0] else "")
        scan_meta["raw_headers"] = raw_hdr_rows
        scan_meta["exact_headers"] = exact_hdr_labels
        scan_meta["detected_headers"] = [h for h in exact_hdr_labels if h]
        scan_meta["column_mapping"] = _build_column_mapping_summary(exact_hdr_labels or eff_headers, col_map)
        scan_meta["col_widths"] = col_widths
        scan_meta["col_ratios"] = col_ratios
    return col_widths, col_ratios


def _col_val(row, idx):
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    return _cell_str(row[idx])


def _is_done_source_status(status_text):
    norm = _norm_vn(status_text)
    return any(tok in norm for tok in ["da tra ket qua", "da giai quyet", "hoan thanh", "da xong"])


def _parse_tam_tru_grid(grid, filename, report_date, resolve_unit, scan_meta=None):
    hdr_idx, data_start, eff_headers, full_headers, table_title = _extract_table_structure(
        grid,
        ["stt", "so ho so", "ma ho so", "thu tuc", "ngay nop", "ngay tiep nhan", "ngay hen tra", "han tra", "don vi", "trang thai"],
        max_scan=25,
    )
    col_map = _map_columns(
        eff_headers,
        [
            ("stt", ["stt", "tt", "so tt"]),
            ("so_ho_so", ["so ho so", "ma ho so", "so/ma ho so", "ma tiep nhan", "so bien nhan", "so hs", "ma hs"]),
            ("thu_tuc", ["thu tuc", "ten thu tuc", "loai ho so", "noi dung"]),
            ("cong_dan", ["ho va ten", "ho ten", "cong dan", "nguoi nop", "chu ho"]),
            ("ngay_nop", ["ngay nop ho so", "ngay nop", "thoi gian nop", "ngay gui", "ngay dang ky"]),
            ("ngay_tiep_nhan", ["ngay tiep nhan", "ngay nhan", "thoi gian tiep nhan", "ngay vao so"]),
            ("han_tra", ["ngay hen tra ket qua", "ngay hen tra", "han tra ket qua", "han tra", "hen tra", "ngay tra ket qua", "han giai quyet", "han xu ly", "thoi han"]),
            ("tinh_dung_han", ["tinh dung han", "tinh trang han", "muc do"]),
            ("can_bo", ["can bo tiep nhan", "can bo xu ly", "nguoi tiep nhan", "can bo"]),
            ("unit_name", ["don vi xu ly", "don vi tiep nhan", "don vi giai quyet", "dia ban tiep nhan", "don vi", "dia ban", "co quan"]),
            ("trang_thai_nguon", ["trang thai ho so", "trang thai", "tinh trang", "ket qua"]),
        ],
        extra_full_headers=full_headers,
    )
    col_map = _infer_missing_dossier_columns(grid, data_start, col_map, resolve_unit)
    if not col_map and len(eff_headers) >= 9:
        col_map = {
            "stt": 0, "so_ho_so": 1, "thu_tuc": 2, "ngay_nop": 3, "ngay_tiep_nhan": 4,
            "han_tra": 5, "tinh_dung_han": 6, "can_bo": 7, "unit_name": 8, "trang_thai_nguon": 9,
        }

    raw_hdr_rows, exact_hdr_labels = _extract_raw_header_rows(grid, hdr_idx, data_start, ncols=len(eff_headers))
    col_widths, col_ratios = _attach_scan_layout_meta(
        scan_meta,
        grid,
        data_start,
        raw_hdr_rows,
        exact_hdr_labels,
        eff_headers,
        col_map,
        table_title,
    )

    mapped_indices = set(col_map.values())
    stt_idx = col_map.get("stt", 0)
    so_idx = col_map.get("so_ho_so")
    table_ncols = len(exact_hdr_labels) if exact_hdr_labels else len(eff_headers)

    records = []
    for idx_r, row in enumerate(grid[data_start:], start=1):
        if not any(row):
            continue
        first_txt = _col_val(row, stt_idx)
        second_txt = _col_val(row, so_idx if so_idx is not None else 1)
        if _is_stop_or_summary_text(first_txt) or _is_stop_or_summary_text(second_txt):
            break
        so_hs = _col_val(row, so_idx)
        cong_dan = _col_val(row, col_map.get("cong_dan"))
        unit_raw = _col_val(row, col_map.get("unit_name"))
        han_raw = _col_val(row, col_map.get("han_tra"))

        # Fallback khi ảnh OCR gộp cả hàng bảng thành 1-2 ô văn bản liên tiếp
        if not so_hs:
            joined_line = " ".join(c for c in row if c).strip()
            m_code = re.search(r"\b([A-Z]\d{2}[A-Z0-9.\-]{4,})\b", joined_line)
            if m_code:
                so_hs = m_code.group(1)
                if not unit_raw:
                    m_u = re.search(r"((?:Phường|Xã|Thị trấn|Quận|Huyện)\s+[^\d/\n]{2,40})", joined_line, re.IGNORECASE)
                    if m_u:
                        unit_raw = re.sub(r"\s+\d{1,2}[./-]\d{1,2}.*$", "", m_u.group(1)).strip()
                if not han_raw:
                    m_d = re.findall(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", joined_line)
                    if m_d:
                        han_raw = m_d[-1]
            elif cong_dan and unit_raw:
                so_hs = f"TT-{idx_r:03d}-{_norm_key(cong_dan)[:12]}"

        if not so_hs or _norm_vn(so_hs) in ("so ho so", "ma ho so", "so/ma ho so"):
            continue
        if not unit_raw and re.fullmatch(r"\d+", so_hs) and not _col_val(row, col_map.get("thu_tuc")):
            continue

        unit_info = resolve_unit(unit_raw)
        ngay_nop_raw = _col_val(row, col_map.get("ngay_nop"))
        ngay_nop_d = _parse_vn_date(ngay_nop_raw)
        ngay_tn_raw = _col_val(row, col_map.get("ngay_tiep_nhan"))
        ngay_tn_d = _parse_vn_date(ngay_tn_raw)
        han_tra_d = _parse_vn_date(han_raw)
        thu_tuc = _col_val(row, col_map.get("thu_tuc")) or "Đăng ký tạm trú"
        tinh_dh = _col_val(row, col_map.get("tinh_dung_han"))
        can_bo = _col_val(row, col_map.get("can_bo"))
        tt_nguon = _col_val(row, col_map.get("trang_thai_nguon"))
        custom_fields = _collect_custom_fields(row, exact_hdr_labels or eff_headers, mapped_indices)
        raw_row = [_col_val(row, c) for c in range(table_ncols)]
        is_done = _is_done_source_status(tt_nguon)

        note_parts = [thu_tuc]
        if cong_dan:
            note_parts.append(cong_dan)
        if tt_nguon:
            note_parts.append(tt_nguon)

        records.append({
            "category_tab": "tam_tru",
            "loai": "cu-tru",
            "ma_ho_so": so_hs,
            "so_ho_so": so_hs,
            "thu_tuc": thu_tuc,
            "cong_dan": cong_dan,
            "ngay_nop": ngay_nop_d.strftime("%Y-%m-%d") if ngay_nop_d else "",
            "ngay_tiep_nhan": ngay_tn_d.strftime("%Y-%m-%d") if ngay_tn_d else "",
            "han_tra": (han_tra_d or report_date).strftime("%Y-%m-%d"),
            "has_deadline": bool(han_tra_d),
            "tinh_dung_han": tinh_dh,
            "can_bo": can_bo,
            "unit_area": unit_raw,
            "unit_code": unit_info["unit_code"],
            "unit_key": unit_info["unit_key"],
            "unit_label": unit_info["unit_label"],
            "unit_matched": unit_info["matched"],
            "trang_thai_nguon": tt_nguon,
            "trang_thai": "da_tra" if is_done else "dang_xu_ly",
            "ghi_chu": " — ".join(p for p in note_parts if p),
            "report_date": report_date.strftime("%Y-%m-%d"),
            "pending_total": 0 if is_done else 1,
            "is_pending": not is_done,
            "include": True,
            "raw_row": raw_row,
            "extra": {
                "stt": first_txt,
                "source_row_index": len(records) + 1,
                "ngay_nop_raw": ngay_nop_raw,
                "ngay_tiep_nhan_raw": ngay_tn_raw,
                "han_tra_raw": han_raw,
                "tinh_dung_han": tinh_dh,
                "cong_dan": cong_dan,
                "custom_fields": custom_fields,
                "row_cells": raw_row,
                "source_headers": exact_hdr_labels,
                "source_header_rows": raw_hdr_rows,
                "source_col_widths": col_widths,
                "source_col_ratios": col_ratios,
            },
        })
    return records


def _parse_thuong_tru_grid(grid, filename, report_date, resolve_unit, scan_meta=None):
    hdr_idx, data_start, eff_headers, full_headers, table_title = _extract_table_structure(
        grid,
        ["stt", "so ho so", "ma ho so", "thu tuc", "dia ban tiep nhan", "ngay tiep nhan", "ngay nop", "can bo", "trang thai"],
        max_scan=25,
    )
    col_map = _map_columns(
        eff_headers,
        [
            ("stt", ["stt", "tt", "so tt"]),
            ("so_ho_so", ["so ho so", "ma ho so", "so/ma ho so", "ma tiep nhan", "so bien nhan", "so hs"]),
            ("thu_tuc", ["thu tuc", "ten thu tuc", "loai ho so"]),
            ("cong_dan", ["ho va ten", "ho ten", "cong dan", "nguoi nop", "chu ho"]),
            ("ngay_nop", ["ngay nop ho so", "ngay nop", "thoi gian nop", "ngay gui"]),
            ("ngay_tiep_nhan", ["ngay tiep nhan", "ngay nhan", "thoi gian tiep nhan"]),
            ("han_tra", ["ngay hen tra", "han tra ket qua", "han tra", "hen tra", "han giai quyet"]),
            ("can_bo", ["can bo tiep nhan", "can bo xu ly", "can bo", "nguoi tiep nhan"]),
            ("unit_name", ["dia ban tiep nhan", "don vi xu ly", "don vi tiep nhan", "don vi", "dia ban"]),
            ("trang_thai_nguon", ["trang thai ho so", "trang thai", "tinh trang"]),
        ],
        extra_full_headers=full_headers,
    )
    col_map = _infer_missing_dossier_columns(grid, data_start, col_map, resolve_unit)
    if not col_map and len(eff_headers) >= 6:
        col_map = {
            "stt": 0, "so_ho_so": 1, "thu_tuc": 2, "ngay_tiep_nhan": 3,
            "can_bo": 4, "unit_name": 5, "trang_thai_nguon": 6,
        }

    raw_hdr_rows, exact_hdr_labels = _extract_raw_header_rows(grid, hdr_idx, data_start, ncols=len(eff_headers))
    col_widths, col_ratios = _attach_scan_layout_meta(
        scan_meta,
        grid,
        data_start,
        raw_hdr_rows,
        exact_hdr_labels,
        eff_headers,
        col_map,
        table_title,
    )

    mapped_indices = set(col_map.values())
    stt_idx = col_map.get("stt", 0)
    so_idx = col_map.get("so_ho_so")
    table_ncols = len(exact_hdr_labels) if exact_hdr_labels else len(eff_headers)

    records = []
    for row in grid[data_start:]:
        if not any(row):
            continue
        first_txt = _col_val(row, stt_idx)
        second_txt = _col_val(row, so_idx if so_idx is not None else 1)
        if _is_stop_or_summary_text(first_txt) or _is_stop_or_summary_text(second_txt):
            break
        so_hs = _col_val(row, so_idx)
        unit_raw = _col_val(row, col_map.get("unit_name"))
        if not so_hs or _norm_vn(so_hs) in ("so ho so", "ma ho so", "so/ma ho so"):
            continue
        if not unit_raw and re.fullmatch(r"\d+", so_hs) and not _col_val(row, col_map.get("thu_tuc")):
            continue

        unit_info = resolve_unit(unit_raw)
        ngay_nop_raw = _col_val(row, col_map.get("ngay_nop"))
        ngay_nop_d = _parse_vn_date(ngay_nop_raw)
        ngay_tn_raw = _col_val(row, col_map.get("ngay_tiep_nhan"))
        ngay_tn_d = _parse_vn_date(ngay_tn_raw)
        han_raw = _col_val(row, col_map.get("han_tra"))
        han_tra_d = _parse_vn_date(han_raw)
        thu_tuc = _col_val(row, col_map.get("thu_tuc")).rstrip(" -")
        cong_dan = _col_val(row, col_map.get("cong_dan"))
        can_bo = _col_val(row, col_map.get("can_bo"))
        tt_nguon = _col_val(row, col_map.get("trang_thai_nguon"))
        custom_fields = _collect_custom_fields(row, exact_hdr_labels or eff_headers, mapped_indices)
        raw_row = [_col_val(row, c) for c in range(table_ncols)]
        is_done = _is_done_source_status(tt_nguon)

        records.append({
            "category_tab": "thuong_tru",
            "loai": "cu-tru",
            "ma_ho_so": so_hs,
            "so_ho_so": so_hs,
            "thu_tuc": thu_tuc,
            "cong_dan": cong_dan,
            "ngay_nop": ngay_nop_d.strftime("%Y-%m-%d") if ngay_nop_d else "",
            "ngay_tiep_nhan": ngay_tn_d.strftime("%Y-%m-%d") if ngay_tn_d else "",
            "han_tra": (han_tra_d or ngay_tn_d or report_date).strftime("%Y-%m-%d"),
            "has_deadline": bool(han_tra_d),
            "tinh_dung_han": "",
            "can_bo": can_bo,
            "unit_area": unit_raw,
            "unit_code": unit_info["unit_code"],
            "unit_key": unit_info["unit_key"],
            "unit_label": unit_info["unit_label"],
            "unit_matched": unit_info["matched"],
            "trang_thai_nguon": tt_nguon,
            "trang_thai": "da_tra" if is_done else "dang_xu_ly",
            "ghi_chu": " — ".join(p for p in (thu_tuc, cong_dan, tt_nguon) if p),
            "report_date": report_date.strftime("%Y-%m-%d"),
            "pending_total": 0 if is_done else 1,
            "is_pending": not is_done,
            "include": True,
            "raw_row": raw_row,
            "extra": {
                "stt": first_txt,
                "source_row_index": len(records) + 1,
                "ngay_nop_raw": ngay_nop_raw,
                "ngay_tiep_nhan_raw": ngay_tn_raw,
                "han_tra_raw": han_raw,
                "dia_ban_tiep_nhan": unit_raw,
                "cong_dan": cong_dan,
                "custom_fields": custom_fields,
                "row_cells": raw_row,
                "source_headers": exact_hdr_labels,
                "source_header_rows": raw_hdr_rows,
                "source_col_widths": col_widths,
                "source_col_ratios": col_ratios,
            },
        })
    return records


def _parse_ct10_grid(grid, filename, report_date, resolve_unit, scan_meta=None):
    hdr_idx = _find_header_row_idx(grid, ["don vi", "lap phieu xac minh", "tra loi xac minh", "qua han"])
    tier1 = grid[hdr_idx] if hdr_idx < len(grid) else []
    tier2 = grid[hdr_idx + 1] if hdr_idx + 1 < len(grid) else []
    # Kiểm tra dòng sau có phải là tier2 của tiêu đề 2 tầng không
    has_tier2 = any(
        "hoan thanh" in _norm_vn(c) or "cho tra loi" in _norm_vn(c) or "tra ket qua" in _norm_vn(c)
        for c in tier2
    )
    data_start = hdr_idx + (2 if has_tier2 else 1)

    unit_col = 1
    for i, c in enumerate(tier1):
        if "don vi" in _norm_vn(c):
            unit_col = i
            break

    stt_col = None
    for row_scan in (tier1, tier2):
        for i, c in enumerate(row_scan):
            if _norm_vn(c) in ("stt", "tt", "so tt", "so thu tu"):
                stt_col = i
                break
        if stt_col is not None:
            break
    if stt_col is None and unit_col > 0:
        stt_col = 0

    col_indices = {}
    last_group = ""
    ncols = max(len(tier1), len(tier2))
    for i in range(ncols):
        g = _norm_vn(tier1[i] if i < len(tier1) else "")
        s = _norm_vn(tier2[i] if (has_tier2 and i < len(tier2)) else "")
        if g and g not in ("stt", "don vi"):
            last_group = g
        eff_g = g or last_group

        if "qua han" in g or "qua han" in s:
            col_indices["qua_han"] = i
        elif "lap phieu" in eff_g:
            if s == "tong":
                col_indices["lap_tong"] = i
            elif "hoan thanh" in s:
                col_indices["lap_hoan_thanh"] = i
            elif "cho phe duyet" in s:
                col_indices["lap_cho_pd"] = i
            elif "tra lai" in s:
                col_indices["lap_tra_lai"] = i
            elif "cho tra loi" in s:
                col_indices["lap_cho_tl"] = i
            elif "da tra loi" in s:
                col_indices["lap_da_tl"] = i
        elif "tra loi xac minh" in eff_g:
            if s == "tong":
                col_indices["tl_tong"] = i
            elif "cho tra loi" in s:
                col_indices["tl_cho_tl"] = i
            elif "dang tra loi" in s:
                col_indices["tl_dang_tl"] = i
            elif "cho phe duyet" in s:
                col_indices["tl_cho_pd"] = i
            elif "tra ket qua" in s and "da tra" not in s:
                col_indices["tl_tra_kq"] = i
            elif "da tra ket qua" in s:
                col_indices["tl_da_kq"] = i

    # Fallback theo layout chuẩn 15 cột CT10 nếu OCR mất chữ tiêu đề
    if not col_indices and ncols >= 15:
        col_indices = {
            "lap_tong": 2, "lap_hoan_thanh": 3, "lap_cho_pd": 4, "lap_tra_lai": 5, "lap_cho_tl": 6, "lap_da_tl": 7,
            "tl_tong": 8, "tl_cho_tl": 9, "tl_dang_tl": 10, "tl_cho_pd": 11, "tl_tra_kq": 12, "tl_da_kq": 13,
            "qua_han": 14,
        }

    raw_hdr_rows, exact_hdr_labels = _extract_raw_header_rows(grid, hdr_idx, data_start)
    ncols_raw = len(exact_hdr_labels) or ncols
    table_title = _pick_table_title(grid[:hdr_idx])
    meta_col_map = {"unit_name": unit_col}
    if stt_col is not None:
        meta_col_map["stt"] = stt_col
    col_widths, col_ratios = _attach_scan_layout_meta(
        scan_meta,
        grid,
        data_start,
        raw_hdr_rows,
        exact_hdr_labels,
        tier2 if has_tier2 else tier1,
        meta_col_map,
        table_title,
    )

    records = []
    rep_str = report_date.strftime("%Y-%m-%d")
    for row in grid[data_start:]:
        if not any(row):
            continue
        unit_raw = _col_val(row, unit_col)
        if not unit_raw and len(row) > 0:
            unit_raw = _col_val(row, 0)
        if _is_stop_or_summary_text(unit_raw) or _is_province_or_total_unit(unit_raw):
            continue

        raw_row = [_col_val(row, ci) for ci in range(ncols_raw)]
        stt_raw = _col_val(row, stt_col) if stt_col is not None else ""

        m = {k: _parse_int(_col_val(row, idx), 0) for k, idx in col_indices.items()}
        lap_pending = m.get("lap_hoan_thanh", 0) + m.get("lap_cho_pd", 0) + m.get("lap_tra_lai", 0) + m.get("lap_cho_tl", 0)
        tl_pending = m.get("tl_cho_tl", 0) + m.get("tl_dang_tl", 0) + m.get("tl_cho_pd", 0)
        qua_han = m.get("qua_han", 0)
        pending_total = lap_pending + tl_pending
        is_pending = (pending_total > 0 or qua_han > 0)

        unit_info = resolve_unit(unit_raw)
        key_code = unit_info["unit_code"] or unit_info["unit_key"] or _norm_key(unit_raw)
        so_hs = f"CT10-{rep_str}-{key_code}"

        summary_parts = []
        if lap_pending:
            summary_parts.append(f"Lập phiếu chờ: {lap_pending}")
        if tl_pending:
            summary_parts.append(f"Trả lời chờ: {tl_pending}")
        if qua_han:
            summary_parts.append(f"Quá hạn: {qua_han}")
        tt_nguon = "; ".join(summary_parts) if summary_parts else "Đã xử lý hết phiếu CT10"

        records.append({
            "category_tab": "ct10",
            "loai": "xac-thuc",
            "ma_ho_so": f"Phiếu XM CT10 — {unit_info['unit_label'] or unit_raw}",
            "so_ho_so": so_hs,
            "thu_tuc": f"Phiếu CT10 ngày {report_date.strftime('%d/%m/%Y')}",
            "ngay_nop": "",
            "ngay_tiep_nhan": rep_str,
            "han_tra": rep_str,
            "has_deadline": bool(qua_han > 0),
            "tinh_dung_han": f"Quá hạn {qua_han}" if qua_han > 0 else ("Còn tồn" if is_pending else "Hoàn tất"),
            "can_bo": "",
            "unit_area": unit_raw,
            "unit_code": unit_info["unit_code"],
            "unit_key": unit_info["unit_key"],
            "unit_label": unit_info["unit_label"],
            "unit_matched": unit_info["matched"],
            "trang_thai_nguon": tt_nguon,
            "trang_thai": "dang_xu_ly" if is_pending else "da_tra",
            "ghi_chu": tt_nguon,
            "report_date": rep_str,
            "pending_total": pending_total,
            "is_pending": is_pending,
            "include": is_pending,
            "raw_row": raw_row,
            "extra": {
                "stt": stt_raw,
                "source_row_index": len(records) + 1,
                "lap_tong": m.get("lap_tong", 0),
                "lap_hoan_thanh": m.get("lap_hoan_thanh", 0),
                "lap_cho_pd": m.get("lap_cho_pd", 0),
                "lap_tra_lai": m.get("lap_tra_lai", 0),
                "lap_cho_tl": m.get("lap_cho_tl", 0),
                "lap_da_tl": m.get("lap_da_tl", 0),
                "tl_tong": m.get("tl_tong", 0),
                "tl_cho_tl": m.get("tl_cho_tl", 0),
                "tl_dang_tl": m.get("tl_dang_tl", 0),
                "tl_cho_pd": m.get("tl_cho_pd", 0),
                "tl_tra_kq": m.get("tl_tra_kq", 0),
                "tl_da_kq": m.get("tl_da_kq", 0),
                "qua_han": qua_han,
                "lap_pending": lap_pending,
                "tl_pending": tl_pending,
                "pending_total": pending_total,
                "row_cells": raw_row,
                "source_headers": exact_hdr_labels,
                "source_header_rows": raw_hdr_rows,
                "source_col_widths": col_widths,
                "source_col_ratios": col_ratios,
            },
        })
    return records


def _parse_tich_hop_grid(grid, sheet_name, filename, report_date, resolve_unit):
    hdr_idx = _find_header_row_idx(
        grid,
        ["don vi", "dinh danh", "tich hop", "cho xac nhan", "nhan khau", "da tich hop", "ty le"],
        step_up_if_merged=True,
    )
    tier1 = grid[hdr_idx] if hdr_idx < len(grid) else []
    tier2 = grid[hdr_idx + 1] if hdr_idx + 1 < len(grid) else []
    has_tier2 = any(
        any(tok in _norm_vn(c) for tok in ["da tich hop", "cho xac nhan", "tu choi", "ty le", "da kich hoat", "da duoc cap"])
        for c in tier2
    )
    data_start = hdr_idx + (2 if has_tier2 else 1)

    unit_col = 1
    for row_scan in (tier1, tier2):
        for i, c in enumerate(row_scan):
            if "don vi" in _norm_vn(c) or "dia ban" in _norm_vn(c):
                unit_col = i
                break
        else:
            continue
        break

    stt_col = None
    for row_scan in (tier1, tier2):
        for i, c in enumerate(row_scan):
            if _norm_vn(c) in ("stt", "tt", "so tt", "so thu tu"):
                stt_col = i
                break
        if stt_col is not None:
            break
    if stt_col is None and unit_col > 0:
        stt_col = 0

    ncols = max([len(r) for r in grid[hdr_idx:data_start + 5]] + [1])
    col_defs = []
    last_grp = ""
    for i in range(ncols):
        raw_t1 = _cell_str(tier1[i] if i < len(tier1) else "")
        raw_t2 = _cell_str(tier2[i] if (has_tier2 and i < len(tier2)) else "")
        nt1, nt2 = _norm_vn(raw_t1), _norm_vn(raw_t2)
        if i == unit_col or nt1 in ("stt", "don vi", "dia ban") or nt2 in ("stt", "don vi", "dia ban"):
            continue
        if raw_t1:
            last_grp = raw_t1
        grp = raw_t1 or last_grp or sheet_name or "Chỉ tiêu"
        sub = raw_t2 or raw_t1
        norm_sub = _norm_vn(sub)
        norm_grp = _norm_vn(grp)
        if not norm_sub and not norm_grp:
            continue
        col_defs.append({
            "idx": i,
            "group": grp,
            "sub": sub,
            "norm_grp": norm_grp,
            "norm_sub": norm_sub,
            "is_pct": "ty le" in norm_sub or "%" in sub,
            "is_cho_xn": "cho xac nhan" in norm_sub,
            "is_tu_choi": "tu choi" in norm_sub,
            "is_done": "da tich hop" in norm_sub or "da kich hoat" in norm_sub,
            "is_pop": "nhan khau" in norm_sub or "nhan khau" in norm_grp,
        })

    # Xác định nhóm chính (đối với sub-sheet đơn lẻ hoặc ảnh chụp 1 loại giấy tờ)
    distinct_groups = []
    for cd in col_defs:
        if not cd["is_pop"] and cd["group"] not in distinct_groups:
            distinct_groups.append(cd["group"])
    if len(distinct_groups) == 1:
        primary_group = distinct_groups[0]
    elif sheet_name and _norm_vn(sheet_name) not in ("chi tieu", "sheet1", "trang tinh"):
        primary_group = sheet_name
    elif distinct_groups:
        primary_group = f"Tổng hợp {len(distinct_groups)} nhóm chỉ tiêu"
    else:
        primary_group = "ĐDĐT & Tích hợp giấy tờ"

    rep_str = report_date.strftime("%Y-%m-%d")
    records = []
    for row in grid[data_start:]:
        if not any(row):
            continue
        unit_raw = _find_unit_in_row(row, unit_col, resolve_unit)
        if _is_stop_or_summary_text(unit_raw) or _is_province_or_total_unit(unit_raw):
            continue
        if re.fullmatch(r"\d+", unit_raw):
            continue

        unit_info = resolve_unit(unit_raw)
        key_code = unit_info["unit_code"] or unit_info["unit_key"] or _norm_key(unit_raw)
        grp_slug = _norm_key(sheet_name or primary_group)[:18] or "chung"
        so_hs = f"TICHHOP-{grp_slug}-{rep_str}-{key_code}"

        cho_xac_nhan_total = 0
        da_tich_hop_total = 0
        tu_choi_total = 0
        nk_ref = 0
        rate_display = ""
        groups_breakdown = {}

        for cd in col_defs:
            raw_v = _col_val(row, cd["idx"])
            if not raw_v:
                continue
            grp_entry = groups_breakdown.setdefault(cd["group"], {})
            if cd["is_pct"]:
                pct_str = _format_pct(raw_v)
                grp_entry["Tỷ lệ"] = pct_str
                if len(distinct_groups) <= 2 or "dinh danh" in cd["norm_grp"] or "muc 2" in cd["norm_grp"]:
                    rate_display = rate_display or pct_str
            else:
                ival = _parse_int(raw_v, 0)
                grp_entry[cd["sub"]] = ival
                if cd["is_cho_xn"]:
                    cho_xac_nhan_total += ival
                elif cd["is_tu_choi"]:
                    tu_choi_total += ival
                elif cd["is_done"] and "da tich hop" in cd["norm_sub"]:
                    da_tich_hop_total += ival
                elif cd["is_pop"] and nk_ref == 0:
                    nk_ref = ival

        # Nếu là biểu chỉ tiêu ĐDĐT mức 2 (không có cột Chờ xác nhận, có Đã kích hoạt & NK trên 14 tuổi)
        da_kh_m2 = 0
        nk_14 = nk_ref
        for g_name, g_dict in groups_breakdown.items():
            for k_lbl, v_num in g_dict.items():
                if "da kich hoat" in _norm_vn(k_lbl):
                    da_kh_m2 = v_num if isinstance(v_num, int) else da_kh_m2
                    if da_tich_hop_total == 0:
                        da_tich_hop_total = da_kh_m2

        if cho_xac_nhan_total == 0 and nk_14 > 0 and da_kh_m2 > 0 and len(distinct_groups) == 1 and "dinh danh" in _norm_vn(primary_group):
            pending_total = max(nk_14 - da_kh_m2, 0)
        else:
            pending_total = cho_xac_nhan_total

        status_parts = []
        if cho_xac_nhan_total:
            status_parts.append(f"Chờ XN: {cho_xac_nhan_total:,}")
        if da_tich_hop_total:
            status_parts.append(f"Đã tích hợp: {da_tich_hop_total:,}")
        if tu_choi_total:
            status_parts.append(f"Từ chối: {tu_choi_total:,}")
        if rate_display:
            status_parts.append(f"Tỷ lệ: {rate_display}")
        tt_nguon = " | ".join(status_parts) if status_parts else "Chỉ tiêu tích hợp"

        is_pending = pending_total > 0 or len(distinct_groups) > 1 or da_tich_hop_total >= 0

        records.append({
            "category_tab": "tich_hop",
            "loai": "dinh-danh",
            "ma_ho_so": f"{primary_group} — {unit_info['unit_label'] or unit_raw}",
            "so_ho_so": so_hs,
            "thu_tuc": primary_group,
            "ngay_nop": "",
            "ngay_tiep_nhan": rep_str,
            "han_tra": rep_str,
            "has_deadline": False,
            "tinh_dung_han": rate_display,
            "can_bo": "",
            "unit_area": unit_raw,
            "unit_code": unit_info["unit_code"],
            "unit_key": unit_info["unit_key"],
            "unit_label": unit_info["unit_label"],
            "unit_matched": unit_info["matched"],
            "trang_thai_nguon": tt_nguon,
            "trang_thai": "dang_xu_ly" if pending_total > 0 else "da_tra",
            "ghi_chu": tt_nguon,
            "report_date": rep_str,
            "pending_total": pending_total,
            "is_pending": pending_total > 0,
            "include": pending_total > 0 or (len(distinct_groups) <= 1),
            "extra": {
                "stt": _col_val(row, stt_col) if stt_col is not None else "",
                "source_row_index": len(records) + 1,
                "group_name": primary_group,
                "sheet_name": sheet_name or "",
                "nk_ref": nk_ref,
                "cho_xac_nhan": cho_xac_nhan_total,
                "da_tich_hop": da_tich_hop_total,
                "tu_choi": tu_choi_total,
                "ty_le": rate_display,
                "groups": groups_breakdown,
            },
        })
    return records


def _find_unit_in_row(row, preferred_col, resolve_unit):
    """Tìm tên đơn vị trong hàng (ưu tiên cột chuẩn, fallback sang các cột đầu khi OCR lệch cột)."""
    def _clean_unit(text):
        return re.sub(
            r"^\d+[\s.)\-]+(?=(?:Phường|Xã|Thị|Công|UBND|Tỉnh|Quận|Huyện|Sở|Phòng))",
            "",
            text or "",
            flags=re.IGNORECASE,
        ).strip()

    direct = _clean_unit(_col_val(row, preferred_col))
    if direct and not re.fullmatch(r"\d+", direct):
        return direct
    for idx in range(min(len(row), 4)):
        cand = _clean_unit(_col_val(row, idx))
        if not cand or re.fullmatch(r"\d+", cand):
            continue
        if resolve_unit(cand).get("matched") or any(
            k in _norm_vn(cand) for k in ("phuong ", "xa ", "thi tran ", "cong an ", "ubnd ", "tinh ", "tong")
        ):
            return cand
    return direct


def _parse_lam_sach_grid(grid, filename, report_date, resolve_unit):
    hdr_idx = _find_header_row_idx(grid, ["don vi", "dia ban", "lam sach", "chi tieu", "ton", "da xu ly", "ty le"])
    headers = grid[hdr_idx] if hdr_idx < len(grid) else []
    tier2 = grid[hdr_idx + 1] if hdr_idx + 1 < len(grid) else []
    # Kiểm tra header 2 tầng nếu dòng sau không phải dữ liệu đơn vị
    has_tier2 = bool(
        tier2
        and not resolve_unit(_col_val(tier2, 1)).get("matched")
        and any(_norm_vn(c) in ("tong", "da lam sach", "con ton", "ty le", "hoan thanh", "chua xu ly") for c in tier2)
    )
    data_start = hdr_idx + (2 if has_tier2 else 1)

    unit_col = 1
    for i, c in enumerate(headers):
        nc = _norm_vn(c)
        if any(k in nc for k in ["don vi", "dia ban", "cong an xa", "xa/phuong", "phuong/xa"]):
            unit_col = i
            break

    stt_col = None
    for row_scan in (headers, tier2):
        for i, c in enumerate(row_scan):
            if _norm_vn(c) in ("stt", "tt", "so tt", "so thu tu"):
                stt_col = i
                break
        if stt_col is not None:
            break
    if stt_col is None and unit_col > 0:
        stt_col = 0

    col_meta = []
    ncols = max([len(headers)] + [len(r) for r in grid[data_start:data_start + 5]] + [1])
    for i in range(ncols):
        if i == unit_col:
            continue
        h1 = _cell_str(headers[i] if i < len(headers) else "")
        h2 = _cell_str(tier2[i] if has_tier2 and i < len(tier2) else "")
        label = f"{h1} - {h2}".strip(" -") if (h1 and h2 and h1 != h2) else (h2 or h1 or f"Cột {i + 1}")
        nl = _norm_vn(label)
        if nl in ("stt", "ghi chu"):
            continue
        is_total = any(k in nl for k in ["tong so", "chi tieu", "tong can", "tong phai"])
        is_done = any(k in nl for k in ["da lam sach", "da xu ly", "hoan thanh", "da cap nhat"])
        is_pending_c = (not is_total and not is_done) and (
            any(k in nl for k in ["con ton", "chua ", "can lam sach", "sai ", "lech", "thieu", "trung", "phai lam"])
            or bool(re.search(r"\bton\b", nl))
        )
        col_meta.append({
            "idx": i,
            "label": label,
            "norm": nl,
            "is_pct": "ty le" in nl or "%" in label,
            "is_pending_col": is_pending_c,
            "is_done_col": is_done,
            "is_total_col": is_total,
        })

    # Lấy tiêu đề bảng làm nội dung chỉ tiêu
    title_lines = [r[0] for r in grid[:hdr_idx] if r and r[0]]
    indicator_title = title_lines[0] if title_lines else "Chỉ tiêu làm sạch dữ liệu dân cư"

    rep_str = report_date.strftime("%Y-%m-%d")
    records = []
    for row in grid[data_start:]:
        if not any(row):
            continue
        unit_raw = _find_unit_in_row(row, unit_col, resolve_unit)
        if _is_stop_or_summary_text(unit_raw) or _is_province_or_total_unit(unit_raw):
            continue
        if re.fullmatch(r"\d+", unit_raw):
            continue

        unit_info = resolve_unit(unit_raw)
        key_code = unit_info["unit_code"] or unit_info["unit_key"] or _norm_key(unit_raw)
        so_hs = f"LAMSACH-{rep_str}-{key_code}"

        metrics = []
        pending_total = 0
        has_explicit_pending = False
        done_total = 0
        target_total = 0
        rate_display = ""

        for cm in col_meta:
            raw_v = _col_val(row, cm["idx"])
            if not raw_v:
                continue
            if cm["is_pct"]:
                pct_str = _format_pct(raw_v)
                metrics.append({"label": cm["label"], "value": pct_str, "is_pct": True})
                rate_display = rate_display or pct_str
            else:
                ival = _parse_int(raw_v, 0)
                metrics.append({"label": cm["label"], "value": ival, "is_pct": False})
                if cm["is_pending_col"]:
                    pending_total += ival
                    has_explicit_pending = True
                elif cm["is_done_col"]:
                    done_total += ival
                elif cm["is_total_col"]:
                    target_total += ival

        if not has_explicit_pending and target_total > 0 and done_total <= target_total:
            pending_total = max(target_total - done_total, 0)

        is_pending = pending_total > 0 or not has_explicit_pending
        summary = " | ".join(f"{m['label']}: {m['value']}" for m in metrics[:4])

        records.append({
            "category_tab": "lam_sach",
            "loai": "xac-thuc",
            "ma_ho_so": f"Làm sạch DL — {unit_info['unit_label'] or unit_raw}",
            "so_ho_so": so_hs,
            "thu_tuc": indicator_title[:240],
            "ngay_nop": "",
            "ngay_tiep_nhan": rep_str,
            "han_tra": rep_str,
            "has_deadline": False,
            "tinh_dung_han": rate_display or (f"Còn {pending_total}" if pending_total else "Đạt chỉ tiêu"),
            "can_bo": "",
            "unit_area": unit_raw,
            "unit_code": unit_info["unit_code"],
            "unit_key": unit_info["unit_key"],
            "unit_label": unit_info["unit_label"],
            "unit_matched": unit_info["matched"],
            "trang_thai_nguon": summary or "Theo dõi chỉ tiêu làm sạch",
            "trang_thai": "dang_xu_ly" if is_pending else "da_tra",
            "ghi_chu": summary,
            "report_date": rep_str,
            "pending_total": pending_total,
            "is_pending": is_pending,
            "include": is_pending,
            "extra": {
                "stt": _col_val(row, stt_col) if stt_col is not None else "",
                "source_row_index": len(records) + 1,
                "chi_tieu": indicator_title[:240],
                "tong_so": target_total,
                "da_lam_sach": done_total,
                "con_ton": pending_total,
                "ty_le": rate_display,
                "metrics": metrics,
            },
        })
    return records


def _parse_generic_grid(grid, filename, report_date, resolve_unit, scan_meta=None):
    hdr_idx, data_start, eff_headers, full_headers, table_title = _extract_table_structure(
        grid,
        ["stt", "ma ho so", "so ho so", "ten ho so", "thu tuc", "ho ten", "don vi", "ngay nop", "ngay tiep nhan", "han tra", "ngay hen tra", "trang thai"],
        max_scan=25,
    )
    col_map = _map_columns(
        eff_headers,
        [
            ("stt", ["stt", "tt"]),
            ("so_ho_so", ["so ho so", "ma ho so", "so/ma ho so", "ten ho so", "ma tiep nhan", "noi dung"]),
            ("thu_tuc", ["thu tuc", "loai ho so", "chi tieu"]),
            ("cong_dan", ["ho va ten", "ho ten", "cong dan", "nguoi nop", "chu ho"]),
            ("ngay_nop", ["ngay nop ho so", "ngay nop", "thoi gian nop", "ngay gui"]),
            ("ngay_tiep_nhan", ["ngay tiep nhan", "ngay nhan", "ngay"]),
            ("han_tra", ["ngay hen tra", "han tra", "hen tra", "han giai quyet", "thoi han"]),
            ("can_bo", ["can bo", "nguoi xu ly"]),
            ("unit_name", ["don vi", "dia ban", "co quan"]),
            ("trang_thai_nguon", ["trang thai", "tinh trang", "ghi chu"]),
        ],
        extra_full_headers=full_headers,
    )
    col_map = _infer_missing_dossier_columns(grid, data_start, col_map, resolve_unit)
    raw_hdr_rows, exact_hdr_labels = _extract_raw_header_rows(grid, hdr_idx, data_start, ncols=len(eff_headers))
    col_widths, col_ratios = _attach_scan_layout_meta(
        scan_meta,
        grid,
        data_start,
        raw_hdr_rows,
        exact_hdr_labels,
        eff_headers,
        col_map,
        table_title,
    )

    mapped_indices = set(col_map.values())
    stt_idx = col_map.get("stt", 0)
    table_ncols = len(exact_hdr_labels) if exact_hdr_labels else len(eff_headers)
    rep_str = report_date.strftime("%Y-%m-%d")
    records = []
    for idx_r, row in enumerate(grid[data_start:], start=1):
        if not any(row):
            continue
        first_txt = _col_val(row, stt_idx)
        if _is_stop_or_summary_text(first_txt):
            break
        ma_hs = _col_val(row, col_map.get("so_ho_so")) or _col_val(row, 1) or _col_val(row, 0)
        if not ma_hs or _is_province_or_total_unit(ma_hs):
            continue
        unit_raw = _col_val(row, col_map.get("unit_name"))
        unit_info = resolve_unit(unit_raw)
        ngay_nop_raw = _col_val(row, col_map.get("ngay_nop"))
        nop_d = _parse_vn_date(ngay_nop_raw)
        han_raw = _col_val(row, col_map.get("han_tra"))
        han_d = _parse_vn_date(han_raw)
        tn_raw = _col_val(row, col_map.get("ngay_tiep_nhan"))
        tn_d = _parse_vn_date(tn_raw)
        cong_dan = _col_val(row, col_map.get("cong_dan"))
        can_bo = _col_val(row, col_map.get("can_bo"))
        tt_nguon = _col_val(row, col_map.get("trang_thai_nguon"))
        is_done = _is_done_source_status(tt_nguon)
        thu_tuc = _col_val(row, col_map.get("thu_tuc"))
        custom_fields = _collect_custom_fields(row, exact_hdr_labels or eff_headers, mapped_indices)
        raw_row = [_col_val(row, c) for c in range(table_ncols)]

        records.append({
            "category_tab": "khac",
            "loai": "khac",
            "ma_ho_so": ma_hs,
            "so_ho_so": ma_hs,
            "thu_tuc": thu_tuc,
            "cong_dan": cong_dan,
            "ngay_nop": nop_d.strftime("%Y-%m-%d") if nop_d else "",
            "ngay_tiep_nhan": tn_d.strftime("%Y-%m-%d") if tn_d else "",
            "han_tra": (han_d or report_date).strftime("%Y-%m-%d"),
            "has_deadline": bool(han_d),
            "tinh_dung_han": "",
            "can_bo": can_bo,
            "unit_area": unit_raw,
            "unit_code": unit_info["unit_code"],
            "unit_key": unit_info["unit_key"],
            "unit_label": unit_info["unit_label"],
            "unit_matched": unit_info["matched"],
            "trang_thai_nguon": tt_nguon,
            "trang_thai": "da_tra" if is_done else "dang_xu_ly",
            "ghi_chu": " — ".join(p for p in (thu_tuc, cong_dan, tt_nguon) if p),
            "report_date": rep_str,
            "pending_total": 0 if is_done else 1,
            "is_pending": not is_done,
            "include": True,
            "raw_row": raw_row,
            "extra": {
                "stt": first_txt,
                "source_row_index": len(records) + 1,
                "ngay_nop_raw": ngay_nop_raw,
                "ngay_tiep_nhan_raw": tn_raw,
                "han_tra_raw": han_raw,
                "cong_dan": cong_dan,
                "custom_fields": custom_fields,
                "raw_row": [c for c in row if c],
                "row_cells": raw_row,
                "source_headers": exact_hdr_labels,
                "source_header_rows": raw_hdr_rows,
                "source_col_widths": col_widths,
                "source_col_ratios": col_ratios,
            },
        })
    return records


def _pick_default_sheet(sheetnames):
    for s in sheetnames:
        ns = _norm_vn(s)
        if ns in ("danh sach ho so", "thong ke phieu xac minh ct10", "chi tieu"):
            return s
    for s in sheetnames:
        ns = _norm_vn(s)
        if not ("tong hop" in ns or "bieu do" in ns):
            return s
    return sheetnames[0] if sheetnames else ""


def parse_dossier_upload(
    file_bytes=None,
    filename="",
    raw_text="",
    sheet_name="",
    override_tab="",
    override_report_date="",
):
    """Phân tích file Excel/CSV/ảnh hoặc bảng văn bản dán vào thành bản xem trước để nhập sổ theo dõi."""
    ext = os.path.splitext(filename or "")[1].lower()
    grid = []
    excel_col_widths = None
    sheets = []
    selected_sheet = sheet_name or ""
    engine_used = "paste"
    source_type = "paste"

    if file_bytes:
        if ext in (".xlsx", ".xlsm"):
            source_type = "excel"
            engine_used = "openpyxl"
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=False)
            sheets = list(wb.sheetnames)
            if not selected_sheet or selected_sheet not in sheets:
                selected_sheet = _pick_default_sheet(sheets)
            if selected_sheet:
                ws_selected = wb[selected_sheet]
                grid = _sheet_to_grid(ws_selected)
                max_grid_cols = max((len(r) for r in grid), default=0)
                excel_col_widths = _extract_sheet_col_widths(ws_selected, max_col=max_grid_cols or None)
        elif ext in (".csv", ".tsv", ".txt"):
            source_type = "csv"
            engine_used = "csv_parser"
            for enc in ("utf-8-sig", "utf-8", "cp1258", "latin1"):
                try:
                    decoded = file_bytes.decode(enc)
                    break
                except UnicodeDecodeError:
                    decoded = ""
            grid = _text_to_grid(decoded)
        elif ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            source_type = "image"
            grid, engine_used, err_msg = extract_image_table_grid(file_bytes, ext=ext)
            if not grid:
                return {
                    "ok": False,
                    "ocr_unavailable": engine_used == "ocr_unavailable",
                    "error": err_msg or "Không trích xuất được dữ liệu bảng từ ảnh tải lên.",
                    "engine": engine_used,
                    "source_type": source_type,
                    "filename": filename,
                }
        else:
            return {
                "ok": False,
                "error": f"Định dạng file '{ext}' chưa được hỗ trợ. Hỗ trợ: .xlsx, .csv, .png, .jpg, .webp.",
            }
    elif raw_text:
        source_type = "paste"
        engine_used = "text_table"
        grid = _text_to_grid(raw_text)
    else:
        return {"ok": False, "error": "Vui lòng chọn file Excel/ảnh chụp hoặc dán nội dung bảng."}

    if not grid:
        return {"ok": False, "error": "Không tìm thấy dữ liệu bảng hợp lệ."}

    detected_tab = detect_dossier_category(
        grid,
        filename=filename,
        sheet_name=selected_sheet,
        override_tab=override_tab,
    )
    resolved_hdr_idx, resolved_data_start, _, resolved_full_headers, detected_table_title = _extract_table_structure(
        grid, _DOSSIER_ALL_KEYWORDS, max_scan=25
    )
    fallback_raw_rows, fallback_exact_headers = _extract_raw_header_rows(grid, resolved_hdr_idx, resolved_data_start)
    title_candidates = []
    for row in grid[: max(resolved_hdr_idx, 4)]:
        non_empty = [c for c in row if c]
        if non_empty and not any("g01." in _norm_vn(c) for c in non_empty) and not (len(non_empty) >= 5 and re.fullmatch(r"\d+", non_empty[0])):
            title_candidates.append(" ".join(dict.fromkeys(non_empty)))
    report_date = _parse_vn_date(override_report_date) or _extract_report_date(
        title_candidates + [selected_sheet],
        filename=filename,
    )
    resolve_unit = build_unit_matcher()
    scan_meta = {
        "table_title": detected_table_title or _cell_str(grid[0][0] if grid and grid[0] else ""),
        "raw_headers": fallback_raw_rows,
        "exact_headers": fallback_exact_headers,
        "detected_headers": [h for h in fallback_exact_headers if h],
        "column_mapping": [],
        "excel_col_widths": excel_col_widths,
        "col_widths": [],
        "col_ratios": [],
    }

    if detected_tab == "tam_tru":
        records = _parse_tam_tru_grid(grid, filename, report_date, resolve_unit, scan_meta=scan_meta)
    elif detected_tab == "thuong_tru":
        records = _parse_thuong_tru_grid(grid, filename, report_date, resolve_unit, scan_meta=scan_meta)
    elif detected_tab == "ct10":
        records = _parse_ct10_grid(grid, filename, report_date, resolve_unit, scan_meta=scan_meta)
    elif detected_tab == "tich_hop":
        records = _parse_tich_hop_grid(grid, selected_sheet, filename, report_date, resolve_unit)
    elif detected_tab == "lam_sach":
        records = _parse_lam_sach_grid(grid, filename, report_date, resolve_unit)
    else:
        records = _parse_generic_grid(grid, filename, report_date, resolve_unit, scan_meta=scan_meta)

    if not scan_meta.get("col_ratios") and fallback_exact_headers:
        fb_w, fb_r = _compute_column_width_metrics(
            grid,
            resolved_data_start,
            fallback_exact_headers,
            excel_col_widths=excel_col_widths,
        )
        scan_meta["col_widths"] = fb_w
        scan_meta["col_ratios"] = fb_r

    pending_rows = sum(1 for r in records if r.get("is_pending"))
    matched_units = sum(1 for r in records if r.get("unit_matched"))

    return {
        "ok": True,
        "source_type": source_type,
        "engine": engine_used,
        "filename": filename,
        "sheets": sheets,
        "selected_sheet": selected_sheet,
        "detected_tab": detected_tab,
        "detected_tab_label": get_dossier_tab_labels().get(detected_tab, "Hồ sơ khác"),
        "report_date": report_date.strftime("%Y-%m-%d"),
        "title": (scan_meta.get("table_title") or " ".join(c for c in (grid[0] if grid else []) if c))[:200],
        "table_title": scan_meta.get("table_title", ""),
        "raw_headers": scan_meta.get("raw_headers", fallback_raw_rows),
        "exact_headers": scan_meta.get("exact_headers", fallback_exact_headers),
        "detected_headers": scan_meta.get("detected_headers", []),
        "column_mapping": scan_meta.get("column_mapping", []),
        "col_widths": scan_meta.get("col_widths", []),
        "col_ratios": scan_meta.get("col_ratios", []),
        "total_rows": len(records),
        "pending_rows": pending_rows,
        "matched_units": matched_units,
        "records": records,
        "raw_preview": grid[:15],
    }
