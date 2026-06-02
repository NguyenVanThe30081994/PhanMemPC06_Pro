from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta


ALL_WEEKDAYS = tuple(range(7))
DEFAULT_MODE = "interval"
DEFAULT_DAY_START = "08:00"
DEFAULT_DAY_END = "17:00"
DEFAULT_INTERVAL_MINUTES = 120
DEFAULT_EARLY_CHECKIN_MINUTES = 15
DEFAULT_LATE_ALLOW_MINUTES = 60

WEEKDAY_LABELS = {
    0: "Thứ 2",
    1: "Thứ 3",
    2: "Thứ 4",
    3: "Thứ 5",
    4: "Thứ 6",
    5: "Thứ 7",
    6: "Chủ nhật",
}


def parse_hhmm(value, fallback=None):
    raw_value = str(value or "").strip()
    if not raw_value:
        return fallback
    if not re.fullmatch(r"\d{1,2}:\d{2}", raw_value):
        return fallback
    hour_text, minute_text = raw_value.split(":", 1)
    try:
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return fallback
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return fallback
    return time(hour=hour, minute=minute)


def normalize_time_string(value, fallback):
    fallback_time = parse_hhmm(fallback)
    parsed = parse_hhmm(value, fallback=fallback_time)
    if not parsed:
        return fallback_time.strftime("%H:%M") if fallback_time else ""
    return parsed.strftime("%H:%M")


def normalize_weekdays(value):
    if value in (None, "", []):
        return list(ALL_WEEKDAYS)

    items = value
    if isinstance(value, str):
        raw_text = value.strip()
        if not raw_text:
            return list(ALL_WEEKDAYS)
        try:
            decoded = json.loads(raw_text)
            if isinstance(decoded, list):
                items = decoded
            else:
                items = re.split(r"[\s,;|]+", raw_text)
        except Exception:
            items = re.split(r"[\s,;|]+", raw_text)

    normalized = []
    for item in items or []:
        try:
            weekday = int(item)
        except (TypeError, ValueError):
            continue
        if weekday in WEEKDAY_LABELS and weekday not in normalized:
            normalized.append(weekday)

    return normalized or list(ALL_WEEKDAYS)


def normalize_schedule_times(value):
    items = value
    if value in (None, ""):
        items = []
    elif isinstance(value, str):
        raw_text = value.strip()
        if not raw_text:
            items = []
        else:
            try:
                decoded = json.loads(raw_text)
                if isinstance(decoded, list):
                    items = decoded
                else:
                    items = re.split(r"[\n,;|]+", raw_text)
            except Exception:
                items = re.split(r"[\n,;|]+", raw_text)

    normalized = []
    seen = set()
    for item in items or []:
        time_text = normalize_time_string(item, "")
        if not time_text or time_text in seen:
            continue
        seen.add(time_text)
        normalized.append(time_text)

    return sorted(normalized)


def normalize_attendance_config(config):
    mode = (getattr(config, "mode", None) or DEFAULT_MODE).strip().lower()
    if mode not in {"interval", "schedule"}:
        mode = DEFAULT_MODE

    interval_minutes = getattr(config, "interval_minutes", None) or DEFAULT_INTERVAL_MINUTES
    try:
        interval_minutes = max(1, int(interval_minutes))
    except (TypeError, ValueError):
        interval_minutes = DEFAULT_INTERVAL_MINUTES

    early_checkin_minutes = getattr(config, "early_checkin_minutes", None)
    late_allow_minutes = getattr(config, "late_allow_minutes", None)
    try:
        early_checkin_minutes = max(0, int(early_checkin_minutes))
    except (TypeError, ValueError):
        early_checkin_minutes = DEFAULT_EARLY_CHECKIN_MINUTES
    try:
        late_allow_minutes = max(0, int(late_allow_minutes))
    except (TypeError, ValueError):
        late_allow_minutes = DEFAULT_LATE_ALLOW_MINUTES

    schedule_times = normalize_schedule_times(getattr(config, "schedule_times_json", None))
    active_weekdays = normalize_weekdays(getattr(config, "active_weekdays_json", None))
    day_start_time = normalize_time_string(getattr(config, "day_start_time", None), DEFAULT_DAY_START)
    day_end_time = normalize_time_string(getattr(config, "day_end_time", None), DEFAULT_DAY_END)

    return {
        "name": (getattr(config, "name", None) or "Điểm danh tự động").strip(),
        "mode": mode,
        "interval_minutes": interval_minutes,
        "day_start_time": day_start_time,
        "day_end_time": day_end_time,
        "schedule_times": schedule_times,
        "active_weekdays": active_weekdays,
        "early_checkin_minutes": early_checkin_minutes,
        "late_allow_minutes": late_allow_minutes,
        "is_active": bool(getattr(config, "is_active", True)),
        "note": (getattr(config, "note", None) or "").strip(),
    }


def describe_weekdays(weekdays):
    normalized = normalize_weekdays(weekdays)
    if normalized == list(ALL_WEEKDAYS):
        return "Tất cả các ngày"
    return ", ".join(WEEKDAY_LABELS[weekday] for weekday in normalized)


def _build_interval_times(config):
    start_at = parse_hhmm(config["day_start_time"])
    end_at = parse_hhmm(config["day_end_time"])
    if not start_at or not end_at:
        return []

    start_minutes = start_at.hour * 60 + start_at.minute
    end_minutes = end_at.hour * 60 + end_at.minute
    if end_minutes < start_minutes:
        return []

    output = []
    current_minutes = start_minutes
    while current_minutes <= end_minutes:
        output.append(f"{current_minutes // 60:02d}:{current_minutes % 60:02d}")
        current_minutes += config["interval_minutes"]
    return output


def build_slots_for_date(target_date, config):
    normalized = normalize_attendance_config(config)
    if not normalized["is_active"]:
        return []
    if target_date.weekday() not in normalized["active_weekdays"]:
        return []

    if normalized["mode"] == "schedule":
        time_points = normalized["schedule_times"]
    else:
        time_points = _build_interval_times(normalized)

    slots = []
    for time_text in time_points:
        due_time = parse_hhmm(time_text)
        if not due_time:
            continue
        due_at = datetime.combine(target_date, due_time)
        window_start_at = due_at - timedelta(minutes=normalized["early_checkin_minutes"])
        window_end_at = due_at + timedelta(minutes=normalized["late_allow_minutes"])
        slot_key = f"{target_date.strftime('%Y%m%d')}-{time_text.replace(':', '')}"
        slots.append(
            {
                "slot_key": slot_key,
                "slot_label": f"Mốc {time_text}",
                "slot_time": time_text,
                "slot_date": target_date,
                "due_at": due_at,
                "window_start_at": window_start_at,
                "window_end_at": window_end_at,
            }
        )
    return slots


def build_slots_for_range(start_date, end_date, config):
    if start_date > end_date:
        return []
    output = []
    current_date = start_date
    while current_date <= end_date:
        output.extend(build_slots_for_date(current_date, config))
        current_date += timedelta(days=1)
    return output


def resolve_slot_status(slot, submission=None, now=None):
    if submission:
        return "completed"
    now = now or datetime.now()
    if now < slot["window_start_at"]:
        return "upcoming"
    if now <= slot["window_end_at"]:
        return "available"
    return "missed"
