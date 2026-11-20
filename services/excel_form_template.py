# -*- coding: utf-8 -*-
"""
Xử lý Biểu mẫu Excel (.xlsx) cho luồng Giao việc theo biểu mẫu (FORM):
- Phân tích file .xlsx mẫu (giữ nguyên banner, tiêu đề gộp ô multi-row, cột, dòng mẫu).
- Sinh nhanh file .xlsx mẫu từ danh sách cột (khi không tải sẵn file).
- Đọc dữ liệu từ file .xlsx đơn vị nộp lên hoặc từ lưới nhập web.
- Tổng hợp số liệu & xuất lại file .xlsx gộp giữ đúng bố cục file mẫu ban đầu.
"""

from copy import copy as copy_style
from decimal import Decimal, InvalidOperation
import io
import json
import os
import re
import uuid

from werkzeug.utils import secure_filename

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
except ImportError:
    Workbook = None
    load_workbook = None
    get_column_letter = None

from utils import remove_accents

EXCEL_TEMPLATE_ALLOWED_EXTENSIONS = {".xlsx"}
MAX_PREVIEW_BANNER_ROWS = 12
MAX_TEMPLATE_BODY_ROWS = 300
MAX_TEMPLATE_COLUMNS = 60

UNIT_HEADER_TOKENS = (
    "don vi",
    "ten don vi",
    "dia ban",
    "co quan",
    "don vi bao cao",
    "don vi xu ly",
    "don vi thuc hien",
    "xa phuong",
    "doi tuong",
)

NUMBER_HEADER_TOKENS = (
    "so luong",
    "so ho so",
    "tong so",
    "tong cong",
    "ty le",
    "%",
    "kinh phi",
    "gia tri",
    "so tien",
    "luot ",
    "so van ban",
    "so don vi",
    "so nguoi",
    "so ca",
    "truc tuyen",
    "truc tiep",
    "qua han",
    "da xu ly",
    "so lieu",
)


def _ascii_vn(text):
    raw = str(text or "").replace("đ", "d").replace("Đ", "D")
    return remove_accents(raw)


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Có" if value else "Không"
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:g}"
    return str(value).strip()


def _parse_numeric_value(raw_value):
    if raw_value is None or isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, (int, float, Decimal)):
        return float(raw_value)
    text = str(raw_value).strip()
    if not text:
        return None
    # Bỏ dấu phân cách hàng nghìn phổ biến và khoảng trắng
    cleaned = text.replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", cleaned):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", cleaned):
        cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _is_summary_row_values(row_texts):
    joined = " ".join(
        _ascii_vn(val).strip().lower()
        for val in (row_texts or [])[:3]
        if str(val or "").strip()
    )
    if not joined:
        return False
    return bool(re.match(r"^(tong(\s+cong)?|cong)\b", joined))


def _is_column_index_marker(text):
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    return bool(
        re.fullmatch(r"\(?\d{1,2}\)?", cleaned)
        or re.fullmatch(r"\(?[a-zA-Z]\)?", cleaned)
        or re.fullmatch(r"\(\d+\)\s*=\s*.*", cleaned)
    )


def _is_stt_label(label):
    norm = re.sub(r"[^a-z0-9]", "", _ascii_vn(label).lower())
    return norm in {"stt", "tt", "sothutu"}


def _column_index_to_letter(excel_col_num):
    if get_column_letter:
        return get_column_letter(int(excel_col_num))
    n = int(excel_col_num)
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out or "A"


def _letter_to_column_index(letter):
    val = 0
    for ch in str(letter or "").upper():
        if "A" <= ch <= "Z":
            val = val * 26 + (ord(ch) - 64)
    return val


def _detect_unit_col_index(columns):
    best_idx = None
    best_score = 0
    for col in columns or []:
        if col.get("is_stt"):
            continue
        norm = re.sub(r"\s+", " ", _ascii_vn(col.get("full_label") or col.get("label") or "").lower()).strip()
        leaf_norm = re.sub(r"\s+", " ", _ascii_vn(col.get("label") or "").lower()).strip()
        if leaf_norm in {"don vi", "ten don vi", "dia ban", "co quan don vi", "don vi thuc hien", "don vi xu ly", "don vi bao cao"}:
            return col.get("col_index")
        for token in UNIT_HEADER_TOKENS:
            if token in norm:
                score = 2 if leaf_norm.startswith(token) else 1
                if score > best_score:
                    best_score = score
                    best_idx = col.get("col_index")
    return best_idx


def _percent_decimals_from_format(number_format):
    fmt = str(number_format or "")
    if "%" not in fmt:
        return 1
    m = re.search(r"\.(0+)%", fmt)
    if m:
        return min(4, len(m.group(1)))
    if "0%" in fmt:
        return 0
    return 1


def normalize_column_formula(raw_formula, columns, *, sample_excel_row=None):
    """Chuẩn hóa công thức Excel theo dòng về dạng dùng placeholder {r}, vd: =E{r}/C{r}."""
    expr = str(raw_formula or "").strip()
    if not expr:
        return ""
    if not expr.startswith("="):
        expr = "=" + expr

    valid_letters = {
        str(col.get("col_letter") or "").upper()
        for col in (columns or [])
        if col.get("col_letter")
    }
    if not valid_letters:
        return ""

    # Tách chuỗi ngoài dấu nháy nếu có, thay tham chiếu $E$6 hoặc E6 hoặc chữ cột trần E -> E{r}
    known_funcs = {"SUM", "AVERAGE", "AVG", "MIN", "MAX", "COUNT", "ROUND", "ABS", "IF"}

    def _replace_token(match):
        token = match.group(0)
        dollar_less = token.replace("$", "").upper()
        # Nếu là tên hàm Excel theo sau bởi '(' -> giữ nguyên
        end_pos = match.end()
        if end_pos < len(expr) and expr[end_pos] == "(":
            return token.upper() if dollar_less in known_funcs else token
        m_cell = re.fullmatch(r"([A-Z]{1,3})(\d+)?", dollar_less)
        if not m_cell:
            return token
        col_let, row_str = m_cell.group(1), m_cell.group(2)
        if col_let not in valid_letters:
            return token
        if row_str is None:
            return f"{col_let}{{r}}"
        if sample_excel_row is None or int(row_str) == int(sample_excel_row):
            return f"{col_let}{{r}}"
        return f"{col_let}{{r}}" if abs(int(row_str) - int(sample_excel_row or 0)) <= 2 else token

    body = expr[1:]
    # Xử lý từng token dạng [$]?[A-Za-z]{1,3}[$]?\d*(?!\{)
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch in ('"', "'"):
            quote = ch
            j = i + 1
            while j < len(body) and body[j] != quote:
                j += 1
            out.append(body[i : j + 1])
            i = j + 1
            continue
        if body[i:].startswith("{r}"):
            out.append("{r}")
            i += 3
            continue
        m = re.match(r"\$?[A-Za-z]{1,3}\$?\d*", body[i:])
        if m and (i == 0 or not body[i - 1].isalnum()):
            tok = m.group(0)
            after_pos = i + len(tok)
            if body[after_pos : after_pos + 3] == "{r}":
                col_let = tok.replace("$", "").upper()
                if col_let in valid_letters:
                    out.append(f"{col_let}{{r}}")
                else:
                    out.append(tok)
                i = after_pos + 3
                continue
            dollar_less = tok.replace("$", "").upper()
            is_func = after_pos < len(body) and body[after_pos] == "("
            if is_func:
                out.append(dollar_less if dollar_less in known_funcs else tok)
                i = after_pos
                continue
            m_cell = re.fullmatch(r"([A-Z]{1,3})(\d+)?", dollar_less)
            if m_cell and m_cell.group(1) in valid_letters:
                out.append(f"{m_cell.group(1)}{{r}}")
                i = after_pos
                continue
        out.append(ch)
        i += 1
    normalized = "=" + "".join(out).strip()
    return normalized if len(normalized) > 1 else ""


def render_excel_formula_for_row(formula_tpl, excel_row_num, columns=None):
    """Sinh công thức Excel thật cho dòng excel_row_num (vd: =E6/C6)."""
    tpl = str(formula_tpl or "").strip()
    if not tpl:
        return ""
    if not tpl.startswith("="):
        tpl = "=" + tpl
    return tpl.replace("{r}", str(int(excel_row_num))).replace("{sr}", str(int(excel_row_num)))


def _resolve_formula_col_map(columns):
    letter_to_idx = {}
    for idx, col in enumerate(columns or []):
        letter = str(col.get("col_letter") or "").upper()
        if letter:
            letter_to_idx[letter] = idx
    return letter_to_idx


