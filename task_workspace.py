# -*- coding: utf-8 -*-
from datetime import date

from report_cycles import cycle_summary_text


def task_assignment_display_status(status, status_labels, normalize_status):
    raw_value = str(status or "").strip()
    if not raw_value:
        return "Chưa tiếp nhận"
    lowered = raw_value.lower()
    if lowered in status_labels:
        return status_labels[lowered]
    return normalize_status(raw_value)


def summarize_task_assignments(assignments, current_uid, is_submitted):
    normalized_assignments = list(assignments or [])
    total_assignments = len(normalized_assignments)
    submitted_assignments = sum(1 for assignment in normalized_assignments if is_submitted(assignment))
    in_progress_assignments = sum(
        1
        for assignment in normalized_assignments
        if str(getattr(assignment, "status", "") or "").strip().lower() == "in_progress"
    )
    current_assignment = next(
        (assignment for assignment in normalized_assignments if getattr(assignment, "user_id", None) == current_uid),
        None,
    )
    progress_percent = int(round((submitted_assignments / total_assignments) * 100)) if total_assignments else 0
    return {
        "total_assignments": total_assignments,
        "submitted_assignments": submitted_assignments,
        "in_progress_assignments": in_progress_assignments,
        "current_assignment": current_assignment,
        "progress_percent": progress_percent,
    }


def task_deadline_display(deadline, today=None):
    if not deadline:
        return "Không đặt hạn"
    today = today or date.today()
    delta_days = (deadline - today).days
    if delta_days < 0:
        return f"Quá hạn {abs(delta_days)} ngày"
    if delta_days == 0:
        return "Đến hạn hôm nay"
    if delta_days == 1:
        return "Hạn ngày mai"
    return f"Còn {delta_days} ngày"


def task_workspace_tone(status_text, is_overdue=False):
    normalized = str(status_text or "").strip().lower()
    if is_overdue or "quá hạn" in normalized:
        return "danger"
    if normalized in {"hoàn thành", "đã nộp", "đã nhận đủ báo cáo", "đã hoàn tất"}:
        return "success"
    if normalized in {"đang thực hiện", "đang theo dõi tiến độ", "đang triển khai", "bị trả lại"}:
        return "warning"
    if normalized in {"chờ đơn vị tiếp nhận", "chưa tiếp nhận", "chưa bắt đầu", "chưa phân công", "chưa có người nhận", "chờ thiết lập đầu mục"}:
        return "muted"
    return "info"


def task_assignment_submit_scope(assignment):
    assignee_type = str(getattr(assignment, "assignee_type", "") or "user").strip().lower()
    if assignee_type == "unit":
        return {
            "mode": "unit",
            "label": "Nộp theo đơn vị",
            "hint": "Nhiệm vụ này được giao theo đơn vị. Một cán bộ đại diện nộp báo cáo là hệ thống sẽ ghi nhận cho cả đơn vị.",
        }
    if assignee_type == "role":
        return {
            "mode": "role",
            "label": "Nộp theo vai trò",
            "hint": "Nhiệm vụ này được giao theo vai trò trong từng đơn vị. Một cán bộ đại diện của nhóm nhận việc nộp báo cáo là hệ thống sẽ ghi nhận cho cả nhóm.",
        }
    return {"mode": "user", "label": "", "hint": ""}


