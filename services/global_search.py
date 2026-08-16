# -*- coding: utf-8 -*-
"""
Tìm kiếm toàn cục: task, user, comment, submission.

Pha 3 Feature 2. Query-driven, không có scheduler.
"""

from flask import request, session, url_for
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from models import Task, TaskAssignment, TaskComment, TaskSubmission, User, db
from permissions import current_is_admin
from services.task_guards import _can_manage_task, _can_watch_task
from services.task_permissions import _can_process_task_module, _can_view_all_tasks, _current_perms
from task_page_builders import task_visible_for_user
from utils import render_auto_template as render_template


def _search_tasks(q, uid, flags):
    """Tìm task theo title hoặc content, limit 20."""
    term = f"%{q}%"
    tasks = (
        Task.query.filter(
            or_(Task.title.ilike(term), Task.content.ilike(term))
        )
        .limit(20)
        .all()
    )
    results = []
    for task in tasks:
        is_executor = bool(
            TaskAssignment.query.filter_by(task_id=task.id, user_id=uid).first()
        )
        is_manager = _can_manage_task(task, user=db.session.get(User, uid))
        is_viewer = _can_watch_task(task, user=db.session.get(User, uid))
        if not task_visible_for_user(
            task, uid,
            can_view_all_tasks=flags["can_view_all_tasks"],
            is_admin=flags["is_admin"],
            is_executor=is_executor,
            is_manager=is_manager,
            is_viewer=is_viewer,
        ):
            continue
        preview = (task.content or "")[:200]
        results.append({
            "id": task.id,
            "title": task.title,
            "type": "task",
            "url": url_for("tasks_bp.task_detail", tid=task.id),
            "preview": preview,
        })
    return results


def _search_users(q):
    """Tìm user theo fullname/username/unit_area, limit 20."""
    term = f"%{q}%"
    users = (
        User.query.filter(
            or_(
                User.fullname.ilike(term),
                User.username.ilike(term),
                User.unit_area.ilike(term),
            )
        )
        .limit(20)
        .all()
    )
    return [
        {
            "id": u.id,
            "fullname": u.fullname,
            "username": u.username,
            "unit_display": u.unit_area or "",
            "type": "user",
            "url": None,
        }
        for u in users
    ]


def _search_comments(q, uid, flags):
    """Tìm comment theo content, lọc task visibility, limit 20."""
    term = f"%{q}%"
    comments = (
        TaskComment.query.filter(TaskComment.content.ilike(term))
        .limit(20)
        .all()
    )
    task_ids = set(c.task_id for c in comments)
    tasks_map = {t.id: t for t in Task.query.filter(Task.id.in_(task_ids)).all()} if task_ids else {}
    results = []
    for comment in comments:
        task = tasks_map.get(comment.task_id)
        if not task:
            continue
        is_executor = bool(
            TaskAssignment.query.filter_by(task_id=task.id, user_id=uid).first()
        )
        is_manager = _can_manage_task(task, user=db.session.get(User, uid))
        is_viewer = _can_watch_task(task, user=db.session.get(User, uid))
        if not task_visible_for_user(
            task, uid,
            can_view_all_tasks=flags["can_view_all_tasks"],
            is_admin=flags["is_admin"],
            is_executor=is_executor,
            is_manager=is_manager,
            is_viewer=is_viewer,
        ):
            continue
        preview = (comment.content or "")[:200]
        results.append({
            "content": comment.content,
            "task_id": task.id,
            "task_title": task.title,
            "type": "comment",
            "url": url_for("tasks_bp.task_detail", tid=task.id),
            "preview": preview,
        })
    return results


def _search_submissions(q, uid, flags):
    """Tìm submission theo narrative_content, lọc task visibility, limit 20."""
    term = f"%{q}%"
    submissions = (
        TaskSubmission.query.options(joinedload(TaskSubmission.assignment))
        .filter(TaskSubmission.narrative_content.ilike(term))
        .limit(20)
        .all()
    )
    task_ids = set(s.task_id for s in submissions)
    tasks_map = {t.id: t for t in Task.query.filter(Task.id.in_(task_ids)).all()} if task_ids else {}
    results = []
    for submission in submissions:
        task = tasks_map.get(submission.task_id)
        if not task:
            continue
        is_executor = bool(
            TaskAssignment.query.filter_by(task_id=task.id, user_id=uid).first()
        )
        is_manager = _can_manage_task(task, user=db.session.get(User, uid))
        is_viewer = _can_watch_task(task, user=db.session.get(User, uid))
        if not task_visible_for_user(
            task, uid,
            can_view_all_tasks=flags["can_view_all_tasks"],
            is_admin=flags["is_admin"],
            is_executor=is_executor,
            is_manager=is_manager,
            is_viewer=is_viewer,
        ):
            continue
        preview = (submission.narrative_content or "")[:200]
        results.append({
            "content": submission.narrative_content,
            "task_id": task.id,
            "task_title": task.title,
            "type": "submission",
            "url": url_for("tasks_bp.task_detail", tid=task.id),
            "preview": preview,
        })
    return results


def _global_search_page():
    """Handler: trang tìm kiếm toàn cục."""
    q = request.args.get("q", "").strip()
    if not q:
        return render_template("global_search.html", q="", results={}, total=0)

    uid = session["uid"]
    perms = _current_perms()
    flags = {
        "can_view_all_tasks": _can_view_all_tasks(perms),
        "is_admin": current_is_admin(),
        "can_process_task_module": _can_process_task_module(perms),
    }

    results = {
        "tasks": _search_tasks(q, uid, flags),
        "users": _search_users(q),
        "comments": _search_comments(q, uid, flags),
        "submissions": _search_submissions(q, uid, flags),
    }
    total = sum(len(items) for items in results.values())

    return render_template(
        "global_search.html",
        q=q,
        results=results,
        total=total,
    )