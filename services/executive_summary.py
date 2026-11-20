# -*- coding: utf-8 -*-
"""
Dịch vụ Tổng hợp nhanh cho Lãnh đạo / Chỉ huy (Executive Summary) — PhanMemPC06_Pro.

Cung cấp góc nhìn tổng quan một màn hình (không cần mở từng hồ sơ lẻ):
- Tổng số hồ sơ theo dõi theo trạng thái (Quá hạn / Sắp đến hạn / Đang xử lý / Đã hoàn thành).
- Phân bổ chi tiết theo từng lĩnh vực (Tạm trú, Thường trú, Phiếu XM CT10, Tích hợp, Làm sạch...).
- Xếp hạng đơn vị cần đôn đốc theo mức độ tồn đọng / quá hạn (lọc được theo từng lĩnh vực).
- Tổng hợp tiến độ báo cáo công việc & báo cáo định kỳ.
- Xuất nhanh báo cáo tổng hợp Excel 3 sheet.
"""

import io
import json
from datetime import date, datetime, timedelta

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from models import Dossier, Task, TaskAssignment, User, db
from permissions import user_effective_roles
from services.dossier_importer import (
    _norm_vn,
    get_dossier_tab_defs,
    get_user_dossier_identity,
    get_valid_dossier_tabs,
)
from services.task_deadline import _task_report_kind_label, _task_report_period
from services.task_units import _task_assignee_unit_name
from utils import match_standard_role

REMIND_DAYS_DEFAULT = 2


def is_province_wide_viewer(authz):
    """True nếu người dùng là Quản trị hệ thống hoặc thuộc cấp Tỉnh (CAT / Lãnh đạo - Chỉ huy CAT)."""
    if not authz:
        return False
    if authz.get("is_admin"):
        return True
    role_name = authz.get("role_name") or ""
    role_def = match_standard_role(role_name)
    if role_def and role_def.get("level") in ("system", "cat"):
        return True
    user = authz.get("user")
    if user:
        for r in user_effective_roles(user):
            rd = match_standard_role(getattr(r, "name", "") or "")
            if rd and rd.get("level") in ("system", "cat"):
                return True
    return False


def _parse_extra(raw):
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _safe_int(val):
    if val is None or val == "":
        return 0
    try:
        return int(round(float(str(val).replace(",", "").strip())))
    except (TypeError, ValueError):
        return 0


def _calc_state(dossier, today, extra=None):
    if dossier.trang_thai == "da_tra":
        return "done"
    if dossier.category_tab == "ct10":
        ex = extra if extra is not None else _parse_extra(dossier.extra_json)
        if _safe_int(ex.get("qua_han")) > 0:
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


def _blank_counts():
    return {
        "total": 0,
        "overdue": 0,
        "soon": 0,
        "pending": 0,
        "done": 0,
        "active": 0,
        "urgent": 0,
        "completion_pct": 0,
    }


def _finalize_counts(bucket):
    bucket["active"] = bucket["overdue"] + bucket["soon"] + bucket["pending"]
    bucket["urgent"] = bucket["overdue"] + bucket["soon"]
    bucket["completion_pct"] = (
        round((bucket["done"] * 100.0) / bucket["total"])
        if bucket["total"] > 0
        else 0
    )
    return bucket