def build_task_detail_context(
    task,
    summary,
    mode,
    can_manage_task_view,
    can_submit,
    status_labels,
    normalize_status,
    my_file_assignment=None,
    my_form_assignment=None,
    outline_groups=None,
    today=None,
):
    outline_groups = outline_groups or []
    total_assignments = int(summary.get("total_assignments", 0) or 0)
    submitted_assignments = int(summary.get("submitted_assignments", 0) or 0)
    in_progress_assignments = int(summary.get("in_progress_assignments", 0) or 0)
    progress_percent = int(summary.get("progress_percent", 0) or 0)
    is_complete = bool(total_assignments and submitted_assignments >= total_assignments)
    today = today or date.today()
    task_deadline = getattr(task, "deadline", None)
    is_overdue = bool(task_deadline and task_deadline < today and not is_complete)

    if mode == "OUTLINE" and total_assignments == 0 and can_manage_task_view:
        status_text = "Chờ thiết lập đầu mục"
    elif total_assignments == 0:
        status_text = "Chưa phân công"
    elif is_complete:
        status_text = "Đã hoàn tất"
    elif is_overdue:
        status_text = "Quá hạn cần xử lý"
    elif submitted_assignments > 0 or in_progress_assignments > 0:
        status_text = "Đang triển khai"
    else:
        status_text = "Chờ tiếp nhận"

    next_step_title = "Theo dõi tiến độ công việc"
    next_step_body = "Xem nhanh trạng thái chung rồi đi thẳng vào khu vực làm việc phù hợp ở bên dưới."
    default_tab = "overview"
    submit_status_text = ""
    submit_scope_mode = ""
    submit_scope_label = ""
    submit_scope_hint = ""

    if mode == "OUTLINE":
        if can_manage_task_view and not outline_groups:
            next_step_title = "Thiết lập đầu mục đầu tiên"
            next_step_body = "Bắt đầu ở mục thiết lập đầu mục để tạo nội dung báo cáo, gán người nhận và chuẩn hóa cách nộp."
            default_tab = "outline-create"
        elif can_manage_task_view:
            next_step_title = "Theo dõi tiến độ chung"
            next_step_body = "Xem ma trận tiến độ để biết đầu mục nào còn thiếu, rồi mở từng nhóm khi cần kiểm tra chi tiết."
            default_tab = "outline-matrix"
        else:
            next_step_title = "Mở đúng nhóm được giao"
            next_step_body = "Chọn nhóm nhận việc của bạn để tiếp nhận và gửi báo cáo theo từng đầu mục cụ thể."
            default_tab = "outline-group"
    elif mode == "FILE":
        assignment = my_file_assignment if can_submit else None
        submit_scope = task_assignment_submit_scope(assignment)
        submit_scope_mode = submit_scope["mode"]
        submit_scope_label = submit_scope["label"]
        submit_scope_hint = submit_scope["hint"]
        submit_status_text = task_assignment_display_status(
            getattr(assignment, "status", ""),
            status_labels,
            normalize_status,
        ) if assignment else ""
        if assignment:
            default_tab = "file-submit"
            if str(getattr(assignment, "status", "") or "").strip().lower() == "assigned":
                next_step_title = "Tiếp nhận rồi nộp báo cáo"
                next_step_body = submit_scope_hint or "Tiếp nhận công việc trước, sau đó cập nhật nội dung tóm tắt và tải tệp báo cáo của bạn."
            else:
                next_step_title = "Cập nhật phần việc của bạn"
                next_step_body = submit_scope_hint or "Phần việc của bạn đang mở. Kiểm tra lại nội dung và nộp tệp mới nhất nếu cần."
        elif can_manage_task_view:
            default_tab = "file-list"
            next_step_title = "Theo dõi tiến độ người nhận"
            next_step_body = "Xem ai đã nộp, ai chưa nộp, rồi mở chi tiết để đôn đốc hoặc kiểm tra kết quả."
        else:
            default_tab = "file-list"
            next_step_title = "Xem tiến độ chung"
            next_step_body = "Bạn đang ở chế độ xem. Theo dõi trạng thái nộp của các đơn vị/cán bộ trong danh sách."
    else:
        assignment = my_form_assignment if can_submit else None
        submit_scope = task_assignment_submit_scope(assignment)
        submit_scope_mode = submit_scope["mode"]
        submit_scope_label = submit_scope["label"]
        submit_scope_hint = submit_scope["hint"]
        submit_status_text = task_assignment_display_status(
            getattr(assignment, "status", ""),
            status_labels,
            normalize_status,
        ) if assignment else ""
        if assignment:
            default_tab = "form-submit"
            if str(getattr(assignment, "status", "") or "").strip().lower() == "assigned":
                next_step_title = "Tiếp nhận rồi nhập biểu mẫu"
                next_step_body = submit_scope_hint or "Tiếp nhận công việc trước, sau đó nhập đầy đủ các trường bắt buộc trong biểu mẫu của bạn."
            else:
                next_step_title = "Cập nhật biểu mẫu của bạn"
                next_step_body = submit_scope_hint or "Mở phần việc của bạn để kiểm tra dữ liệu đã nhập và gửi lại nếu cần chỉnh sửa."
        elif can_manage_task_view:
            default_tab = "form-list"
            next_step_title = "Theo dõi dữ liệu đã nộp"
            next_step_body = "Xem nhanh đơn vị nào đã nhập biểu mẫu, rồi mở dữ liệu chi tiết hoặc xuất Excel khi cần tổng hợp."
        else:
            default_tab = "form-list"
            next_step_title = "Xem dữ liệu biểu mẫu"
            next_step_body = "Bạn đang ở chế độ xem. Theo dõi trạng thái và nội dung biểu mẫu đã được các đơn vị gửi lên."

    return {
        "status_text": status_text,
        "status_tone": task_workspace_tone(status_text, is_overdue=is_overdue),
        "next_step_title": next_step_title,
        "next_step_body": next_step_body,
        "default_tab": default_tab,
        "submit_status_text": submit_status_text,
        "submit_scope_mode": submit_scope_mode,
        "submit_scope_label": submit_scope_label,
        "submit_scope_hint": submit_scope_hint,
        "is_complete": is_complete,
        "is_overdue": is_overdue,
        "progress_percent": progress_percent,
    }


