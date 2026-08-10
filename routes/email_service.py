# -*- coding: utf-8 -*-
"""
Email notification service for PhanMemPC06_Pro.
Uses Python's built-in smtplib — no external dependency required.
All config comes from environment variables (loaded via .env).
"""

import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

logger = logging.getLogger(__name__)


def _mail_config():
    """Read mail settings from environment variables."""
    return {
        "server": os.environ.get("MAIL_SERVER", "").strip(),
        "port": int(os.environ.get("MAIL_PORT", "587")),
        "use_tls": os.environ.get("MAIL_USE_TLS", "True").lower() in ("true", "1", "yes"),
        "username": os.environ.get("MAIL_USERNAME", "").strip(),
        "password": os.environ.get("MAIL_PASSWORD", "").strip(),
    }


def _is_configured():
    cfg = _mail_config()
    return bool(cfg["server"] and cfg["username"] and cfg["password"])


def send_email(to_addr, subject, html_body, from_addr=None, cc=None, bcc=None):
    """
    Send a single email. Returns (True, None) on success or (False, error_message) on failure.

    Args:
        to_addr: recipient email address (str)
        subject: email subject line (str)
        html_body: HTML content of the email (str)
        from_addr: optional override sender; defaults to MAIL_USERNAME
        cc: optional list of CC addresses
        bcc: optional list of BCC addresses

    Email is skipped silently (logged as info) if MAIL_* env vars are not configured.
    """
    cfg = _mail_config()
    if not cfg["server"]:
        logger.info("Email skipped: MAIL_SERVER not configured.")
        return False, "Email server not configured (MAIL_SERVER missing)."

    sender = from_addr or cfg["username"]
    if not sender:
        logger.info("Email skipped: no sender address (MAIL_USERNAME missing).")
        return False, "No sender address configured (MAIL_USERNAME missing)."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    if cc:
        msg["Cc"] = ", ".join(cc)

    html_part = MIMEText(html_body, "html", "utf-8")
    msg.attach(html_part)

    recipients = [to_addr]
    if cc:
        recipients.extend(cc)
    if bcc:
        recipients.extend(bcc)

    try:
        if cfg["use_tls"]:
            server = smtplib.SMTP(cfg["server"], cfg["port"], timeout=15)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(cfg["server"], cfg["port"], timeout=15)

        if cfg["password"]:
            server.login(cfg["username"], cfg["password"])

        server.sendmail(sender, recipients, msg.as_string())
        server.quit()
        logger.info("Email sent to %s — subject: %s", to_addr, subject)
        return True, None

    except smtplib.SMTPAuthenticationError as e:
        msg_err = f"SMTP authentication failed: {e}"
        logger.error(msg_err)
        return False, msg_err
    except smtplib.SMTPException as e:
        msg_err = f"SMTP error: {e}"
        logger.error(msg_err)
        return False, msg_err
    except Exception as e:
        msg_err = f"Failed to send email: {e}"
        logger.error(msg_err)
        return False, msg_err


def build_task_assignment_email(user, task, base_url=None):
    """
    Build and send an email notifying a user they've been assigned to a task.

    Args:
        user: User model instance (must have .fullname, .email)
        task: Task model instance (must have .title, .deadline, .id, .created_at)
        base_url: optional base URL for the task detail link

    Returns:
        (True, None) on success, (False, error_message) otherwise.
    """
    if not getattr(user, "email", None):
        logger.info(
            "Email skipped for user '%s' (id=%s): no email address.",
            user.fullname or user.username,
            user.id,
        )
        return False, "User has no email address."

    subject = f"[PC06] Bạn được giao nhiệm vụ: {task.title}"

    deadline_str = ""
    if getattr(task, "deadline", None):
        try:
            deadline_str = task.deadline.strftime("%H:%M %d/%m/%Y")
        except Exception:
            deadline_str = str(task.deadline)

    task_url = ""
    if base_url:
        base_url = base_url.rstrip("/")
        task_url = f"{base_url}/tasks/{task.id}"

    created_at_str = ""
    if getattr(task, "created_at", None):
        try:
            created_at_str = task.created_at.strftime("%H:%M %d/%m/%Y")
        except Exception:
            created_at_str = str(task.created_at)

    html_body = f"""\
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; background: #f5f7fa; margin: 0; padding: 0; }}
    .wrapper {{ max-width: 600px; margin: 24px auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
    .header {{ background: linear-gradient(135deg, #1a73e8, #0d47a1); color: #fff; padding: 28px 24px; }}
    .header h1 {{ margin: 0; font-size: 20px; }}
    .header p {{ margin: 6px 0 0; opacity: 0.85; font-size: 14px; }}
    .body {{ padding: 24px; color: #333; line-height: 1.6; }}
    .body p {{ margin: 0 0 14px; }}
    .info-table {{ width: 100%%; border-collapse: collapse; margin: 16px 0; }}
    .info-table td {{ padding: 8px 12px; border-bottom: 1px solid #e8eaed; font-size: 14px; }}
    .info-table td:first-child {{ font-weight: 600; color: #555; width: 140px; }}
    .btn {{ display: inline-block; background: #1a73e8; color: #fff; padding: 12px 28px; border-radius: 6px; text-decoration: none; font-size: 15px; font-weight: 600; margin-top: 8px; }}
    .footer {{ background: #f8f9fa; padding: 16px 24px; font-size: 12px; color: #888; text-align: center; border-top: 1px solid #e8eaed; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1>Thông báo giao nhiệm vụ</h1>
      <p>Hệ thống quản lý công việc PC06</p>
    </div>
    <div class="body">
      <p>Chào <strong>{user.fullname or user.username}</strong>,</p>
      <p>Bạn vừa được giao một nhiệm vụ mới trên hệ thống. Chi tiết như sau:</p>
      <table class="info-table">
        <tr><td>Tiêu đề</td><td>{task.title}</td></tr>
        <tr><td>Người tạo</td><td>{getattr(task, 'creator_name', '—')}</td></tr>
        <tr><td>Ngày tạo</td><td>{created_at_str or '—'}</td></tr>
        <tr><td>Hạn chót</td><td>{deadline_str or '—'}</td></tr>
      </table>
"""
    if task_url:
        html_body += f"""\
      <p style="margin-top:20px;">
        <a class="btn" href="{task_url}" target="_blank">Xem chi tiết nhiệm vụ</a>
      </p>
"""
    html_body += """\
    </div>
    <div class="footer">
      Email này được gửi tự động từ hệ thống PC06. Vui lòng không trả lời trực tiếp email này.<br>
      &copy; 2026 PC06 — Hệ thống quản lý công việc.
    </div>
  </div>
</body>
</html>"""

    return send_email(user.email, subject, html_body)


def send_task_assignment_emails(users, task, base_url=None):
    """
    Send task assignment emails to a list of users.

    Args:
        users: list of User model instances
        task: Task model instance
        base_url: optional base URL

    Returns:
        dict with keys: sent (list of user ids), skipped (list of (user_id, reason))
    """
    result = {"sent": [], "skipped": []}
    for user in users:
        ok, err = build_task_assignment_email(user, task, base_url)
        if ok:
            result["sent"].append(user.id)
        else:
            result["skipped"].append((user.id, err))
    return result