def _build_task_executive_summary(authz, uid):
    """Tổng hợp nhanh công việc & báo cáo theo phạm vi người dùng nhìn thấy."""
    from routes.admin import (
        _overdue_task_count,
        _task_dashboard_unit_metrics,
        _visible_dashboard_task_ids,
    )

    perms = authz.get("perms") or {}
    visible_task_ids = _visible_dashboard_task_ids(perms)
    unit_metrics = _task_dashboard_unit_metrics(visible_task_ids=visible_task_ids)
    overdue_tasks = _overdue_task_count(visible_task_ids=visible_task_ids)

    task_q = (
        Task.query.options(joinedload(Task.assignments).joinedload(TaskAssignment.user))
        .filter(Task.parent_task_id.is_(None))
        .order_by(Task.deadline.asc().nullslast(), Task.created_at.desc(), Task.id.desc())
    )
    if visible_task_ids is not None:
        if not visible_task_ids:
            root_tasks = []
        else:
            root_tasks = task_q.filter(Task.id.in_(visible_task_ids)).all()
    else:
        root_tasks = task_q.all()

    today_d = date.today()
    periodic_count = 0
    completed_tasks = 0
    recent_reports = []

    for task in root_tasks:
        cfg = _task_report_period(task)
        is_periodic = cfg.get("kind") == "periodic"
        if is_periodic:
            periodic_count += 1

        assignments = list(task.assignments or [])
        units_map = {}
        for a in assignments:
            u = getattr(a, "user", None)
            u_name = (
                _task_assignee_unit_name(u)
                if u
                else (getattr(a, "unit_name", None) or "Đơn vị")
            ) or "Chưa rõ đơn vị"
            st = (getattr(a, "status", "") or "").strip().lower()
            entry = units_map.setdefault(u_name, {"done": 0, "total": 0})
            entry["total"] += 1
            if st in ("submitted", "completed"):
                entry["done"] += 1

        total_u = len(units_map)
        reported_u = sum(1 for item in units_map.values() if item["done"] > 0)
        progress_pct = round((reported_u * 100.0) / total_u) if total_u else 0

        is_done_task = total_u > 0 and reported_u == total_u
        if is_done_task:
            completed_tasks += 1

        is_overdue = bool(task.deadline and task.deadline < today_d and not is_done_task)
        recent_reports.append(
            {
                "id": task.id,
                "title": task.title or f"Công việc #{task.id}",
                "task_mode": (getattr(task, "task_mode", None) or "OUTLINE").upper(),
                "report_kind_label": _task_report_kind_label(task),
                "is_periodic": is_periodic,
                "deadline_str": task.deadline.strftime("%d/%m/%Y") if task.deadline else "Không hạn",
                "is_overdue": is_overdue,
                "total_units": total_u,
                "reported_units": reported_u,
                "unreported_units": max(total_u - reported_u, 0),
                "progress_pct": progress_pct,
                "href": f"/tasks/{task.id}",
            }
        )

    # Ưu tiên đưa báo cáo quá hạn / chưa hoàn thành lên đầu
    recent_reports.sort(
        key=lambda r: (
            0 if r["is_overdue"] else 1,
            0 if r["progress_pct"] < 100 else 1,
            r["progress_pct"],
            r["title"].lower(),
        )
    )

    total_u_all = unit_metrics.get("total_units", 0)
    reported_u_all = unit_metrics.get("reported_units", 0)
    unreported_u_all = unit_metrics.get("unreported_units", 0)
    report_rate_pct = (
        round((reported_u_all * 100.0) / total_u_all) if total_u_all > 0 else 0
    )

    return {
        "total_tasks": unit_metrics.get("total_tasks", len(root_tasks)),
        "active_tasks": max(len(root_tasks) - completed_tasks, 0),
        "completed_tasks": completed_tasks,
        "overdue_tasks": overdue_tasks,
        "periodic_tasks": periodic_count,
        "total_units": total_u_all,
        "reported_units": reported_u_all,
        "unreported_units": unreported_u_all,
        "report_rate_pct": report_rate_pct,
        "recent_reports": recent_reports[:10],
    }