def evaluate_excel_formula(formula_tpl, row_values, columns):
    """Tính giá trị công thức theo dòng một cách an toàn (không dùng eval)."""
    tpl = str(formula_tpl or "").strip()
    if not tpl:
        return None
    if tpl.startswith("="):
        tpl = tpl[1:].strip()
    if not tpl:
        return None

    letter_to_idx = _resolve_formula_col_map(columns)

    def _cell_num(col_idx):
        if col_idx is None or col_idx < 0 or col_idx >= len(row_values or []):
            return 0.0
        val = _parse_numeric_value(row_values[col_idx])
        return val if val is not None else 0.0

    def _range_nums(start_let, end_let):
        s_num = _letter_to_column_index(start_let)
        e_num = _letter_to_column_index(end_let)
        if s_num > e_num:
            s_num, e_num = e_num, s_num
        nums = []
        for idx, col in enumerate(columns or []):
            c_let = str(col.get("col_letter") or "").upper()
            c_num = _letter_to_column_index(c_let) if c_let else -1
            if s_num <= c_num <= e_num:
                val = _parse_numeric_value(row_values[idx] if idx < len(row_values) else None)
                if val is not None:
                    nums.append(val)
        return nums

    # Tokenizer cho biểu thức Excel an toàn
    tokens = []
    pos = 0
    n = len(tpl)
    while pos < n:
        ch = tpl[pos]
        if ch.isspace():
            pos += 1
            continue
        if tpl[pos : pos + 2] in ("<=", ">=", "<>", "!="):
            tokens.append(("OP", tpl[pos : pos + 2]))
            pos += 2
            continue
        if ch in "+-*/(),:<>=":
            tokens.append(("OP" if ch in "+-*/<>=" else ch, ch))
            pos += 1
            continue
        if ch.isdigit() or (ch == "." and pos + 1 < n and tpl[pos + 1].isdigit()):
            m = re.match(r"\d+(?:\.\d+)?", tpl[pos:])
            tokens.append(("NUM", float(m.group(0))))
            pos += len(m.group(0))
            continue
        if ch in ('"', "'"):
            q = ch
            j = pos + 1
            while j < n and tpl[j] != q:
                j += 1
            tokens.append(("STR", tpl[pos + 1 : j]))
            pos = j + 1
            continue
        m_ref = re.match(r"\$?([A-Za-z]{1,3})\$?(?:\{r\}|\{sr\}|\d+)?", tpl[pos:])
        if m_ref:
            ident = m_ref.group(1).upper()
            full_len = len(m_ref.group(0))
            after = pos + full_len
            if after < n and tpl[after] == "(":
                tokens.append(("FUNC", ident))
                pos = after
                continue
            tokens.append(("REF", ident))
            pos = after
            continue
        return None

    idx_ptr = [0]

    def _peek():
        return tokens[idx_ptr[0]] if idx_ptr[0] < len(tokens) else None

    def _consume():
        tok = _peek()
        idx_ptr[0] += 1
        return tok

    def _parse_expr():
        val = _parse_cmp()
        return val

    def _parse_cmp():
        left = _parse_add()
        while _peek() and _peek()[0] == "OP" and _peek()[1] in ("=", "<>", "!=", "<", "<=", ">", ">="):
            op = _consume()[1]
            right = _parse_add()
            if left is None or right is None:
                left = 0.0
            elif op == "=":
                left = 1.0 if abs(left - right) < 1e-12 else 0.0
            elif op in ("<>", "!="):
                left = 1.0 if abs(left - right) >= 1e-12 else 0.0
            elif op == "<":
                left = 1.0 if left < right else 0.0
            elif op == "<=":
                left = 1.0 if left <= right else 0.0
            elif op == ">":
                left = 1.0 if left > right else 0.0
            elif op == ">=":
                left = 1.0 if left >= right else 0.0
        return left

    def _parse_add():
        left = _parse_mul()
        while _peek() and _peek()[0] == "OP" and _peek()[1] in ("+", "-"):
            op = _consume()[1]
            right = _parse_mul()
            if left is None or right is None:
                return None
            left = (left + right) if op == "+" else (left - right)
        return left

    def _parse_mul():
        left = _parse_unary()
        while _peek() and _peek()[0] == "OP" and _peek()[1] in ("*", "/"):
            op = _consume()[1]
            right = _parse_unary()
            if left is None or right is None:
                return None
            if op == "/":
                if abs(right) < 1e-12:
                    return None
                left = left / right
            else:
                left = left * right
        return left

    def _parse_unary():
        if _peek() and _peek()[0] == "OP" and _peek()[1] in ("+", "-"):
            op = _consume()[1]
            val = _parse_unary()
            if val is None:
                return None
            return -val if op == "-" else val
        return _parse_primary()

    def _collect_func_args():
        args = []
        if _peek() and _peek()[0] == ")":
            _consume()
            return args
        while True:
            # Kiểm tra range REF : REF
            if (
                idx_ptr[0] + 2 < len(tokens)
                and tokens[idx_ptr[0]][0] == "REF"
                and tokens[idx_ptr[0] + 1][0] == ":"
                and tokens[idx_ptr[0] + 2][0] == "REF"
            ):
                s_let = _consume()[1]
                _consume()
                e_let = _consume()[1]
                args.extend(_range_nums(s_let, e_let))
            else:
                val = _parse_expr()
                args.append(val)
            if _peek() and _peek()[0] == ",":
                _consume()
                continue
            if _peek() and _peek()[0] == ")":
                _consume()
                break
            break
        return args

    def _parse_primary():
        tok = _peek()
        if not tok:
            return None
        kind, val = tok
        if kind == "NUM":
            _consume()
            return float(val)
        if kind == "STR":
            _consume()
            num = _parse_numeric_value(val)
            return num if num is not None else 0.0
        if kind == "REF":
            _consume()
            if val not in letter_to_idx:
                return None
            return _cell_num(letter_to_idx[val])
        if kind == "FUNC":
            fn = _consume()[1]
            if not _peek() or _peek()[0] != "(":
                return None
            _consume()
            args = _collect_func_args()
            clean_nums = [a for a in args if a is not None]
            if fn == "SUM":
                return sum(clean_nums) if clean_nums else 0.0
            if fn in ("AVERAGE", "AVG"):
                return (sum(clean_nums) / len(clean_nums)) if clean_nums else None
            if fn == "MIN":
                return min(clean_nums) if clean_nums else None
            if fn == "MAX":
                return max(clean_nums) if clean_nums else None
            if fn == "COUNT":
                return float(len(clean_nums))
            if fn == "ABS":
                return abs(clean_nums[0]) if clean_nums else None
            if fn == "ROUND":
                if not clean_nums:
                    return None
                digits = int(clean_nums[1]) if len(clean_nums) > 1 else 0
                return round(clean_nums[0], digits)
            if fn == "IF":
                cond = args[0] if args else 0.0
                if cond:
                    return args[1] if len(args) > 1 else 0.0
                return args[2] if len(args) > 2 else 0.0
            return None
        if kind == "(":
            _consume()
            val = _parse_expr()
            if _peek() and _peek()[0] == ")":
                _consume()
            return val
        return None

    try:
        res = _parse_expr()
        if res is None or idx_ptr[0] < len(tokens):
            return None
        return float(res)
    except Exception:
        return None


def _format_computed_formula_text(num, col):
    if num is None:
        return ""
    if abs(num) < 1e-12:
        num = 0.0
    if col.get("is_percent"):
        # Giá trị công thức tỷ lệ lưu dạng số thực 6 chữ số (vd 0.9075) để xuất Excel không sai 100x
        rounded = round(float(num), 6)
        return f"{int(rounded)}" if rounded.is_integer() else f"{rounded:.6g}"
    rounded = round(float(num), 4)
    return f"{int(rounded)}" if rounded.is_integer() else f"{rounded:g}"


def format_excel_cell_display(raw_val, col):
    """Định dạng chuỗi hiển thị trên web (hỗ trợ tỷ lệ % và phân tách số)."""
    text = _cell_text(raw_val)
    if not text:
        return ""
    if not col:
        return text
    if col.get("is_percent"):
        if text.endswith("%"):
            return text
        num = _parse_numeric_value(text)
        if num is None:
            return text
        decimals = int(col.get("percent_decimals") if col.get("percent_decimals") is not None else 1)
        if col.get("role") == "formula" or col.get("data_type") == "formula":
            pct = num * 100.0
            return f"{pct:.{decimals}f}%"
        return f"{num:.{decimals}f}%"
    return text


def _infer_column_type(label, samples, is_stt=False):
    if is_stt:
        return "text"
    non_empty = [str(v).strip() for v in (samples or []) if str(v or "").strip() and not str(v).strip().startswith("=")]
    if non_empty:
        num_count = sum(1 for val in non_empty if _parse_numeric_value(val) is not None)
        if num_count / len(non_empty) >= 0.6:
            return "number"
        # Nếu cột đã có dữ liệu mẫu rõ ràng mà chủ yếu là chữ -> giữ text
        if num_count == 0:
            return "text"
    norm = _ascii_vn(label).strip().lower()
    if any(token in norm for token in NUMBER_HEADER_TOKENS) or norm in {"so", "tong", "con lai"}:
        return "number"
    return "text"


def _copy_cell_style(src_cell, dst_cell):
    if not src_cell or not dst_cell:
        return
    if src_cell.has_style:
        dst_cell.font = copy_style(src_cell.font)
        dst_cell.fill = copy_style(src_cell.fill)
        dst_cell.border = copy_style(src_cell.border)
        dst_cell.alignment = copy_style(src_cell.alignment)
        dst_cell.number_format = src_cell.number_format


def _load_workbook_pair(source):
    if load_workbook is None:
        raise ValueError("Máy chủ chưa cài thư viện đọc/ghi Excel (.xlsx).")
    if isinstance(source, (str, os.PathLike)):
        with open(source, "rb") as fh:
            raw_bytes = fh.read()
    else:
        source.seek(0)
        raw_bytes = source.read()
    if not raw_bytes:
        raise ValueError("File Excel trống.")
    try:
        wb_vals = load_workbook(io.BytesIO(raw_bytes), data_only=True)
        wb_raw = load_workbook(io.BytesIO(raw_bytes), data_only=False)
    except Exception as exc:
        raise ValueError("Không đọc được file Excel. Vui lòng dùng file định dạng .xlsx hợp lệ.") from exc
    return wb_vals, wb_raw, raw_bytes


def _pick_non_empty_sheet(wb_vals):
    if wb_vals.active and wb_vals.active.max_row > 0 and wb_vals.active.max_column > 0:
        for row in wb_vals.active.iter_rows(max_row=min(30, wb_vals.active.max_row), values_only=True):
            if any(v is not None and str(v).strip() for v in row):
                return wb_vals.active
    for sheet in wb_vals.worksheets:
        if sheet.max_row > 0 and sheet.max_column > 0:
            for row in sheet.iter_rows(max_row=min(30, sheet.max_row), values_only=True):
                if any(v is not None and str(v).strip() for v in row):
                    return sheet
    raise ValueError("Không tìm thấy dữ liệu trong file Excel.")


