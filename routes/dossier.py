"""
Phân hệ Sổ Theo Dõi Thời Hạn Hồ Sơ & Chỉ Tiêu Hàng Ngày — PhanMemPC06_Pro
Hỗ trợ:
- Nhập lẻ hồ sơ thủ công & cảnh báo Quá hạn / Sắp đến hạn / Trong hạn / Đã trả.
- Tải file Excel (.xlsx/.csv), ảnh chụp bảng số liệu hoặc dán bảng để tự nhận diện thành các tab riêng:
  Tạm trú | Thường trú | Phiếu XM CT10 | Tích hợp giấy tờ | Làm sạch dữ liệu | Hồ sơ khác.
- Phân quyền theo đơn vị xử lý / địa bàn tiếp nhận để các đơn vị tự tích hoàn thành hàng ngày.
"""
import io
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from flask import Blueprint, current_app, jsonify, render_template, request, send_file, session

from models import AppSetting, Dossier, Unit, User, db
from permissions import load_current_authz
from services.dossier_importer import (
    DOSSIER_TAB_DEFS,
    DOSSIER_TAB_LABELS,
    VALID_TABS,
    _norm_vn,
    build_unit_matcher,
    get_dossier_loai_defs,
    get_dossier_loai_labels,
    get_dossier_tab_defs,
    get_dossier_tab_labels,
    get_user_dossier_identity,
    get_valid_dossier_tabs,
    parse_dossier_upload,
)
from utils import apply_migrations, is_unit_match, render_auto_template

dossier_bp = Blueprint("dossier_bp", __name__)

REMIND_DAYS_DEFAULT = 2

LOAI_LABELS = {
    "can-cuoc": "Căn cước",
    "cu-tru": "Cư trú",
    "dinh-danh": "Định danh VNeID",
    "xac-thuc": "Xác thực ĐA06",
    "khac": "Hồ sơ khác",
}

ALLOWED_UPLOAD_EXTS = {
    ".xlsx",
    ".xlsm",
    ".csv",
    ".tsv",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
}


def _require_login():
    return bool(session.get("uid"))


def _ensure_dossier_schema():
    """Bảo đảm bảng dossiers và app_setting có đầy đủ ngay cả trên DB cũ chưa migrate."""
    runtime_flags = current_app.extensions.setdefault("pc06_runtime_flags", {})
    db_uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI", ""))
    done_uris = runtime_flags.setdefault("dossier_migrated_uris", set())
    if db_uri in done_uris:
        return
    try:
        apply_migrations(current_app)
        AppSetting.__table__.create(db.engine, checkfirst=True)
        done_uris.add(db_uri)
    except Exception as exc:
        current_app.logger.warning(f"Dossier migration safeguard failed: {exc}")


DOSSIER_COL_WIDTHS_KEY = "dossier_column_widths_v1"


def _sanitize_width_list(raw_widths):
    if not isinstance(raw_widths, list) or not (2 <= len(raw_widths) <= 60):
        return None
    cleaned = []
    for v in raw_widths:
        try:
            iv = int(round(float(v)))
        except (TypeError, ValueError):
            return None
        cleaned.append(max(32, min(1200, iv)))
    return cleaned


def _load_dossier_column_widths():
    try:
        AppSetting.__table__.create(db.engine, checkfirst=True)
        row = db.session.get(AppSetting, DOSSIER_COL_WIDTHS_KEY)
        if not row or not row.value:
            return {}
        parsed = json.loads(row.value)
        if not isinstance(parsed, dict):
            return {}
        out = {}
        for k, v in parsed.items():
            key_s = str(k or "").strip()
            w_list = _sanitize_width_list(v)
            if key_s and len(key_s) <= 240 and w_list:
                out[key_s] = w_list
        return out
    except Exception as exc:
        current_app.logger.warning(f"Load dossier column widths failed: {exc}")
        return {}


def _save_dossier_column_widths(widths_map, uid=None):
    AppSetting.__table__.create(db.engine, checkfirst=True)
    row = db.session.get(AppSetting, DOSSIER_COL_WIDTHS_KEY)
    payload = json.dumps(widths_map or {}, ensure_ascii=False)
    if not row:
        row = AppSetting(key=DOSSIER_COL_WIDTHS_KEY, value=payload, updated_by=uid, updated_at=datetime.now())
        db.session.add(row)
    else:
        row.value = payload
        row.updated_by = uid
        row.updated_at = datetime.now()
    db.session.commit()


