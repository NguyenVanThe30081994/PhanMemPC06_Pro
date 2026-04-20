"""
Zalo OA Integration Service
- OAuth2 Token Management (auto-refresh)
- ZNS Message Sending
- Phone Validation (E.164 format)
- Error Handling with Retry
"""
import requests
import time
import random
import hashlib
import hmac
from datetime import datetime, timedelta
from phonenumbers import parse as phone_parse, is_valid_number, PhoneNumberFormat, NumberParseException

# API Endpoints
TOKEN_URL = "https://oauth.zaloapp.com/v4/oa/access_token"
API_URL = "https://business.openapi.zalo.me"


class ZaloOAService:
    """Service class for Zalo OA operations"""
    
    def __init__(self, config=None):
        self.config = config
    
    # ==================== PHONE VALIDATION ====================
    
    def format_phone(self, phone):
        """
        Format phone number to E.164 format (+84...)
        Vietnamese: 098xxx -> +8498xxx
        """
        if not phone:
            return None
        
        # Remove common separators
        phone = phone.strip().replace(' ', '').replace('.', '').replace('-', '')
        
        try:
            # Try parsing as Vietnamese number
            parsed = phone_parse(phone, "VN")
            if is_valid_number(parsed):
                return format_number(parsed, PhoneNumberFormat.E164)
        except NumberParseException:
            pass
        
        return None
    
    # ==================== TOKEN MANAGEMENT ====================
    
    def refresh_token(self, db_session):
        """Refresh access token using refresh_token"""
        if not self.config:
            return None
        
        # Check if refresh is needed (token expires within 5 minutes)
        if self.config.token_expires_at and self.config.token_expires_at > datetime.now() + timedelta(minutes=5):
            return self.config.access_token
        
        # Need to refresh
        response = requests.post(
            TOKEN_URL,
            headers={"secret_key": self.config.secret_key},
            data={
                "app_id": self.config.app_id,
                "grant_type": "refresh_token",
                "refresh_token": self.config.refresh_token
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            self.config.access_token = data.get('access_token')
            self.config.refresh_token = data.get('refresh_token')
            # Token typically expires in 1 hour
            self.config.token_expires_at = datetime.now() + timedelta(hours=1)
            self.config.updated_at = datetime.now()
            db_session.commit()
            return self.config.access_token
        else:
            raise Exception(f"Token refresh failed: {response.text}")
        
        return None
    
    # ==================== SEND ZNS ====================
    
    def send_zns(self, db_session, phone, template_id, template_data, template_type='general', mode='development'):
        """
        Send ZNS message via template
        
        Args:
            db_session: SQLAlchemy session
            phone: Recipient phone number (will be formatted to E.164)
            template_id: ZNS template ID from ZCA
            template_data: Dict of template parameters
            template_type: Type for logging
            mode: 'development' (test only) or 'production'
        
        Returns:
            Dict with result
        """
        # 1. Format phone
        formatted_phone = self.format_phone(phone)
        if not formatted_phone:
            return {'error': 'Invalid phone number', 'error_code': -1}
        
        # 2. Get valid token
        try:
            token = self.refresh_token(db_session)
        except Exception as e:
            return {'error': str(e), 'error_code': -2}
        
        if not token:
            return {'error': 'No access token', 'error_code': -3}
        
        # 3. Send request
        response = requests.post(
            f"{API_URL}/message/template",
            headers={
                "access_token": token,
                "Content-Type": "application/json"
            },
            json={
                "phone": formatted_phone,
                "template_id": template_id,
                "template_data": template_data,
                "mode": mode  # 'development' = test only, no charge
            }
        )
        
        # 4. Parse result
        result = response.json()
        
        # 5. Log to database
        self._log_message(
            db_session,
            phone=formatted_phone,
            template_type=template_type,
            status='sent' if result.get('data', {}).get('message_id') else 'failed',
            error_code=result.get('error', -1),
            error_message=result.get('message', ''),
            zalo_message_id=result.get('data', {}).get('message_id')
        )
        
        return result
    
    def send_zns_with_retry(self, db_session, phone, template_id, template_data, template_type='general', max_retries=3, mode='development'):
        """Send ZNS with exponential backoff retry"""
        
        for attempt in range(max_retries):
            result = self.send_zns(db_session, phone, template_id, template_data, template_type, mode)
            
            # Success
            if result.get('data', {}).get('message_id'):
                return result
            
            # Rate limit (error -202) - retry with backoff
            if result.get('error') == -202:
                wait_time = (2 ** attempt) + random.randint(0, 1)
                time.sleep(wait_time)
                continue
            
            # Other error - don't retry
            return result
        
        return {'error': 'Max retries exceeded', 'error_code': -999}
    
    # ==================== LOGGING ====================
    
    def _log_message(self, db_session, phone, template_type, status, error_code=0, error_message='', zalo_message_id=None):
        """Log message to database"""
        from models import ZaloMessageLog
        
        log = ZaloMessageLog(
            recipient_phone=phone,
            template_type=template_type,
            status=status,
            error_code=str(error_code) if error_code else None,
            error_message=error_message,
            zalo_message_id=zalo_message_id
        )
        db_session.add(log)
        db_session.commit()
    
    # ==================== WEBHOOK VERIFICATION ====================
    
    def verify_webhook_signature(self, data, timestamp, signature):
        """Verify webhook signature from Zalo"""
        if not self.config or not self.config.oa_secret:
            return False
        
        # Build message: app_id + data + timestamp + oa_secret
        message = f"{self.config.app_id}{data}{timestamp}{self.config.oa_secret}"
        expected = hmac.new(
            self.config.oa_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)


# ==================== HELPER FUNCTIONS ====================

def get_zalo_service():
    """Get ZaloOAService instance from database config"""
    from models import db, ZaloConfig
    
    config = ZaloConfig.query.first()
    if not config or not config.is_active:
        return None
    
    return ZaloOAService(config)


def send_reminder_notification(task_id):
    """Send reminder for a specific task - called by scheduler"""
    from models import db, Task, TaskAssignment, User, ZaloConfig
    
    config = ZaloConfig.query.first()
    if not config or not config.is_active:
        return {'error': 'Zalo not configured'}
    
    service = ZaloOAService(config)
    task = db.session.get(Task, task_id)
    if not task:
        return {'error': 'Task not found'}
    
    results = []
    for assignment in task.assignments:
        if assignment.status == 'Hoàn thành':
            continue
        
        user = db.session.get(User, assignment.user_id)
        if not user or not user.phone:
            continue
        
        # Determine template based on deadline
        from datetime import date
        today = date.today()
        
        if task.deadline and task.deadline < today:
            # Overdue
            template_id = config.template_overdue
            template_data = {
                'ten_can_bo': user.fullname or user.username,
                'ten_nhiem_vu': task.title,
                'ngay_deadline': task.deadline.strftime('%d/%m/%Y'),
                'so_ngay_qua_han': (today - task.deadline).days,
                'nguoi_giao': task.author_name or 'Admin',
                'link_nhiem_vu': f"https://domain.com/tasks/{task.id}"
            }
        elif task.deadline and task.deadline <= today + timedelta(days=2):
            # Deadline approaching within 2 days
            template_id = config.template_deadline_warning
            template_data = {
                'ten_can_bo': user.fullname or user.username,
                'ten_nhiem_vu': task.title,
                'ngay_giao': task.created_at.strftime('%d/%m/%Y'),
                'ngay_deadline': task.deadline.strftime('%d/%m/%Y'),
                'muc_uu_tien': task.priority or 'Bình thường',
                'link_nhiem_vu': f"https://domain.com/tasks/{task.id}"
            }
        else:
            continue  # No reminder needed
        
        result = service.send_zns(
            db.session,
            phone=user.phone,
            template_id=template_id,
            template_data=template_data,
            template_type='overdue' if task.deadline and task.deadline < today else 'deadline_warning'
        )
        results.append({'user': user.username, 'result': result})
    
    return {'task_id': task_id, 'notifications': results}
