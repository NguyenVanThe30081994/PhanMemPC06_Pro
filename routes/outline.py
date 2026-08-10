# -*- coding: utf-8 -*-
"""
routes/outline.py — Blueprint: Trình biên tập đề cương

Chức năng:
    GET  /outline-editor            -> Trang giao diện (yêu cầu đăng nhập)
    POST /api/parse-outline         -> Upload .docx/.txt, parse cây cấu trúc
    POST /api/save-outline          -> Lưu cây đã chỉnh sửa (JSON -> .docx)

Tích hợp vào app.py:
    from routes.outline import outline_bp
    app.register_blueprint(outline_bp)
"""
import io
import json
import os
import re
import uuid

from flask import (Blueprint, current_app, flash, jsonify, render_template,
                   request, session, url_for)
from werkzeug.utils import secure_filename

from outline_parser import parse_docx, parse_text, build_tree, collect_stats

outline_bp = Blueprint('outline_bp', __name__, url_prefix='')

OUTLINE_ALLOWED_EXTENSIONS = {'.docx', '.txt'}


def _require_login():
    """Các endpoint của blueprint yêu cầu đăng nhập."""
    return bool(session.get('uid'))


def _save_uploaded_file(file_storage):
    """Lưu file upload vào thư mục tạm, trả về đường dẫn."""
    ext = os.path.splitext(file_storage.filename or '')[1].lower()
    if ext not in OUTLINE_ALLOWED_EXTENSIONS:
        raise ValueError('Chỉ hỗ trợ file .docx hoặc .txt.')

    tmp_dir = current_app.config.get('TMP_FOLDER') or 'tmp'
    os.makedirs(tmp_dir, exist_ok=True)
    token = uuid.uuid4().hex[:12]
    fname = f"outline_{token}{ext}"
    path = os.path.join(tmp_dir, fname)
    file_storage.save(path)
    return path


@outline_bp.route('/outline-editor')
def editor_page():
    """Trang trình biên tập đề cương."""
    if not _require_login():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Unauthorized'}), 401
        return ('Bạn cần đăng nhập để dùng chức năng này.', 401)
    return render_template('outline_editor.html')


@outline_bp.route('/api/parse-outline', methods=['POST'])
def api_parse_outline():
    """Upload file đề cương -> JSON cây cấu trúc."""
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401

    if 'file' not in request.files:
        return jsonify({'error': 'Không có file nào được upload.'}), 400

    file_storage = request.files['file']
    if not file_storage or not getattr(file_storage, 'filename', ''):
        return jsonify({'error': 'File không hợp lệ.'}), 400

    try:
        path = _save_uploaded_file(file_storage)
        ext = os.path.splitext(file_storage.filename)[1].lower()

        if ext == '.docx':
            tree = parse_docx(path)
        else:
            with open(path, encoding='utf-8', errors='replace') as f:
                tree = parse_text(f.read())

        # Xoá file tạm sau khi parse xong
        try:
            os.remove(path)
        except OSError:
            pass

        tree['filename'] = file_storage.filename
        tree['stats'] = collect_stats(tree)
        return jsonify(tree)

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f'parse-outline failed: {e}', exc_info=True)
        return jsonify({'error': f'Lỗi khi phân tích file: {str(e)}'}), 500


@outline_bp.route('/api/save-outline', methods=['POST'])
def api_save_outline():
    """Lưu cây đã chỉnh sửa thành file .docx."""
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401

    payload = request.get_json(silent=True) or {}
    tree = payload.get('tree')
    filename = (payload.get('filename') or 'de-cuong.docx').strip()

    if not tree or not isinstance(tree, dict):
        return jsonify({'error': 'Dữ liệu đề cương không hợp lệ.'}), 400

    try:
        docx_bytes = _tree_to_docx(tree)
    except Exception as e:
        current_app.logger.error(f'save-outline failed: {e}', exc_info=True)
        return jsonify({'error': f'Lỗi khi tạo file Word: {str(e)}'}), 500

    # Lưu ra file trong TASK_FOLDER / uploads để tải về
    save_dir = current_app.config.get('UPLOAD_FOLDER') or 'uploads'
    os.makedirs(save_dir, exist_ok=True)
    safe_name = secure_filename(filename) or 'de-cuong.docx'
    if not safe_name.lower().endswith('.docx'):
        safe_name += '.docx'
    out_path = os.path.join(save_dir, f"outline_{uuid.uuid4().hex[:8]}_{safe_name}")

    with open(out_path, 'wb') as f:
        f.write(docx_bytes)

    return jsonify({
        'success': True,
        'message': 'Đã tạo file Word.',
        'download_url': url_for('outline_bp.api_download_outline', fname=os.path.basename(out_path)),
    })


