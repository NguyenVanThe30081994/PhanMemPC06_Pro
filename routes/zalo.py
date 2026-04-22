"""
Zalo OA Routes - Admin Management
- /admin/zalo: Configuration & settings
- /admin/zalo/callback: OAuth2 callback
- /admin/zalo/test: Test send message
- /admin/zalo/webhook: Webhook endpoint
- /admin/zalo/logs: Message logs
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from models import db, ZaloConfig, ZaloMessageLog
from zalo_service import ZaloOAService
import requests
import secrets

zalo_bp = Blueprint('zalo_bp', __name__, url_prefix='/admin/zalo')


# ==================== AUTH URLs ====================

AUTH_URL = "https://oauth.zaloapp.com/v4/permission"
TOKEN_URL = "https://oauth.zaloapp.com/v4/oa/access_token"


@zalo_bp.route('/', methods=['GET', 'POST'])
def index():
    """Main config page"""
    if not session.get('uid') or not session.get('is_admin'):
        return redirect(url_for('auth_bp.login'))
    
    config = ZaloConfig.query.first()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'save_config':
            # Save basic config
            if not config:
                config = ZaloConfig(
                    app_id=request.form.get('app_id'),
                    secret_key=request.form.get('secret_key'),
                    oa_id=request.form.get('oa_id'),
                    oa_secret=request.form.get('oa_secret'),
                    template_deadline_warning=request.form.get('template_deadline'),
                    template_overdue=request.form.get('template_overdue'),
                    template_report_remind=request.form.get('template_report'),
                    is_active=request.form.get('is_active') == 'on'
                )
                db.session.add(config)
            else:
                config.app_id = request.form.get('app_id')
                config.secret_key = request.form.get('secret_key')
                config.oa_id = request.form.get('oa_id')
                config.oa_secret = request.form.get('oa_secret')
                config.template_deadline_warning = request.form.get('template_deadline')
                config.template_overdue = request.form.get('template_overdue')
                config.template_report_remind = request.form.get('template_report')
                config.is_active = request.form.get('is_active') == 'on'
            
            db.session.commit()
            flash('Đã lưu cấu hình Zalo!', 'success')
            return redirect(url_for('zalo_bp.index'))
        
        if action == 'connect':
            # Start OAuth flow
            if not config:
                flash('Vui lòng lưu App ID và Secret Key trước!', 'error')
                return redirect(url_for('zalo_bp.index'))
            
            # Generate state
            state = secrets.token_urlsafe(16)
            session['zalo_oauth_state'] = state
            
            # Build auth URL
            redirect_uri = url_for('zalo_bp.callback', _external=True, _scheme='https')
            auth_url = f"{AUTH_URL}?app_id={config.app_id}&redirect_uri={redirect_uri}&state={state}"
            
            return redirect(auth_url)
        
        if action == 'test_send':
            # Test send
            if not config:
                flash('Chưa cấu hình!', 'error')
                return redirect(url_for('zalo_bp.index'))
            
            test_phone = request.form.get('test_phone')
            template_id = request.form.get('template_id')
            
            if test_phone and template_id:
                service = ZaloOAService(config)
                result = service.send_zns(
                    db.session,
                    phone=test_phone,
                    template_id=template_id,
                    template_data={
                        'ten_can_bo': 'Test User',
                        'ten_nhiem_vu': 'Test Task',
                        'ngay_giao': '20/04/2026',
                        'ngay_deadline': '25/04/2026',
                        'muc_uu_tien': 'Bình thường',
                        'link_nhiem_vu': 'https://domain.com'
                    },
                    template_type='test',
                    mode='development'
                )
                
                if result.get('data', {}).get('message_id'):
                    flash(f'Test tin nhắn đã gửi! (ID: {result["data"]["message_id"]})', 'success')
                else:
                    flash(f'Gửi thất bại: {result}', 'error')
            
            return redirect(url_for('zalo_bp.index'))
    
    # Get logs
    recent_logs = ZaloMessageLog.query.order_by(ZaloMessageLog.created_at.desc()).limit(50).all()
    
    return render_template('admin_zalo.html', config=config, logs=recent_logs)


@zalo_bp.route('/callback')
def callback():
    """OAuth2 callback"""
    if not session.get('uid'):
        return redirect(url_for('auth_bp.login'))
    
    # Verify state
    expected_state = session.pop('zalo_oauth_state', None)
    actual_state = request.args.get('state')
    
    if actual_state != expected_state:
        flash('Invalid state - có thể bị CSRF!', 'error')
        return redirect(url_for('zalo_bp.index'))
    
    code = request.args.get('code')
    if not code:
        flash('Không nhận được authorization code!', 'error')
        return redirect(url_for('zalo_bp.index'))
    
    # Exchange code for tokens
    config = ZaloConfig.query.first()
    if not config:
        flash('Chưa cấu hình!', 'error')
        return redirect(url_for('zalo_bp.index'))
    
    try:
        response = requests.post(
            TOKEN_URL,
            headers={"secret_key": config.secret_key},
            data={
                "app_id": config.app_id,
                "grant_type": "authorization_code",
                "code": code
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            config.access_token = data.get('access_token')
            config.refresh_token = data.get('refresh_token')
            config.token_expires_at = db.func.now()  # Will be set on first use
            db.session.commit()
            flash('Kết nối Zalo OA thành công!', 'success')
        else:
            flash(f'Lỗi lấy token: {response.text}', 'error')
    
    except Exception as e:
        flash(f'Lỗi: {str(e)}', 'error')
    
    return redirect(url_for('zalo_bp.index'))


@zalo_bp.route('/webhook', methods=['POST'])
def webhook():
    """Webhook endpoint for Zalo events"""
    config = ZaloConfig.query.first()
    if not config:
        return jsonify({'error': 'Not configured'}), 400
    
    # Verify signature
    signature = request.headers.get('X-ZEvent-Signature')
    timestamp = request.headers.get('X-ZEvent-Timestamp')
    
    if signature and timestamp:
        service = ZaloOAService(config)
        data = request.data.decode('utf-8')
        if not service.verify_webhook_signature(data, timestamp, signature):
            return jsonify({'error': 'Invalid signature'}), 403
    
    # Process event
    payload = request.get_json()
    event_name = payload.get('event_name')
    follower = payload.get('follower', {})
    user_id = follower.get('id')
    
    if event_name == 'follow':
        current_app.logger.info(f"New Zalo follower: {user_id}")
    elif event_name == 'unfollow':
        current_app.logger.info(f"Zalo unfollower: {user_id}")
    
    return jsonify({'success': True}), 200


@zalo_bp.route('/logs')
def logs():
    """View message logs"""
    if not session.get('uid') or not session.get('is_admin'):
        return redirect(url_for('auth_bp.login'))
    
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    logs = ZaloMessageLog.query.order_by(
        ZaloMessageLog.created_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('admin_zalo_logs.html', logs=logs)


@zalo_bp.route('/refresh_token')
def refresh_token():
    """Manually refresh token"""
    if not session.get('uid') or not session.get('is_admin'):
        return redirect(url_for('auth_bp.login'))
    
    config = ZaloConfig.query.first()
    if not config:
        flash('Chưa cấu hình!', 'error')
        return redirect(url_for('zalo_bp.index'))
    
    try:
        service = ZaloOAService(config)
        new_token = service.refresh_token(db.session)
        
        if new_token:
            flash('Token đã được làm mới!', 'success')
        else:
            flash('Token còn hạn, không cần làm mới!', 'info')
    
    except Exception as e:
        flash(f'Lỗi làm mới token: {str(e)}', 'error')
    
    return redirect(url_for('zalo_bp.index'))
