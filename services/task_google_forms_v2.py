# -*- coding: utf-8 -*-
"""
Cụm đồng bộ Google Form cho task: trả assignment về (_return_task_assignment_v2),
tạo/cập nhật/xuất bản/nhập cấu trúc/đồng bộ phản hồi Google Form
(_create_task_google_form_v2, _update_task_google_form_v2, _publish_task_google_form_v2,
_import_task_google_form_structure_v2, _sync_google_form_task_v2).

Tách từ routes/tasks.py (Pha 2). routes/tasks.py re-export các tên còn dùng.
"""

from datetime import datetime

from flask import current_app, flash, redirect, request, session, url_for

from models import (
    Task,
    TaskAssignment,
    TaskComment,
    TaskSubmission,
    User,
    db,
)
from google_forms import (
    build_google_forms_service,
    create_google_form,
    extract_google_form_id,
    fetch_google_form_definition,
    fetch_google_form_responses,
    load_google_form_into_builder,
    parse_google_form_definition,
    parse_google_form_responses,
    publish_google_form,
    update_google_form,
)
from permissions import current_is_admin

from services.task_google_forms import (
    _filter_google_form_response_for_assignment,
    _hydrate_google_form_fields,
    _match_google_form_response_to_assignment,
    _merge_google_form_field_targets,
    _normalize_google_form_builder_schema_with_targets,
    _normalize_google_form_match_mode,
    _parse_google_form_builder_schema,
    _replace_task_form_fields,
    _task_google_form_builder,
    _task_google_form_manage_service,
    _task_google_form_runtime,
    _task_google_form_runtime_payload,
    _task_google_form_sync_state,
)
from services.task_guards import (
    _can_edit_task,
    _can_manage_task,
    _can_watch_task,
)
from services.task_import_draft_helpers import _json_dump
from services.task_import_drafts import (
    _task_assignment_scope_lists,
    _validate_task_visibility_before_publish,
)
from services.task_modes import _task_mode
from services.task_permissions import _can_process_task_module, _current_perms
from services.task_runtime_sync import _task_assignment_records
from services.task_units import _dedupe_users
from services.task_workspace_helpers import _sync_assignment_group_submission

