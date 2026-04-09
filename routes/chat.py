import os
import uuid
from flask import Blueprint, render_template, request, jsonify, session, send_from_directory, current_app
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_
from models import db, ChatMessage, User

chat_bp = Blueprint('chat_bp', __name__)

@chat_bp.route('/chat')
def chat():
    if not session.get('uid'): 
        return "Unauthorized", 401
    uid = session.get('uid')
    c_type = request.args.get('t', 'private')
    users = User.query.filter(User.id != uid).order_by(User.fullname).all()
    # Thống nhất tham số cho template chat
    return render_template('chat.html', title='Kênh Trực tuyến', users=users, c_type=c_type)

@chat_bp.route('/api_hist', methods=['GET'])
def api_hist():
    if not session.get('uid'): return jsonify({'ok': False, 'msg': 'Auth'})
    uid = session.get('uid')
    o_uid = str(uid)
    s = request.args.get('s')
    t = request.args.get('t', '')
    
    if s == 'all':
        msgs = ChatMessage.query.filter_by(scope='all').order_by(ChatMessage.id.asc()).all()
    else:
        # Private chat between uid và t
        msgs = ChatMessage.query.filter(
            ChatMessage.scope == 'private',
            or_(
                and_(ChatMessage.sender_id == uid, ChatMessage.target_id == t),
                and_(ChatMessage.sender_id == int(t) if t.isdigit() else 0, ChatMessage.target_id == o_uid)
            )
        ).order_by(ChatMessage.id.asc()).all()

    html = ""
    for m in msgs:
        is_me = (m.sender_id == uid)
        c_class = "me" if is_me else "other"
        
        # Tạo Component View cho Media (Ảnh/Video/File)
        media_html = ""
        if m.file_path:
            ft = m.file_type or ''
            url = f"/uploads/{m.file_path}"
            
            if 'image' in ft:
                media_html = f"<div class='mt-2'><img src='{url}' class='chat-media chat-media-img img-fluid shadow-sm d-block' style='max-height: 250px; border-radius: 12px;' onclick='window.open(\"{url}\")'></div>"
            elif 'video' in ft:
                media_html = f"<div class='mt-2'><video src='{url}' controls class='chat-media shadow-sm w-100' style='max-height: 300px; border-radius: 12px;'></video></div>"
            else:
                icon = "fa-file-pdf text-danger" if 'pdf' in ft else ("fa-file-word text-primary" if 'document' in ft or 'word' in ft else "fa-file-lines text-secondary")
                media_html = f"<div class='mt-2 p-3 bg-light border shadow-sm rounded-3 d-flex align-items-center gap-2'><i class='fa-solid {icon} fs-4'></i><a href='{url}' target='_blank' class='text-decoration-none fw-bold text-dark text-truncate d-block' style='max-width: 200px;'>{m.real_filename}</a></div>"

        # Khối tin nhắn Text HTML
        txt = ""
        if m.message:
            txt = f"<div class='msg-content shadow-sm'>{m.message}{media_html}</div>"
        else:
            txt = f"<div class='msg-content shadow-sm pt-2 pb-2 ps-2 pe-2 bg-transparent border-0'>{media_html}</div>"

        name_display = ""
        if not is_me:
            name_display = f"<small class='text-muted mb-1 px-1' style='font-size:11px;'><i class='fa-solid fa-user-circle'></i> {m.sender_name}</small>"
            
        html += f"<div class='msg-line {c_class}'>{name_display}{txt}</div>"

    return jsonify({'ok': True, 'h': html})

@chat_bp.route('/api_send', methods=['POST'])
def api_send():
    if not session.get('uid'): return jsonify({'ok': False, 'msg': 'Auth'})
    uid = session.get('uid')
    uname = session.get('fullname')
    
    s = request.form.get('s')  # scope: all or private
    t = request.form.get('t')  # target_id
    m = request.form.get('m', '').strip()
    
    f = request.files.get('f')
    file_path = None
    real_filename = None
    file_type = None

    if f and f.filename:
        from werkzeug.utils import secure_filename
        import uuid, os
        real_filename = secure_filename(f.filename)
        ext = real_filename.split('.')[-1].lower()
        new_name = f"chat_{uuid.uuid4().hex[:8]}.{ext}"
        save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], new_name)
        f.save(save_path)
        file_path = new_name
        
        # Xác định Type (Basic mime)
        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']: file_type = 'image'
        elif ext in ['mp4', 'webm', 'ogg', 'mov']: file_type = 'video'
        elif ext in ['pdf']: file_type = 'pdf'
        else: file_type = 'file'

    if not m and not file_path:
        return jsonify({'ok': False, 'msg': 'Empty message'})

    msg = ChatMessage(
        sender_id=uid,
        sender_name=uname,
        scope=s,
        target_id=t,
        message=m,
        file_path=file_path,
        real_filename=real_filename,
        file_type=file_type
    )
    db.session.add(msg)
    try:
        db.session.commit()
        # Notify recipient if private
        if s == 'private':
            from utils import push_notif
            push_notif(t, "Tin nhắn mới", f"{uname}: {m[:30]}...", "/chat")
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'msg': str(e)})

# Để truy cập File công khai với Session
@chat_bp.route('/uploads/<filename>')
def uploaded_file(filename):
    if not session.get('uid'): return "Forbidden", 403
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
