# -*- coding: utf-8 -*-
"""
Security helper functions
"""
import re
from functools import wraps
from flask import session, redirect, url_for, flash, request, current_app

def require_login(f):
    """Decorator to require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('uid'):
            flash('Vui lòng đăng nhập để tiếp tục', 'warning')
            return redirect(url_for('auth_bp.login'))
        return f(*args, **kwargs)
    return decorated_function

def require_admin(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('uid'):
            flash('Vui lòng đăng nhập để tiếp tục', 'warning')
            return redirect(url_for('auth_bp.login'))
        if not session.get('is_admin'):
            flash('Bạn không có quyền truy cập trang này', 'danger')
            return redirect(url_for('tasks_bp.tasks'))
        return f(*args, **kwargs)
    return decorated_function

def require_permission(perm_name):
    """Decorator to require specific permission"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('uid'):
                flash('Vui lòng đăng nhập để tiếp tục', 'warning')
                return redirect(url_for('auth_bp.login'))
            
            # Admin has all permissions
            if session.get('is_admin'):
                return f(*args, **kwargs)
            
            # Check permission
            from models import AppRole, db
            role_id = session.get('role_id')
            if role_id:
                role = db.session.get(AppRole, role_id)
                if role and role.perms:
                    import json
                    try:
                        perms = json.loads(role.perms)
                        if perms.get(perm_name):
                            return f(*args, **kwargs)
                    except Exception:
                        pass
            
            flash('Bạn không có quyền thực hiện thao tác này', 'danger')
            return redirect(url_for('tasks_bp.tasks'))
        return decorated_function
    return decorator

def validate_table_name(table_name):
    """Validate table name to prevent SQL injection"""
    # Only allow alphanumeric and underscore
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table_name):
        return False
    
    # Whitelist of allowed tables
    allowed_tables = {
        'user', 'app_role', 'task', 'task_assignment', 'task_comment',
        'category', 'category_group', 'category_item', 'category_group_module',
        'module_registry', 'module_field_binding', 'contact', 'contact_group',
        'contact_role', 'document_lib', 'library_field', 'master_data',
        'news_category', 'news_doc', 'notification', 'professional_unit',
        'ranking_entry', 'ranking_indicator', 'ranking_unit',
        'report_audit_v2', 'report_config', 'report_data',
        'report_submission_v2', 'report_template_v2', 'report_value_v2',
        'report_version_v2', 'short_link', 'system_log',
        'zalo_config', 'zalo_message_log'
    }
    
    return table_name in allowed_tables

def validate_column_name(column_name):
    """Validate column name to prevent SQL injection"""
    # Only allow alphanumeric and underscore
    return bool(re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', column_name))

def validate_column_type(column_type):
    """Validate SQL column type"""
    allowed_types = {
        'INTEGER', 'TEXT', 'REAL', 'BLOB', 'BOOLEAN',
        'VARCHAR(50)', 'VARCHAR(100)', 'VARCHAR(255)', 'VARCHAR(500)',
        'DATE', 'DATETIME', 'FLOAT'
    }
    return column_type.upper() in allowed_types

def log_security_event(event_type, details=''):
    """Log security-related events"""
    try:
        user_id = session.get('uid', 0)
        username = session.get('username', 'anonymous')
        ip_address = request.remote_addr
        
        current_app.logger.warning(
            f"SECURITY: {event_type} | User: {username} (ID: {user_id}) | "
            f"IP: {ip_address} | Details: {details}"
        )
    except Exception as e:
        current_app.logger.error(f"Failed to log security event: {e}")

def sanitize_html(text):
    """Basic HTML sanitization"""
    if not text:
        return text
    
    # Remove script tags
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove event handlers
    text = re.sub(r'on\w+\s*=\s*["\'].*?["\']', '', text, flags=re.IGNORECASE)
    
    return text
