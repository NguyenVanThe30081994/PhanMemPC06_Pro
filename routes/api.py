from flask import Blueprint, jsonify, session
from models import db, Notification, ReportData, User
import json, random
from datetime import datetime

api_bp = Blueprint('api_bp', __name__)

@api_bp.route('/api/notifications')
def get_notifications():
    if not session.get('uid'): return jsonify([])
    notifs = Notification.query.filter_by(user_id=session['uid']).order_by(Notification.created_at.desc()).limit(10).all()
    res = []
    for n in notifs:
        res.append({
            'id': n.id,
            'title': n.title,
            'msg': n.msg,
            'link': n.link,
            'is_read': n.is_read or False,
            'time': n.created_at.strftime('%H:%M %d/%m/%Y')
        })
    return jsonify(res)

@api_bp.route('/api/notifications/read', methods=['POST'])
def mark_all_read():
    if not session.get('uid'): return jsonify({'status': 'error'}), 401
    Notification.query.filter_by(user_id=session['uid']).update({'is_read': 1})
    db.session.commit()
    return jsonify({'status': 'success'})

@api_bp.route('/api/performance-stats')
def get_perf_stats():
    # Dynamic ranking logic based on report count per unit
    raw = db.session.query(ReportData, User).join(User, ReportData.user_id == User.id).all()
    units = {}
    for r, u in raw:
        ua = u.unit_area or "Khác"
        units[ua] = units.get(ua, 0) + 1
    
    # Normalize scores for the UI progress bar (max 100)
    max_val = max(units.values()) if units else 1
    ranking = sorted([
        {'name': k, 'score': (v / max_val) * 100 if max_val > 0 else 0} 
        for k, v in units.items()
    ], key=lambda x: x['score'], reverse=True)
    
    return jsonify({'full_list': ranking})
