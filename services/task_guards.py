# -*- coding: utf-8 -*-
"""
Cụm helper quyền trên công việc: nạp task cha, kiểm tra quản lý/sửa/xóa/theo dõi/xem
(uốn về task_policies với ngữ cảnh session hiện tại) và lọc bình luận theo phạm vi
đơn vị của người xem.

Tách từ routes/tasks.py (Pha 2). routes/tasks.py re-export toàn bộ tên cũ.
"""

from flask import session

from models import Task, User, db
from permissions import current_is_admin
from task_policies import (
    can_delete_task,
    can_manage_task,
    can_view_task,
    can_watch_task,
)
from services.task_permissions import _can_process_task_module
from services.task_runtime_sync import _task_user_is_executor, _visible_child_tasks_for_user
from services.task_scope import _load_manager_scope, _load_viewer_scope
from services.task_units import _user_unit_key

def _load_task_parent(task):
    parent_task = getattr(task, "parent_task", None)
    if not parent_task and getattr(task, "parent_task_id", None):
        parent_task = Task.query.filter_by(id=task.parent_task_id).first()
    return parent_task

def _can_manage_task(task, user=None):
    if user is None:
        uid = session.get("uid")
        user = db.session.get(User, uid) if uid else None
    return can_manage_task(
        task,
        session_uid=session.get("uid"),
        is_admin=bool(current_is_admin()),
        can_process_module=_can_process_task_module(),
        load_manager_scope_fn=_load_manager_scope,
        user=user,
        load_parent_task_fn=_load_task_parent,
    )

def _can_edit_task(task):
    return _can_manage_task(task)

def _can_delete_task(task, is_lead=False):
    return can_delete_task(
        task,
        session_uid=session.get("uid"),
        is_admin=bool(current_is_admin()),
        is_lead=is_lead,
        can_manage=_can_manage_task(task),
    )

def _can_watch_task(task, user=None):
    if user is None:
        uid = session.get("uid")
        user = db.session.get(User, uid) if uid else None
    return can_watch_task(
        task,
        load_viewer_scope_fn=_load_viewer_scope,
        user=user,
        load_parent_task_fn=_load_task_parent,
    )

def _can_view_task(task, is_lead=False):
    return can_view_task(
        task,
        session_uid=session.get("uid"),
        is_admin=bool(current_is_admin()),
        is_lead=is_lead,
        is_executor=_task_user_is_executor(task, session.get("uid")),
        can_manage=_can_manage_task(task),
        can_watch=_can_watch_task(task),
        has_visible_child_tasks=bool(_visible_child_tasks_for_user(task.id, session.get("uid"))) if task else False,
    )

def _filter_comments_for_viewer(task, comments, viewer, can_manage_all=False):
    if can_manage_all or not viewer:
        return comments

    viewer_unit_key = _user_unit_key(viewer)
    comment_user_ids = sorted({
        user_id
        for comment in comments
        for user_id in [getattr(comment, "user_id", None), getattr(comment, "assignee_id", None)]
        if user_id
    })
    comment_users = {}
    if comment_user_ids:
        comment_users = {
            user.id: user
            for user in User.query.filter(User.id.in_(comment_user_ids)).all()
        }

    visible_comments = []
    for comment in comments:
        comment_user_id = getattr(comment, "user_id", None)
        comment_assignee_id = getattr(comment, "assignee_id", 0) or 0
        if comment_user_id == viewer.id:
            visible_comments.append(comment)
            continue

        if comment_user_id == task.author_id:
            if not comment_assignee_id:
                visible_comments.append(comment)
                continue
            target_user = comment_users.get(comment_assignee_id)
            if target_user and viewer_unit_key and _user_unit_key(target_user) == viewer_unit_key:
                visible_comments.append(comment)
                continue

        comment_user = comment_users.get(comment_user_id)
        if comment_user and viewer_unit_key and _user_unit_key(comment_user) == viewer_unit_key:
            visible_comments.append(comment)

    return visible_comments
