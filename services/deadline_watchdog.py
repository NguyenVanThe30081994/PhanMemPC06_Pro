# -*- coding: utf-8 -*-
"""
Deadline watchdog (Pha 1 — theo dõi tiến độ & cảnh báo hạn).

Quét `Task.deadline` của các công việc gốc (không phải task con) CHƯA hoàn
thành, sinh Notification theo 3 ngưỡng (cấu hình qua biến môi trường):

- `PC06_DEADLINE_UPCOMING_DAYS` (mặc định 3): còn <= N ngày → "sắp đến hạn".
- `PC06_DEADLINE_URGENT_DAYS`   (mặc định 1): còn <= N ngày → "gấp".
- `PC06_DEADLINE_LOOKBACK_DAYS` (mặc định 7): cửa sổ dedupe — trong N ngày,
  mỗi (user, task, ngưỡng) chỉ nhắc MỘT lần.

Người nhận cảnh báo (theo task, chỉ assignment còn dang dở):
- Ưu tiên assignment trực tiếp (assignee_type='user').
- Nếu KHÔNG có assignment trực tiếp, quy đổi assignment đơn vị/vai trò:
  lãnh đạo/quản trị + user cùng `unit_key` + user có `role_id` trùng.
- Task chạm ngưỡng mà chưa gán cho ai: báo cho quản trị.

`send_emails=True` gửi kèm email qua `routes.email_service` cho user có
khai báo email (tự bỏ qua khi MAIL_* chưa cấu hình). Mọi lỗi được bắt và
trả về trong summary, không làm gãy request.

Phải gọi trong app context: `with app.app_context(): run_deadline_watchdog()`.
"""

from datetime import date, datetime, timedelta
import os


DONE_STATUSES = {"submitted", "completed"}

OVERDUE_MARKER = "Công việc QUÁ HẠN"
URGENT_MARKER = "Công việc gấp"
UPCOMING_MARKER = "Công việc sắp đến hạn"


def _is_done_status(value):
    return str(value or "").strip().lower() in DONE_STATUSES


def _watchdog_settings():
    def _int_env(name, default, minimum=0):
        try:
            return max(int(os.environ.get(name, default)), minimum)
        except (TypeError, ValueError):
            return default

    upcoming_days = _int_env("PC06_DEADLINE_UPCOMING_DAYS", 3)
    urgent_days = _int_env("PC06_DEADLINE_URGENT_DAYS", 1)
    # Ngưỡng "gấp" không được rộng hơn "sắp đến hạn" để không trùng lặp.
    return {
        "upcoming_days": upcoming_days,
        "urgent_days": min(urgent_days, upcoming_days),
        "lookback_days": _int_env("PC06_DEADLINE_LOOKBACK_DAYS", 7, minimum=1),
        "max_tasks": _int_env("PC06_DEADLINE_MAX_TASKS", 500, minimum=1),
        "send_emails": os.environ.get(
            "PC06_DEADLINE_EMAIL_ENABLED", "1"
        ).lower() in ("1", "true", "yes"),
    }


def _classify_task_deadline(task_deadline, today, settings):
    """Trả về (level, days_left) hoặc None nếu chưa chạm ngưỡng."""
    if not task_deadline:
        return None
    if isinstance(task_deadline, datetime):
        task_deadline = task_deadline.date()
    days_left = (task_deadline - today).days
    if days_left < 0:
        return "overdue", days_left
    if days_left <= settings["urgent_days"]:
        return "urgent", days_left
    if days_left <= settings["upcoming_days"]:
        return "upcoming", days_left
    return None


def _format_deadline(task_deadline):
    try:
        return task_deadline.strftime("%d/%m/%Y")
    except Exception:
        return str(task_deadline)


def _message_for(level, task, days_left, settings):
    """Trả về (title, msg, link). Title là marker dedupe theo ngưỡng."""
    deadline_text = _format_deadline(task.deadline)
    link = f"/tasks/{task.id}"
    if level == "overdue":
        return (
            OVERDUE_MARKER,
            f"'{task.title}' đã quá hạn {-days_left} ngày "
            f"(hạn {deadline_text}). Vui lòng khẩn trương hoàn thành "
            f"hoặc báo cáo vướng mắc.",
            link,
        )
    if level == "urgent":
        if days_left == 0:
            msg = f"'{task.title}' đến hạn HÔM NAY ({deadline_text})."
        else:
            msg = (
                f"'{task.title}' chỉ còn {days_left} ngày là đến hạn "
                f"({deadline_text})."
            )
        return URGENT_MARKER, msg, link
    return (
        UPCOMING_MARKER,
        f"'{task.title}' còn {days_left} ngày là đến hạn "
        f"({deadline_text}, ngưỡng nhắc {settings['upcoming_days']} ngày).",
        link,
    )


def _recent_notif_exists(user_id, task_id, marker, since):
    """Đã có thông báo cùng ngưỡng (prefix title) cho (user, task) gần đây?"""
    from models import Notification

    return Notification.query.filter(
        Notification.user_id == user_id,
        Notification.created_at >= since,
        Notification.title.like(f"{marker}%"),
        Notification.link == f"/tasks/{task_id}",
    ).first() is not None