def _return_task_assignment_v2(tid, assignment_id):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404
    assignment = TaskAssignment.query.filter_by(id=assignment_id, task_id=tid).first()
    if not assignment:
        flash("Không tìm thấy phần việc cần trả lại.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
        or _can_watch_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền trả lại phần việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    reason = (request.form.get("return_reason") or "").strip()[:500]
    assignment.status = "returned"
    assignment.returned_at = datetime.now()
    assignment.updated_at = datetime.now()
    db.session.add(
        TaskComment(
            task_id=task.id,
            user_id=session["uid"],
            user_name=session.get("fullname", "Quản trị"),
            content=f"[TRẢ LẠI] {reason or 'Yêu cầu bổ sung nội dung'}",
        )
    )
    db.session.commit()
    flash("Đã trả lại phần việc để bổ sung.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _create_task_google_form_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền tạo Google Form cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if _task_mode(task) != "FORM":
        flash("Công việc này không dùng chế độ biểu mẫu.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        builder_schema = _parse_google_form_builder_schema(
            getattr(task, "google_form_builder_json", None),
            fallback_title=task.title or "Biểu mẫu",
            fallback_description=task.content or "",
        )
        service = _task_google_form_manage_service()
        runtime = create_google_form(
            service,
            builder_schema,
            title=task.title or builder_schema.get("form_info", {}).get("title") or "Biểu mẫu",
            description=task.content or builder_schema.get("form_info", {}).get("description") or "",
        )
    except Exception as exc:
        flash(str(exc) or "Không thể tạo Google Form thật.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task.form_provider = "google"
    task.google_form_builder_json = _json_dump(builder_schema)
    task.google_form_id = str(runtime.get("form_id") or "").strip() or None
    task.google_form_url = str(runtime.get("form_url") or "").strip() or task.google_form_url
    task.google_form_match_mode = _normalize_google_form_match_mode(
        task.google_form_match_mode or builder_schema.get("matching", {}).get("mode") or "unit"
    )
    task.google_form_match_field = str(
        task.google_form_match_field or builder_schema.get("matching", {}).get("match_field") or ""
    ).strip()[:255] or None
    task.google_form_runtime_json = _json_dump(_task_google_form_runtime_payload(task, runtime.get("raw"), runtime))
    actual_fields, _question_map = parse_google_form_definition(runtime.get("raw") or {})
    field_defs = _merge_google_form_field_targets(actual_fields, task=task, builder_schema=builder_schema) if actual_fields else _hydrate_google_form_fields(builder_schema)
    assignment_scope = _task_assignment_scope_lists(task)
    assignees = [assignment.user for assignment in _task_assignment_records(task) if getattr(assignment, "user", None)]
    try:
        _validate_task_visibility_before_publish(
            "FORM",
            _dedupe_users(assignees),
            assign_type=assignment_scope["assign_type"],
            domain=assignment_scope["domain"],
            role_ids=assignment_scope["role_ids"],
            user_ids=assignment_scope["user_ids"],
            field_defs=field_defs,
            ignored_form_field_labels=[task.google_form_match_field] if task.google_form_match_field else [],
        )
    except ValueError as visibility_error:
        flash(str(visibility_error), "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if actual_fields:
        _replace_task_form_fields(task, field_defs)
    db.session.add(task)
    db.session.commit()
    flash("Đã tạo Google Form thật từ builder.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _update_task_google_form_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền cập nhật Google Form cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if _task_mode(task) != "FORM":
        flash("Công việc này không dùng chế độ biểu mẫu.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        builder_schema = _parse_google_form_builder_schema(
            request.form.get("google_form_builder_json") or getattr(task, "google_form_builder_json", None),
            fallback_title=task.title or "Biểu mẫu",
            fallback_description=task.content or "",
        )
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task.form_provider = "google"
    task.google_form_builder_json = _json_dump(builder_schema)
    task.google_form_match_mode = _normalize_google_form_match_mode(
        builder_schema.get("matching", {}).get("mode") or task.google_form_match_mode or "unit"
    )
    task.google_form_match_field = str(
        builder_schema.get("matching", {}).get("match_field") or task.google_form_match_field or ""
    ).strip()[:255] or None

    assignment_scope = _task_assignment_scope_lists(task)
    assignees = _dedupe_users([assignment.user for assignment in _task_assignment_records(task) if getattr(assignment, "user", None)])
    if not getattr(task, "google_form_id", None):
        hydrated_fields = _hydrate_google_form_fields(builder_schema)
        try:
            _validate_task_visibility_before_publish(
                "FORM",
                assignees,
                assign_type=assignment_scope["assign_type"],
                domain=assignment_scope["domain"],
                role_ids=assignment_scope["role_ids"],
                user_ids=assignment_scope["user_ids"],
                field_defs=hydrated_fields,
                ignored_form_field_labels=[task.google_form_match_field] if task.google_form_match_field else [],
            )
        except ValueError as visibility_error:
            flash(str(visibility_error), "danger")
            return redirect(url_for("tasks_bp.task_detail", tid=tid))
        if hydrated_fields:
            _replace_task_form_fields(task, hydrated_fields)
        db.session.add(task)
        db.session.commit()
        flash("Đã lưu schema builder Google Form.", "success")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        service = _task_google_form_manage_service()
        runtime = update_google_form(
            service,
            task.google_form_id,
            builder_schema,
            revision_id=_task_google_form_runtime(task).get("revision_id"),
        )
    except Exception as exc:
        flash(str(exc) or "Không thể cập nhật Google Form thật.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    task.google_form_url = str(runtime.get("form_url") or task.google_form_url or "").strip() or None
    task.google_form_runtime_json = _json_dump(_task_google_form_runtime_payload(task, runtime.get("raw"), runtime))
    actual_fields, _question_map = parse_google_form_definition(runtime.get("raw") or {})
    field_defs = _merge_google_form_field_targets(actual_fields, task=task, builder_schema=builder_schema) if actual_fields else []
    try:
        _validate_task_visibility_before_publish(
            "FORM",
            assignees,
            assign_type=assignment_scope["assign_type"],
            domain=assignment_scope["domain"],
            role_ids=assignment_scope["role_ids"],
            user_ids=assignment_scope["user_ids"],
            field_defs=field_defs,
            ignored_form_field_labels=[task.google_form_match_field] if task.google_form_match_field else [],
        )
    except ValueError as visibility_error:
        flash(str(visibility_error), "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if actual_fields:
        _replace_task_form_fields(task, field_defs)
    db.session.add(task)
    db.session.commit()
    flash("Đã cập nhật Google Form thật theo builder.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _publish_task_google_form_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền phát hành Google Form cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if not getattr(task, "google_form_id", None):
        flash("Công việc này chưa có Google Form thật để phát hành.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    is_published = str(request.form.get("is_published") or "true").strip().lower() in {"1", "true", "yes", "on"}
    accept_responses = str(request.form.get("accept_responses") or "true").strip().lower() in {"1", "true", "yes", "on"}
    try:
        service = _task_google_form_manage_service()
        publish_result = publish_google_form(
            service,
            task.google_form_id,
            is_published=is_published,
            accept_responses=accept_responses,
        )
    except Exception as exc:
        flash(str(exc) or "Không thể đổi trạng thái phát hành Google Form.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    runtime = _task_google_form_runtime(task)
    runtime["publish_settings"] = publish_result.get("publishSettings") or runtime.get("publish_settings") or {}
    task.google_form_runtime_json = _json_dump(runtime)
    db.session.add(task)
    db.session.commit()
    flash("Đã cập nhật trạng thái phát hành Google Form.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _import_task_google_form_structure_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    if not can_manage_task_view:
        flash("Bạn không có quyền nhập cấu trúc Google Form cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    form_reference = str(request.form.get("google_form_url") or getattr(task, "google_form_url", None) or getattr(task, "google_form_id", None) or "").strip()
    form_id = extract_google_form_id(form_reference)
    if not form_id:
        flash("Không nhận diện được Google Form URL hoặc form ID.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        service = build_google_forms_service(current_app.config)
        imported = load_google_form_into_builder(service, form_id)
    except Exception as exc:
        flash(str(exc) or "Không thể nhập cấu trúc từ Google Form.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    builder_schema = imported.get("builder_schema") if isinstance(imported, dict) else {}
    form_payload = imported.get("form_payload") if isinstance(imported, dict) else {}
    if not isinstance(builder_schema, dict):
        flash("Google Form không trả về schema builder hợp lệ.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    builder_schema.setdefault("matching", {})
    builder_schema["matching"]["mode"] = _normalize_google_form_match_mode(
        request.form.get("google_form_match_mode") or task.google_form_match_mode or builder_schema["matching"].get("mode") or "unit"
    )
    builder_schema["matching"]["match_field"] = str(
        request.form.get("google_form_match_field") or task.google_form_match_field or builder_schema["matching"].get("match_field") or ""
    ).strip()[:255]
    builder_schema = _normalize_google_form_builder_schema_with_targets(
        builder_schema,
        fallback_title=task.title or "Biểu mẫu",
        fallback_description=task.content or "",
    )

    task.form_provider = "google"
    task.google_form_id = form_id
    task.google_form_url = str(
        (form_payload.get("responderUri") if isinstance(form_payload, dict) else "") or form_reference
    ).strip()[:500] or None
    task.google_form_match_mode = builder_schema.get("matching", {}).get("mode") or "unit"
    task.google_form_match_field = builder_schema.get("matching", {}).get("match_field") or None
    task.google_form_builder_json = _json_dump(builder_schema)
    task.google_form_runtime_json = _json_dump(
        _task_google_form_runtime_payload(task, form_payload, base_runtime=_task_google_form_runtime(task))
    )
    actual_fields, _question_map = parse_google_form_definition(form_payload or {})
    if actual_fields:
        _replace_task_form_fields(task, _merge_google_form_field_targets(actual_fields, task=task, builder_schema=builder_schema))
    db.session.add(task)
    db.session.commit()
    flash("Đã nhập cấu trúc từ Google Form vào builder.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))

def _sync_google_form_task_v2(tid):
    task = Task.query.filter_by(id=tid).first()
    if not task:
        return "Not Found", 404

    current_user = db.session.get(User, session["uid"])
    perms = _current_perms()
    can_manage_task_view = bool(
        bool(current_is_admin())
        or _can_process_task_module(perms)
        or _can_edit_task(task)
        or _can_manage_task(task, user=current_user)
    )
    is_executor = TaskAssignment.query.filter_by(task_id=task.id, user_id=session["uid"]).first() is not None
    if not (can_manage_task_view or is_executor):
        flash("Bạn không có quyền đồng bộ phản hồi Google Form cho công việc này.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))
    if not getattr(task, "google_form_id", None):
        flash("Công việc này chưa có Google Form thật để đồng bộ.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    try:
        service = build_google_forms_service(current_app.config)
        form_payload = fetch_google_form_definition(service, task.google_form_id)
        responses_payload = fetch_google_form_responses(service, task.google_form_id)
        actual_fields, parsed_responses = parse_google_form_responses(form_payload, responses_payload)
    except Exception as exc:
        flash(str(exc) or "Không thể đồng bộ phản hồi Google Form.", "danger")
        return redirect(url_for("tasks_bp.task_detail", tid=tid))

    if actual_fields:
        builder_schema = _task_google_form_builder(task)
        _replace_task_form_fields(task, _merge_google_form_field_targets(actual_fields, task=task, builder_schema=builder_schema))

    matched_total = 0
    unmatched_total = 0
    ignored_scoped_fields_total = 0
    ignored_scoped_response_ids = []
    now = datetime.now()
    for response_row in parsed_responses:
        assignment = _match_google_form_response_to_assignment(task, response_row)
        if not assignment:
            unmatched_total += 1
            continue
        filtered_response = _filter_google_form_response_for_assignment(task, assignment, response_row)
        filtered_payload = filtered_response.get("payload") or {}
        filtered_payload_by_label = filtered_response.get("payload_by_label") or {}
        ignored_keys = list(filtered_response.get("ignored_keys") or [])
        if ignored_keys:
            ignored_scoped_fields_total += len(ignored_keys)
            ignored_scoped_response_ids.append(
                {
                    "response_id": response_row.get("response_id"),
                    "user_id": getattr(assignment, "user_id", None),
                    "ignored_keys": ignored_keys,
                }
            )

        submission = (
            TaskSubmission.query.filter_by(
                task_id=task.id,
                assignment_id=assignment.id,
                external_source="google_form",
                external_submission_id=response_row.get("response_id"),
            )
            .order_by(TaskSubmission.id.desc())
            .first()
        )
        if not submission:
            submission = TaskSubmission(
                task_id=task.id,
                assignment_id=assignment.id,
                submitted_by=assignment.user_id,
                external_source="google_form",
                external_submission_id=response_row.get("response_id"),
            )
            db.session.add(submission)
            db.session.flush()

        submission.submission_type = "FORM"
        submission.status = "submitted"
        submission.payload_json = _json_dump(filtered_payload)
        submission.submitted_at = response_row.get("submitted_at") or now
        submission.synced_at = now

        assignment.status = "submitted"
        assignment.submitted_at = submission.submitted_at
        assignment.last_submission_id = submission.id
        assignment.report_payload_json = _json_dump(
            {
                "mode": "google_form_sync",
                "payload": filtered_payload,
                "payload_by_label": filtered_payload_by_label,
                "external_submission_id": response_row.get("response_id"),
                "ignored_scoped_keys": ignored_keys,
                "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
            }
        )
        assignment.updated_at = now
        _sync_assignment_group_submission(
            task,
            assignment,
            submission,
            report_payload_json=assignment.report_payload_json or "",
            result_file=assignment.result_file or "",
            submitted_at=assignment.submitted_at,
            updated_at=assignment.updated_at,
            status="submitted",
        )
        matched_total += 1

    sync_state = _task_google_form_sync_state(task)
    info = form_payload.get("info") if isinstance(form_payload.get("info"), dict) else {}
    sync_state.update(
        {
            "form_id": str(form_payload.get("formId") or task.google_form_id or "").strip(),
            "form_title": str(info.get("title") or sync_state.get("form_title") or task.title or "").strip(),
            "matched_total": matched_total,
            "unmatched_total": unmatched_total,
            "ignored_scoped_fields_total": ignored_scoped_fields_total,
            "ignored_scoped_response_ids": ignored_scoped_response_ids[:10],
            "last_sync_at": now.isoformat(),
        }
    )
    task.google_form_url = str(
        form_payload.get("responderUri") or task.google_form_url or f"https://docs.google.com/forms/d/{task.google_form_id}/viewform"
    ).strip()[:500] or None
    task.google_form_runtime_json = _json_dump(
        _task_google_form_runtime_payload(task, form_payload, base_runtime=_task_google_form_runtime(task))
    )
    task.google_form_sync_state_json = _json_dump(sync_state)
    db.session.add(task)
    db.session.commit()
    flash("Đã đồng bộ phản hồi Google Form vào công việc.", "success")
    return redirect(url_for("tasks_bp.task_detail", tid=tid))
