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
        
        # Xử lý danh sách tệp đính kèm (có thể là chuỗi phân cách bởi '|')
        media_html = ""
        if m.file_path:
            paths = m.file_path.split('|')
            names = m.real_filename.split('|') if m.real_filename else [f"File_{i}" for i in range(len(paths))]
            types = m.file_type.split('|') if m.file_type else ['file' for _ in range(len(paths))]
            
            media_html += "<div class='chat-attachments-grid mt-2 d-flex flex-wrap gap-2'>"
            for i, path in enumerate(paths):
                if not path: continue
                url = f"/uploads/{path}"
                ft = types[i] if i < len(types) else 'file'
                fname = names[i] if i < len(names) else 'Unknown'
                
                if ft == 'image':
                    media_html += f"<div class='attachment-item'><img src='{url}' class='chat-media chat-media-img img-fluid shadow-sm d-block pointer' style='max-height: 180px; border-radius: 12px;' onclick='window.open(\"{url}\")'></div>"
                elif ft == 'video':
                    media_html += f"<div class='attachment-item'><video src='{url}' controls class='chat-media shadow-sm' style='max-height: 180px; max-width: 250px; border-radius: 12px;'></video></div>"
                else:
                    icon = "fa-file-pdf text-danger" if ft == 'pdf' else ("fa-file-word text-primary" if 'doc' in ft else "fa-file-lines text-secondary")
                    media_html += f"<div class='attachment-item p-2 bg-white border shadow-sm rounded-3 d-flex align-items-center gap-2' style='min-width: 150px;'><i class='fa-solid {icon} fs-5'></i><a href='{url}' target='_blank' class='text-decoration-none fw-bold text-dark text-truncate tiny' style='max-width: 120px;'>{fname}</a></div>"
            media_html += "</div>"

        # Khối tin nhắn Text HTML
        txt = ""
        inner_content = f"{m.message if m.message else ''}{media_html}"
        if m.message or media_html:
            bg_style = "" # Use CSS classes
            txt = f"<div class='msg-content shadow-sm'>{inner_content}</div>"
        
        name_display = ""
        if not is_me:
            name_display = f"<small class='text-muted mb-1 px-1' style='font-size:11px;'><i class='fa-solid fa-user-circle'></i> {m.sender_name}</small>"
            
        html += f"<div class='msg-line {c_class} animate__animated animate__fadeInUp' data-msg-id='{m.id}'>{name_display}{txt}</div>"

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
