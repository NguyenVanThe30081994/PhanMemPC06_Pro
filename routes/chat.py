import os
import uuid
from flask import Blueprint, render_template, request, jsonify, session, send_from_directory, current_app
from utils import render_auto_template
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
    return render_auto_template('chat.html', title='Kênh Trực tuyến', users=users, c_type=c_type)

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
    prev_sender = None
    
    for i, m in enumerate(msgs):
        is_me = (m.sender_id == uid)
        # Xác định logic gộp tin nhắn
        is_start = (m.sender_id != prev_sender)
        is_end = (i == len(msgs)-1 or msgs[i+1].sender_id != m.sender_id)
        
        c_class = "me" if is_me else "other"
        group_class = ""
        if is_start: group_class += " msg-group-start"
        if is_end: group_class += " msg-group-end"
        
        # Xử lý media
        media_html = ""
        if m.file_path:
            paths = m.file_path.split('|')
            names = m.real_filename.split('|') if m.real_filename else [f"File_{i}" for i in range(len(paths))]
            types = m.file_type.split('|') if m.file_type else ['file' for _ in range(len(paths))]
            
            media_html += "<div class='chat-attachments-grid d-flex flex-wrap gap-2 mb-1'>"
            for j, path in enumerate(paths):
                if not path: continue
                url = f"/uploads/{path}"
                ft = types[j] if j < len(types) else 'file'
                fname = names[j] if j < len(names) else 'Unknown'
                
                if ft == 'image':
                    media_html += f"<div class='attachment-item'><img src='{url}' class='chat-media-img shadow-sm' onclick='window.open(\"{url}\")'></div>"
                elif ft == 'video':
                    media_html += f"<div class='attachment-item'><video src='{url}' controls class='chat-media-video shadow-sm'></video></div>"
                else:
                    icon = "fa-file-pdf text-danger" if ft == 'pdf' else ("fa-file-word text-primary" if 'doc' in ft else "fa-file-lines text-secondary")
                    media_html += f"<div class='attachment-item p-2 bg-white border shadow-sm rounded-3 d-flex align-items-center gap-2' style='min-width: 140px;'><i class='fa-solid {icon}'></i><a href='{url}' target='_blank' class='text-decoration-none fw-bold text-dark text-truncate tiny' style='max-width: 100px;'>{fname}</a></div>"
            media_html += "</div>"

        # Thời gian
        time_str = m.created_at.strftime("%H:%M")
        
        # Avatar cho người khác (chỉ hiển thị ở tin nhắn cuối nhóm)
        avatar_html = ""
        if not is_me and is_end:
            initial = m.sender_name[:1].upper() if m.sender_name else "?"
            avatar_html = f"<div class='chat-avatar'>{initial}</div>"
        
        # Nội dung chính
        msg_body = ""
        if m.message or media_html:
            msg_body = f"<div class='bubble-content'>{m.message if m.message else ''}{media_html}<div class='msg-time'>{time_str}</div></div>"
        
        # Tên người gửi (chỉ hiển thị ở đầu nhóm)
        name_label = ""
        if not is_me and is_start:
            name_label = f"<div class='msg-sender-name'>{m.sender_name}</div>"
            
        html += f"<div class='msg-wrapper {c_class}{group_class}' data-msg-id='{m.id}'>{avatar_html}<div class='msg-body-wrapper'>{name_label}{msg_body}</div></div>"
        prev_sender = m.sender_id

    return jsonify({'ok': True, 'h': html, 'last_id': msgs[-1].id if msgs else 0})

    return jsonify({'ok': True, 'h': html, 'last_id': msgs[-1].id if msgs else 0})

@chat_bp.route('/api_send', methods=['POST'])
def api_send():
    if not session.get('uid'): return jsonify({'ok': False, 'msg': 'Auth'})
    uid = session.get('uid')
    uname = session.get('fullname')
    
    s = request.form.get('s')  # scope: all or private
    t = request.form.get('t')  # target_id
    m = request.form.get('m', '').strip()
    
    # Nhận danh sách tệp đính kèm
    files = request.files.getlist('f')
    file_paths = []
    real_filenames = []
    file_types = []
    
    MAX_SIZE = 10 * 1024 * 1024 # 10MB
    
    for f in files:
        if f and f.filename:
            # Kiểm tra kích thước tệp
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(0)
            if size > MAX_SIZE:
                return jsonify({'ok': False, 'msg': f'Tệp {f.filename} vượt quá 10MB!'})
                
            real_name = secure_filename(f.filename)
            ext = real_name.split('.')[-1].lower()
            new_name = f"chat_{uuid.uuid4().hex[:8]}.{ext}"
            save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], new_name)
            f.save(save_path)
            
            file_paths.append(new_name)
            real_filenames.append(real_name)
            
            # Xác định Type
            if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']: ft = 'image'
            elif ext in ['mp4', 'webm', 'ogg', 'mov']: ft = 'video'
            elif ext in ['pdf']: ft = 'pdf'
            else: ft = 'file'
            file_types.append(ft)

    if not m and not file_paths:
        return jsonify({'ok': False, 'msg': 'Nội dung tin nhắn trống'})

    msg = ChatMessage(
        sender_id=uid,
        sender_name=uname,
        scope=s,
        target_id=t,
        message=m,
        file_path="|".join(file_paths),
        real_filename="|".join(real_filenames),
        file_type="|".join(file_types)
    )
    db.session.add(msg)
    try:
        db.session.commit()
        # Notify recipient if private
        if s == 'private':
            from utils import push_notif
            push_notif(t, "Tin nhắn mới", f"{uname}: {m[:30] if m else '[Tệp đính kèm]'}", "/chat")
        return jsonify({'ok': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'msg': str(e)})

# Để truy cập File công khai với Session
@chat_bp.route('/uploads/<filename>')
def uploaded_file(filename):
    if not session.get('uid'): return "Forbidden", 403
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