def build_executive_summary(authz, uid, tab_filter="all", unit_search="", only_urgent=False):
    """Xây dựng toàn bộ gói số liệu Tổng hợp Lãnh đạo (hồ sơ + đơn vị + báo cáo công việc)."""
    current_user = authz.get("user") or (db.session.get(User, uid) if uid else None)
    province_wide = is_province_wide_viewer(authz)
    ident = get_user_dossier_identity(current_user)
    scope_label = (
        "Toàn tỉnh"
        if province_wide
        else (f"Đơn vị: {ident.get('unit_name')}" if ident.get("unit_name") else "Phạm vi cá nhân")
    )

    today_d = date.today()
    tab_defs = get_dossier_tab_defs(include_inactive=False)
    valid_tabs = get_valid_dossier_tabs()

    active_tab = (tab_filter or "all").strip()
    if active_tab != "all" and active_tab not in valid_tabs:
        active_tab = "all"

    base_q = Dossier.query
    if not province_wide:
        base_q = _scope_dossier_query(base_q, current_user, uid)

    rows = base_q.all()

    overall = _blank_counts()
    filtered_overall = _blank_counts()
    ct10_totals = {"tong_phieu": 0, "da_tra_loi": 0, "chua_tra_loi": 0, "qua_han": 0}

    tab_buckets = {}
    for td in tab_defs:
        tab_buckets[td["key"]] = {
            "key": td["key"],
            "label": td["label"],
            **_blank_counts(),
            "ct10_phieu": 0,
            "ct10_tra_loi": 0,
            "ct10_qua_han": 0,
        }
    if "khac" not in tab_buckets:
        tab_buckets["khac"] = {
            "key": "khac",
            "label": "Hồ sơ khác",
            **_blank_counts(),
            "ct10_phieu": 0,
            "ct10_tra_loi": 0,
            "ct10_qua_han": 0,
        }

    unit_buckets = {}
    all_units_set = set()
    urgent_units_set = set()

    for d in rows:
        extra = _parse_extra(d.extra_json)
        st = _calc_state(d, today_d, extra=extra)
        t_key = d.category_tab if d.category_tab in valid_tabs else "khac"
        if t_key not in tab_buckets:
            tab_buckets[t_key] = {
                "key": t_key,
                "label": t_key,
                **_blank_counts(),
                "ct10_phieu": 0,
                "ct10_tra_loi": 0,
                "ct10_qua_han": 0,
            }

        # Overall
        overall["total"] += 1
        overall[st] += 1

        # Per tab
        tb = tab_buckets[t_key]
        tb["total"] += 1
        tb[st] += 1

        if t_key == "ct10":
            phieu = _safe_int(extra.get("tong_phieu"))
            tra_loi = _safe_int(extra.get("da_tra_loi"))
            chua_tl = _safe_int(extra.get("chua_tra_loi"))
            qh = _safe_int(extra.get("qua_han"))
            ct10_totals["tong_phieu"] += phieu
            ct10_totals["da_tra_loi"] += tra_loi
            ct10_totals["chua_tra_loi"] += chua_tl
            ct10_totals["qua_han"] += qh
            tb["ct10_phieu"] += phieu
            tb["ct10_tra_loi"] += tra_loi
            tb["ct10_qua_han"] += qh

        u_name = (d.unit_area or d.unit_code or "Chưa gán đơn vị").strip()
        u_key = (d.unit_code or d.unit_key or u_name).strip()
        all_units_set.add(u_key)
        if st in ("overdue", "soon"):
            urgent_units_set.add(u_key)

        if active_tab == "all" or t_key == active_tab:
            filtered_overall["total"] += 1
            filtered_overall[st] += 1

            ub = unit_buckets.get(u_key)
            if ub is None:
                ub = {
                    "unit_key": u_key,
                    "unit_code": (d.unit_code or "").strip(),
                    "unit_name": u_name,
                    **_blank_counts(),
                }
                unit_buckets[u_key] = ub
            ub["total"] += 1
            ub[st] += 1

    _finalize_counts(overall)
    _finalize_counts(filtered_overall)

    by_tab = []
    for tb in tab_buckets.values():
        _finalize_counts(tb)
        by_tab.append(tb)

    # Sắp xếp đơn vị: ưu tiên quá hạn -> sắp đến hạn -> đang xử lý -> tổng số
    q_norm = _norm_vn(unit_search) if unit_search else ""
    by_unit = []
    for ub in unit_buckets.values():
        _finalize_counts(ub)
        if only_urgent and ub["urgent"] <= 0:
            continue
        if q_norm and q_norm not in _norm_vn(ub["unit_name"]):
            continue
        by_unit.append(ub)

    by_unit.sort(
        key=lambda u: (
            -u["overdue"],
            -u["soon"],
            -u["active"],
            -u["total"],
            u["unit_name"].lower(),
        )
    )

    tasks_summary = _build_task_executive_summary(authz, uid)

    return {
        "scope_label": scope_label,
        "is_province_wide": province_wide,
        "active_tab": active_tab,
        "generated_at": datetime.now().strftime("%H:%M · %d/%m/%Y"),
        "overall": overall,
        "filtered_overall": filtered_overall,
        "ct10_totals": ct10_totals,
        "total_units_with_dossiers": len(all_units_set),
        "total_units_with_urgent": len(urgent_units_set),
        "by_tab": by_tab,
        "by_unit": by_unit,
        "tasks": tasks_summary,
    }