def _build_merge_lookup(worksheet):
    merge_origins = {}
    merge_covered = {}
    for cell_range in worksheet.merged_cells.ranges:
        top, left, bottom, right = cell_range.min_row, cell_range.min_col, cell_range.max_row, cell_range.max_col
        merge_origins[(top, left)] = (bottom, right)
        for r in range(top, bottom + 1):
            for c in range(left, right + 1):
                merge_covered[(r, c)] = (top, left)
    return merge_origins, merge_covered


def _used_bounds(ws_vals, merge_origins):
    max_r = min(ws_vals.max_row or 1, 300)
    max_c = min(ws_vals.max_column or 1, MAX_TEMPLATE_COLUMNS)
    min_col = max_c + 1
    max_col = 0
    first_row = max_r + 1
    last_row = 0
    for r in range(1, max_r + 1):
        row_has = False
        for c in range(1, max_c + 1):
            val = ws_vals.cell(row=r, column=c).value
            if val is not None and str(val).strip() != "":
                row_has = True
                if c < min_col:
                    min_col = c
                span_right = merge_origins.get((r, c), (r, c))[1]
                span_right = min(span_right, max_c)
                if span_right > max_col:
                    max_col = span_right
        if row_has:
            first_row = min(first_row, r)
            last_row = max(last_row, r)
    if max_col < min_col or last_row < first_row:
        raise ValueError("File Excel chưa có dữ liệu bảng biểu mẫu.")
    return first_row, last_row, min_col, max_col