def _parse_extra_json(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except Exception:
        return {}


def _parse_positive_int_order(val):
    """Phân tích số thứ tự nguyên không âm từ giá trị ô Excel/extra."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if val >= 0 else None
    if isinstance(val, float):
        return int(val) if val >= 0 else None
    s = str(val).strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d+)(?:\.0+)?\.?", s)
    return int(m.group(1)) if m else None


def _extract_dossier_source_order(extra):
    """Lấy thứ tự dòng gốc theo file Excel/nguồn nhập (ưu tiên source_row_index, sau đó cột STT)."""
    if not isinstance(extra, dict):
        return None
    row_idx = _parse_positive_int_order(extra.get("source_row_index"))
    if row_idx is not None:
        return row_idx
    stt_val = _parse_positive_int_order(extra.get("stt"))
    if stt_val is not None:
        return stt_val
    headers = extra.get("source_headers")
    cells = extra.get("row_cells")
    if isinstance(headers, list) and isinstance(cells, list):
        for i, hdr in enumerate(headers):
            if i < len(cells) and _norm_vn(hdr) in ("stt", "tt", "so tt", "so thu tu", "#"):
                parsed = _parse_positive_int_order(cells[i])
                if parsed is not None:
                    return parsed
                break
    return None


def _dossier_sort_key(dossier, extra=None):
    """Sắp xếp danh sách hồ sơ giữ đúng thứ tự gốc từ file Excel/nguồn nhập; hồ sơ thủ công xếp theo hạn trả."""
    ex = extra if isinstance(extra, dict) else _parse_extra_json(dossier.extra_json)
    status_rank = 1 if dossier.trang_thai == "da_tra" else 0
    source_order = _extract_dossier_source_order(ex)
    is_imported = bool((dossier.source_type or "manual") != "manual" or source_order is not None)
    if is_imported:
        rep_ord = -(dossier.report_date.toordinal()) if dossier.report_date else 0
        if source_order is not None:
            return (status_rank, 0, rep_ord, 0, source_order, dossier.id or 0)
        return (status_rank, 0, rep_ord, 1, dossier.id or 0, 0)
    han_ord = dossier.han_tra.toordinal() if dossier.han_tra else 9999999
    return (status_rank, 1, han_ord, 0, -(dossier.id or 0), 0)


def _is_ct10_overdue(dossier, extra=None):
    if dossier.category_tab != "ct10":
        return False
    ex = extra if extra is not None else _parse_extra_json(dossier.extra_json)
    try:
        return int(ex.get("qua_han") or 0) > 0
    except (TypeError, ValueError):
        return False


def _calc_dossier_state(dossier, today, extra=None):
    """Tính trạng thái cảnh báo: overdue | soon | pending | done."""
    if dossier.trang_thai == "da_tra":
        return "done"
    if _is_ct10_overdue(dossier, extra=extra):
        return "overdue"
    has_deadline = True if dossier.has_deadline is None else bool(dossier.has_deadline)
    if not has_deadline or not dossier.han_tra:
        return "pending"
    diff = (dossier.han_tra - today).days
    if diff < 0:
        return "overdue"
    if diff <= REMIND_DAYS_DEFAULT:
        return "soon"
    return "pending"


def _scope_dossier_query(query, current_user, uid):
    ident = get_user_dossier_identity(current_user)
    conds = [Dossier.created_by == uid]
    if ident["unit_code"]:
        conds.append(Dossier.unit_code == ident["unit_code"])
    if ident["unit_key"]:
        conds.append(
            db.and_(
                Dossier.unit_key == ident["unit_key"],
                db.or_(Dossier.unit_code.is_(None), Dossier.unit_code == ""),
            )
        )
    if ident["area_variants"]:
        conds.append(Dossier.unit_area.in_(list(ident["area_variants"])))
    return query.filter(db.or_(*conds))


def _dossier_belongs_to_user(dossier, current_user, uid):
    if dossier.created_by == uid:
        return True
    ident = get_user_dossier_identity(current_user)
    if ident["unit_code"] and dossier.unit_code and dossier.unit_code == ident["unit_code"]:
        return True
    if (
        ident["unit_key"]
        and dossier.unit_key
        and not (dossier.unit_code and ident["unit_code"] and dossier.unit_code != ident["unit_code"])
        and dossier.unit_key == ident["unit_key"]
    ):
        return True
    if dossier.unit_area and ident["area_variants"]:
        if dossier.unit_area in ident["area_variants"]:
            return True
        for v in ident["area_variants"]:
            if is_unit_match(dossier.unit_area, v):
                return True
    return False


def _serialize_dossier(d, today, is_manager, current_user, uid):
    extra = _parse_extra_json(d.extra_json)
    state = _calc_dossier_state(d, today, extra=extra)
    has_deadline = True if d.has_deadline is None else bool(d.has_deadline)
    days_left = (d.han_tra - today).days if (has_deadline and d.han_tra) else None
    valid_tabs = get_valid_dossier_tabs()
    tab_labels = get_dossier_tab_labels()
    loai_labels = get_dossier_loai_labels()
    tab_key = d.category_tab or "khac"
    if tab_key not in valid_tabs:
        tab_key = "khac"
    can_manage_row = is_manager or (d.created_by == uid)
    can_complete_row = can_manage_row or _dossier_belongs_to_user(d, current_user, uid)

    return {
        "id": d.id,
        "ma_ho_so": d.ma_ho_so,
        "so_ho_so": d.so_ho_so or d.ma_ho_so,
        "loai": d.loai,
        "loai_label": loai_labels.get(d.loai, d.loai or "Hồ sơ khác"),
        "category_tab": tab_key,
        "category_tab_label": tab_labels.get(tab_key, tab_key or "Hồ sơ khác"),
        "thu_tuc": d.thu_tuc or "",
        "ngay_nop": d.ngay_nop.strftime("%Y-%m-%d") if d.ngay_nop else "",
        "ngay_tiep_nhan": d.ngay_tiep_nhan.strftime("%Y-%m-%d") if d.ngay_tiep_nhan else "",
        "han_tra": d.han_tra.strftime("%Y-%m-%d") if d.han_tra else "",
        "has_deadline": has_deadline,
        "tinh_dung_han": d.tinh_dung_han or "",
        "can_bo": d.can_bo or "",
        "ghi_chu": d.ghi_chu or "",
        "trang_thai": d.trang_thai,
        "trang_thai_nguon": d.trang_thai_nguon or "",
        "da_tra_at": d.da_tra_at.strftime("%d/%m/%Y %H:%M") if d.da_tra_at else "",
        "hoan_thanh_by": d.hoan_thanh_by,
        "hoan_thanh_by_name": d.hoan_thanh_by_name or "",
        "hoan_thanh_note": d.hoan_thanh_note or "",
        "state": state,
        "days_left": days_left,
        "created_by": d.created_by,
        "author_name": d.author.fullname if d.author else "",
        "unit_area": d.unit_area or "",
        "unit_code": d.unit_code or "",
        "unit_key": d.unit_key or "",
        "report_date": d.report_date.strftime("%Y-%m-%d") if d.report_date else "",
        "import_batch_id": d.import_batch_id or "",
        "source_type": d.source_type or "manual",
        "source_name": d.source_name or "",
        "extra": extra,
        "can_edit": can_manage_row,
        "can_complete": can_complete_row,
    }


def _parse_iso_or_vn_date(val):
    s = (val or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@dossier_bp.route("/dossiers")
def list_dossiers_page():
    """Giao diện Sổ theo dõi thời hạn hồ sơ & chỉ tiêu hàng ngày."""
    if not _require_login():
        return render_template("login.html")
    _ensure_dossier_schema()
    from services.executive_summary import is_province_wide_viewer
    authz = load_current_authz()
    user = authz.get("user")
    ident = get_user_dossier_identity(user)
    return render_auto_template(
        "dossiers.html",
        is_admin=authz["is_admin"],
        can_view_all_dossiers=is_province_wide_viewer(authz),
        dossier_tabs=get_dossier_tab_defs(),
        dossier_loais=get_dossier_loai_defs(),
        column_widths_map=_load_dossier_column_widths(),
        user_unit_name=ident.get("unit_name", ""),
        user_unit_code=ident.get("unit_code", ""),
    )


@dossier_bp.route("/api/dossiers", methods=["GET"])
def api_list_dossiers():
    """API lấy danh sách hồ sơ theo tab phân hệ, đơn vị và trạng thái."""
    if not _require_login():
        return jsonify({"error": "Unauthorized"}), 401
    _ensure_dossier_schema()

    from services.executive_summary import is_province_wide_viewer
    authz = load_current_authz()
    uid = session.get("uid")
    current_user = db.session.get(User, uid)
    is_manager = bool(authz["is_admin"])
    can_view_all = is_province_wide_viewer(authz)

    base_q = Dossier.query
    if not can_view_all:
        base_q = _scope_dossier_query(base_q, current_user, uid)

    active_tabs = get_dossier_tab_defs(include_inactive=True)
    valid_tabs = get_valid_dossier_tabs()

    # Tính badge pending / total cho toàn bộ các tab (theo phạm vi người dùng nhìn thấy)
    tab_counts = {
        "all": {"pending": 0, "done": 0, "total": 0},
    }
    for td in active_tabs:
        tab_counts[td["key"]] = {"pending": 0, "done": 0, "total": 0}

    category_tab = (request.args.get("category_tab") or "").strip()
    active_scope_tab = category_tab if (category_tab and category_tab != "all" and category_tab in valid_tabs) else "all"

    unit_options_map = {}
    for tab_val, tt_val, u_code, u_area in base_q.with_entities(
        Dossier.category_tab, Dossier.trang_thai, Dossier.unit_code, Dossier.unit_area
    ).all():
        t_key = tab_val if tab_val in valid_tabs else "khac"
        is_done = tt_val == "da_tra"
        tab_counts["all"]["total"] += 1
        tab_counts.setdefault(t_key, {"pending": 0, "done": 0, "total": 0})
        tab_counts[t_key]["total"] += 1
        if is_done:
            tab_counts["all"]["done"] += 1
            tab_counts[t_key]["done"] += 1
        else:
            tab_counts["all"]["pending"] += 1
            tab_counts[t_key]["pending"] += 1
        if active_scope_tab == "all" or t_key == active_scope_tab:
            label = (u_area or u_code or "").strip()
            if label:
                key = (u_code or label).strip()
                unit_options_map.setdefault(key, label)

    q = base_q

    if active_scope_tab != "all":
        if active_scope_tab == "khac":
            q = q.filter(db.or_(Dossier.category_tab == "khac", Dossier.category_tab.is_(None), Dossier.category_tab == ""))
        else:
            q = q.filter(Dossier.category_tab == active_scope_tab)

    search = (request.args.get("q") or "").strip()
    if search:
        like_pat = f"%{search}%"
        q = q.filter(
            db.or_(
                Dossier.ma_ho_so.ilike(like_pat),
                Dossier.so_ho_so.ilike(like_pat),
                Dossier.thu_tuc.ilike(like_pat),
                Dossier.can_bo.ilike(like_pat),
                Dossier.unit_area.ilike(like_pat),
                Dossier.ghi_chu.ilike(like_pat),
                Dossier.trang_thai_nguon.ilike(like_pat),
            )
        )

    loai_filter = (request.args.get("loai") or "").strip()
    if loai_filter:
        q = q.filter(Dossier.loai == loai_filter)

    unit_filter = (request.args.get("unit_filter") or "").strip()
    if unit_filter:
        q = q.filter(db.or_(Dossier.unit_code == unit_filter, Dossier.unit_area == unit_filter, Dossier.unit_key == unit_filter))

    report_date_filter = _parse_iso_or_vn_date(request.args.get("report_date"))
    if report_date_filter:
        q = q.filter(Dossier.report_date == report_date_filter)

    status_filter = (request.args.get("trang_thai") or "dang_xu_ly").strip()
    state_filter = (request.args.get("state_filter") or "").strip()
    if state_filter not in ("overdue", "soon", "pending", "done"):
        state_filter = ""

    # Tính toàn bộ thống kê (quá hạn / sắp đến hạn / đang xử lý / đã hoàn thành) theo ĐÚNG phạm vi lĩnh vực + bộ lọc hiện tại
    scoped_rows = q.order_by(Dossier.id.asc()).all()

    today = date.today()
    counts = {"overdue": 0, "soon": 0, "pending": 0, "done": 0}
    sortable_result = []
    for d in scoped_rows:
        item = _serialize_dossier(d, today, is_manager, current_user, uid)
        counts[item["state"]] += 1
        if state_filter:
            if item["state"] != state_filter:
                continue
        elif status_filter != "all" and d.trang_thai != status_filter:
            continue
        sortable_result.append((_dossier_sort_key(d, item.get("extra")), item))
    sortable_result.sort(key=lambda pair: pair[0])
    result = [item for _, item in sortable_result]

    units_list = sorted(
        [{"value": k, "label": v} for k, v in unit_options_map.items()],
        key=lambda x: x["label"],
    )

    return jsonify(
        {
            "dossiers": result,
            "counts": counts,
            "tab_counts": tab_counts,
            "active_category_tab": active_scope_tab,
            "units": units_list,
            "remind_days": REMIND_DAYS_DEFAULT,
            "today": today.strftime("%Y-%m-%d"),
            "is_admin": is_manager,
            "column_widths_map": _load_dossier_column_widths(),
        }
    )


@dossier_bp.route("/api/dossiers", methods=["POST"])
def api_create_dossier():
    """Thêm mới một hồ sơ theo dõi hạn thủ công."""
    if not _require_login():
        return jsonify({"error": "Unauthorized"}), 401
    _ensure_dossier_schema()

    data = request.get_json(silent=True) or {}
    ma_ho_so = (data.get("ma_ho_so") or data.get("name") or data.get("code") or data.get("dossier_code") or data.get("title") or "").strip()
    han_tra_str = (data.get("han_tra") or data.get("deadline") or data.get("due_date") or "").strip()

    if not ma_ho_so:
        return jsonify({"error": "Vui lòng nhập mã hoặc tên hồ sơ"}), 400
    if not han_tra_str:
        return jsonify({"error": "Vui lòng chọn ngày hết hạn trả kết quả"}), 400

    han_tra = _parse_iso_or_vn_date(han_tra_str)
    if not han_tra:
        return jsonify({"error": "Ngày hết hạn không đúng định dạng YYYY-MM-DD"}), 400

    ngay_tiep_nhan = _parse_iso_or_vn_date(data.get("ngay_tiep_nhan"))
    valid_tabs = get_valid_dossier_tabs()
    category_tab = (data.get("category_tab") or "").strip()
    if category_tab not in valid_tabs:
        category_tab = "khac"

    uid = session.get("uid")
    usr = db.session.get(User, uid)
    authz = load_current_authz()
    ident = get_user_dossier_identity(usr)

    requested_unit = (data.get("unit_area") or "").strip()
    if requested_unit and authz["is_admin"]:
        matcher = build_unit_matcher()
        resolved = matcher(requested_unit)
        unit_area = resolved["unit_area"]
        unit_code = resolved["unit_code"]
        unit_key = resolved["unit_key"]
    else:
        unit_area = ident.get("unit_name") or getattr(usr, "unit_area", "") or ""
        unit_code = ident.get("unit_code") or ""
        unit_key = ident.get("unit_key") or ""

    dossier = Dossier(
        ma_ho_so=ma_ho_so,
        so_ho_so=ma_ho_so,
        loai=data.get("loai") or "can-cuoc",
        category_tab=category_tab,
        thu_tuc=(data.get("thu_tuc") or "").strip() or None,
        can_bo=(data.get("can_bo") or "").strip() or None,
        ngay_tiep_nhan=ngay_tiep_nhan or date.today(),
        han_tra=han_tra,
        has_deadline=True,
        ghi_chu=(data.get("ghi_chu") or "").strip(),
        trang_thai="dang_xu_ly",
        created_by=uid,
        unit_area=unit_area,
        unit_code=unit_code,
        unit_key=unit_key,
        source_type="manual",
    )

    db.session.add(dossier)
    db.session.commit()

    return jsonify({"success": True, "id": dossier.id, "category_tab": dossier.category_tab})


@dossier_bp.route("/api/dossiers/parse-upload", methods=["POST"])
def api_parse_dossier_upload():
    """Nhận file Excel/CSV/ảnh hoặc text dán bảng, phân loại và trả bản xem trước."""
    if not _require_login():
        return jsonify({"error": "Unauthorized"}), 401
    _ensure_dossier_schema()

    if request.content_type and "multipart/form-data" in request.content_type:
        uploaded = request.files.get("file")
        raw_text = (request.form.get("raw_text") or "").strip()
        sheet_name = (request.form.get("sheet_name") or "").strip()
        override_tab = (request.form.get("override_tab") or "").strip()
        override_report_date = (request.form.get("override_report_date") or "").strip()

        file_bytes = None
        filename = ""
        if uploaded and uploaded.filename:
            filename = uploaded.filename
            ext = os.path.splitext(filename)[1].lower()
            if ext not in ALLOWED_UPLOAD_EXTS:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": f"Định dạng '{ext}' không được hỗ trợ. Vui lòng tải file .xlsx, .csv hoặc ảnh .png/.jpg/.webp.",
                        }
                    ),
                    400,
                )
            file_bytes = uploaded.read()
            if len(file_bytes) > 15 * 1024 * 1024:
                return jsonify({"ok": False, "error": "File vượt quá giới hạn 15MB."}), 400
    else:
        payload = request.get_json(silent=True) or {}
        file_bytes = None
        filename = (payload.get("filename") or "").strip()
        raw_text = (payload.get("raw_text") or "").strip()
        sheet_name = (payload.get("sheet_name") or "").strip()
        override_tab = (payload.get("override_tab") or "").strip()
        override_report_date = (payload.get("override_report_date") or "").strip()

    result = parse_dossier_upload(
        file_bytes=file_bytes,
        filename=filename,
        raw_text=raw_text,
        sheet_name=sheet_name,
        override_tab=override_tab,
        override_report_date=override_report_date,
    )
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@dossier_bp.route("/api/dossiers/bulk-import", methods=["POST"])
def api_bulk_import_dossiers():
    """Nhập hàng loạt các dòng đã kiểm tra từ Excel / ảnh / dán bảng vào sổ theo dõi."""
    if not _require_login():
        return jsonify({"error": "Unauthorized"}), 401
    _ensure_dossier_schema()

    authz = load_current_authz()
    uid = session.get("uid")
    current_user = db.session.get(User, uid)
    is_manager = bool(authz["is_admin"])
    user_ident = get_user_dossier_identity(current_user)

    data = request.get_json(silent=True) or {}
    records = data.get("records") or []
    if not isinstance(records, list) or not records:
        return jsonify({"error": "Không có dòng dữ liệu nào được chọn để nhập."}), 400

    valid_tabs = get_valid_dossier_tabs()
    category_tab = (data.get("category_tab") or "").strip()
    if category_tab not in valid_tabs:
        category_tab = "khac"

    import_mode = (data.get("import_mode") or "upsert").strip()
    if import_mode not in ("upsert", "replace_pending"):
        import_mode = "upsert"

    source_type = (data.get("source_type") or "excel").strip()[:32]
    source_name = (data.get("source_name") or "").strip()[:255]
    batch_report_date = _parse_iso_or_vn_date(data.get("report_date")) or date.today()
    batch_id = uuid.uuid4().hex[:12]
    matcher = build_unit_matcher()

    if import_mode == "replace_pending":
        del_q = Dossier.query.filter(
            Dossier.category_tab == category_tab,
            Dossier.trang_thai == "dang_xu_ly",
        )
        if not is_manager:
            del_q = _scope_dossier_query(del_q, current_user, uid)
        del_q.delete(synchronize_session=False)

    created = 0
    updated = 0
    skipped = 0

    default_loai_map = {
        "tam_tru": "cu-tru",
        "thuong_tru": "cu-tru",
        "ct10": "xac-thuc",
        "tich_hop": "dinh-danh",
        "lam_sach": "xac-thuc",
        "khac": "khac",
    }

    for rec_pos, raw_rec in enumerate(records, start=1):
        if not isinstance(raw_rec, dict):
            skipped += 1
            continue
        if raw_rec.get("include") is False:
            skipped += 1
            continue

        ma_hs = (raw_rec.get("ma_ho_so") or raw_rec.get("so_ho_so") or "").strip()
        if not ma_hs:
            skipped += 1
            continue
        so_hs = (raw_rec.get("so_ho_so") or ma_hs).strip()[:255]
        rec_tab = (raw_rec.get("category_tab") or category_tab).strip()
        if rec_tab not in valid_tabs:
            rec_tab = category_tab

        unit_raw = (raw_rec.get("unit_area") or "").strip()
        if is_manager:
            unit_code = (raw_rec.get("unit_code") or "").strip()
            unit_key = (raw_rec.get("unit_key") or "").strip()
            if unit_raw and (not unit_code or not unit_key):
                resolved = matcher(unit_raw)
                unit_code = unit_code or resolved["unit_code"]
                unit_key = unit_key or resolved["unit_key"]
        else:
            # Cán bộ đơn vị nhập chỉ gắn phạm vi đơn vị của mình nếu dòng chưa khớp hoặc thuộc đơn vị khác
            resolved = matcher(unit_raw) if unit_raw else {}
            same_unit = bool(
                (resolved.get("unit_code") and user_ident["unit_code"] and resolved["unit_code"] == user_ident["unit_code"])
                or (resolved.get("unit_key") and user_ident["unit_key"] and resolved["unit_key"] == user_ident["unit_key"])
            )
            if same_unit:
                unit_code = resolved.get("unit_code") or user_ident["unit_code"]
                unit_key = resolved.get("unit_key") or user_ident["unit_key"]
            else:
                unit_area = unit_raw or user_ident.get("unit_name", "")
                unit_code = user_ident["unit_code"]
                unit_key = user_ident["unit_key"]
                unit_raw = unit_area

        rep_d = _parse_iso_or_vn_date(raw_rec.get("report_date")) or batch_report_date
        ngay_nop_d = _parse_iso_or_vn_date(raw_rec.get("ngay_nop"))
        ngay_tn_d = _parse_iso_or_vn_date(raw_rec.get("ngay_tiep_nhan"))
        han_tra_d = _parse_iso_or_vn_date(raw_rec.get("han_tra")) or rep_d
        has_dl = bool(raw_rec.get("has_deadline"))
        extra_dict = dict(raw_rec.get("extra")) if isinstance(raw_rec.get("extra"), dict) else {}
        if _parse_positive_int_order(extra_dict.get("source_row_index")) is None:
            extra_dict["source_row_index"] = rec_pos
        extra_str = json.dumps(extra_dict, ensure_ascii=False) if extra_dict else None
        src_status = (raw_rec.get("trang_thai_nguon") or "").strip()[:150]
        rec_status = "da_tra" if raw_rec.get("trang_thai") == "da_tra" else "dang_xu_ly"

        existing = None
        if import_mode == "upsert" and so_hs:
            existing_q = Dossier.query.filter(
                Dossier.category_tab == rec_tab,
                Dossier.so_ho_so == so_hs,
            )
            if not is_manager:
                existing_q = _scope_dossier_query(existing_q, current_user, uid)
            existing = existing_q.first()

        if existing:
            existing.ma_ho_so = ma_hs[:255]
            existing.thu_tuc = (raw_rec.get("thu_tuc") or existing.thu_tuc or "")[:255] or None
            existing.ngay_nop = ngay_nop_d or existing.ngay_nop
            existing.ngay_tiep_nhan = ngay_tn_d or existing.ngay_tiep_nhan
            existing.han_tra = han_tra_d or existing.han_tra
            existing.has_deadline = has_dl
            existing.tinh_dung_han = (raw_rec.get("tinh_dung_han") or existing.tinh_dung_han or "")[:64] or None
            existing.can_bo = (raw_rec.get("can_bo") or existing.can_bo or "")[:150] or None
            existing.unit_area = unit_raw[:255] if unit_raw else existing.unit_area
            existing.unit_code = (unit_code or existing.unit_code or "")[:64] or None
            existing.unit_key = (unit_key or existing.unit_key or "")[:100] or None
            existing.trang_thai_nguon = src_status or existing.trang_thai_nguon
            existing.ghi_chu = (raw_rec.get("ghi_chu") or existing.ghi_chu or "")
            existing.report_date = rep_d
            existing.import_batch_id = batch_id
            existing.source_type = source_type
            existing.source_name = source_name or existing.source_name
            if extra_str:
                existing.extra_json = extra_str
            # Nếu file nguồn mới báo đã xong thì cập nhật hoàn thành; nếu đang xử lý giữ nguyên nếu đơn vị đã tích xong hoặc cập nhật
            if rec_status == "da_tra" and existing.trang_thai != "da_tra":
                existing.trang_thai = "da_tra"
                existing.da_tra_at = datetime.now()
            updated += 1
        else:
            row = Dossier(
                ma_ho_so=ma_hs[:255],
                so_ho_so=so_hs,
                loai=(raw_rec.get("loai") or default_loai_map.get(rec_tab, "khac"))[:50],
                category_tab=rec_tab,
                thu_tuc=(raw_rec.get("thu_tuc") or "")[:255] or None,
                ngay_nop=ngay_nop_d,
                ngay_tiep_nhan=ngay_tn_d,
                han_tra=han_tra_d,
                has_deadline=has_dl,
                tinh_dung_han=(raw_rec.get("tinh_dung_han") or "")[:64] or None,
                can_bo=(raw_rec.get("can_bo") or "")[:150] or None,
                ghi_chu=(raw_rec.get("ghi_chu") or ""),
                trang_thai=rec_status,
                trang_thai_nguon=src_status or None,
                da_tra_at=datetime.now() if rec_status == "da_tra" else None,
                created_by=uid,
                unit_area=unit_raw[:255] if unit_raw else None,
                unit_code=unit_code[:64] if unit_code else None,
                unit_key=unit_key[:100] if unit_key else None,
                report_date=rep_d,
                import_batch_id=batch_id,
                source_type=source_type,
                source_name=source_name or None,
                extra_json=extra_str,
            )
            db.session.add(row)
            created += 1

    db.session.commit()
    return jsonify(
        {
            "success": True,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "batch_id": batch_id,
            "category_tab": category_tab,
        }
    )


@dossier_bp.route("/api/dossiers/<int:id>", methods=["PUT"])
def api_update_dossier(id):
    """Cập nhật thông tin hồ sơ."""
    if not _require_login():
        return jsonify({"error": "Unauthorized"}), 401
    _ensure_dossier_schema()

    dossier = db.session.get(Dossier, id)
    if not dossier:
        return jsonify({"error": "Không tìm thấy hồ sơ"}), 404

    authz = load_current_authz()
    uid = session.get("uid")
    current_user = db.session.get(User, uid)
    if not (authz["is_admin"] or dossier.created_by == uid or _dossier_belongs_to_user(dossier, current_user, uid)):
        return jsonify({"error": "Bạn không có quyền chỉnh sửa hồ sơ của đơn vị khác"}), 403

    data = request.get_json(silent=True) or {}
    ma_ho_so = (data.get("ma_ho_so") or data.get("name") or data.get("code") or data.get("dossier_code") or data.get("title") or "").strip()
    han_tra_str = (data.get("han_tra") or data.get("deadline") or data.get("due_date") or "").strip()

    if ma_ho_so:
        dossier.ma_ho_so = ma_ho_so
    if data.get("loai"):
        dossier.loai = data.get("loai")
    if data.get("category_tab") in VALID_TABS:
        dossier.category_tab = data.get("category_tab")

    if han_tra_str:
        parsed_dl = _parse_iso_or_vn_date(han_tra_str)
        if not parsed_dl:
            return jsonify({"error": "Ngày hết hạn không hợp lệ"}), 400
        dossier.han_tra = parsed_dl
        dossier.has_deadline = True

    if data.get("ngay_tiep_nhan"):
        parsed_tn = _parse_iso_or_vn_date(data.get("ngay_tiep_nhan"))
        if parsed_tn:
            dossier.ngay_tiep_nhan = parsed_tn

    if "ghi_chu" in data:
        dossier.ghi_chu = (data.get("ghi_chu") or "").strip()
    if "thu_tuc" in data:
        dossier.thu_tuc = (data.get("thu_tuc") or "").strip() or None
    if "can_bo" in data:
        dossier.can_bo = (data.get("can_bo") or "").strip() or None

    db.session.commit()
    return jsonify({"success": True})


@dossier_bp.route("/api/dossiers/<int:id>", methods=["DELETE"])
def api_delete_dossier(id):
    """Xóa hồ sơ."""
    if not _require_login():
        return jsonify({"error": "Unauthorized"}), 401
    _ensure_dossier_schema()

    dossier = db.session.get(Dossier, id)
    if not dossier:
        return jsonify({"error": "Không tìm thấy hồ sơ"}), 404

    authz = load_current_authz()
    uid = session.get("uid")
    if not (authz["is_admin"] or dossier.created_by == uid):
        return jsonify({"error": "Chỉ quản trị hoặc người tạo mới được xóa hồ sơ này"}), 403

    db.session.delete(dossier)
    db.session.commit()
    return jsonify({"success": True})


_DOSSIER_CASE_TABS = {"thuong_tru", "tam_tru", "khac"}


def _is_dossier_awaiting_receive(dossier, extra=None):
    """Hồ sơ cá nhân chưa có ngày tiếp nhận được xem là hồ sơ chờ tiếp nhận."""
    tab_key = (dossier.category_tab or "khac").strip()
    if tab_key not in _DOSSIER_CASE_TABS:
        return False
    ex = extra if isinstance(extra, dict) else _parse_extra_json(dossier.extra_json)
    raw_tn = (ex.get("ngay_tiep_nhan_raw") or "").strip()
    if dossier.ngay_tiep_nhan is None and not raw_tn:
        return True
    if raw_tn and _norm_vn(raw_tn) in ("--", "-", "chua tiep nhan", "cho tiep nhan"):
        return True
    return False


def _sync_extra_row_cells(extra, ngay_tn_vn=None, new_source_status=None):
    """Đồng bộ giá trị Ngày tiếp nhận và Trạng thái trong row_cells gốc sau khi chuyển trạng thái."""
    if not isinstance(extra, dict):
        return extra
    headers = extra.get("source_headers")
    cells = extra.get("row_cells")
    if isinstance(headers, list) and isinstance(cells, list) and len(headers) == len(cells):
        for idx, hdr in enumerate(headers):
            norm_h = _norm_vn(hdr)
            if ngay_tn_vn is not None and norm_h in ("ngay tiep nhan", "ngay nhan", "thoi gian tiep nhan"):
                cells[idx] = ngay_tn_vn
            elif new_source_status is not None and any(k in norm_h for k in ("trang thai", "tinh trang")):
                cells[idx] = new_source_status
    return extra


def _apply_dossier_status_transition(dossier, requested_status, uid, actor_name, note="", now_dt=None):
    """Áp dụng chuyển trạng thái 2 bước cho hồ sơ:
    - Chưa có ngày tiếp nhận -> chuyển thành Đang xử lý + gán ngày tiếp nhận là hôm nay.
    - Đã có ngày tiếp nhận -> hoàn thành (da_tra).
    """
    now_dt = now_dt or datetime.now()
    today_d = now_dt.date()
    today_vn = today_d.strftime("%d/%m/%Y")
    extra = _parse_extra_json(dossier.extra_json)

    if requested_status == "da_tra":
        if _is_dossier_awaiting_receive(dossier, extra=extra):
            dossier.trang_thai = "dang_xu_ly"
            dossier.ngay_tiep_nhan = today_d
            dossier.trang_thai_nguon = "Hồ sơ đang xử lý"
            dossier.da_tra_at = None
            dossier.hoan_thanh_by = None
            dossier.hoan_thanh_by_name = None
            extra["ngay_tiep_nhan_raw"] = today_vn
            _sync_extra_row_cells(extra, ngay_tn_vn=today_vn, new_source_status="Hồ sơ đang xử lý")
            dossier.extra_json = json.dumps(extra, ensure_ascii=False)
            return "received"

        dossier.trang_thai = "da_tra"
        dossier.da_tra_at = now_dt
        dossier.hoan_thanh_by = uid
        dossier.hoan_thanh_by_name = actor_name
        if note:
            dossier.hoan_thanh_note = note
        return "completed"

    dossier.trang_thai = "dang_xu_ly"
    dossier.da_tra_at = None
    dossier.hoan_thanh_by = None
    dossier.hoan_thanh_by_name = None
    if note is not None:
        dossier.hoan_thanh_note = note or None
    return "reopened"


@dossier_bp.route("/api/dossiers/<int:id>/status", methods=["POST"])
def api_set_dossier_status(id):
    """Cập nhật bước xử lý / hoàn thành cho hồ sơ theo đơn vị hoặc quản trị."""
    if not _require_login():
        return jsonify({"error": "Unauthorized"}), 401
    _ensure_dossier_schema()

    dossier = db.session.get(Dossier, id)
    if not dossier:
        return jsonify({"error": "Không tìm thấy hồ sơ"}), 404

    authz = load_current_authz()
    uid = session.get("uid")
    current_user = db.session.get(User, uid)
    if not (authz["is_admin"] or dossier.created_by == uid or _dossier_belongs_to_user(dossier, current_user, uid)):
        return jsonify({"error": "Bạn không thuộc đơn vị xử lý hồ sơ này"}), 403

    data = request.get_json(silent=True) or {}
    trang_thai = data.get("trang_thai")
    if trang_thai not in ("dang_xu_ly", "da_tra"):
        return jsonify({"error": "Trạng thái không hợp lệ"}), 400

    actor_name = (getattr(current_user, "fullname", None) or getattr(current_user, "username", None) or "").strip()
    has_note_key = ("note" in data or "hoan_thanh_note" in data)
    note_val = (data.get("note") or data.get("hoan_thanh_note") or "").strip()
    stage = _apply_dossier_status_transition(
        dossier,
        trang_thai,
        uid,
        actor_name,
        note=(note_val if (trang_thai == "da_tra" or has_note_key) else None),
    )

    db.session.commit()
    return jsonify(
        {
            "success": True,
            "action_stage": stage,
            "trang_thai": dossier.trang_thai,
            "ngay_tiep_nhan": dossier.ngay_tiep_nhan.strftime("%Y-%m-%d") if dossier.ngay_tiep_nhan else "",
            "ngay_tiep_nhan_vn": dossier.ngay_tiep_nhan.strftime("%d/%m/%Y") if dossier.ngay_tiep_nhan else "",
            "trang_thai_nguon": dossier.trang_thai_nguon or "",
            "hoan_thanh_by_name": dossier.hoan_thanh_by_name or "",
            "da_tra_at": dossier.da_tra_at.strftime("%d/%m/%Y %H:%M") if dossier.da_tra_at else "",
        }
    )


@dossier_bp.route("/api/dossiers/bulk-status", methods=["POST"])
def api_bulk_dossier_status():
    """Tích hoàn thành hoặc xóa hàng loạt cho các dòng được chọn."""
    if not _require_login():
        return jsonify({"error": "Unauthorized"}), 401
    _ensure_dossier_schema()

    authz = load_current_authz()
    uid = session.get("uid")
    current_user = db.session.get(User, uid)
    is_manager = bool(authz["is_admin"])

    data = request.get_json(silent=True) or {}
    ids = [int(i) for i in (data.get("ids") or []) if str(i).isdigit()]
    action = (data.get("action") or data.get("trang_thai") or "").strip()
    note = (data.get("note") or "").strip()

    if not ids:
        return jsonify({"error": "Chưa chọn dòng nào"}), 400
    if action not in ("da_tra", "dang_xu_ly", "delete"):
        return jsonify({"error": "Thao tác không hợp lệ"}), 400

    rows = Dossier.query.filter(Dossier.id.in_(ids)).all()
    affected = 0
    received_count = 0
    completed_count = 0
    actor_name = (getattr(current_user, "fullname", None) or getattr(current_user, "username", None) or "").strip()
    now_dt = datetime.now()

    for d in rows:
        if action == "delete":
            if not (is_manager or d.created_by == uid):
                continue
            db.session.delete(d)
            affected += 1
        else:
            if not (is_manager or d.created_by == uid or _dossier_belongs_to_user(d, current_user, uid)):
                continue
            stage = _apply_dossier_status_transition(
                d,
                action,
                uid,
                actor_name,
                note=(note if action == "da_tra" else None),
                now_dt=now_dt,
            )
            if stage == "received":
                received_count += 1
            elif stage == "completed":
                completed_count += 1
            affected += 1

    db.session.commit()
    return jsonify({
        "success": True,
        "affected": affected,
        "received": received_count,
        "completed": completed_count,
    })


@dossier_bp.route("/api/dossiers/export", methods=["GET"])
def api_export_dossiers():
    """Xuất Excel danh sách theo dõi & tiến độ hoàn thành của các đơn vị."""
    if not _require_login():
        return jsonify({"error": "Unauthorized"}), 401
    _ensure_dossier_schema()

    authz = load_current_authz()
    uid = session.get("uid")
    current_user = db.session.get(User, uid)
    is_manager = bool(authz["is_admin"])

    q = Dossier.query
    if not is_manager:
        q = _scope_dossier_query(q, current_user, uid)

    valid_tabs = get_valid_dossier_tabs()
    category_tab = (request.args.get("category_tab") or "").strip()
    if category_tab and category_tab != "all" and category_tab in valid_tabs:
        q = q.filter(Dossier.category_tab == category_tab)
    status_filter = (request.args.get("trang_thai") or "").strip()
    if status_filter:
        q = q.filter(Dossier.trang_thai == status_filter)
    unit_filter = (request.args.get("unit_filter") or "").strip()
    if unit_filter:
        q = q.filter(db.or_(Dossier.unit_code == unit_filter, Dossier.unit_area == unit_filter, Dossier.unit_key == unit_filter))

    raw_rows = q.order_by(Dossier.id.asc()).all()
    rows_with_extra = [(d, _parse_extra_json(d.extra_json)) for d in raw_rows]
    rows_with_extra.sort(key=lambda pair: ((pair[0].category_tab or "khac"), _dossier_sort_key(pair[0], pair[1])))

    wb = openpyxl.Workbook()
    ws = wb.active
    tab_labels = get_dossier_tab_labels()
    tab_title = tab_labels.get(category_tab, "Tổng hợp theo dõi")
    ws.title = "Theo doi ho so"

    ws.append([f"BÁO CÁO THEO DÕI HỒ SƠ & CHỈ TIÊU — {tab_title.upper()} ({date.today().strftime('%d/%m/%Y')})"])
    ws["A1"].font = Font(bold=True, size=13)
    headers = [
        "STT",
        "Phân hệ",
        "Số hồ sơ / Chỉ tiêu",
        "Đơn vị xử lý / Địa bàn",
        "Thủ tục / Nhóm",
        "Ngày nộp / Số liệu",
        "Ngày tiếp nhận",
        "Hạn trả",
        "Cán bộ tiếp nhận",
        "Trạng thái gốc",
        "Kết quả thực hiện",
        "Người tích hoàn thành",
        "Thời gian hoàn thành",
        "Ghi chú",
    ]
    ws.append(headers)
    hdr_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    hdr_font = Font(bold=True, color="FFFFFF")
    for c_idx in range(1, len(headers) + 1):
        cell = ws.cell(2, c_idx)
        cell.fill = hdr_fill
        cell.font = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    single_tab_export = bool(category_tab and category_tab != "all")
    for idx, (d, ex) in enumerate(rows_with_extra, start=1):
        has_dl = True if d.has_deadline is None else bool(d.has_deadline)
        stt_cell = (ex.get("stt") or idx) if single_tab_export else idx
        ws.append(
            [
                stt_cell,
                tab_labels.get(d.category_tab or "khac", "Khác"),
                d.so_ho_so or d.ma_ho_so,
                d.unit_area or "",
                d.thu_tuc or "",
                d.ngay_nop.strftime("%d/%m/%Y") if d.ngay_nop else (d.report_date.strftime("%d/%m/%Y") if d.report_date else ""),
                d.ngay_tiep_nhan.strftime("%d/%m/%Y") if d.ngay_tiep_nhan else "",
                d.han_tra.strftime("%d/%m/%Y") if (has_dl and d.han_tra) else "",
                d.can_bo or "",
                d.trang_thai_nguon or "",
                "Đã hoàn thành" if d.trang_thai == "da_tra" else "Chưa hoàn thành",
                d.hoan_thanh_by_name or "",
                d.da_tra_at.strftime("%d/%m/%Y %H:%M") if d.da_tra_at else "",
                d.hoan_thanh_note or d.ghi_chu or "",
            ]
        )

    widths = [6, 18, 28, 24, 30, 16, 15, 14, 22, 26, 18, 22, 20, 32]
    for idx_w, w in enumerate(widths, start=1):
        col_letter = openpyxl.utils.get_column_letter(idx_w)
        ws.column_dimensions[col_letter].width = w

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    fname = f"theo_doi_ho_so_{category_tab or 'all'}_{date.today().strftime('%Y%m%d')}.xlsx"
    return send_file(
        out,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=fname,
    )


@dossier_bp.route("/api/dossiers/column-widths", methods=["POST"])
def api_dossier_column_widths():
    """Quản trị viên lưu hoặc khôi phục độ rộng các cột bảng hồ sơ dùng chung toàn hệ thống."""
    if not _require_login():
        return jsonify({"error": "Unauthorized"}), 401
    _ensure_dossier_schema()

    authz = load_current_authz()
    if not authz.get("is_admin"):
        return jsonify({"error": "Chỉ quản trị viên mới được điều chỉnh cấu hình cột mặc định."}), 403

    data = request.get_json(silent=True) or {}
    action = (data.get("action") or "save").strip().lower()
    layout_key = (data.get("layout_key") or "").strip()
    if not layout_key or len(layout_key) > 240:
        return jsonify({"error": "Khóa bố cục cột không hợp lệ."}), 400

    uid = session.get("uid")
    widths_map = _load_dossier_column_widths()
    if action == "reset":
        widths_map.pop(layout_key, None)
        _save_dossier_column_widths(widths_map, uid=uid)
        return jsonify({"ok": True, "layout_key": layout_key, "column_widths_map": widths_map})

    if action != "save":
        return jsonify({"error": "Hành động không hợp lệ."}), 400

    cleaned_widths = _sanitize_width_list(data.get("widths"))
    if not cleaned_widths:
        return jsonify({"error": "Danh sách độ rộng cột không hợp lệ."}), 400

    widths_map[layout_key] = cleaned_widths
    _save_dossier_column_widths(widths_map, uid=uid)
    return jsonify({
        "ok": True,
        "layout_key": layout_key,
        "widths": cleaned_widths,
        "column_widths_map": widths_map,
    })