def export_executive_summary_xlsx(summary):
    """Xuất file Excel tổng hợp 3 sheet phục vụ Lãnh đạo báo cáo/giao ban."""
    wb = openpyxl.Workbook()
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="2B5396", end_color="2B5396", fill_type="solid")
    title_font = Font(bold=True, size=13, color="1E293B")
    bold_font = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center")
    left = Alignment(horizontal="left", vertical="center")

    def _style_header(ws, row_idx, headers, widths):
        for col_idx, text in enumerate(headers, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=text)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center
        for col_idx, width in enumerate(widths, start=1):
            col_letter = openpyxl.utils.get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = width

    # Sheet 1: Tổng hợp theo lĩnh vực
    ws1 = wb.active
    ws1.title = "Theo lĩnh vực"
    ws1.cell(row=1, column=1, value=f"BÁO CÁO TỔNG HỢP LÃNH ĐẠO ({summary['scope_label']})").font = title_font
    ws1.cell(row=2, column=1, value=f"Thời điểm cập nhật: {summary['generated_at']}")
    _style_header(
        ws1,
        4,
        ["STT", "Lĩnh vực hồ sơ", "Tổng số", "Quá hạn", "Sắp đến hạn", "Đang xử lý", "Đã hoàn thành", "Tỷ lệ xong (%)"],
        [8, 30, 12, 12, 14, 14, 16, 15],
    )
    r = 5
    for idx, tab in enumerate(summary["by_tab"], start=1):
        vals = [
            idx,
            tab["label"],
            tab["total"],
            tab["overdue"],
            tab["soon"],
            tab["pending"],
            tab["done"],
            tab["completion_pct"],
        ]
        for c, val in enumerate(vals, start=1):
            cell = ws1.cell(row=r, column=c, value=val)
            cell.alignment = left if c == 2 else center
        r += 1
    ov = summary["overall"]
    total_vals = ["", "TỔNG CỘNG", ov["total"], ov["overdue"], ov["soon"], ov["pending"], ov["done"], ov["completion_pct"]]
    for c, val in enumerate(total_vals, start=1):
        cell = ws1.cell(row=r, column=c, value=val)
        cell.font = bold_font
        cell.alignment = left if c == 2 else center

    # Sheet 2: Tổng hợp theo đơn vị
    ws2 = wb.create_sheet("Theo đơn vị")
    ws2.cell(row=1, column=1, value=f"TỔNG HỢP HỒ SƠ THEO ĐƠN VỊ ({summary['scope_label']})").font = title_font
    _style_header(
        ws2,
        3,
        ["STT", "Đơn vị / Địa bàn", "Tổng số", "Quá hạn", "Sắp đến hạn", "Đang xử lý", "Đã hoàn thành", "Tỷ lệ xong (%)"],
        [8, 36, 12, 12, 14, 14, 16, 15],
    )
    for idx, unit in enumerate(summary["by_unit"], start=1):
        row_i = idx + 3
        vals = [
            idx,
            unit["unit_name"],
            unit["total"],
            unit["overdue"],
            unit["soon"],
            unit["pending"],
            unit["done"],
            unit["completion_pct"],
        ]
        for c, val in enumerate(vals, start=1):
            cell = ws2.cell(row=row_i, column=c, value=val)
            cell.alignment = left if c == 2 else center

    # Sheet 3: Báo cáo công việc
    ws3 = wb.create_sheet("Báo cáo công việc")
    ts = summary["tasks"]
    ws3.cell(row=1, column=1, value="TỔNG HỢP CÔNG VIỆC & BÁO CÁO").font = title_font
    ws3.cell(
        row=2,
        column=1,
        value=(
            f"Tổng việc: {ts['total_tasks']} | Quá hạn: {ts['overdue_tasks']} | "
            f"Định kỳ: {ts['periodic_tasks']} | Đơn vị đã báo cáo: {ts['reported_units']}/{ts['total_units']} ({ts['report_rate_pct']}%)"
        ),
    )
    _style_header(
        ws3,
        4,
        ["STT", "Tên công việc / báo cáo", "Hình thức", "Hạn nộp", "ĐV đã nộp", "Tổng ĐV", "Tiến độ (%)"],
        [8, 44, 18, 15, 13, 12, 14],
    )
    for idx, rep in enumerate(ts["recent_reports"], start=1):
        row_i = idx + 4
        vals = [
            idx,
            rep["title"],
            rep["report_kind_label"],
            rep["deadline_str"],
            rep["reported_units"],
            rep["total_units"],
            rep["progress_pct"],
        ]
        for c, val in enumerate(vals, start=1):
            cell = ws3.cell(row=row_i, column=c, value=val)
            cell.alignment = left if c == 2 else center

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
