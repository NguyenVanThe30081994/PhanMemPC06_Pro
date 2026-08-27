# -*- coding: utf-8 -*-
"""
Test đầu vào (input testing) chức năng GIAO VIỆC theo đề cương
với file biểu mẫu thật: "Đề cương báo cáo ĐA06 - H.T.Q.docx"

Chạy: /tmp/pc06_venv/bin/python scripts/test_da06_input.py
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DOCX_PATH = "/Users/thenhung/Downloads/Đề cương báo cáo ĐA06 - H.T.Q.docx"

results = []


def record(step, status, detail=""):
    results.append((step, status, detail))
    icon = "PASS" if status == "PASS" else ("FAIL" if status == "FAIL" else "INFO")
    print(f"[{icon}] {step}" + (f" — {detail}" if detail else ""))


def main():
    from app import app, db
    from models import Task, TaskItem, TaskAssignment, TaskParticipant, Notification, User
    from outline_parser import parse_docx, collect_stats, dump_tree

    # ── BƯỚC 1: Parse file biểu mẫu thật ──────────────────────────────
    with open(DOCX_PATH, "rb") as f:
        docx_bytes = f.read()
    tree = parse_docx(docx_bytes)
    stats = collect_stats(tree)
    record(
        "P1. Parser .docx → cây cấu trúc",
        "PASS",
        f'title="{tree["title"]}", sections={len(tree["sections"])}, stats={stats}',
    )

    n_headings = stats["h1"] + stats["h2"] + stats["h3"] + stats["h4"]

    def count_headings(nodes):
        c = 0
        for n in nodes:
            if n["type"].startswith("h"):
                c += 1 + count_headings(n.get("children") or [])
        return c

    total_headings = count_headings(tree["sections"])
    print("     Tổng số mục (heading) trong biểu mẫu:", total_headings)

    # ── BƯỚC 2: Upload qua API /api/parse-outline ──────────────────────
    client = app.test_client()

    # lấy admin (test db tự seed khi import app)
    with app.app_context():
        admin = User.query.filter_by(username="admin").first()
        if not admin:
            raise RuntimeError("Không tìm thấy user admin trong DB test")
        admin_id, admin_name = admin.id, admin.fullname
        # tạo 2 cán bộ nhận việc
        import uuid as _uuid

        created_ids = []
        for nm in ("Cán bộ A (test ĐA06)", "Cán bộ B (test ĐA06"):
            u = User(
                username=f"da06_{_uuid.uuid4().hex[:8]}",
                fullname=nm,
                is_active=True,
            )
            u.set_password("123456")
            db.session.add(u)
            db.session.commit()
            created_ids.append(u.id)
        cb_a, cb_b = created_ids

    with client.session_transaction() as sess:
        sess["uid"] = admin_id
        sess["username"] = "admin"
        sess["fullname"] = admin_name
        sess["role_id"] = None
        sess["is_admin"] = True
        sess["session_version"] = 0
        sess["csrf_token"] = "da06-input-test"
        sess["last_active"] = __import__("time").time()
        sess["login_nonce"] = "da06-input-test"

    resp = client.post(
        "/api/parse-outline",
        data={"file": (io.BytesIO(docx_bytes), "De cuong bao cao DA06 - H.T.Q.docx")},
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": "da06-input-test"},
    )
    if resp.status_code != 200:
        record("P2. POST /api/parse-outline", "FAIL", f"{resp.status_code} {resp.get_json()}")
        return
    payload = resp.get_json()
    record(
        "P2. POST /api/parse-outline",
        "PASS",
        f'sections={len(payload.get("sections") or [])}, stats={payload.get("stats")}',
    )

    # ── BƯỚC 3: Giao việc — gán mục cho cán bộ, gọi /api/create-outline-task ──
    def find_section(nodes, label_prefix):
        for n in nodes:
            if n.get("label") == label_prefix and n["type"].startswith("h"):
                return n
            found = find_section(n.get("children") or [], label_prefix)
            if found:
                return found
        return None

    sections = payload.get("sections") or []
    muc_1 = find_section(sections, "1")       # 1. CÔNG TÁC THAM MƯU...
    muc_22 = find_section(sections, "2.2")    # 2.2 Nhận xét, đánh giá
    muc_81 = find_section(sections, "8")      # 8. Mô hình điểm Đề án 06
    targets = [s for s in (muc_1, muc_22, muc_81) if s]
    record(
        "P3a. Chọn 3 mục để gán",
        "PASS" if len(targets) == 3 else "FAIL",
        "labels=" + ", ".join(s.get("label") + ". " + (s.get("text") or "")[:40] for s in targets),
    )

    assignments = {}
    for i, sec in enumerate(targets):
        assignments[str(sec["id"])] = {"ids": [cb_a if i % 2 == 0 else cb_b]}

    body = {
        "tree": payload,
        "title": "[TEST ĐẦU VÀO] Báo cáo ĐA06 theo đề cương H.T.Q",
        "deadline": "2026-09-30",
        "assignments": assignments,
    }
    resp = client.post(
        "/api/create-outline-task",
        data=json.dumps(body),
        content_type="application/json",
        headers={"X-CSRF-Token": "da06-input-test"},
    )
    if resp.status_code != 200:
        record("P3b. POST /api/create-outline-task", "FAIL", f"{resp.status_code} {resp.get_json()}")
        return
    data = resp.get_json()
    record(
        "P3b. POST /api/create-outline-task",
        "PASS",
        f'task_id={data["task_id"]}, items={data["items_created"]}, '
        f'giao={data["assignments_created"]}, notif={data["notifications_created"]}, email={data["emails_sent"]}',
    )
    task_id = data["task_id"]

    # ── BƯỚC 4: Kiểm tra dữ liệu DB sau khi giao ───────────────────────
    with app.app_context():
        task = db.session.get(Task, task_id)
        record(
            "P4a. Task trong DB",
            "PASS" if task and task.task_mode == "OUTLINE" else "FAIL",
            f'task_mode={task.task_mode}, status={task.initial_status}, deadline={task.deadline}',
        )
        items = TaskItem.query.filter_by(task_id=task_id).order_by(TaskItem.sort_order).all()
        record("P4b. TaskItem", "PASS", f"count={len(items)}")
        for it in items:
            preview = (it.title or "")[:60]
            n_lines = len((it.content or "").splitlines())
            print(f"       - item {it.item_code}: [{preview}] ({n_lines} dòng nội dung gộp)")

        assigns = TaskAssignment.query.filter_by(task_id=task_id).all()
        ok_assign = all(a.user_id in (cb_a, cb_b) and a.status == "assigned" for a in assigns)
        record(
            "P4c. TaskAssignment",
            "PASS" if assigns and ok_assign else "FAIL",
            f"count={len(assigns)}, user_ids={sorted({a.user_id for a in assigns})}",
        )
        parts = TaskParticipant.query.filter_by(task_id=task_id).all()
        record(
            "P4d. TaskParticipant (cầu nối runtime)",
            "PASS" if parts else "FAIL",
            f"count={len(parts)}",
        )
        notifs = Notification.query.filter_by(link=f"/tasks/{task_id}").all()
        record("P4e. Thông báo (Notification)", "PASS" if notifs else "FAIL", f"count={len(notifs)}")
        scope = json.loads(task.assignment_scope_json or "{}")
        record(
            "P4f. Phạm vi giao (assignment_scope)",
            "PASS" if scope.get("mode") == "user" else "FAIL",
            f"mode={scope.get('mode')}, user_ids={scope.get('user_ids')}",
        )

    # ── BƯỚC 5: Người được giao nhìn thấy việc & nộp báo cáo ──────────
    with client.session_transaction() as sess:
        sess["uid"] = cb_a
        sess["username"] = "canbo_a"
        sess["fullname"] = "Cán bộ A (test ĐA06)"
        sess["role_id"] = None
        sess["is_admin"] = False
        sess["session_version"] = 0
        sess["csrf_token"] = "da06-input-test"
        sess["last_active"] = __import__("time").time()
        sess["login_nonce"] = "da06-input-test"

    resp = client.get(f"/tasks/{task_id}")
    record("P5a. GET /tasks/<id> (người thực hiện)", "PASS" if resp.status_code == 200 else "FAIL", f"HTTP {resp.status_code}")

    # tìm assignment + task_item của Cán bộ A rồi POST nộp báo cáo theo đúng
    # route chuẩn: POST /tasks/<id>/submit_report (task_item_id + report_content)
    with app.app_context():
        a_of_a = TaskAssignment.query.filter_by(task_id=task_id, user_id=cb_a).first()
        assign_id = a_of_a.id if a_of_a else None
        item_id = a_of_a.task_item_id if a_of_a else None
    resp = client.post(
        f"/tasks/{task_id}/submit_report",
        data={
            "csrf_token": "da06-input-test",
            "task_item_id": str(item_id or ""),
            "report_content": "Kết quả báo cáo tháng 8/2026 của mục được giao: đã hoàn thành tham mưu ban hành 3 văn bản.",
        },
        follow_redirects=True,
    )
    record("P5b. POST nộp báo cáo (submit_report)", "PASS" if resp.status_code == 200 else "FAIL", f"HTTP {resp.status_code}")

    with app.app_context():
        from models import TaskSubmission

        subs = TaskSubmission.query.filter_by(task_id=task_id).all()
        record(
            "P5c. TaskSubmission lưu trong DB",
            "PASS" if subs else "FAIL",
            f'count={len(subs)}, status={subs[0].status if subs else "-"}',
        )

    # ── BƯỚC 6: Xuất Word tổng hợp ────────────────────────────────────
    resp = client.get(f"/tasks/{task_id}/export-outline.docx")
    ctype = resp.headers.get("Content-Type", "")
    is_docx = resp.status_code == 200 and "wordprocessingml" in ctype and resp.data[:2] == b"PK"
    record(
        "P6. GET /tasks/<id>/export-outline.docx (admin)",
        "PASS" if is_docx else "FAIL",
        f"HTTP {resp.status_code}, size={len(resp.data)}B",
    )

    # ── Dọn dẹp ───────────────────────────────────────────────────────
    with app.app_context():
        from models import TaskComment

        TaskComment.query.filter_by(task_id=task_id).delete()
        TaskAssignment.query.filter_by(task_id=task_id).update(
            {TaskAssignment.last_submission_id: None}, synchronize_session=False
        )
        TaskSubmission.query.filter_by(task_id=task_id).delete()
        TaskAssignment.query.filter_by(task_id=task_id).delete()
        TaskParticipant.query.filter_by(task_id=task_id).delete()
        TaskItem.query.filter_by(task_id=task_id).delete()
        TaskFormField if False else None
        Task.query.filter_by(id=task_id).delete()
        Notification.query.filter_by(link=f"/tasks/{task_id}").delete()
        for uid in (cb_a, cb_b):
            TaskParticipant.query.filter_by(user_id=uid).delete()
            TaskAssignment.query.filter_by(user_id=uid).delete()
            User.query.filter_by(id=uid).delete()
        db.session.commit()

    print("\n═══════ TỔNG KẾT ═══════")
    n_pass = sum(1 for _, s, _ in results if s == "PASS")
    n_fail = sum(1 for _, s, _ in results if s == "FAIL")
    for step, status, detail in results:
        print(f"  {status:4} | {step}")
    print(f"  → {n_pass} PASS / {n_fail} FAIL")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
