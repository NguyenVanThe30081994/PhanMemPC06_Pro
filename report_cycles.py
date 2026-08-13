# -*- coding: utf-8 -*-
"""
Bộ máy "Loại công việc / cách báo cáo" cho chức năng giao việc.

Mỗi công việc có một cấu hình báo cáo (report_period_json) mô tả CÁCH báo cáo:

- one_time   : Báo cáo đột xuất / một lần — chỉ có hạn nộp 1 ngày.
- periodic   : Báo cáo định kỳ — lặp lại theo tuần / tháng / quý / năm,
               mỗi chu kỳ có hạn nộp riêng, đơn vị nộp theo từng chu kỳ.
- milestone  : Báo cáo theo mốc / giai đoạn — danh sách các mốc thời gian,
               mỗi mốc là một lần báo cáo.
- ongoing    : Công việc thường xuyên (duy trì) — không đặt hạn.

Chu kỳ hiện tại = chu kỳ CHỨA ngày hôm nay (kỳ báo cáo đang diễn ra),
hạn nộp của chu kỳ nằm trong chính chu kỳ đó → quá hạn được tính đúng
theo từng kỳ.
"""
from datetime import date, datetime, timedelta
import json
import re

KIND_ONETIME = "one_time"
KIND_PERIODIC = "periodic"
KIND_MILESTONE = "milestone"
KIND_ONGOING = "ongoing"

PERIOD_WEEK = "week"
PERIOD_MONTH = "month"
PERIOD_QUARTER = "quarter"
PERIOD_YEAR = "year"

KIND_LABELS = {
    KIND_ONETIME: "Báo cáo đột xuất / một lần",
    KIND_PERIODIC: "Báo cáo định kỳ",
    KIND_MILESTONE: "Báo cáo theo mốc / giai đoạn",
    KIND_ONGOING: "Công việc thường xuyên (duy trì)",
}

PERIOD_LABELS = {
    PERIOD_WEEK: "Hàng tuần",
    PERIOD_MONTH: "Hàng tháng",
    PERIOD_QUARTER: "Hàng quý",
    PERIOD_YEAR: "Hàng năm",
}

WEEKDAY_LABELS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]

_ISO_WEEK_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y")


def default_config(kind=KIND_ONETIME):
    """Cấu hình mặc định cho một loại báo cáo."""
    kind = kind if kind in KIND_LABELS else KIND_ONETIME
    return {
        "kind": kind,
        "period": PERIOD_MONTH,
        "weekday": 4,          # Thứ 6 — dùng cho định kỳ tuần
        "day_of_month": 5,     # Ngày 5 — dùng cho định kỳ tháng / quý
        "month_of_year": 12,   # Tháng 12 — dùng cho định kỳ năm
        "start_date": None,    # yyyy-mm-dd (tùy chọn)
        "end_date": None,      # yyyy-mm-dd (tùy chọn)
        "milestones": [],      # ["yyyy-mm-dd", ...] — loại theo mốc
        "deadline": None,      # yyyy-mm-dd — loại một lần
    }


def kind_from_task_type(task_type):
    """Suy ra loại báo cáo từ tên 'Loại công việc' (để tương thích dữ liệu cũ)."""
    name = str(task_type or "").lower()
    if any(token in name for token in ("định kỳ", "đinh ky", "định kì", "dinh ki")):
        return KIND_PERIODIC
    if any(token in name for token in ("thường xuyên", "duy trì", "thuong xuyen", "duy tri")):
        return KIND_ONGOING
    if any(token in name for token in ("theo mốc", "giai đoạn", "gai doan", "mốc", "moc")):
        return KIND_MILESTONE
    return KIND_ONETIME


def _int(value, default, lo, hi):
    try:
        number = int(str(value or "").strip())
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, number))


