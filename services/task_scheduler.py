# -*- coding: utf-8 -*-
"""
Nối deadline watchdog vào runtime qua APScheduler.

Cả dev (`python app.py`) lẫn production (`passenger_wsgi.py`) gọi
`start_task_scheduler(app)` để chạy `run_deadline_watchdog` nền theo chu kỳ.

- Mặc định BẬT (chạy mỗi giờ) vì đây là tính năng vận hành cốt lõi đã có test.
- Tắt khi cần bằng `PC06_TASK_SCHEDULER=0` (biến env dạng chữ thường
  `0`/`false`/`no`/`off`).
- An toàn: chỉ khởi động một scheduler cho toàn quá trình (guarded bằng cờ
  trên `app.extensions`), gọi `run_deadline_watchdog` trong app context, mọi
  lỗi được log và không làm chết luồng.

Vì schedule dùng `timestamp()` nên hiếm khi đụng cùng nhịp; có lệnh theo cờ
`PC06_TASK_SCHEDULER_RUN_ONCE` (chu kỳ `date`) để global search/quét nặng.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Chu kỳ quét watchdog (giờ). Cấu hình qua biến môi trường.
_DEFAULT_WATCHDOG_HOUR_INTERVAL = int(os.environ.get("PC06_WATCHDOG_HOURS", "1"))


def task_scheduler_enabled():
    """Cờ bật/tắt scheduler (mặc định bật). Luôn tắt trong test/CI."""
    if os.environ.get("FLASK_ENV") == "testing":
        return False
    raw = os.environ.get("PC06_TASK_SCHEDULER", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def start_task_scheduler(app):
    """Khởi động scheduler nền cho deadline watchdog (bật khi đủ điều kiện)."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except Exception as exc:  # pragma: no cover
        logger.warning("APScheduler không khả dụng, bỏ qua scheduler: %s", exc)
        return

    if not task_scheduler_enabled():
        logger.info("Deadline watchdog scheduler bị tắt (PC06_TASK_SCHEDULER=0).")
        return

    extensions = getattr(app, "extensions", None)
    if extensions is None:  # pragma: no cover
        logger.warning("app.extensions chưa khởi tạo, bỏ qua scheduler.")
        return
    if extensions.get("pc06_task_scheduler"):  # đã chạy, tránh khởi động kép
        return
    try:
        scheduler = BackgroundScheduler(daemon=True)
        # Mỗi interval dùng timestamp riêng để tránh canh đúng cùng lúc.
        scheduler.add_job(
            lambda: _run_watchdog_job(app),
            "interval",
            hours=max(_DEFAULT_WATCHDOG_HOUR_INTERVAL, 1),
            id="pc06_deadline_watchdog",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        extensions["pc06_task_scheduler"] = scheduler
        logger.info(
            "Deadline watchdog scheduler đã bật (mỗi %s giờ).",
            max(_DEFAULT_WATCHDOG_HOUR_INTERVAL, 1),
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Không thể khởi động scheduler: %s", exc)


def _run_watchdog_job(app):
    """Chạy watchdog trong app context; log tóm tắt, không ném lỗi ra ngoài."""
    with app.app_context():
        try:
            from services.deadline_watchdog import run_deadline_watchdog

            summary = run_deadline_watchdog()
            logger.info(
                "Deadline watchdog: scanned=%s notifications=%s emails=%s levels=%s",
                summary.get("scanned", 0),
                summary.get("notifications_created", 0),
                summary.get("emails_sent", 0),
                summary.get("levels", {}),
            )
        except Exception as exc:  # pragma: no cover
            logger.exception("Deadline watchdog job thất bại: %s", exc)


def current_task_scheduler(app):
    """Trả scheduler đang chạy (nếu có) — dùng cho test/teardown."""
    extensions = getattr(app, "extensions", None)
    if not extensions:
        return None
    return extensions.get("pc06_task_scheduler")