def _detect_header_band(ws_vals, merge_origins, merge_covered, first_row, last_row, min_col, max_col):
    num_cols = max_col - min_col + 1
    scan_limit = min(last_row, first_row + MAX_PREVIEW_BANNER_ROWS)

    def _row_non_empty_slots(r):
        slots = []
        for c in range(min_col, max_col + 1):
            origin = merge_covered.get((r, c), (r, c))
            val = _cell_text(ws_vals.cell(row=origin[0], column=origin[1]).value)
            if val:
                slots.append((c, origin, val))
        return slots

    header_start = first_row
    if num_cols >= 2:
        for r in range(first_row, scan_limit + 1):
            slots = _row_non_empty_slots(r)
            distinct_origins = {s[1] for s in slots}
            # Bỏ qua các dòng tiêu đề/banner nằm gộp gần hết bảng ở phía trên
            if len(distinct_origins) >= 2:
                header_start = r
                break

    header_end = header_start
    # Mở rộng theo merge dọc bắt đầu từ header_start
    changed = True
    while changed:
        changed = False
        for r in range(header_start, header_end + 1):
            for c in range(min_col, max_col + 1):
                if (r, c) in merge_origins:
                    bottom, _right = merge_origins[(r, c)]
                    if bottom > header_end and bottom <= min(last_row, header_start + 4):
                        header_end = bottom
                        changed = True

    # Nếu ngay dưới header_end là dòng sub-header hoặc dòng đánh số cột (1), (2)... thì gộp vào header
    for _step in range(2):
        r_next = header_end + 1
        if r_next > min(last_row, header_start + 4):
            break
        next_slots = _row_non_empty_slots(r_next)
        if not next_slots:
            break
        texts = [s[2] for s in next_slots]
        all_markers = len(texts) >= max(2, num_cols // 2) and all(_is_column_index_marker(t) for t in texts)
        has_horizontal_merge = any(
            (r, c) in merge_origins and merge_origins[(r, c)][1] > c
            for r in range(header_start, header_end + 1)
            for c in range(min_col, max_col + 1)
        )
        numeric_body_hits = sum(1 for t in texts if _parse_numeric_value(t) is not None and not _is_column_index_marker(t))
        looks_like_data_row = bool(texts) and (
            _is_stt_label(texts[0]) is False
            and (re.fullmatch(r"\d+\.?", texts[0]) is not None or numeric_body_hits >= max(1, len(texts) // 2))
        )
        if all_markers or (has_horizontal_merge and not looks_like_data_row and header_end == header_start):
            header_end = r_next
            for c in range(min_col, max_col + 1):
                if (header_end, c) in merge_origins:
                    header_end = max(header_end, min(merge_origins[(header_end, c)][0], header_start + 4))
        else:
            break

    return header_start, header_end


def _extract_column_labels(ws_vals, merge_covered, header_start, header_end, min_col, max_col):
    used_keys = set()
    columns = []
    for idx, c in enumerate(range(min_col, max_col + 1), start=1):
        hierarchy = []
        for r in range(header_start, header_end + 1):
            origin = merge_covered.get((r, c), (r, c))
            txt = _cell_text(ws_vals.cell(row=origin[0], column=origin[1]).value)
            if txt and (not hierarchy or hierarchy[-1] != txt):
                hierarchy.append(txt)
        meaningful = [item for item in hierarchy if not _is_column_index_marker(item)]
        leaf_label = (meaningful[-1] if meaningful else (hierarchy[-1] if hierarchy else f"Cột {idx}"))[:255]
        full_label = " — ".join(meaningful or hierarchy or [leaf_label])[:255]

        slug = _ascii_vn(leaf_label).lower()
        slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")[:48]
        base_key = f"excel_c{idx}_{slug}" if slug else f"excel_c{idx}"
        key = base_key
        counter = 2
        while key in used_keys:
            key = f"{base_key}_{counter}"
            counter += 1
        used_keys.add(key)

        col_letter = get_column_letter(c) if get_column_letter else str(c)
        col_dim = ws_vals.column_dimensions.get(col_letter)
        raw_width = getattr(col_dim, "width", None) or 14
        width_px = max(72, min(320, int(float(raw_width) * 8.2)))
        is_stt = _is_stt_label(leaf_label)
        columns.append(
            {
                "col_index": idx - 1,
                "excel_col": c,
                "col_letter": col_letter,
                "field_key": key,
                "label": leaf_label,
                "full_label": full_label,
                "width_px": width_px,
                "is_stt": is_stt,
                "type": "text",
                "data_type": "text",
                "role": "stt" if is_stt else "data",
                "formula": "",
                "is_percent": False,
                "percent_decimals": 1,
                "readonly": False,
            }
        )
    return columns


def _build_header_grid(ws_vals, merge_origins, merge_covered, header_start, header_end, min_col, max_col):
    grid = []
    for r in range(header_start, header_end + 1):
        row_cells = []
        for c in range(min_col, max_col + 1):
            if (r, c) in merge_covered and merge_covered[(r, c)] != (r, c):
                continue
            bottom, right = merge_origins.get((r, c), (r, c))
            rowspan = max(1, min(bottom, header_end) - r + 1)
            colspan = max(1, min(right, max_col) - c + 1)
            text = _cell_text(ws_vals.cell(row=r, column=c).value)
            row_cells.append(
                {
                    "text": text,
                    "rowspan": rowspan,
                    "colspan": colspan,
                    "col_index": c - min_col,
                }
            )
        grid.append(row_cells)
    return grid


def parse_excel_template_layout(source, *, filename="", allow_add_rows=None):
    """Đọc cấu trúc bảng Excel (.xlsx) đầy đủ header gộp ô, banner và dòng mẫu."""
    ext = os.path.splitext(str(filename or ""))[1].lower()
    if ext and ext not in EXCEL_TEMPLATE_ALLOWED_EXTENSIONS:
        raise ValueError("Biểu mẫu Excel hiện hỗ trợ định dạng .xlsx. Vui lòng lưu/chuyển tệp sang .xlsx.")

    wb_vals, wb_raw, _raw_bytes = _load_workbook_pair(source)
    ws_vals = _pick_non_empty_sheet(wb_vals)
    ws_raw = wb_raw[ws_vals.title]

    merge_origins, merge_covered = _build_merge_lookup(ws_vals)
    first_row, last_row, min_col, max_col = _used_bounds(ws_vals, merge_origins)
    header_start, header_end = _detect_header_band(
        ws_vals, merge_origins, merge_covered, first_row, last_row, min_col, max_col
    )

    banner_rows = []
    for r in range(first_row, header_start):
        vals = [
            _cell_text(ws_vals.cell(row=r, column=c).value)
            for c in range(min_col, max_col + 1)
        ]
        joined = " ".join(v for v in vals if v).strip()
        if joined:
            banner_rows.append(joined)

    columns = _extract_column_labels(ws_vals, merge_covered, header_start, header_end, min_col, max_col)
    header_grid = _build_header_grid(ws_vals, merge_origins, merge_covered, header_start, header_end, min_col, max_col)

    data_start = header_end + 1
    template_rows = []
    has_summary_row = False
    summary_label = "Tổng cộng"
    summary_position = "none"
    summary_row_excel = None
    summary_row_formulas = []
    body_start_row = None
    first_raw_row_cells = None
    first_num_formats = [None for _ in columns]
    col_samples = [[] for _ in columns]

    for r in range(data_start, min(last_row + 1, data_start + MAX_TEMPLATE_BODY_ROWS)):
        row_texts = []
        row_raw_formulas = []
        row_has_formula = False
        for c_offset, c in enumerate(range(min_col, max_col + 1)):
            origin = merge_covered.get((r, c), (r, c))
            raw_cell = ws_raw.cell(row=origin[0], column=origin[1])
            val_cell = ws_vals.cell(row=origin[0], column=origin[1])
            raw_val = raw_cell.value
            disp_val = val_cell.value
            is_f = isinstance(raw_val, str) and raw_val.strip().startswith("=")
            if is_f:
                row_has_formula = True
            row_raw_formulas.append(raw_val.strip() if is_f else "")
            text = _cell_text(disp_val if disp_val is not None else ("" if is_f else raw_val))
            row_texts.append(text)
            if first_num_formats[c_offset] is None and getattr(raw_cell, "number_format", None):
                nf_str = str(raw_cell.number_format or "")
                if nf_str and nf_str.lower() != "general":
                    first_num_formats[c_offset] = nf_str
        if not any(row_texts) and not row_has_formula:
            continue
        if _is_summary_row_values(row_texts) or (row_has_formula and _is_summary_row_values(row_texts[:2])):
            has_summary_row = True
            non_empty_first = next((t for t in row_texts[:2] if t), "Tổng cộng")
            summary_label = non_empty_first
            summary_row_excel = r
            summary_position = "bottom" if template_rows else "top"
            summary_row_formulas = [
                f_str.replace(str(r), "{sr}") if (f_str and not re.search(r"SUM\s*\(", f_str, re.I)) else ""
                for f_str in row_raw_formulas
            ]
            continue
        if body_start_row is None:
            body_start_row = r
            first_raw_row_cells = list(row_raw_formulas)
            for c_offset, c in enumerate(range(min_col, max_col + 1)):
                nf = getattr(ws_raw.cell(row=r, column=c), "number_format", None)
                if nf and str(nf).lower() != "general":
                    first_num_formats[c_offset] = str(nf)
        template_rows.append(row_texts)
        for idx, val in enumerate(row_texts):
            if val:
                col_samples[idx].append(val)

    effective_data_start = body_start_row if body_start_row is not None else data_start

    for idx, col in enumerate(columns):
        col["type"] = _infer_column_type(col["full_label"], col_samples[idx], is_stt=col["is_stt"])
        nf = first_num_formats[idx] or ""
        is_pct = "%" in nf
        col["is_percent"] = bool(is_pct)
        col["percent_decimals"] = _percent_decimals_from_format(nf)
        raw_f = first_raw_row_cells[idx] if (first_raw_row_cells and idx < len(first_raw_row_cells)) else ""
        if raw_f:
            norm_f = normalize_column_formula(raw_f, columns, sample_excel_row=effective_data_start)
            if norm_f:
                col["formula"] = norm_f
                col["role"] = "formula"
                col["data_type"] = "formula"
                col["type"] = "number"
                col["readonly"] = True
                continue
        if col["is_stt"]:
            col["role"] = "stt"
            col["data_type"] = "text"
        elif is_pct:
            col["role"] = "data"
            col["data_type"] = "percent"
            col["type"] = "number"
        else:
            col["role"] = "data"
            col["data_type"] = "number" if col["type"] == "number" else "text"

    # Đảm bảo mọi ô của cột công thức trong template_rows có giá trị tính chuẩn
    if any(col.get("role") == "formula" for col in columns):
        for r_vals in template_rows:
            for idx, col in enumerate(columns):
                if col.get("role") == "formula" and col.get("formula"):
                    if idx >= len(r_vals):
                        r_vals.extend([""] * (idx + 1 - len(r_vals)))
                    if not str(r_vals[idx] or "").strip():
                        val = evaluate_excel_formula(col["formula"], r_vals, columns)
                        r_vals[idx] = _format_computed_formula_text(val, col)

    # Phát hiện bảng chỉ tiêu cố định (đã điền sẵn cột chỉ tiêu ở >= 2 dòng, số liệu trống)
    has_prefilled_rows = False
    if len(template_rows) >= 2:
        text_cols = [c["col_index"] for c in columns if c["type"] == "text" and not c["is_stt"]]
        num_cols = [c["col_index"] for c in columns if c["type"] == "number"]
        if text_cols and num_cols:
            first_text_col = text_cols[0]
            filled_labels = sum(1 for row in template_rows if str(row[first_text_col] or "").strip())
            if filled_labels >= len(template_rows):
                has_prefilled_rows = True
                for c in columns:
                    if c["is_stt"] or c["col_index"] in text_cols[:1]:
                        c["readonly"] = True

    resolved_allow_add_rows = (not has_prefilled_rows) if allow_add_rows is None else bool(allow_add_rows)
    if not template_rows:
        template_rows = [[("1" if col["is_stt"] else "") for col in columns]]

    suggested_unit_col_index = _detect_unit_col_index(columns)
    stem = os.path.splitext(os.path.basename(str(filename or "").strip()))[0]
    suggested_title = (banner_rows[0] if banner_rows else "") or stem.replace("_", " ").replace("-", " ").strip() or ws_vals.title
    suggested_title = re.sub(r"\s+", " ", str(suggested_title or "")).strip()[:255]

    return {
        "kind": "excel_template",
        "version": 2,
        "template_filename": os.path.basename(str(filename or "").strip()) or "bieu_mau.xlsx",
        "suggested_title": suggested_title,
        "sheet_name": ws_vals.title,
        "min_col": min_col,
        "max_col": max_col,
        "header_start_row": header_start,
        "header_end_row": header_end,
        "data_start_row": effective_data_start,
        "allow_add_rows": resolved_allow_add_rows,
        "has_prefilled_rows": has_prefilled_rows,
        "has_summary_row": has_summary_row,
        "summary_label": summary_label,
        "summary_position": summary_position,
        "summary_row_excel": summary_row_excel,
        "summary_row_formulas": summary_row_formulas,
        "suggested_unit_col_index": suggested_unit_col_index,
        "unit_col_index": None,
        "assign_row_mode": "shared_table",
        "unit_row_assignments": [],
        "banner_rows": banner_rows,
        "header_grid": header_grid,
        "columns": columns,
        "template_rows": template_rows,
    }


def _apply_formula_columns_to_rows(columns, rows):
    if not rows or not any(col.get("role") == "formula" and col.get("formula") for col in (columns or [])):
        return rows
    num_cols = len(columns or [])
    out = []
    for r in rows:
        row_list = list(r[:num_cols]) if isinstance(r, (list, tuple)) else []
        while len(row_list) < num_cols:
            row_list.append("")
        for c_idx, col in enumerate(columns):
            if col.get("role") == "formula" and col.get("formula"):
                val = evaluate_excel_formula(col["formula"], row_list, columns)
                row_list[c_idx] = _format_computed_formula_text(val, col)
        out.append(row_list)
    return out


def apply_excel_schema_overrides(
    schema,
    *,
    allow_add_rows=None,
    column_types=None,
    column_readonly=None,
    column_roles=None,
    column_data_types=None,
    column_formulas=None,
    column_percents=None,
    unit_col_index=None,
    assign_row_mode=None,
    template_rows=None,
    unit_row_assignments=None,
):
    """Áp dụng tùy chỉnh của người giao (vai trò cột, kiểu dữ liệu, công thức, cột đơn vị & dòng sinh sẵn)."""
    if not isinstance(schema, dict):
        return schema
    updated = json.loads(json.dumps(schema, ensure_ascii=False))
    if allow_add_rows is not None:
        updated["allow_add_rows"] = bool(allow_add_rows)

    cols = updated.get("columns") or []
    type_map = column_types if isinstance(column_types, dict) else {}
    dtype_map = column_data_types if isinstance(column_data_types, dict) else {}
    role_map = column_roles if isinstance(column_roles, dict) else {}
    formula_map = column_formulas if isinstance(column_formulas, dict) else {}
    pct_map = column_percents if isinstance(column_percents, dict) else {}
    ro_set = set(column_readonly) if isinstance(column_readonly, (list, set, tuple)) else None
    sample_row_num = int(updated.get("data_start_row") or (int(updated.get("header_end_row") or 1) + 1))

    resolved_unit_idx = None
    if unit_col_index not in (None, "", -1, "-1"):
        try:
            idx_int = int(unit_col_index)
            if 0 <= idx_int < len(cols):
                resolved_unit_idx = idx_int
        except (TypeError, ValueError):
            resolved_unit_idx = None

    for col in cols:
        idx_int = int(col.get("col_index", 0))
        idx_str = str(idx_int)
        key = str(col.get("field_key") or "")

        if ro_set is not None:
            col["readonly"] = (key in ro_set) or (idx_str in ro_set)

        new_role = role_map.get(key) or role_map.get(idx_str)
        if new_role in {"stt", "unit", "data", "formula"}:
            col["role"] = new_role
            col["is_stt"] = new_role == "stt"
            if new_role == "unit" and resolved_unit_idx is None:
                resolved_unit_idx = idx_int

        new_dtype = dtype_map.get(key) or dtype_map.get(idx_str)
        if new_dtype in {"text", "number", "integer", "percent", "date", "formula"}:
            col["data_type"] = new_dtype
            if new_dtype == "formula":
                col["role"] = "formula"
            elif new_dtype == "percent":
                col["is_percent"] = True

        new_type = type_map.get(key) or type_map.get(idx_str)
        if new_type in {"text", "number"}:
            col["type"] = new_type
            if not new_dtype and col.get("role") not in {"stt", "unit", "formula"}:
                col["data_type"] = new_type

        if key in pct_map or idx_str in pct_map:
            pct_val = pct_map.get(key) if key in pct_map else pct_map.get(idx_str)
            col["is_percent"] = bool(pct_val)

        if key in formula_map or idx_str in formula_map:
            raw_f = formula_map.get(key) if key in formula_map else formula_map.get(idx_str)
            norm_f = normalize_column_formula(raw_f, cols, sample_excel_row=sample_row_num)
            col["formula"] = norm_f
            if norm_f:
                col["role"] = "formula"
                col["data_type"] = "formula"

        # Đồng bộ lại flag chuẩn theo role / data_type cuối cùng
        final_role = col.get("role") or ("stt" if col.get("is_stt") else "data")
        if final_role == "stt":
            col["is_stt"] = True
            col["type"] = "text"
            col["data_type"] = "text"
            col["readonly"] = True
            col["formula"] = ""
        elif final_role == "unit":
            col["is_stt"] = False
            col["type"] = "text"
            col["data_type"] = "text"
            col["readonly"] = True
            col["formula"] = ""
            resolved_unit_idx = idx_int
        elif final_role == "formula" and col.get("formula"):
            col["is_stt"] = False
            col["type"] = "number"
            col["data_type"] = "formula"
            col["readonly"] = True
        else:
            col["role"] = "data"
            col["formula"] = ""
            dt = col.get("data_type") or ("number" if col.get("type") == "number" else "text")
            if dt in {"number", "integer", "percent"}:
                col["type"] = "number"
                if dt == "percent":
                    col["is_percent"] = True
            else:
                col["type"] = "text"

    updated["unit_col_index"] = resolved_unit_idx
    if assign_row_mode in {"unit_rows", "shared_table"}:
        updated["assign_row_mode"] = assign_row_mode
    elif resolved_unit_idx is not None:
        updated["assign_row_mode"] = "unit_rows"

    if isinstance(template_rows, list) and template_rows:
        num_cols = len(cols)
        clean_tpl_rows = []
        for raw_r in template_rows[:MAX_TEMPLATE_BODY_ROWS]:
            row_cells = [_cell_text(raw_r[i]) if i < len(raw_r) else "" for i in range(num_cols)]
            clean_tpl_rows.append(row_cells)
        updated["template_rows"] = clean_tpl_rows

    if isinstance(unit_row_assignments, list):
        updated["unit_row_assignments"] = [
            {
                "row_index": int(item.get("row_index", idx)),
                "unit_code": str(item.get("unit_code") or "").strip(),
                "unit_name": str(item.get("unit_name") or "").strip(),
            }
            for idx, item in enumerate(unit_row_assignments)
            if isinstance(item, dict) and (item.get("unit_name") or item.get("unit_code"))
        ]

    updated["template_rows"] = _apply_formula_columns_to_rows(cols, updated.get("template_rows") or [])
    if updated.get("assign_row_mode") == "unit_rows" and resolved_unit_idx is not None:
        # Chế độ phân dòng đơn vị -> không cộng gộp tất cả các ô theo hàng mẫu như bảng chỉ tiêu cố định
        updated["has_prefilled_rows"] = False
        if allow_add_rows is None:
            updated["allow_add_rows"] = False
    return updated


def load_excel_form_schema(task):
    """Đọc schema Biểu mẫu Excel của Task nếu form_provider == 'excel'."""
    if not task or str(getattr(task, "task_mode", "") or "").strip().upper() != "FORM":
        return None
    if str(getattr(task, "form_provider", "") or "").strip().lower() != "excel":
        return None
    cached = getattr(task, "_excel_form_schema_cache", None)
    if cached is not None:
        return cached
    raw = getattr(task, "outline_table_schema_json", None) or ""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except Exception:
        return None
    if not isinstance(parsed, dict) or parsed.get("kind") != "excel_template":
        return None
    setattr(task, "_excel_form_schema_cache", parsed)
    return parsed


def form_fields_from_excel_schema(schema):
    """Tạo danh sách TaskFormField tương ứng các cột Excel để giữ đồng bộ metadata."""
    fields = []
    for order, col in enumerate(schema.get("columns") or []):
        fields.append(
            {
                "field_key": str(col.get("field_key") or f"excel_c{order + 1}")[:100],
                "field_label": str(col.get("full_label") or col.get("label") or f"Cột {order + 1}")[:255],
                "field_type": "number" if col.get("type") == "number" else "text",
                "field_options_json": json.dumps(
                    {
                        "excel_col_index": col.get("col_index"),
                        "is_stt": bool(col.get("is_stt")),
                        "readonly": bool(col.get("readonly")),
                        "target_type": "all",
                    },
                    ensure_ascii=False,
                ),
                "sort_order": order,
                "is_required": False,
            }
        )
    return fields


def generate_quick_excel_template_bytes(title, column_defs):
    """Sinh file .xlsx chuẩn từ cấu hình cột nhanh trên web."""
    if Workbook is None:
        raise ValueError("Máy chủ chưa cài thư viện tạo Excel (.xlsx).")
    wb = Workbook()
    ws = wb.active
    ws.title = "Bieu mau"
    clean_cols = [c for c in (column_defs or []) if str(c.get("label") or "").strip()]
    if not clean_cols:
        raise ValueError("Cần ít nhất 1 cột cho biểu mẫu Excel.")

    thin_side = Side(border_style="thin", color="CBD5E1")
    border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    header_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    header_font = Font(name="Times New Roman", size=11, bold=True, color="0F172A")
    body_font = Font(name="Times New Roman", size=11, color="0F172A")

    sheet_title = (str(title or "BIỂU MẪU BÁO CÁO SỐ LIỆU").strip() or "BIỂU MẪU BÁO CÁO SỐ LIỆU")[:255]
    ws.cell(row=1, column=1, value=sheet_title.upper())
    ws.cell(row=1, column=1).font = Font(name="Times New Roman", size=13, bold=True, color="0F172A")
    ws.cell(row=1, column=1).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if len(clean_cols) > 1:
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(clean_cols))
    ws.row_dimensions[1].height = 28

    for idx, col in enumerate(clean_cols, start=1):
        cell = ws.cell(row=2, column=idx, value=str(col["label"]).strip())
        cell.font = header_font
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        col_letter = get_column_letter(idx)
        ws.column_dimensions[col_letter].width = 10 if _is_stt_label(col["label"]) else 24

        sample_cell = ws.cell(row=3, column=idx, value="1" if _is_stt_label(col["label"]) else "")
        sample_cell.font = body_font
        sample_cell.border = border
        sample_cell.alignment = Alignment(
            horizontal="center" if _is_stt_label(col["label"]) else ("right" if col.get("type") == "number" else "left"),
            vertical="center",
            wrap_text=True,
        )
    ws.row_dimensions[2].height = 28
    ws.row_dimensions[3].height = 22

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def parse_uploaded_submission_excel(file_storage, schema):
    """Đọc các dòng dữ liệu đơn vị điền trong file .xlsx nộp lại theo template."""
    ext = os.path.splitext(str(getattr(file_storage, "filename", "") or ""))[1].lower()
    if ext not in EXCEL_TEMPLATE_ALLOWED_EXTENSIONS:
        raise ValueError("Vui lòng chọn file Excel .xlsx đúng theo mẫu.")

    wb_vals, _wb_raw, _bytes = _load_workbook_pair(file_storage.stream)
    sheet_name = schema.get("sheet_name")
    if sheet_name and sheet_name in wb_vals.sheetnames:
        ws = wb_vals[sheet_name]
    else:
        ws = _pick_non_empty_sheet(wb_vals)

    min_col = int(schema.get("min_col") or 1)
    columns = schema.get("columns") or []
    max_col = min_col + len(columns) - 1
    data_start = int(schema.get("data_start_row") or (int(schema.get("header_end_row") or 1) + 1))

    rows = []
    for r in range(data_start, min(ws.max_row + 1, data_start + MAX_TEMPLATE_BODY_ROWS)):
        row_vals = [_cell_text(ws.cell(row=r, column=c).value) for c in range(min_col, max_col + 1)]
        if not any(row_vals):
            continue
        if _is_summary_row_values(row_vals):
            continue
        rows.append(row_vals)
    if not rows:
        raise ValueError("Không tìm thấy dữ liệu trong file Excel đã tải lên.")
    return rows


def resolve_unit_rows_for_user(schema, user):
    """Trả về dòng mẫu ban đầu tương ứng với đơn vị của user (hỗ trợ chế độ phân dòng theo đơn vị)."""
    if not isinstance(schema, dict):
        return []
    columns = schema.get("columns") or []
    template_rows = schema.get("template_rows") or []
    unit_col_idx = schema.get("unit_col_index")
    if schema.get("assign_row_mode") != "unit_rows" or unit_col_idx is None:
        return template_rows

    from services.task_units import _task_assignee_unit_name

    unit_name = _task_assignee_unit_name(user) if user else ""
    unit_key = str(getattr(user, "unit_key", "") or "").strip().lower()
    norm_target = re.sub(r"\s+", " ", _ascii_vn(unit_name).lower()).strip()

    matched_rows = []
    assignments = schema.get("unit_row_assignments") or []
    for entry in assignments:
        r_idx = int(entry.get("row_index", -1))
        e_code = str(entry.get("unit_code") or "").strip().lower()
        e_name = re.sub(r"\s+", " ", _ascii_vn(entry.get("unit_name") or "").lower()).strip()
        if (unit_key and e_code and e_code == unit_key) or (norm_target and e_name and e_name == norm_target):
            if 0 <= r_idx < len(template_rows):
                row_copy = list(template_rows[r_idx])
                while len(row_copy) < len(columns):
                    row_copy.append("")
                for c in columns:
                    if c.get("is_stt"):
                        row_copy[c["col_index"]] = "1"
                matched_rows.append(row_copy)

    if not matched_rows:
        for r_vals in template_rows:
            cell_txt = re.sub(r"\s+", " ", _ascii_vn(r_vals[unit_col_idx] if unit_col_idx < len(r_vals) else "").lower()).strip()
            if norm_target and cell_txt and cell_txt == norm_target:
                row_copy = list(r_vals)
                while len(row_copy) < len(columns):
                    row_copy.append("")
                for c in columns:
                    if c.get("is_stt"):
                        row_copy[c["col_index"]] = "1"
                matched_rows.append(row_copy)

    if not matched_rows:
        blank = []
        for c in columns:
            if c.get("is_stt"):
                blank.append("1")
            elif c.get("col_index") == unit_col_idx:
                blank.append(unit_name)
            else:
                blank.append("")
        matched_rows = [blank]
    return _apply_formula_columns_to_rows(columns, matched_rows)


def evaluate_summary_row_values(schema, col_totals_vector):
    """Tính toán từng ô dòng Tổng (tổng số liệu cho cột nhập số và tính công thức cho cột tỷ lệ/công thức)."""
    columns = (schema or {}).get("columns") or []
    num_cols = len(columns)
    row_vec = ["" for _ in range(num_cols)]
    for c_idx, col in enumerate(columns):
        if col.get("role") == "formula":
            continue
        if col.get("type") == "number" and not col.get("is_percent"):
            val = col_totals_vector[c_idx] if c_idx < len(col_totals_vector) else None
            if val is not None:
                row_vec[c_idx] = _format_computed_formula_text(val, col)
    # Sau khi có tổng các cột số liệu, tính công thức cho cột formula (vd Tỷ lệ = Tổng E / Tổng C)
    for c_idx, col in enumerate(columns):
        if col.get("role") == "formula" and col.get("formula"):
            f_val = evaluate_excel_formula(col["formula"], row_vec, columns)
            row_vec[c_idx] = _format_computed_formula_text(f_val, col)
    return row_vec


def normalize_submitted_excel_rows(schema, raw_rows, *, unit_name=None):
    """Chuẩn hóa & validate các dòng dữ liệu đơn vị gửi cho biểu mẫu Excel (tự tính lại công thức)."""
    columns = schema.get("columns") or []
    num_cols = len(columns)
    if num_cols == 0:
        raise ValueError("Biểu mẫu Excel chưa có cột dữ liệu hợp lệ.")

    allow_add_rows = bool(schema.get("allow_add_rows", True))
    is_unit_rows_mode = bool(schema.get("assign_row_mode") == "unit_rows" and schema.get("unit_col_index") is not None)
    unit_col_idx = schema.get("unit_col_index")
    template_rows = schema.get("template_rows") or []

    parsed_rows = []
    for row_idx, raw_row in enumerate(raw_rows or []):
        cells = list(raw_row[:num_cols]) if isinstance(raw_row, (list, tuple)) else []
        while len(cells) < num_cols:
            cells.append("")
        clean_row = []
        for c_idx, col in enumerate(columns):
            if col.get("role") == "formula":
                clean_row.append("")
                continue
            val_text = _cell_text(cells[c_idx])
            # Trong chế độ unit_rows -> khóa cột đơn vị theo đúng đơn vị đang nộp
            if is_unit_rows_mode and c_idx == unit_col_idx and unit_name:
                val_text = str(unit_name).strip()
            elif not is_unit_rows_mode and col.get("readonly") and row_idx < len(template_rows) and c_idx < len(template_rows[row_idx]):
                val_text = _cell_text(template_rows[row_idx][c_idx])

            if col.get("type") == "number" and val_text:
                cleaned_val = val_text[:-1].strip() if (col.get("is_percent") and val_text.endswith("%")) else val_text
                num_val = _parse_numeric_value(cleaned_val)
                if num_val is None:
                    raise ValueError(
                        f"Dòng {row_idx + 1}, cột \"{col.get('label')}\" yêu cầu giá trị số hợp lệ (nhận được: \"{val_text}\")."
                    )
                if col.get("data_type") == "integer" and not float(num_val).is_integer():
                    raise ValueError(
                        f"Dòng {row_idx + 1}, cột \"{col.get('label')}\" yêu cầu số nguyên hợp lệ (nhận được: \"{val_text}\")."
                    )
                val_text = f"{int(num_val)}" if float(num_val).is_integer() else f"{num_val:g}"
            clean_row.append(val_text)
        parsed_rows.append(clean_row)

    if allow_add_rows:
        trimmed = []
        for row in parsed_rows:
            has_editable_content = any(
                str(row[c_idx] or "").strip()
                for c_idx, col in enumerate(columns)
                if not col.get("is_stt")
                and col.get("role") != "formula"
                and not (is_unit_rows_mode and c_idx == unit_col_idx)
            )
            if has_editable_content:
                trimmed.append(row)
        parsed_rows = trimmed
        for idx, row in enumerate(parsed_rows, start=1):
            for c_idx, col in enumerate(columns):
                if col.get("is_stt") and not str(row[c_idx] or "").strip():
                    row[c_idx] = str(idx)
    elif is_unit_rows_mode:
        if not parsed_rows:
            parsed_rows = [
                [("1" if col.get("is_stt") else (str(unit_name or "") if c_i == unit_col_idx else "")) for c_i, col in enumerate(columns)]
            ]
        else:
            parsed_rows = parsed_rows[:1] if len(parsed_rows) > 1 and unit_name else parsed_rows
            for idx, row in enumerate(parsed_rows, start=1):
                for c_idx, col in enumerate(columns):
                    if col.get("is_stt"):
                        row[c_idx] = str(idx)
    else:
        for r_idx in range(len(parsed_rows), len(template_rows)):
            parsed_rows.append([_cell_text(v) for v in template_rows[r_idx][:num_cols]])

    # Tự động tính lại tất cả cột công thức ở server
    parsed_rows = _apply_formula_columns_to_rows(columns, parsed_rows)

    has_any_value = any(
        str(row[c_idx] or "").strip()
        for row in parsed_rows
        for c_idx, col in enumerate(columns)
        if not col.get("readonly") and not col.get("is_stt") and col.get("role") != "formula" and not (is_unit_rows_mode and c_idx == unit_col_idx)
    )
    if not parsed_rows or not has_any_value:
        raise ValueError("Cần nhập ít nhất một ô dữ liệu vào bảng biểu mẫu trước khi gửi.")

    totals = {}
    for c_idx, col in enumerate(columns):
        if col.get("type") != "number" or col.get("role") == "formula" or col.get("is_percent"):
            continue
        col_sum = 0.0
        col_count = 0
        for row in parsed_rows:
            num_val = _parse_numeric_value(row[c_idx]) if c_idx < len(row) else None
            if num_val is not None:
                col_sum += num_val
                col_count += 1
        totals[col["field_key"]] = col_sum if col_count else 0.0

    return parsed_rows, totals


def _excel_payload_rows(payload, schema=None):
    if isinstance(payload, dict) and payload.get("mode") == "excel_sheet" and isinstance(payload.get("rows"), list):
        return payload.get("rows") or []
    if isinstance(payload, dict) and schema:
        # Tương thích nếu payload lưu dạng key -> scalar
        row = [str(payload.get(col["field_key"], "") or "") for col in (schema.get("columns") or [])]
        if any(row):
            return [row]
    return []


def _open_workbook_from_path(template_path):
    if not template_path or not os.path.exists(template_path) or load_workbook is None:
        return None
    try:
        with open(template_path, "rb") as fh:
            raw = fh.read()
        return load_workbook(io.BytesIO(raw))
    except Exception:
        return None


def build_unit_prefilled_excel_bytes(task, schema, template_path=None, unit_rows=None):
    """Tạo file .xlsx để đơn vị tải về điền (giữ nguyên template gốc, điền sẵn dữ liệu nếu đã nộp)."""
    wb = _open_workbook_from_path(template_path)
    if wb is None:
        buf = generate_quick_excel_template_bytes(
            getattr(task, "title", "") or schema.get("suggested_title"),
            schema.get("columns") or [],
        )
        if not unit_rows:
            return buf
        wb = load_workbook(buf)

    if unit_rows:
        sheet_name = schema.get("sheet_name")
        ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active
        min_col = int(schema.get("min_col") or 1)
        data_start = int(schema.get("data_start_row") or (int(schema.get("header_end_row") or 1) + 1))
        columns = schema.get("columns") or []
        style_ref_row = data_start
        is_unit_rows_mode = bool(schema.get("assign_row_mode") == "unit_rows" and schema.get("unit_col_index") is not None)

        if is_unit_rows_mode and ws.max_row >= data_start:
            for merged in list(ws.merged_cells.ranges):
                if merged.max_row >= data_start:
                    ws.unmerge_cells(str(merged))
            for r in range(data_start, ws.max_row + 1):
                for c in range(min_col, min_col + len(columns)):
                    ws.cell(row=r, column=c).value = None

        for r_offset, row_vals in enumerate(unit_rows):
            target_row = data_start + r_offset
            for c_idx, col in enumerate(columns):
                target_col = min_col + c_idx
                cell = ws.cell(row=target_row, column=target_col)
                if r_offset > 0:
                    _copy_cell_style(ws.cell(row=style_ref_row, column=target_col), cell)
                if col.get("role") == "formula" and col.get("formula"):
                    cell.value = render_excel_formula_for_row(col["formula"], target_row, columns)
                    if col.get("is_percent") and "%" not in str(cell.number_format or ""):
                        dec = int(col.get("percent_decimals") or 1)
                        cell.number_format = f"0.{'0' * dec}%" if dec > 0 else "0%"
                    continue
                raw_val = row_vals[c_idx] if c_idx < len(row_vals) else ""
                if col.get("type") == "number" and raw_val not in ("", None):
                    num = _parse_numeric_value(str(raw_val).rstrip("%").strip() if col.get("is_percent") else raw_val)
                    if num is not None:
                        cell.value = int(num) if float(num).is_integer() else num
                    else:
                        cell.value = raw_val
                else:
                    cell.value = str(raw_val or "")
                    if isinstance(cell.value, str):
                        cell.data_type = "s"

        if is_unit_rows_mode and schema.get("summary_position") == "top" and schema.get("summary_row_excel"):
            sr = int(schema["summary_row_excel"])
            last_r = data_start + max(1, len(unit_rows)) - 1
            for c_idx, col in enumerate(columns):
                c_let = _column_index_to_letter(min_col + c_idx)
                sc = ws.cell(row=sr, column=min_col + c_idx)
                if col.get("role") == "formula" and col.get("formula"):
                    sc.value = render_excel_formula_for_row(col["formula"], sr, columns)
                elif col.get("type") == "number" and not col.get("is_percent"):
                    sc.value = f"=SUM({c_let}{data_start}:{c_let}{last_r})"

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def build_aggregated_excel_workbook(task, schema, submission_rows, *, template_path=None):
    """Gộp dữ liệu đã nộp của các đơn vị vào đúng file .xlsx mẫu ban đầu."""
    wb = _open_workbook_from_path(template_path)
    if wb is None:
        buf = generate_quick_excel_template_bytes(
            getattr(task, "title", "") or schema.get("suggested_title"),
            schema.get("columns") or [],
        )
        wb = load_workbook(buf)

    sheet_name = schema.get("sheet_name")
    ws = wb[sheet_name] if sheet_name and sheet_name in wb.sheetnames else wb.active
    columns = schema.get("columns") or []
    min_col = int(schema.get("min_col") or 1)
    header_start = int(schema.get("header_start_row") or 1)
    header_end = int(schema.get("header_end_row") or 1)
    data_start = int(schema.get("data_start_row") or (header_end + 1))
    allow_add_rows = bool(schema.get("allow_add_rows", True))
    has_prefilled_rows = bool(schema.get("has_prefilled_rows"))

    thin_side = Side(border_style="thin", color="CBD5E1")
    fallback_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    header_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
    bold_font = Font(name="Times New Roman", size=11, bold=True, color="0F172A")
    body_font = Font(name="Times New Roman", size=11, color="0F172A")

    # Thu thập dữ liệu từng đơn vị
    submitted_units = []
    for item in submission_rows or []:
        payload = item.get("payload") or {}
        rows = _excel_payload_rows(payload, schema=schema)
        if not rows:
            continue
        submitted_units.append(
            {
                "unit_name": item.get("unit_name") or "",
                "submitter_name": item.get("submitter_name") or "",
                "status_label": item.get("status_label") or "",
                "submitted_at": item.get("submitted_at") or "",
                "rows": rows,
            }
        )

    is_unit_rows_mode = bool(schema.get("assign_row_mode") == "unit_rows" and schema.get("unit_col_index") is not None)

    if is_unit_rows_mode:
        _write_unit_rows_in_template_sheet(
            ws,
            schema,
            columns,
            submission_rows,
            submitted_units,
            min_col=min_col,
            data_start=data_start,
            bold_font=bold_font,
            body_font=body_font,
            header_fill=header_fill,
            border=fallback_border,
        )
        _append_submission_status_sheet(
            wb,
            schema,
            submission_rows,
            bold_font=bold_font,
            body_font=body_font,
            header_fill=header_fill,
            border=fallback_border,
        )
    elif has_prefilled_rows and not allow_add_rows:
        # Sheet 1: Cộng gộp trực tiếp vào đúng các ô của biểu mẫu gốc
        ws.title = "Tong hop"
        template_rows = schema.get("template_rows") or []
        for r_idx in range(len(template_rows)):
            target_row = data_start + r_idx
            for c_idx, col in enumerate(columns):
                if col.get("type") != "number":
                    continue
                target_col = min_col + c_idx
                cell = ws.cell(row=target_row, column=target_col)
                # Giữ nguyên công thức Excel của template nếu có
                if isinstance(cell.value, str) and cell.value.strip().startswith("="):
                    continue
                if col.get("role") == "formula" and col.get("formula"):
                    cell.value = render_excel_formula_for_row(col["formula"], target_row, columns)
                    continue
                total = 0.0
                has_val = False
                for unit_item in submitted_units:
                    if r_idx < len(unit_item["rows"]) and c_idx < len(unit_item["rows"][r_idx]):
                        num = _parse_numeric_value(unit_item["rows"][r_idx][c_idx])
                        if num is not None:
                            total += num
                            has_val = True
                if has_val:
                    cell.value = int(total) if total.is_integer() else total
                else:
                    cell.value = 0

        detail_ws = wb.create_sheet(title="Chi tiet don vi")
        _write_unit_rows_sheet(
            detail_ws,
            columns,
            submitted_units,
            bold_font=bold_font,
            body_font=body_font,
            header_fill=header_fill,
            border=fallback_border,
        )
    else:
        # Bảng động: Giữ banner + header gốc, chèn 2 cột "Đơn vị báo cáo", "Thời điểm nộp" ở đầu hoặc ghi sạch vào sheet
        _write_dynamic_aggregated_sheet(
            ws,
            schema,
            columns,
            submitted_units,
            min_col=min_col,
            header_start=header_start,
            header_end=header_end,
            data_start=data_start,
            bold_font=bold_font,
            body_font=body_font,
            header_fill=header_fill,
            border=fallback_border,
        )
        _append_submission_status_sheet(
            wb,
            schema,
            submission_rows,
            bold_font=bold_font,
            body_font=body_font,
            header_fill=header_fill,
            border=fallback_border,
        )

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def _append_submission_status_sheet(wb, schema, submission_rows, *, bold_font, body_font, header_fill, border):
    status_ws = wb.create_sheet(title="Trang thai nop")
    status_headers = ["Đơn vị / Đối tượng", "Người thực hiện", "Trạng thái", "Thời điểm nộp", "Số dòng đã nộp"]
    status_ws.append(status_headers)
    for col_idx in range(1, len(status_headers) + 1):
        c = status_ws.cell(row=1, column=col_idx)
        c.font = bold_font
        c.fill = header_fill
        c.border = border
        c.alignment = Alignment(horizontal="center", vertical="center")
        status_ws.column_dimensions[_column_index_to_letter(col_idx)].width = 24
    for item in submission_rows or []:
        row_count = len(_excel_payload_rows(item.get("payload") or {}, schema=schema))
        status_ws.append(
            [
                item.get("unit_name") or "",
                item.get("submitter_name") or "",
                item.get("status_label") or "",
                item.get("submitted_at") or "",
                row_count,
            ]
        )
        cur_r = status_ws.max_row
        for col_idx in range(1, len(status_headers) + 1):
            cell = status_ws.cell(row=cur_r, column=col_idx)
            cell.font = body_font
            cell.border = border


def _write_unit_rows_in_template_sheet(
    ws,
    schema,
    columns,
    submission_rows,
    submitted_units,
    *,
    min_col,
    data_start,
    bold_font,
    body_font,
    header_fill,
    border,
):
    """Xuất bảng tổng hợp giữ nguyên cột Đơn vị trong biểu mẫu gốc + công thức Excel thật."""
    unit_col_idx = int(schema.get("unit_col_index"))
    allow_add_rows = bool(schema.get("allow_add_rows", False))

    sample_data_styles = []
    for idx in range(len(columns)):
        sc = ws.cell(row=data_start, column=min_col + idx)
        sample_data_styles.append(
            {
                "font": copy_style(sc.font) if sc.has_style and sc.font else body_font,
                "border": copy_style(sc.border) if sc.has_style and sc.border else border,
                "alignment": copy_style(sc.alignment) if sc.has_style and sc.alignment else Alignment(vertical="center", wrap_text=True),
                "number_format": sc.number_format if sc.has_style else "General",
            }
        )

    for merged in list(ws.merged_cells.ranges):
        if merged.max_row >= data_start:
            ws.unmerge_cells(str(merged))

    if ws.max_row >= data_start:
        for r in range(data_start, ws.max_row + 1):
            for c in range(1, ws.max_column + 1):
                ws.cell(row=r, column=c).value = None

    sub_by_unit = {}
    for unit_item in submitted_units:
        norm_u = re.sub(r"\s+", " ", _ascii_vn(unit_item.get("unit_name") or "").lower()).strip()
        if norm_u:
            sub_by_unit.setdefault(norm_u, []).extend(unit_item.get("rows") or [])

    output_rows = []
    if not allow_add_rows:
        used_keys = set()
        for r_idx, tpl_row in enumerate(schema.get("template_rows") or []):
            u_label = _cell_text(tpl_row[unit_col_idx] if unit_col_idx < len(tpl_row) else "")
            norm_u = re.sub(r"\s+", " ", _ascii_vn(u_label).lower()).strip()
            if norm_u and norm_u in sub_by_unit and sub_by_unit[norm_u]:
                used_keys.add(norm_u)
                row_vals = list(sub_by_unit[norm_u][0])
                if unit_col_idx < len(row_vals) and u_label:
                    row_vals[unit_col_idx] = u_label
                output_rows.append(row_vals)
            else:
                output_rows.append(list(tpl_row))
        # Gắn thêm đơn vị đã nộp nếu không nằm trong danh sách mẫu ban đầu
        for unit_item in submitted_units:
            norm_u = re.sub(r"\s+", " ", _ascii_vn(unit_item.get("unit_name") or "").lower()).strip()
            if norm_u and norm_u not in used_keys:
                used_keys.add(norm_u)
                for r_vals in unit_item.get("rows") or []:
                    output_rows.append(list(r_vals))
    else:
        for unit_item in submitted_units:
            for r_vals in unit_item.get("rows") or []:
                output_rows.append(list(r_vals))

    cur_row = data_start
    for idx, row_vals in enumerate(output_rows, start=1):
        for c_idx, col in enumerate(columns):
            target_col = min_col + c_idx
            cell = ws.cell(row=cur_row, column=target_col)
            st = sample_data_styles[c_idx]
            cell.font = copy_style(st["font"]) if st["font"] and st["font"].name else body_font
            cell.border = copy_style(st["border"]) if st["border"] and st["border"].bottom.style else border
            cell.alignment = copy_style(st["alignment"])
            cell.number_format = st["number_format"] or "General"
            if col.get("is_stt"):
                cell.value = idx
            elif col.get("role") == "formula" and col.get("formula"):
                cell.value = render_excel_formula_for_row(col["formula"], cur_row, columns)
                if col.get("is_percent") and "%" not in str(cell.number_format or ""):
                    dec = int(col.get("percent_decimals") or 1)
                    cell.number_format = f"0.{'0' * dec}%" if dec > 0 else "0%"
            else:
                raw_val = row_vals[c_idx] if c_idx < len(row_vals) else ""
                if col.get("type") == "number" and raw_val not in ("", None):
                    num = _parse_numeric_value(str(raw_val).rstrip("%").strip() if col.get("is_percent") else raw_val)
                    if num is not None:
                        cell.value = int(num) if float(num).is_integer() else num
                    else:
                        cell.value = raw_val
                else:
                    cell.value = str(raw_val or "")
                    cell.data_type = "s"
        cur_row += 1

    last_data_row = max(data_start, cur_row - 1)
    if schema.get("summary_position") == "top" and schema.get("summary_row_excel") and output_rows:
        sr = int(schema["summary_row_excel"])
        for c_idx, col in enumerate(columns):
            target_col = min_col + c_idx
            c_let = _column_index_to_letter(target_col)
            cell = ws.cell(row=sr, column=target_col)
            if col.get("role") == "formula" and col.get("formula"):
                cell.value = render_excel_formula_for_row(col["formula"], sr, columns)
                if col.get("is_percent") and "%" not in str(cell.number_format or ""):
                    dec = int(col.get("percent_decimals") or 1)
                    cell.number_format = f"0.{'0' * dec}%" if dec > 0 else "0%"
            elif col.get("type") == "number" and not col.get("is_percent"):
                cell.value = f"=SUM({c_let}{data_start}:{c_let}{last_data_row})"
    elif any(col.get("type") == "number" for col in columns) and output_rows:
        for c_idx, col in enumerate(columns):
            target_col = min_col + c_idx
            c_let = _column_index_to_letter(target_col)
            cell = ws.cell(row=cur_row, column=target_col)
            cell.font = bold_font
            cell.fill = header_fill
            cell.border = border
            if c_idx == unit_col_idx:
                cell.value = schema.get("summary_label") or "Tổng cộng"
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col.get("role") == "formula" and col.get("formula"):
                cell.value = render_excel_formula_for_row(col["formula"], cur_row, columns)
                cell.alignment = Alignment(horizontal="right", vertical="center")
                if col.get("is_percent"):
                    dec = int(col.get("percent_decimals") or 1)
                    cell.number_format = f"0.{'0' * dec}%" if dec > 0 else "0%"
            elif col.get("type") == "number" and not col.get("is_percent"):
                cell.value = f"=SUM({c_let}{data_start}:{c_let}{last_data_row})"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                cell.value = ""


def _write_unit_rows_sheet(ws, columns, submitted_units, *, bold_font, body_font, header_fill, border):
    headers = ["Đơn vị báo cáo", "Người nộp", "Thời điểm nộp"] + [col.get("full_label") or col.get("label") for col in columns]
    ws.append(headers)
    for idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=idx)
        cell.font = bold_font
        cell.fill = header_fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(idx)].width = 24 if idx <= 3 else 18

    for unit_item in submitted_units:
        for row_vals in unit_item["rows"]:
            out_row = [unit_item["unit_name"], unit_item["submitter_name"], unit_item["submitted_at"]]
            for c_idx, col in enumerate(columns):
                raw_val = row_vals[c_idx] if c_idx < len(row_vals) else ""
                if col.get("type") == "number" and raw_val not in ("", None):
                    num = _parse_numeric_value(raw_val)
                    out_row.append(num if num is not None else raw_val)
                else:
                    out_row.append(str(raw_val or ""))
            ws.append(out_row)
            cur_r = ws.max_row
            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row=cur_r, column=col_idx)
                c.font = body_font
                c.border = border
                if isinstance(c.value, str):
                    c.data_type = "s"