def build_task_workspace_attrs(task, summary, current_uid, current_status_text, today=None):
    today = today or date.today()
    total_assignments = int(getattr(task, "assignee_count", 0) or summary.get("total_assignments", 0) or 0)
    submitted_assignments = int(getattr(task, "submitted_assignments", 0) or summary.get("submitted_assignments", 0) or 0)
    in_progress_assignments = int(getattr(task, "in_progress_assignments", 0) or summary.get("in_progress_assignments", 0) or 0)
    progress_percent = int(getattr(task, "progress_percent", 0) or summary.get("progress_percent", 0) or 0)
    is_overdue = bool(getattr(task, "is_overdue", False))
    is_complete = bool(total_assignments and submitted_assignments >= total_assignments)
    current_assignment = summary.get("current_assignment")
    is_my_task = current_assignment is not None
    is_managed_task = bool(getattr(task, "can_edit", False) or getattr(task, "author_id", None) == current_uid)

    if total_assignments == 0:
        manager_status_text = "Chưa phân công"
        watch_status_text = "Chưa có người nhận"
    elif is_complete:
        manager_status_text = "Đã nhận đủ báo cáo"
        watch_status_text = "Đã hoàn tất"
    elif submitted_assignments > 0 or in_progress_assignments > 0:
        manager_status_text = "Đang theo dõi tiến độ"
        watch_status_text = "Đang triển khai"
    else:
        manager_status_text = "Chờ đơn vị tiếp nhận"
        watch_status_text = "Chưa bắt đầu"

    if is_my_task:
        workspace_role = "my"
        workspace_status_text = current_status_text or "Chưa tiếp nhận"
        workspace_action_label = "Xử lý ngay" if not is_complete else "Xem kết quả"
    elif is_managed_task:
        workspace_role = "managed"
        workspace_status_text = manager_status_text
        workspace_action_label = "Theo dõi tiến độ"
    else:
        workspace_role = "watch"
        workspace_status_text = watch_status_text
        workspace_action_label = "Xem chi tiết"

    if is_overdue and not is_complete:
        workspace_status_text = "Quá hạn cần xử lý"

    task_deadline = getattr(task, "deadline", None)
    due_soon = bool(task_deadline and not is_overdue and not is_complete and (task_deadline - today).days <= 3)
    needs_attention = bool(
        is_overdue
        or due_soon
        or (is_my_task and workspace_status_text in {"Chưa tiếp nhận", "Đang thực hiện", "Bị trả lại"})
    )

    preview_text = str(getattr(task, "content", "") or "").strip()
    if len(preview_text) > 160:
        preview_text = f"{preview_text[:157]}..."

    cycle_text = ""
    try:
        cycle_text = cycle_summary_text(task, today=today)
    except Exception:
        cycle_text = ""
    if cycle_text:
        workspace_deadline_text = cycle_text
    else:
        workspace_deadline_text = task_deadline_display(task_deadline, today=today)

    return {
        "is_complete": is_complete,
        "workspace_role": workspace_role,
        "workspace_status_text": workspace_status_text,
        "workspace_tone": task_workspace_tone(workspace_status_text, is_overdue=is_overdue),
        "workspace_action_label": workspace_action_label,
        "workspace_deadline_text": workspace_deadline_text,
        "workspace_needs_attention": needs_attention,
        "workspace_due_soon": due_soon,
        "workspace_preview_text": preview_text or "Chưa có mô tả.",
        "workspace_meta_text": f"{submitted_assignments}/{total_assignments} lượt nộp",
        "progress_percent": progress_percent,
    }