@outline_bp.route('/api/download-outline/<path:fname>')
def api_download_outline(fname):
    """Tải file .docx đã lưu."""
    if not _require_login():
        return ('Unauthorized', 401)

    from flask import send_file
    base = os.path.basename(fname or '')
    if base != fname or not base.startswith('outline_'):
        return ('Not found', 404)
    path = os.path.join(current_app.config.get('UPLOAD_FOLDER') or 'uploads', base)
    if not os.path.isfile(path):
        return ('Not found', 404)
    return send_file(path, as_attachment=True, download_name=base)


# ── Xuất cây -> .docx ────────────────────────────────────────────────────
def _tree_to_docx(tree):
    """Chuyển cây cấu trúc thành file .docx (python-docx)."""
    try:
        from docx import Document
        from docx.shared import Pt
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise RuntimeError('Máy chủ chưa cài python-docx.')

    doc = Document()

    # Tiêu đề
    title = (tree.get('title') or '').strip()
    if title:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(title)
        r.bold = True
        r.font.size = Pt(16)

    subtitle = (tree.get('subtitle') or '').strip()
    if subtitle:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(subtitle)
        r.bold = True
        r.font.size = Pt(13)

    def walk(nodes, depth=0):
        for n in nodes:
            kind = n.get('type') or 'para'
            label = (n.get('label') or '').strip()
            text = (n.get('text') or '').strip()
            if kind.startswith('h'):
                try:
                    lvl = int(kind[1:])
                except ValueError:
                    lvl = 2
                title_text = (label + '. ' if label else '') + text
                p = doc.add_heading('', level=min(lvl, 4))
                run = p.add_run(title_text)
                run.bold = True
            elif kind == 'bullet':
                doc.add_paragraph(text, style='List Bullet')
            elif kind == 'plus':
                doc.add_paragraph('+ ' + text, style='List Bullet 2')
            else:
                doc.add_paragraph(text)
            walk(n.get('children') or [], depth + 1)

    walk(tree.get('sections') or [])

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════════════════════
#  GIAO VIỆC THEO ĐỀ CƯƠNG — giữ nguyên cấu trúc cây đa tầng
# ═══════════════════════════════════════════════════════════════════════

@outline_bp.route('/outline-giao-viec')
def giao_viec_page():
    """Trang giao việc theo đề cương (tree view + gán cán bộ/vai trò)."""
    if not _require_login():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Unauthorized'}), 401
        return ('Bạn cần đăng nhập để dùng chức năng này.', 401)
    return render_template('outline_assign.html')


@outline_bp.route('/api/outline-assignees')
def api_outline_assignees():
    """Danh sách cán bộ + vai trò để gán việc."""
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401

    from models import AppRole, User

    users = []
    for u in User.query.filter(User.is_active.is_(True)).order_by(User.fullname.asc()).all():
        users.append({
            'id': u.id,
            'name': (u.fullname or u.username or 'Cán bộ #%s' % u.id).strip(),
            'username': (u.username or '').strip(),
            'role_id': getattr(u, 'role_id', None),
        })

    roles = [{'id': r.id, 'name': (r.name or '').strip() or 'Vai trò #%s' % r.id}
             for r in AppRole.query.order_by(AppRole.name.asc()).all()]

    return jsonify({'users': users, 'roles': roles})


