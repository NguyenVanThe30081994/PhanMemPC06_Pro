# -*- coding: utf-8 -*-
"""Chạy P0 end-to-end cho 124 xã/phường Tuyên Quang trên DB cô lập.

Ví dụ:
    python scripts/run_tuyen_quang_124_p0.py \
      --pdf "/Users/thenhung/Downloads/Phụ lục ban hành kèm theo KH (1).pdf"

Script cố ý yêu cầu ``--allow-test-data`` và ``--data-dir`` nếu muốn chỉ rõ
thư mục. Không có đường chạy nào để seed vào DATABASE_URL production.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from io import BytesIO
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF = Path("/Users/thenhung/Downloads/Phụ lục ban hành kèm theo KH (1).pdf")
TEST_PASSWORD = "Pc06Test!124"


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    parser.add_argument("--data-dir", type=Path, help="Thư mục DB/storage test; mặc định tạo trong /tmp")
    parser.add_argument(
        "--allow-test-data",
        action="store_true",
        help="Xác nhận rõ đây là DB test cô lập, bắt buộc để script chạy",
    )
    return parser.parse_args()


def _prepare_environment(data_dir, allow_test_data):
    if not allow_test_data:
        raise SystemExit("Từ chối chạy: cần truyền --allow-test-data để bảo vệ DB production.")
    data_dir = Path(data_dir).resolve()
    if data_dir in {APP_ROOT.resolve(), APP_ROOT.parent.resolve()} or APP_ROOT.resolve() in data_dir.parents:
        raise SystemExit("Từ chối chạy: --data-dir phải nằm ngoài thư mục mã nguồn.")
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PC06_PASSENGER"] = "1"
    os.environ["PC06_ALLOW_SQLITE_IN_PASSENGER"] = "1"
    os.environ["PC06_DATA_DIR"] = str(data_dir)
    os.environ["DATABASE_URL"] = f"sqlite:///{data_dir / 'pc06_p0.db'}"
    os.environ["DEBUG"] = "False"
    os.environ["FLASK_ENV"] = "testing"
    os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "Pc06Test!Admin#2026"
    os.environ["PC06_TEST_ISOLATED"] = "1"
    os.environ["GOOGLE_FORMS_ENABLED"] = "False"
    return data_dir


def _login(client, user, csrf_token, is_admin=False):
    with client.session_transaction() as session:
        session["uid"] = user.id
        session["username"] = user.username
        session["fullname"] = user.fullname
        session["unit"] = user.unit_area or ""
        session["unit_area"] = user.unit_area or ""
        session["unit_area_ref"] = user.unit_area or ""
        session["unit_key"] = user.unit_key or ""
        session["role_id"] = user.role_id
        session["must_change"] = False
        session["is_admin"] = is_admin
        session["session_version"] = int(user.session_version or 0)
        session["csrf_token"] = csrf_token
        session["last_active"] = datetime.now().timestamp()


def _build_outline_form(rows, unit_keys, task_deadline, csrf_token):
    data = {
        "csrf_token": csrf_token,
        "task_mode": "OUTLINE",
        "title": "[P0 TEST124] Báo cáo phụ lục Tuyên Quang",
        "description": "Kiểm thử giao việc 75 đầu mục cho 124 xã, phường.",
        "task_type": "Báo cáo đột xuất / một lần",
        "priority": "Cao",
        "deadline": task_deadline,
        "assign_type": "unit",
        "viewer_scope_mode": "none",
        "manager_scope_mode": "none",
        "item_enabled": [str(index) for index in range(len(rows))],
        "item_title": [str(row.get("title") or f"Đầu mục {index + 1}")[:255] for index, row in enumerate(rows)],
        "item_content": [str(row.get("content") or "")[:3000] for row in rows],
        "item_report_kind": [str(row.get("report_kind") or "narrative") for row in rows],
        "item_assign_type": ["unit" for _ in rows],
        "item_domain": ["" for _ in rows],
        "item_domains": [",".join(unit_keys) for _ in rows],
        "item_role_ids": ["" for _ in rows],
        "item_user_ids": ["" for _ in rows],
        "item_parent": ["" for _ in rows],
        "item_inherit": ["" for _ in rows],
        "item_report_secondary": ["" for _ in rows],
        "item_sources": ["" for _ in rows],
        "item_heading": [str(row.get("heading") or "")[:255] for row in rows],
        "item_table_cells": ["" for _ in rows],
        "item_deadline": [str(row.get("deadline") or task_deadline) for row in rows],
        "item_number_fields": [json.dumps(row.get("number_fields") or [], ensure_ascii=False) for row in rows],
    }
    return data


def main():
    args = _parse_args()
    if not args.pdf.is_file():
        raise SystemExit(f"Không tìm thấy PDF: {args.pdf}")
    data_dir = args.data_dir or Path(tempfile.mkdtemp(prefix="pc06_p0_124_"))
    data_dir = _prepare_environment(data_dir, args.allow_test_data)
    if os.environ.get("PC06_PASSENGER") != "1" or not os.environ.get("DATABASE_URL", "").startswith("sqlite:///"):
        raise SystemExit("Từ chối chạy: môi trường P0 không phải SQLite test cô lập.")

    sys.path.insert(0, str(APP_ROOT))
    from werkzeug.datastructures import FileStorage
    from app import app
    from models import AppRole, Task, TaskAssignment, TaskItem, TaskSubmission, User, db
    from permissions import is_admin_role
    from services.outline_rows import _parse_outline_pdf_rows
    from services.tuyen_quang_124_p0 import expected_assignment_count, seed_tuyen_quang_test_accounts

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{data_dir / 'pc06_p0.db'}"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    csrf_token = "tuyen-quang-p0-csrf"

    with app.app_context():
        started = time.perf_counter()
        seed = seed_tuyen_quang_test_accounts(prefix="TEST124_", password=TEST_PASSWORD)
        accounts_path = data_dir / "tuyen_quang_124_accounts.json"
        accounts_path.write_text(json.dumps(seed["accounts"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        account_users = User.query.filter(User.username.like("TEST124_%")).order_by(User.username.asc()).all()
        if len(account_users) != 124:
            raise RuntimeError(f"Seed sai số tài khoản: {len(account_users)}")
        unit_keys = [user.unit_key for user in account_users]
        admin = next((user for user in User.query.order_by(User.id.asc()).all() if is_admin_role(user.role)), None)
        if admin is None:
            raise RuntimeError("Không tìm thấy tài khoản quản trị trong DB test.")
        parse_file = FileStorage(stream=BytesIO(args.pdf.read_bytes()), filename=args.pdf.name, content_type="application/pdf")
        rows = _parse_outline_pdf_rows(parse_file)
        if len(rows) != 75:
            raise RuntimeError(f"PDF phải tạo đúng 75 đầu mục, thực tế {len(rows)}.")

    _login(client, admin, csrf_token, is_admin=True)
    task_deadline = "2026-09-30"
    create_started = time.perf_counter()
    create_response = client.post(
        "/tasks",
        data=_build_outline_form(rows, unit_keys, task_deadline, csrf_token),
        follow_redirects=False,
    )
    create_seconds = time.perf_counter() - create_started
    if create_response.status_code not in {302, 303}:
        raise RuntimeError(f"Tạo nhiệm vụ thất bại: HTTP {create_response.status_code}")

    with app.app_context():
        task = Task.query.filter_by(title="[P0 TEST124] Báo cáo phụ lục Tuyên Quang").order_by(Task.id.desc()).first()
        if task is None:
            raise RuntimeError("Không tìm thấy task P0 sau khi POST.")
        task_id = task.id
        item_count = TaskItem.query.filter_by(task_id=task_id).count()
        assignment_count = TaskAssignment.query.filter_by(task_id=task_id).count()
        assigned_user_count = db.session.query(TaskAssignment.user_id).filter_by(task_id=task_id).distinct().count()
        per_user = Counter(
            user_id
            for (user_id,) in db.session.query(TaskAssignment.user_id).filter_by(task_id=task_id).all()
        )
        assignment_invariant = assignment_count == expected_assignment_count(item_count, 124)
        distribution_invariant = len(per_user) == 124 and min(per_user.values()) == max(per_user.values()) == item_count
        first_item = TaskItem.query.filter_by(task_id=task_id).order_by(TaskItem.sort_order.asc(), TaskItem.id.asc()).first()
        first_user = account_users[0]

    admin_detail_started = time.perf_counter()
    admin_detail = client.get(f"/tasks/{task_id}")
    admin_detail_seconds = time.perf_counter() - admin_detail_started
    admin_dashboard_started = time.perf_counter()
    admin_dashboard = client.get("/tasks/report-dashboard")
    admin_dashboard_seconds = time.perf_counter() - admin_dashboard_started
    export_started = time.perf_counter()
    export_response = client.get(f"/tasks/{task_id}/export-outline.docx")
    export_seconds = time.perf_counter() - export_started
    export_path = data_dir / f"task_{task_id}_outline.docx"
    export_path.write_bytes(export_response.data)

    _login(client, first_user, csrf_token, is_admin=False)
    unit_started = time.perf_counter()
    unit_detail = client.get(f"/tasks/{task_id}")
    unit_detail_seconds = time.perf_counter() - unit_started
    submit_response = client.post(
        f"/tasks/{task_id}/submit_report",
        data={
            "csrf_token": csrf_token,
            "task_item_id": str(first_item.id),
            "report_content": "P0 smoke test: đơn vị đã tiếp nhận và gửi báo cáo.",
        },
        follow_redirects=False,
    )

    visible_units = 0
    visibility_failures = []
    for user in account_users:
        _login(client, user, csrf_token, is_admin=False)
        response = client.get(f"/tasks/{task_id}")
        if response.status_code == 200:
            visible_units += 1
        else:
            visibility_failures.append({"username": user.username, "status": response.status_code})

    with app.app_context():
        submitted_count = TaskAssignment.query.filter_by(task_id=task_id, status="submitted").count()
        submission_count = TaskSubmission.query.filter_by(task_id=task_id, status="submitted").count()
        report = {
            "status": "PASS" if all(
                [
                    item_count == 75,
                    assignment_invariant,
                    distribution_invariant,
                    admin_detail.status_code == 200,
                    admin_dashboard.status_code == 200,
                    export_response.status_code == 200 and len(export_response.data) > 0,
                    unit_detail.status_code == 200,
                    submit_response.status_code in {302, 303},
                    visible_units == 124,
                ]
            ) else "FAIL",
            "scope": "isolated SQLite test DB",
            "pdf": str(args.pdf),
            "data_dir": str(data_dir),
            "task_id": task_id,
            "pdf_items": len(rows),
            "task_items": item_count,
            "accounts": seed["total"],
            "communes": sum(account["kind"] == "xã" for account in seed["accounts"]),
            "wards": sum(account["kind"] == "phường" for account in seed["accounts"]),
            "assignments": assignment_count,
            "expected_assignments": expected_assignment_count(75, 124),
            "assigned_users": assigned_user_count,
            "min_assignments_per_unit": min(per_user.values()),
            "max_assignments_per_unit": max(per_user.values()),
            "visible_units": visible_units,
            "visibility_failures": visibility_failures,
            "submitted_assignments": submitted_count,
            "submitted_submissions": submission_count,
            "http": {
                "create_seconds": round(create_seconds, 3),
                "admin_detail_status": admin_detail.status_code,
                "admin_detail_seconds": round(admin_detail_seconds, 3),
                "admin_dashboard_status": admin_dashboard.status_code,
                "admin_dashboard_seconds": round(admin_dashboard_seconds, 3),
                "export_status": export_response.status_code,
                "export_bytes": len(export_response.data),
                "export_seconds": round(export_seconds, 3),
                "unit_detail_status": unit_detail.status_code,
                "unit_detail_seconds": round(unit_detail_seconds, 3),
                "submit_status": submit_response.status_code,
            },
            "accounts_file": str(accounts_path),
            "export_file": str(export_path),
        }
        report_path = data_dir / "tuyen_quang_124_p0_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