def _write_dynamic_aggregated_sheet(
    ws,
    schema,
    columns,
    submitted_units,
    *,
    min_col,
    header_start,
    header_end,
    data_start,
    bold_font,
    body_font,
    header_fill,
    border,
):
    # Chụp trước style header & body và danh sách merge ở banner/header (openpyxl insert_cols không dịch merged_cells)
    sample_header_cell = ws.cell(row=header_start, column=min_col)
    hdr_font = copy_style(sample_header_cell.font) if sample_header_cell.has_style else bold_font
    hdr_fill = copy_style(sample_header_cell.fill) if sample_header_cell.has_style else header_fill
    hdr_align = copy_style(sample_header_cell.alignment) if sample_header_cell.has_style else Alignment(horizontal="center", vertical="center", wrap_text=True)

    sample_data_styles = []
    for idx in range(len(columns)):
        sc = ws.cell(row=data_start, column=min_col + idx)
        sample_data_styles.append(
            {
                "font": copy_style(sc.font) if sc.has_style and sc.font else body_font,
                "border": copy_style(sc.border) if sc.has_style and sc.border else border,
                "alignment": copy_style(sc.alignment) if sc.has_style and sc.alignment else Alignment(vertical="center", wrap_text=True),
                "number_format": sc.number_format if sc.has_style else "General",
            }
        )

    orig_col_widths = [
        getattr(ws.column_dimensions.get(get_column_letter(min_col + idx)), "width", None) or 16
        for idx in range(len(columns))
    ]

    saved_top_merges = []
    for merged in list(ws.merged_cells.ranges):
        if merged.max_row < data_start:
            saved_top_merges.append((merged.min_row, merged.min_col, merged.max_row, merged.max_col))
        ws.unmerge_cells(str(merged))

    # Xóa sạch dữ liệu mẫu từ data_start trở xuống
    if ws.max_row >= data_start:
        for r in range(data_start, ws.max_row + 1):
            for c in range(1, ws.max_column + 1):
                ws.cell(row=r, column=c).value = None

    # Chèn 1 cột "Đơn vị báo cáo" ngay trước min_col
    ws.insert_cols(min_col, amount=1)
    ws.column_dimensions[get_column_letter(min_col)].width = 28
    for idx, width in enumerate(orig_col_widths):
        ws.column_dimensions[get_column_letter(min_col + 1 + idx)].width = width

    # Khôi phục merge banner/header sau khi đã dịch +1 cột
    for r_min, c_min, r_max, c_max in saved_top_merges:
        if r_max < header_start and c_min == min_col:
            # Banner bắt đầu từ cột đầu bảng -> dời text sang min_col và nối dài hết bảng mới
            val = ws.cell(row=r_min, column=min_col + 1).value
            ws.cell(row=r_min, column=min_col, value=val)
            _copy_cell_style(ws.cell(row=r_min, column=min_col + 1), ws.cell(row=r_min, column=min_col))
            ws.cell(row=r_min, column=min_col + 1).value = None
            ws.merge_cells(start_row=r_min, start_column=min_col, end_row=r_max, end_column=c_max + 1)
        elif c_min >= min_col:
            ws.merge_cells(start_row=r_min, start_column=c_min + 1, end_row=r_max, end_column=c_max + 1)
        else:
            ws.merge_cells(start_row=r_min, start_column=c_min, end_row=r_max, end_column=c_max + 1)

    unit_hdr = ws.cell(row=header_start, column=min_col, value="Đơn vị báo cáo")
    unit_hdr.font = copy_style(hdr_font)
    unit_hdr.fill = copy_style(hdr_fill)
    unit_hdr.border = border
    unit_hdr.alignment = copy_style(hdr_align)
    if header_end > header_start:
        for extra_r in range(header_start + 1, header_end + 1):
            ws.cell(row=extra_r, column=min_col).border = border
            ws.cell(row=extra_r, column=min_col).fill = copy_style(hdr_fill)
        ws.merge_cells(start_row=header_start, start_column=min_col, end_row=header_end, end_column=min_col)

    cur_row = data_start
    for unit_item in submitted_units:
        for row_vals in unit_item["rows"]:
            u_cell = ws.cell(row=cur_row, column=min_col, value=unit_item["unit_name"])
            u_cell.font = body_font
            u_cell.border = border
            u_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            u_cell.data_type = "s"
            for c_idx, col in enumerate(columns):
                target_col = min_col + 1 + c_idx
                cell = ws.cell(row=cur_row, column=target_col)
                st = sample_data_styles[c_idx]
                cell.font = copy_style(st["font"]) if st["font"] and st["font"].name else body_font
                cell.border = copy_style(st["border"]) if st["border"] and st["border"].bottom.style else border
                cell.alignment = copy_style(st["alignment"])
                cell.number_format = st["number_format"] or "General"
                raw_val = row_vals[c_idx] if c_idx < len(row_vals) else ""
                if col.get("type") == "number" and raw_val not in ("", None):
                    num = _parse_numeric_value(raw_val)
                    cell.value = num if num is not None else raw_val
                else:
                    cell.value = str(raw_val or "")
                    cell.data_type = "s"
            cur_row += 1

    # Thêm dòng Tổng cộng tự động với công thức SUM nếu có cột số liệu và có dữ liệu
    has_numeric = any(col.get("type") == "number" for col in columns)
    if has_numeric and cur_row > data_start:
        last_data_row = cur_row - 1
        sum_label_cell = ws.cell(row=cur_row, column=min_col, value=schema.get("summary_label") or "Tổng cộng")
        sum_label_cell.font = bold_font
        sum_label_cell.fill = header_fill
        sum_label_cell.border = border
        sum_label_cell.alignment = Alignment(horizontal="center", vertical="center")
        for c_idx, col in enumerate(columns):
            target_col = min_col + 1 + c_idx
            c_letter = get_column_letter(target_col)
            cell = ws.cell(row=cur_row, column=target_col)
            cell.font = bold_font
            cell.fill = header_fill
            cell.border = border
            if col.get("type") == "number":
                cell.value = f"=SUM({c_letter}{data_start}:{c_letter}{last_data_row})"
                cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                cell.value = ""


def parse_staged_filename(raw_name):
    """Làm sạch tên file tạm đã stage trong thư mục task_files."""
    cleaned = secure_filename(str(raw_name or "").strip())
    if not cleaned or not cleaned.startswith("staged_excel_"):
        return ""
    return cleaned


def make_staged_excel_filename(original_filename):
    ext = os.path.splitext(secure_filename(original_filename or "bieu_mau.xlsx"))[1].lower()
    if ext not in EXCEL_TEMPLATE_ALLOWED_EXTENSIONS:
        ext = ".xlsx"
    return f"staged_excel_{uuid.uuid4().hex[:10]}{ext}"