def _resolve_selected_assignees(assign_info):
    """
    Chuyển thông tin gán việc thành danh sách (user_id, assignee_type, role_id).
    assign_info: {'assignee_type': 'user'|'role', 'ids': [...]}
    """
    from models import User

    result = []
    atype = str((assign_info or {}).get('assignee_type') or '').strip().lower()
    ids = assign_info.get('ids') or []
    ids = [int(x) for x in ids if str(x).isdigit()]

    if atype == 'user':
        for uid in ids:
            result.append({'user_id': uid, 'assignee_type': 'user', 'role_id': None})
    elif atype == 'role':
        for role_id in ids:
            members = User.query.filter(User.role_id == role_id, User.is_active.is_(True)).all()
            for u in members:
                result.append({'user_id': u.id, 'assignee_type': 'role', 'role_id': role_id})
    return result


@outline_bp.route('/api/create-outline-task', methods=['POST'])
def api_create_outline_task():
    """Tạo công việc OUTLINE từ cây đề cương (giữ nguyên phân cấp TaskItem)."""
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401

    from datetime import datetime
    from models import Task, TaskAssignment, TaskItem, db

    payload = request.get_json(silent=True) or {}
    tree = payload.get('tree')
    title = str(payload.get('title') or '').strip()
    deadline_str = str(payload.get('deadline') or '').strip()
    assignments = payload.get('assignments') or {}   # node_id -> assign_info

    if not tree or not isinstance(tree, dict):
        return jsonify({'error': 'Cấu trúc đề cương không hợp lệ.'}), 400
    if not title:
        return jsonify({'error': 'Cần nhập tên công việc.'}), 400
    if not tree.get('sections'):
        return jsonify({'error': 'Đề cương không có đầu mục nào để giao việc.'}), 400

    task = Task(
        title=title[:255],
        content=(tree.get('subtitle') or '')[:2000] or None,
        author_id=session.get('uid'),
        author_name=session.get('fullname', 'Quản trị'),
        priority='Trung bình',
        task_type='Công việc theo đề cương',
        initial_status='Chưa tiếp nhận',
        task_mode='OUTLINE',
    )
    if deadline_str:
        try:
            task.deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    db.session.add(task)
    db.session.flush()

    total_items = 0
    total_assigned = 0

    def create_items(nodes, parent_item_id=None):
        nonlocal total_items, total_assigned
        for n in nodes or []:
            kind = n.get('type') or 'para'
            label = (n.get('label') or '').strip()
            text = (n.get('text') or '').strip()
            is_heading = kind.startswith('h')
            if not is_heading and kind not in ('bullet', 'plus', 'para'):
                continue

            total_items += 1
            title_item = (label + '. ' if label else '') + text
            item = TaskItem(
                task_id=task.id,
                parent_item_id=parent_item_id,
                item_code=str(total_items),
                title=(title_item or '(chưa có nội dung)')[:255],
                content=text[:2000] or None,
                is_required=True,
                output_type='OUTLINE',
                report_kind='narrative',
                sort_order=total_items,
            )
            db.session.add(item)
            db.session.flush()

            # Gán việc cho mục này
            assign_info = assignments.get(str(n.get('id'))) if assignments else None
            if assign_info:
                for entry in _resolve_selected_assignees(assign_info):
                    db.session.add(TaskAssignment(
                        task_id=task.id,
                        task_item_id=item.id,
                        user_id=entry['user_id'],
                        assignee_type=entry['assignee_type'],
                        role_id=entry['role_id'],
                        title_snapshot=item.title,
                        status='assigned',
                        is_required=True,
                        assigned_at=datetime.now(),
                    ))
                    total_assigned += 1

            if n.get('children'):
                create_items(n['children'], parent_item_id=item.id)

    create_items(tree.get('sections'))

    db.session.commit()

    # Xây link tới chi tiết công việc (an toàn kể cả khi blueprint tasks chưa đăng ký)
    task_url = None
    try:
        task_url = url_for('tasks_bp.task_detail', tid=task.id)
    except Exception:
        task_url = '/tasks/%d' % task.id

    return jsonify({
        'success': True,
        'task_id': task.id,
        'task_url': task_url,
        'items_created': total_items,
        'assignments_created': total_assigned,
        'message': 'Đã tạo công việc với %d đầu mục, %d lượt giao việc.' % (total_items, total_assigned),
    })