def _date_str(value):
    """Chuẩn hóa một giá trị ngày về 'yyyy-mm-dd' hoặc None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    for fmt in _ISO_WEEK_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _to_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _date_str(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_config(data):
    """Chuẩn hóa dict cấu hình (đã parse từ JSON)."""
    data = data or {}
    cfg = default_config()
    kind = str(data.get("kind") or "").strip().lower()
    if kind in KIND_LABELS:
        cfg["kind"] = kind
    else:
        cfg["kind"] = kind_from_task_type(data.get("task_type"))
    period = str(data.get("period") or "").strip().lower()
    if period in PERIOD_LABELS:
        cfg["period"] = period
    cfg["weekday"] = _int(data.get("weekday"), cfg["weekday"], 0, 6)
    cfg["day_of_month"] = _int(data.get("day_of_month"), cfg["day_of_month"], 1, 31)
    cfg["month_of_year"] = _int(data.get("month_of_year"), cfg["month_of_year"], 1, 12)
    cfg["start_date"] = _date_str(data.get("start_date"))
    cfg["end_date"] = _date_str(data.get("end_date"))
    cfg["deadline"] = _date_str(data.get("deadline"))
    milestones = data.get("milestones") or []
    cfg["milestones"] = [_date_str(item) for item in milestones if _date_str(item)]
    return cfg


def parse_config(mapping):
    """Xây cấu hình từ mapping dạng form (request.form / dict).

    Ưu tiên JSON tổng `report_period_json` nếu có; ngược lại đọc từng trường.
    """
    if mapping is not None:
        raw_json = mapping.get("report_period_json")
        if raw_json:
            try:
                parsed = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
                if isinstance(parsed, dict):
                    return normalize_config(parsed)
            except (TypeError, ValueError):
                pass

    cfg = default_config()
    kind = str((mapping or {}).get("report_period_kind") or "").strip().lower()
    if kind in KIND_LABELS:
        cfg["kind"] = kind
    else:
        cfg["kind"] = kind_from_task_type((mapping or {}).get("task_type"))

    if mapping is None:
        return cfg

    period = str(mapping.get("report_period") or "").strip().lower()
    if period in PERIOD_LABELS:
        cfg["period"] = period
    cfg["weekday"] = _int(mapping.get("report_weekday"), cfg["weekday"], 0, 6)
    cfg["day_of_month"] = _int(mapping.get("report_day_of_month"), cfg["day_of_month"], 1, 31)
    cfg["month_of_year"] = _int(mapping.get("report_month_of_year"), cfg["month_of_year"], 1, 12)
    cfg["start_date"] = _date_str(mapping.get("report_start_date"))
    cfg["end_date"] = _date_str(mapping.get("report_end_date"))
    cfg["deadline"] = _date_str(mapping.get("report_deadline")) or _date_str(mapping.get("deadline"))

    milestones = mapping.get("report_milestones")
    if isinstance(milestones, list):
        cfg["milestones"] = [_date_str(item) for item in milestones if _date_str(item)]
    elif isinstance(milestones, str) and milestones.strip():
        cfg["milestones"] = [
            _date_str(item)
            for item in re.split(r"[\n,;]+", milestones)
            if _date_str(item)
        ]
    return cfg


def config_to_json(cfg):
    try:
        return json.dumps(cfg, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def task_config(task):
    """Cấu hình báo cáo của một đối tượng Task (tương thích dữ liệu cũ)."""
    raw = getattr(task, "report_period_json", None)
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                cfg = normalize_config(parsed)
                if cfg["kind"] == KIND_ONETIME and not cfg.get("deadline"):
                    cfg["deadline"] = _date_str(getattr(task, "deadline", None))
                return cfg
        except (TypeError, ValueError):
            pass
    deadline = getattr(task, "deadline", None)
    if deadline:
        cfg = default_config(KIND_ONETIME)
        cfg["deadline"] = _date_str(deadline)
        return cfg
    return default_config(kind_from_task_type(getattr(task, "task_type", "")))


def _monday_of_iso_week(day):
    iso_year, iso_week, _iso_weekday = day.isocalendar()
    return datetime.strptime(f"{iso_year}-W{iso_week:02d}-1", "%G-W%V-%u").date()


def _periodic_bounds(period, day, *, next_cycle=False):
    """Ngày bắt đầu / kết thúc của kỳ chứa `day` (hoặc kỳ kế tiếp)."""
    if next_cycle:
        if period == PERIOD_WEEK:
            day = day + timedelta(days=7)
        elif period == PERIOD_MONTH:
            day = (day.replace(day=1) + timedelta(days=32)).replace(day=1)
        elif period == PERIOD_QUARTER:
            day = (day.replace(day=1, month=((day.month - 1) // 3) * 3 + 1) + timedelta(days=100)).replace(day=1)
        else:  # year
            day = day.replace(month=1, day=1) + timedelta(days=366)

    if period == PERIOD_WEEK:
        start = _monday_of_iso_week(day)
        return start, start + timedelta(days=6)
    if period == PERIOD_MONTH:
        start = day.replace(day=1)
        return start, (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    if period == PERIOD_QUARTER:
        quarter = (day.month - 1) // 3 + 1
        start = day.replace(month=(quarter - 1) * 3 + 1, day=1)
        return start, (start + timedelta(days=100)).replace(day=1) - timedelta(days=1)
    start = day.replace(month=1, day=1)
    return start, day.replace(month=12, day=31)


def _anchor_within(start, end, cfg):
    """Hạn nộp nằm trong [start, end] theo cấu hình định kỳ."""
    period = cfg.get("period", PERIOD_MONTH)
    if period == PERIOD_WEEK:
        return start + timedelta(days=cfg.get("weekday", 4))
    dom = cfg.get("day_of_month", 5)
    if period == PERIOD_QUARTER:
        # Hạn của quý rơi vào tháng cuối quý
        try:
            return end.replace(day=dom)
        except ValueError:
            return end.replace(day=28)
    if period == PERIOD_YEAR:
        mom = cfg.get("month_of_year", 12)
        try:
            return start.replace(month=mom, day=dom)
        except ValueError:
            try:
                return start.replace(month=mom, day=28)
            except ValueError:
                return start.replace(month=12, day=28)
    try:
        return start.replace(day=dom)
    except ValueError:
        return start.replace(day=28)


def _periodic_cycle(cfg, day, *, next_cycle=False):
    """Chu kỳ định kỳ chứa `day` (hoặc chu kỳ kế tiếp).

    Chu kỳ hiện tại = kỳ CHỨA ngày hôm nay (tuần ISO / tháng / quý / năm);
    hạn nộp nằm trong chính kỳ đó → quá hạn tính đúng theo từng kỳ.
    """
    period = cfg.get("period", PERIOD_MONTH)
    start, end = _periodic_bounds(period, day, next_cycle=next_cycle)
    due = _anchor_within(start, end, cfg)

    if period == PERIOD_WEEK:
        iso_year, iso_week, _ = start.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        label = "Tuần {:%d/%m} – {:%d/%m}".format(start, end)
    elif period == PERIOD_MONTH:
        key = f"{start.year}-{start.month:02d}"
        label = "Tháng {}/{}".format(start.month, start.year)
    elif period == PERIOD_QUARTER:
        quarter = (start.month - 1) // 3 + 1
        key = f"{start.year}-Q{quarter}"
        label = "Quý {}/{}".format(quarter, start.year)
    else:  # year
        key = str(start.year)
        label = "Năm {}".format(start.year)

    return {
        "kind": KIND_PERIODIC,
        "period": period,
        "key": key,
        "label": label,
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "due": due.strftime("%Y-%m-%d"),
        "overdue": day > due,
        "is_current": not next_cycle,
    }


def current_cycle(cfg, today=None):
    """Chu kỳ báo cáo hiện tại (chứa ngày hôm nay).

    Trả dict với key/label/start/end/due hoặc None nếu không có chu kỳ nào.
    """
    cfg = normalize_config(cfg)
    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    kind = cfg.get("kind", KIND_ONETIME)

    if kind == KIND_PERIODIC:
        return _periodic_cycle(cfg, today)

    if kind == KIND_MILESTONE:
        milestones = [_to_date(item) for item in (cfg.get("milestones") or [])]
        milestones = [item for item in milestones if item]
        if not milestones:
            return None
        active = next((m for m in sorted(milestones) if m >= today), None)
        if active is None:
            active = max(milestones)
        index = sorted(milestones).index(active) + 1
        return {
            "kind": KIND_MILESTONE,
            "key": "M{}".format(index),
            "label": "Mốc {}/{} ({:%d/%m/%Y})".format(index, len(milestones), active),
            "start": None,
            "end": None,
            "due": active.strftime("%Y-%m-%d"),
            "overdue": today > active,
            "is_current": True,
        }

    if kind == KIND_ONGOING:
        return {
            "kind": KIND_ONGOING,
            "key": "ongoing",
            "label": "Thường xuyên (không đặt hạn)",
            "start": None,
            "end": None,
            "due": None,
            "overdue": False,
            "is_current": True,
        }

    # one_time
    due = _to_date(cfg.get("deadline"))
    return {
        "kind": KIND_ONETIME,
        "key": "one",
        "label": "Một lần",
        "start": None,
        "end": None,
        "due": due.strftime("%Y-%m-%d") if due else None,
        "overdue": bool(due and today > due),
        "is_current": True,
    }


def next_cycle(cfg, today=None):
    """Chu kỳ kế tiếp (sau chu kỳ chứa ngày hôm nay)."""
    cfg = normalize_config(cfg)
    today = today or date.today()
    if isinstance(today, datetime):
        today = today.date()
    kind = cfg.get("kind", KIND_ONETIME)
    if kind == KIND_PERIODIC:
        return _periodic_cycle(cfg, today, next_cycle=True)
    if kind == KIND_MILESTONE:
        milestones = sorted(item for item in (_to_date(m) for m in (cfg.get("milestones") or [])) if item)
        if not milestones:
            return None
        future = [m for m in milestones if m > today]
        if not future:
            return None
        index = milestones.index(future[0]) + 1
        return {
            "kind": KIND_MILESTONE,
            "key": "M{}".format(index),
            "label": "Mốc {}/{} ({:%d/%m/%Y})".format(index, len(milestones), future[0]),
            "start": None,
            "end": None,
            "due": future[0].strftime("%Y-%m-%d"),
            "overdue": False,
            "is_current": False,
        }
    return None


def cycles_between(cfg, start_date, end_date):
    """Danh sách chu kỳ trong khoảng [start_date, end_date] (bao gồm cả hai đầu)."""
    cfg = normalize_config(cfg)
    start = _to_date(start_date) or date.today()
    end = _to_date(end_date) or start
    if end < start:
        start, end = end, start
    kind = cfg.get("kind", KIND_ONETIME)

    if kind == KIND_PERIODIC:
        period = cfg.get("period", PERIOD_MONTH)
        results = []
        cursor = start
        guard = 0
        while cursor <= end and guard < 1000:
            cycle = _periodic_cycle(cfg, cursor)
            cycle_start = _to_date(cycle["start"])
            cycle_end = _to_date(cycle["end"])
            results.append(cycle)
            if period == PERIOD_WEEK:
                cursor = cycle_end + timedelta(days=1)
            elif period == PERIOD_MONTH:
                cursor = (cycle_start.replace(day=1) + timedelta(days=32)).replace(day=1)
            elif period == PERIOD_QUARTER:
                cursor = (cycle_start.replace(day=1, month=((cycle_start.month - 1) // 3) * 3 + 1) + timedelta(days=100)).replace(day=1)
            else:
                cursor = cycle_start.replace(month=1, day=1) + timedelta(days=366)
            guard += 1
        # Loại bỏ chu kỳ trùng key
        seen = set()
        unique = []
        for cycle in results:
            if cycle["key"] in seen:
                continue
            seen.add(cycle["key"])
            unique.append(cycle)
        return unique

    if kind == KIND_MILESTONE:
        milestones = sorted(item for item in (_to_date(m) for m in (cfg.get("milestones") or [])) if item)
        results = []
        for index, milestone in enumerate(milestones, start=1):
            if start <= milestone <= end:
                results.append(
                    {
                        "kind": KIND_MILESTONE,
                        "key": "M{}".format(index),
                        "label": "Mốc {}/{} ({:%d/%m/%Y})".format(index, len(milestones), milestone),
                        "start": None,
                        "end": None,
                        "due": milestone.strftime("%Y-%m-%d"),
                        "overdue": False,
                        "is_current": False,
                    }
                )
        return results

    cycle = current_cycle(cfg, today=start)
    if cycle and cycle.get("due"):
        due = _to_date(cycle["due"])
        if due and start <= due <= end:
            return [cycle]
    return []


def deadline_for(cfg, today=None):
    """Hạn nộp của chu kỳ hiện tại (dùng để gán task.deadline khi tạo)."""
    cycle = current_cycle(cfg, today=today)
    if not cycle:
        return None
    due = cycle.get("due")
    return _to_date(due) if due else None


def cycle_summary_text(task, today=None):
    """Chuỗi ngắn hiển thị chu kỳ + hạn nộp cho 1 task (dùng ở danh sách/workspace).

    Trả về "" nếu task là công việc thường (một lần, đã có hạn) để giữ hiển thị cũ.
    """
    cfg = task_config(task)
    kind = cfg.get("kind", KIND_ONETIME)
    if kind == KIND_ONETIME:
        return ""
    cycle = current_cycle(cfg, today=today)
    if not cycle:
        return ""
    parts = []
    label = cycle.get("label") or ""
    if label:
        parts.append(label)
    due = cycle.get("due")
    if due:
        parts.append("hạn {:%d/%m}".format(_to_date(due)))
    if cycle.get("overdue"):
        parts.append("đã quá hạn")
    return " · ".join(parts)