def _unit_keys_for_ids(unit_ids):
    from models import Unit, db

    if not unit_ids:
        return set()
    rows = db.session.query(Unit.code).filter(Unit.id.in_(unit_ids)).all()
    return {code for (code,) in rows if code}


def _pending_assignee_ids_for_task(task, leader_user_ids):
    """
    Danh sách user id (dedupe) cần nhận cảnh báo cho một task:
    - assignment trực tiếp còn dang dở; nếu không có thì quy đổi
      assignment đơn vị/vai trò về user (lãnh đạo + cùng unit_key + trùng role).
    """
    pending_assignments = [
        assignment
        for assignment in (task.assignments or [])
        if not _is_done_status(assignment.status)
    ]

    direct_ids = []
    for assignment in pending_assignments:
        if (assignment.assignee_type or "user") == "user" and assignment.user_id:
            if assignment.user_id not in direct_ids:
                direct_ids.append(assignment.user_id)
    if direct_ids:
        return direct_ids

    unit_ids = {a.unit_id for a in pending_assignments if a.unit_id}
    role_ids = {a.role_id for a in pending_assignments if a.role_id}
    if not unit_ids and not role_ids:
        return []

    unit_keys = _unit_keys_for_ids(unit_ids)

    from models import User

    recipients = set(leader_user_ids)
    for user in User.query.filter(User.is_active == True).all():  # noqa: E712
        if role_ids and user.role_id in role_ids:
            recipients.add(user.id)
        elif unit_keys and (user.unit_key or "") in unit_keys:
            recipients.add(user.id)
    return sorted(recipients)


def _leader_user_ids(active_users):
    """Quản trị + vai trò tên chứa 'lãnh đạo' — người nhận cảnh báo đơn vị."""
    leader_role_ids = set()
    try:
        from models import AppRole

        leader_role_ids = {
            role.id
            for role in AppRole.query.all()
            if "lãnh đạo" in (role.name or "").lower()
            or (getattr(role, "level", "") or "") == "system"
        }
    except Exception:
        pass
    return {
        user.id
        for user in active_users
        if user.role_id == 1 or user.role_id in leader_role_ids
    }


def run_deadline_watchdog(send_emails=None, today=None):
    """Quét hạn và sinh thông báo. Trả về summary dict. Cần app context."""
    from models import Task, User, db
    from utils import push_notif

    settings = _watchdog_settings()
    if send_emails is None:
        send_emails = settings["send_emails"]
    today = today or date.today()
    lookback_since = datetime.now() - timedelta(days=settings["lookback_days"])

    summary = {
        "scanned": 0,
        "notifications_created": 0,
        "emails_sent": 0,
        "emails_skipped": 0,
        "errors": [],
        "levels": {"upcoming": 0, "urgent": 0, "overdue": 0},
        "date": today.isoformat(),
    }

    active_users = User.query.filter(User.is_active == True).all()  # noqa: E712
    user_by_id = {user.id: user for user in active_users}
    leader_ids = _leader_user_ids(active_users)

    tasks = (
        Task.query.filter(Task.parent_task_id.is_(None))
        .order_by(Task.deadline.asc())
        .limit(settings["max_tasks"])
        .all()
    )
    summary["tasks_total"] = len(tasks)

    for task in tasks:
        try:
            classified = _classify_task_deadline(task.deadline, today, settings)
            if not classified:
                continue
            assignments = task.assignments or []
            # Mọi assignment đã chốt xong thì không nhắc nữa.
            if assignments and all(_is_done_status(a.status) for a in assignments):
                continue
            summary["scanned"] += 1
            level, days_left = classified
            title, msg, link = _message_for(level, task, days_left, settings)

            recipients = _pending_assignee_ids_for_task(task, leader_ids)
            if not recipients:
                # Chạm ngưỡng mà chưa gán cho ai: báo quản trị để xử lý.
                recipients = sorted(
                    uid for uid in leader_ids if uid in user_by_id
                )

            for user_id in recipients:
                user = user_by_id.get(user_id)
                if not user or not getattr(user, "is_active", True):
                    continue
                try:
                    if _recent_notif_exists(user_id, task.id, title, lookback_since):
                        continue
                    push_notif(user_id, title, msg, link)
                    summary["notifications_created"] += 1
                    summary["levels"][level] += 1

                    if send_emails and getattr(user, "email", None):
                        try:
                            from routes.email_service import send_email

                            ok, _err = send_email(
                                user.email,
                                f"[PC06] {title}: {task.title}",
                                f"<p>{msg}</p>"
                                f"<p>Xem chi tiết trong hệ thống: <b>{link}</b></p>",
                            )
                            if ok:
                                summary["emails_sent"] += 1
                            else:
                                summary["emails_skipped"] += 1
                        except Exception as mail_exc:
                            summary["emails_skipped"] += 1
                            summary["errors"].append(
                                f"email user={user_id} task={task.id}: {mail_exc}"
                            )
                except Exception as exc:
                    db.session.rollback()
                    summary["errors"].append(
                        f"notify user={user_id} task={task.id}: {exc}"
                    )
        except Exception as exc:
            db.session.rollback()
            summary["errors"].append(f"task={getattr(task, 'id', '?')}: {exc}")

    return summary
