# -*- coding: utf-8 -*-
"""
routes/outline.py — Blueprint: Trình biên tập đề cương

Chức năng:
    GET  /outline-editor            -> Trang giao diện (yêu cầu đăng nhập)
    POST /api/parse-outline         -> Upload .docx/.txt/.pdf, parse cây cấu trúc
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
from report_cycles import (
    KIND_ONETIME,
    KIND_PERIODIC,
    config_to_json,
    current_cycle,
    normalize_config,
)
from services.outline_rows import _parse_outline_upload_rows

outline_bp = Blueprint('outline_bp', __name__, url_prefix='')

OUTLINE_ALLOWED_EXTENSIONS = {'.docx', '.txt'}


def _pdf_rows_to_tree(rows):
    """Dựng cây tối giản cho trình biên tập cũ từ rows bảng PDF chuẩn."""
    sections = []
    by_heading = {}
    for row in rows or []:
        heading = str(row.get('heading') or '').strip() or 'Nội dung đề cương'
        section = by_heading.get(heading)
        if section is None:
            section = {
                'id': uuid.uuid4().hex[:8],
                'type': 'h1',
                'label': '',
                'text': heading,
                'children': [],
            }
            by_heading[heading] = section
            sections.append(section)
        section['children'].append({
            'id': uuid.uuid4().hex[:8],
            'type': 'h2',
            'label': str(row.get('number') or '').strip(),
            'text': str(row.get('title') or '').strip(),
            'children': [],
        })
    return {
        'title': 'Đề cương từ PDF',
        'subtitle': '',
        'sections': sections,
    }


def _annotate_tree_with_hints(tree):
    """Tự động dò tìm cơ quan / đơn vị phụ trách cho từng node trong cây đề cương."""
    try:
        from services.outline_engine import _task_assignment_catalog, _resolve_outline_assignee_hint
        catalog = _task_assignment_catalog()

        def walk(nodes):
            for n in nodes or []:
                label = str(n.get('label') or '').strip()
                text = str(n.get('text') or '').strip()
                sub_lines = []
                for ch in n.get('children') or []:
                    if ch.get('type') in ('bullet', 'plus', 'para'):
                        sub_lines.append(str(ch.get('text') or '').strip())
                full_text = f"{label}. {text}\n" + '\n'.join(sub_lines)
                hint = _resolve_outline_assignee_hint(full_text, catalog)
                if hint:
                    n['auto_assignee'] = hint
                walk(n.get('children') or [])

        walk(tree.get('sections') or [])
    except Exception as e:
        current_app.logger.warning(f"annotate_tree_with_hints error: {e}")


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
        ext = os.path.splitext(file_storage.filename)[1].lower()

        if ext == '.pdf':
            tree = _pdf_rows_to_tree(_parse_outline_upload_rows(file_storage))
            tree['filename'] = file_storage.filename
            tree['stats'] = collect_stats(tree)
            _annotate_tree_with_hints(tree)
            return jsonify(tree)

        path = _save_uploaded_file(file_storage)

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
        _annotate_tree_with_hints(tree)
        return jsonify(tree)

    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        current_app.logger.error(f'parse-outline failed: {e}', exc_info=True)
        return jsonify({'error': 'Lỗi hệ thống khi phân tích file. Hãy thử lại hoặc kiểm tra nhật ký server.'}), 500


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
        return jsonify({'error': 'Lỗi hệ thống khi tạo file Word. Hãy thử lại hoặc kiểm tra nhật ký server.'}), 500

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
    """Trang giao việc theo đề cương văn bản (tree view + gán đơn vị/cán bộ)."""
    if not _require_login():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Unauthorized'}), 401
        return ('Bạn cần đăng nhập để dùng chức năng này.', 401)
    if not _require_task_process_perm():
        return ('Bạn không có quyền giao công việc.', 403)

    sidebar_submenu_items = [
        {
            "label": "Giao theo Đề cương văn bản",
            "href": "/outline-giao-viec",
            "count": None,
            "active": True,
        },
        {
            "label": "Danh sách công việc",
            "href": url_for("tasks_bp.tasks"),
            "count": None,
            "active": False,
        },
        {
            "label": "Báo cáo định kỳ",
            "href": url_for("tasks_bp.report_dashboard"),
            "count": None,
            "active": False,
        },
    ]
    return render_template(
        'outline_assign.html',
        submenu_parent='tasks',
        sidebar_submenu_items=sidebar_submenu_items,
    )


# ═══════════════════════════════════════════════════════════════════════
#  GIAO VIỆC THEO ĐỀ CƯƠNG — đơn giản: 1 mục = 1 việc
#
#  Sau khi quét đề cương, mỗi MỤC (heading I., 1., 1.1...) là 1 nhiệm vụ
#  gán cho đơn vị/cán bộ. Các dòng nội dung dưới mục được GỘP LẠI thành
#  nội dung của mục đó (không tách từng dòng thành việc riêng).
#  Không bắt buộc file, không tự gán theo vai trò.
# ═══════════════════════════════════════════════════════════════════════

_HEADING_TYPES = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'h7', 'h8', 'h9'}


def _is_outline_heading(node):
    return (node or {}).get('type') in _HEADING_TYPES


def _collect_muc_content_lines(node, out=None):
    """
    Gộp TOÀN BỘ các dòng nội dung (bullet/plus/para) dưới một mục,
    kể cả các dòng nằm trong mục con (heading con) — vì 1 mục = 1 việc
    báo cáo nội dung, người được gán cần biết toàn bộ nội dung của mục.
    """
    out = out if out is not None else []
    for child in (node or {}).get('children') or []:
        if _is_outline_heading(child):
            # Thêm tiêu đề mục con làm dòng phân cấp, rồi gom nội dung mục con
            sub_label = (child.get('label') or '').strip()
            sub_text = (child.get('text') or '').strip()
            if sub_label or sub_text:
                out.append('▸ ' + ((sub_label + '. ') if sub_label else '') + sub_text)
            _collect_muc_content_lines(child, out)
            continue
        text = (child.get('text') or '').strip()
        if text:
            prefix = ''
            if child.get('type') == 'bullet':
                prefix = '– '
            elif child.get('type') == 'plus':
                prefix = '+ '
            out.append(prefix + text)
        _collect_muc_content_lines(child, out)
    return out


def _require_task_process_perm():
    """Chỉ người có quyền xử lý module Công việc mới được giao việc (đồng bộ wizard chính)."""
    from services.task_permissions import _can_process_task_module
    return _can_process_task_module()


@outline_bp.route('/api/outline-assignees')
def api_outline_assignees():
    """Danh sách cán bộ, đơn vị, vai trò và preset khối để gán việc theo chính quyền 2 cấp.
    
    Quy tắc phân cấp:
    - Cấp Tỉnh (19 Sở / Ban / Ngành / Toàn quyền): Giao việc xuống Cấp Xã và giao việc ngang cấp giữa các Sở.
    - Cấp Xã (124 UBND Xã / 124 CAX): Giao việc nội bộ đơn vị mình và phối hợp đồng cấp Xã.
      TUYỆT ĐỐI KHÔNG giao việc ngược lên Cấp Tỉnh / Sở.
    """
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401
    if not _require_task_process_perm():
        return jsonify({'error': 'Bạn không có quyền giao công việc.'}), 403

    from models import User, AppRole, Unit, db
    from permissions import current_is_admin

    current_uid = session.get('uid')
    current_user = db.session.get(User, current_uid) if current_uid else None
    is_admin = bool(current_is_admin() or getattr(current_user, 'username', '') == 'admin')

    caller_level = 'system'
    caller_unit_id = getattr(current_user, 'unit_id', None)
    caller_unit_name = ''
    if not is_admin and current_user:
        u = getattr(current_user, 'unit', None)
        if u:
            caller_level = str(u.level or 'province').lower()
            caller_unit_name = u.name or ''
        else:
            uname = current_user.username or ''
            if uname.startswith(('admin_ubnd_', 'bc_ubnd_', 'admin_cax_', 'bc_cax_')):
                caller_level = 'commune'
            else:
                caller_level = 'province'

    # 1. Danh sách Đơn vị chuẩn từ bảng Unit (chính quyền 2 cấp: Tỉnh - Xã)
    units = []
    seen_keys = set()
    province_keys = []
    ubnd_commune_keys = []
    cax_commune_keys = []

    db_units_query = Unit.query.filter(
        Unit.is_active.is_(True),
        Unit.code != 'hethong'
    )
    if caller_level == 'commune':
        db_units_query = db_units_query.filter(Unit.level == 'commune')

    db_units = db_units_query.order_by(Unit.level.asc(), Unit.sort_order.asc(), Unit.name.asc()).all()

    for u in db_units:
        code = str(u.code or '').strip()
        name = str(u.name or '').strip()
        if not name or code.startswith('tq_'):
            continue
        key = code or name

        group = 'other'
        group_label = 'Đơn vị khác'
        if u.level == 'province' or code.startswith(('so_', 'vp_', 'cong_an_tinh', 'thanh_tra_', 'bql_')):
            group = 'province'
            group_label = 'Sở, Ban, Ngành'
            province_keys.append(key)
        elif code.startswith('ubnd_') or 'UBND' in name:
            group = 'commune_ubnd'
            group_label = 'UBND Xã, Phường'
            ubnd_commune_keys.append(key)
        elif code.startswith('cax_') or 'Công an' in name:
            group = 'commune_cax'
            group_label = 'Công an Xã, Phường'
            cax_commune_keys.append(key)

        if key not in seen_keys:
            seen_keys.add(key)
            units.append({
                'id': u.id,
                'key': key,
                'code': key,
                'name': name,
                'group': group,
                'group_label': group_label,
            })

    # 2. Danh sách Cán bộ (User) chuẩn theo đơn vị
    users = []
    for u in User.query.filter(
        User.is_active.is_(True),
        User.username != 'admin'
    ).order_by(User.fullname.asc()).all():
        u_unit = (getattr(u, 'unit_area_display', None) or getattr(u, 'unit_area', None) or '').strip()
        r_name = getattr(u.role, 'name', '') if getattr(u, 'role', None) else ''
        uname = (u.username or '').strip()

        u_group = 'other'
        if uname.startswith(('admin_ubnd_', 'bc_ubnd_')) or 'UBND' in u_unit:
            u_group = 'commune_ubnd'
        elif uname.startswith(('admin_cax_', 'bc_cax_')) or 'Công an' in u_unit:
            u_group = 'commune_cax'
        elif getattr(u.unit, 'level', '') == 'province' or any(uname.startswith(f"{p}_{x}") for p in ('admin', 'bc') for x in ('vpubnd', 'pvhcc', 'catinh', 'sotuphap', 'soyte', 'sogddt', 'sonoivu', 'sotaichinh', 'bhxhtinh', 'thuetinh', 'sonnmt', 'nhnnkv4', 'sodttg', 'socongthuong', 'soxaydung', 'sovhttdl', 'sokhcn', 'thanhtratinh', 'bqlkcn')):
            u_group = 'province'

        # Nếu người tạo việc là cấp Xã: LOẠI BỎ hoàn toàn cán bộ cấp Tỉnh
        if caller_level == 'commune' and u_group == 'province':
            continue

        is_own_unit = bool(caller_unit_id and u.unit_id == caller_unit_id)

        users.append({
            'id': u.id,
            'name': (u.fullname or u.username or f'Cán bộ #{u.id}').strip(),
            'username': uname,
            'unit': u_unit,
            'unit_name': u_unit,
            'unit_key': getattr(u, 'unit_key', None) or '',
            'role': r_name,
            'group': u_group,
            'is_own_unit': is_own_unit,
        })

    # 3. Danh sách Vai trò (Role)
    roles = []
    for r in AppRole.query.order_by(AppRole.name.asc()).all():
        roles.append({'id': r.id, 'name': r.name.strip()})

    # 4. Các Presets khối thông minh theo cấp hành chính
    presets = []
    if caller_level != 'commune':
        # Cấp Tỉnh / Toàn quyền: được giao toàn tỉnh, khối sở, khối xã
        presets.append({
            'id': 'toan_tinh',
            'label': 'Toàn Tỉnh (19 Sở & 124 Xã)',
            'unit_domains': ['cac_so_ban_nganh', 'uy_ban_nhan_dan_xa_phuong'] + province_keys + ubnd_commune_keys,
            'display_tag': '🌐 Toàn Tỉnh (Sở + Xã)'
        })
        presets.append({
            'id': 'khoi_so_nganh',
            'label': f'Khối 19 Sở, Ban, Ngành ({len(province_keys)} đơn vị)',
            'unit_domains': ['cac_so_ban_nganh'] + province_keys,
            'display_tag': '🏛️ Khối 19 Sở Ban Ngành'
        })
    else:
        # Cấp Xã: chỉ giao nội bộ đơn vị mình và phối hợp đồng cấp xã
        own_uids = [u['id'] for u in users if u.get('is_own_unit')]
        if own_uids:
            presets.append({
                'id': 'noi_bo_don_vi',
                'label': f'Nội bộ đơn vị ({caller_unit_name or "Đơn vị mình"})',
                'unit_domains': [],
                'user_ids': own_uids,
                'display_tag': f'🏢 Nội bộ {caller_unit_name or "đơn vị"}'
            })

    presets.extend([
        {
            'id': 'khoi_ubnd_xa',
            'label': f'Khối 124 UBND Xã, Phường ({len(ubnd_commune_keys)} đơn vị)',
            'unit_domains': ['uy_ban_nhan_dan_xa_phuong'] + ubnd_commune_keys,
            'display_tag': '🏡 124 UBND Xã/Phường'
        },
        {
            'id': 'khoi_cax',
            'label': f'Khối 124 Công an Xã, Phường ({len(cax_commune_keys)} đơn vị)',
            'unit_domains': ['cong_an_xa_phuong'] + cax_commune_keys,
            'display_tag': '👮 124 Công an Xã'
        },
    ])

    return jsonify({
        'users': users,
        'units': units,
        'roles': roles,
        'presets': presets,
        'caller_level': caller_level,
        'caller_unit_name': caller_unit_name,
        'counts': {
            'province': len(province_keys) if caller_level != 'commune' else 0,
            'ubnd_commune': len(ubnd_commune_keys),
            'cax_commune': len(cax_commune_keys),
            'total_units': len(units),
            'total_users': len(users),
        }
    })


def _resolve_selected_assignees(assign_info):
    """Chuyển thông tin gán việc thành danh sách gồm user, unit, role."""
    result = []
    info = assign_info or {}

    # 1. User ids
    ids = info.get('ids') or info.get('user_ids') or []
    for uid in ids:
        if str(uid).isdigit():
            result.append({'assignee_type': 'user', 'user_id': int(uid), 'unit_domain': None, 'role_id': None})

    # 2. Unit domains
    unit_domains = info.get('unit_domains') or []
    for ukey in unit_domains:
        if ukey is None:
            continue
        ukey_str = str(ukey).strip()
        if not ukey_str or ukey_str.lower() in {'none', 'null', 'undefined'}:
            continue
        result.append({'assignee_type': 'unit', 'user_id': None, 'unit_domain': ukey_str, 'role_id': None})

    # 3. Role ids
    role_ids = info.get('role_ids') or []
    for rid in role_ids:
        if str(rid).isdigit():
            result.append({'assignee_type': 'role', 'user_id': None, 'unit_domain': None, 'role_id': int(rid)})

    return result


@outline_bp.route('/api/create-outline-task', methods=['POST'])
def api_create_outline_task():
    """Tạo công việc OUTLINE từ cây đề cương.

    Mỗi MỤC được gán (heading) tạo 1 TaskItem; nội dung là toàn bộ các dòng
    dưới mục gộp lại. Chỉ tạo việc cho những mục đã được gán người thực hiện.
    """
    if not _require_login():
        return jsonify({'error': 'Unauthorized'}), 401
    if not _require_task_process_perm():
        return jsonify({'error': 'Bạn không có quyền giao công việc.'}), 403

    from datetime import datetime
    from models import Task, TaskAssignment, TaskItem, User, db
    from services.task_scope import _store_assignment_scope
    from services.task_runtime_sync import _ensure_task_runtime_bridge
    from routes.email_service import send_task_assignment_emails
    from utils import log_action, push_notif

    payload = request.get_json(silent=True) or {}
    tree = payload.get('tree')
    title = str(payload.get('title') or '').strip()
    deadline_str = str(payload.get('deadline') or '').strip()
    assignments = payload.get('assignments') or {}   # node_id -> {'ids': [...]}

    if not tree or not isinstance(tree, dict):
        return jsonify({'error': 'Cấu trúc đề cương không hợp lệ.'}), 400
    if not title:
        return jsonify({'error': 'Cần nhập tên công việc.'}), 400
    if not tree.get('sections'):
        return jsonify({'error': 'Đề cương không có đầu mục nào để giao việc.'}), 400

    # ── Kiểm tra phân cấp giao việc (Cấp Xã KHÔNG THỂ giao việc cho Cấp Tỉnh / Sở) ──
    from permissions import current_is_admin
    from models import Unit

    current_uid = session.get('uid')
    current_user = db.session.get(User, current_uid) if current_uid else None
    is_admin = bool(current_is_admin() or getattr(current_user, 'username', '') == 'admin')

    caller_level = 'system'
    if not is_admin and current_user:
        u = getattr(current_user, 'unit', None)
        if u:
            caller_level = str(u.level or 'province').lower()
        else:
            uname = current_user.username or ''
            caller_level = 'commune' if uname.startswith(('admin_ubnd_', 'bc_ubnd_', 'admin_cax_', 'bc_cax_')) else 'province'

    if caller_level == 'commune':
        for node_id, ainfo in (assignments or {}).items():
            sel = _resolve_selected_assignees(ainfo)
            for entry in sel:
                atype = entry.get('assignee_type')
                uid = entry.get('user_id')
                ukey = entry.get('unit_domain')

                if atype == 'user' and uid:
                    tgt_user = db.session.get(User, uid)
                    tgt_unit = getattr(tgt_user, 'unit', None) if tgt_user else None
                    if tgt_unit and tgt_unit.level == 'province':
                        return jsonify({
                            'error': f'Thẩm quyền cấp Xã không thể giao việc cho đơn vị Cấp Tỉnh / Sở ({tgt_user.fullname} - {tgt_unit.name}). Vui lòng chỉ giao việc nội bộ đơn vị hoặc phối hợp đồng cấp.'
                        }), 403
                elif atype == 'unit' and ukey:
                    if ukey in ('cac_so_ban_nganh', 'khoi_so_nganh', 'toan_tinh'):
                        return jsonify({
                            'error': 'Thẩm quyền cấp Xã không thể giao việc cho Khối Sở, Ban, Ngành.'
                        }), 403
                    from services.task_units import _resolve_unit_record
                    tgt_unit = _resolve_unit_record(ukey) or Unit.query.filter(db.or_(Unit.code == ukey, Unit.name == ukey)).first()
                    if tgt_unit and tgt_unit.level == 'province':
                        return jsonify({
                            'error': f'Thẩm quyền cấp Xã không thể giao việc cho Cấp Tỉnh / Sở ({tgt_unit.name}). Vui lòng chỉ giao việc nội bộ đơn vị hoặc phối hợp đồng cấp.'
                        }), 403

    # Phân loại kiểu báo cáo (đột xuất / định kỳ tuần, tháng, quý, năm / theo mốc)
    report_period_input = payload.get('report_period') or {}
    if not isinstance(report_period_input, dict):
        report_period_input = {}
    if deadline_str and not report_period_input.get('deadline'):
        report_period_input['deadline'] = deadline_str

    cfg = normalize_config(report_period_input)
    period_json = config_to_json(cfg)

    task_type = 'Báo cáo định kỳ' if cfg.get('kind') == KIND_PERIODIC else (
        'Báo cáo theo mốc' if cfg.get('kind') == 'milestone' else (
            'Công việc thường xuyên' if cfg.get('kind') == 'ongoing' else 'Báo cáo đột xuất'
        )
    )

    task = Task(
        title=title[:255],
        content=(tree.get('subtitle') or '')[:2000] or None,
        author_id=session.get('uid'),
        author_name=session.get('fullname', 'Quản trị'),
        priority='Trung bình',
        task_type=task_type,
        initial_status='Chưa tiếp nhận',
        task_mode='OUTLINE',
        report_period_json=period_json,
    )
    if cfg.get('kind') == KIND_PERIODIC:
        curr = current_cycle(cfg)
        if curr and curr.get('due'):
            task.deadline = curr['due']
        elif cfg.get('deadline'):
            try:
                task.deadline = datetime.strptime(cfg['deadline'], '%Y-%m-%d').date()
            except ValueError:
                pass
    elif cfg.get('deadline'):
        try:
            task.deadline = datetime.strptime(cfg['deadline'], '%Y-%m-%d').date()
        except ValueError:
            pass
    elif deadline_str:
        try:
            task.deadline = datetime.strptime(deadline_str, '%Y-%m-%d').date()
        except ValueError:
            pass
    db.session.add(task)
    db.session.flush()

    total_items = 0
    total_assigned = 0
    assignee_user_ids = set()
    preset_group_markers = {
        'cac_so_ban_nganh',
        'uy_ban_nhan_dan_xa_phuong',
        'cong_an_xa_phuong',
        'khoi_so_nganh',
        'toan_tinh',
    }

    def _resolve_item_assignment_specs(selected):
        """Quy đổi danh sách gán của 1 mục thành các bản ghi TaskAssignment hợp lệ, có khử trùng."""
        from services.task_units import _resolve_unit_record, _users_for_unit

        specs = []
        seen_user_ids = set()
        seen_empty_unit_ids = set()
        seen_role_ids = set()

        for entry in selected or []:
            atype = entry.get('assignee_type') or 'user'
            uid = entry.get('user_id')
            ukey = entry.get('unit_domain')
            rid = entry.get('role_id')

            if atype == 'user' and uid:
                uid_int = int(uid)
                if uid_int in seen_user_ids:
                    continue
                seen_user_ids.add(uid_int)
                u_obj = db.session.get(User, uid_int)
                if not u_obj or not u_obj.is_active:
                    continue
                specs.append({
                    'user_id': uid_int,
                    'unit_id': getattr(u_obj, 'unit_id', None),
                    'assignee_type': 'user',
                    'role_id': None,
                })
            elif atype == 'unit' and ukey:
                if ukey in preset_group_markers:
                    continue
                target_unit = _resolve_unit_record(ukey)
                matching_users = _users_for_unit(ukey)
                if matching_users:
                    for mu in matching_users:
                        if mu.id in seen_user_ids:
                            continue
                        seen_user_ids.add(mu.id)
                        specs.append({
                            'user_id': mu.id,
                            'unit_id': target_unit.id if target_unit else getattr(mu, 'unit_id', None),
                            'assignee_type': 'unit',
                            'role_id': None,
                        })
                elif target_unit:
                    if target_unit.id not in seen_empty_unit_ids:
                        seen_empty_unit_ids.add(target_unit.id)
                        specs.append({
                            'user_id': None,
                            'unit_id': target_unit.id,
                            'assignee_type': 'unit',
                            'role_id': None,
                        })
                else:
                    current_app.logger.warning(
                        f'create-outline-task: bỏ qua mã đơn vị không xác định {ukey!r}'
                    )
            elif atype == 'role' and rid:
                rid_int = int(rid)
                if rid_int in seen_role_ids:
                    continue
                seen_role_ids.add(rid_int)
                specs.append({
                    'user_id': None,
                    'unit_id': None,
                    'assignee_type': 'role',
                    'role_id': rid_int,
                })
        return specs

    def create_items(nodes, parent_item_id=None, ancestor_labels=None):
        """Duyệt toàn cây đề cương; tạo TaskItem cho mọi nút đã gán (cả heading lẫn bullet/plus/para)."""
        nonlocal total_items, total_assigned
        ancestor_labels = list(ancestor_labels or [])

        for n in nodes or []:
            node_type = (n.get('type') or 'para').strip()
            is_heading = _is_outline_heading(n)
            label = (n.get('label') or '').strip()
            text = (n.get('text') or '').strip()
            next_ancestors = ancestor_labels + ([label] if (is_heading and label) else [])

            assign_info = assignments.get(str(n.get('id'))) if assignments else None
            selected = _resolve_selected_assignees(assign_info) if assign_info else []
            specs = _resolve_item_assignment_specs(selected) if selected else []

            if not specs:
                # Mục chưa gán hợp lệ -> tiếp tục duyệt các nút con giữ nguyên cha gần nhất
                create_items(n.get('children') or [], parent_item_id, next_ancestors)
                continue

            if is_heading:
                title_item = (label + '. ' if label else '') + text
                content_lines = _collect_muc_content_lines(n)
            else:
                ctx_prefix = f"[{ancestor_labels[-1]}] " if ancestor_labels else ""
                title_item = ctx_prefix + text
                node_prefix = '– ' if node_type == 'bullet' else ('+ ' if node_type == 'plus' else '')
                content_lines = ([node_prefix + text] if text else []) + _collect_muc_content_lines(n)

            total_items += 1
            item = TaskItem(
                task_id=task.id,
                parent_item_id=parent_item_id,
                item_code=str(total_items),
                title=(title_item or '(chưa có nội dung)')[:255],
                content=('\n'.join(content_lines))[:5000] or None,
                is_required=True,
                output_type='OUTLINE',
                report_kind='narrative',
                attachment_required=False,
                sort_order=total_items,
            )
            db.session.add(item)
            db.session.flush()

            for spec in specs:
                db.session.add(TaskAssignment(
                    task_id=task.id,
                    task_item_id=item.id,
                    user_id=spec['user_id'],
                    unit_id=spec['unit_id'],
                    assignee_type=spec['assignee_type'],
                    role_id=spec['role_id'],
                    title_snapshot=item.title,
                    status='assigned',
                    is_required=True,
                    assigned_at=datetime.now(),
                ))
                if spec['user_id']:
                    assignee_user_ids.add(spec['user_id'])
                total_assigned += 1

            create_items(n.get('children') or [], item.id, next_ancestors)

    create_items(tree.get('sections'))

    if total_items == 0 or total_assigned == 0:
        db.session.rollback()
        return jsonify({'error': 'Chưa gán mục nào. Hãy gán ít nhất một mục cho đơn vị hoặc cán bộ thực hiện.'}), 400

    # Lưu phạm vi giao việc theo cá nhân — cùng cơ chế với wizard chính,
    # để lọc/kiểm tra phạm vi nhìn thấy việc nhất quán trên toàn hệ thống.
    try:
        _store_assignment_scope(task, 'user', user_ids=sorted(assignee_user_ids))
    except Exception as scope_error:
        current_app.logger.warning(f'create-outline-task: store scope failed: {scope_error}')

    db.session.commit()

    # Đồng bộ cầu nối runtime (TaskParticipant/submission hiện hành) ngay sau
    # khi tạo, thay vì chờ "vá lười" ở lần xem chi tiết đầu tiên.
    try:
        if _ensure_task_runtime_bridge(task):
            db.session.commit()
    except Exception as bridge_error:
        db.session.rollback()
        current_app.logger.warning(f'create-outline-task: runtime bridge failed: {bridge_error}')

    # Thông báo trong ứng dụng cho từng người được giao.
    for uid in sorted(assignee_user_ids):
        push_notif(uid, 'Công việc mới', f'Bạn vừa được giao: {task.title}', f'/tasks/{task.id}')

    log_action(
        session.get('uid'),
        session.get('fullname', ''),
        'Tạo công việc theo đề cương',
        module='Công việc',
        det=f'{task.title} ({total_items} đầu mục, {total_assigned} lượt giao)',
    )

    # Email thông báo giao việc — không làm hỏng request nếu máy thư lỗi.
    email_sent = 0
    try:
        assignee_users = User.query.filter(User.id.in_(sorted(assignee_user_ids))).all() if assignee_user_ids else []
        base_url = request.host_url.rstrip('/')
        email_result = send_task_assignment_emails(assignee_users, task, base_url=base_url)
        email_sent = len(email_result.get('sent') or [])
    except Exception as email_error:
        current_app.logger.error(f'create-outline-task: send emails failed: {email_error}')

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
        'notifications_created': len(assignee_user_ids),
        'emails_sent': email_sent,
        'message': 'Đã tạo công việc với %d đầu mục, %d lượt giao việc.' % (total_items, total_assigned),
    })
