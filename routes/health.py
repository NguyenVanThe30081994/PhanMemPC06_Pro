# -*- coding: utf-8 -*-
"""
Health check endpoint for monitoring
"""
from flask import Blueprint, jsonify
from models import db
import os

health_bp = Blueprint('health_bp', __name__)

@health_bp.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        # Check database connection
        db.session.execute('SELECT 1')
        db_status = 'ok'
    except Exception:
        # Không trả chi tiết lỗi DB ra endpoint public (B3)
        db_status = 'error'
    
    # Check disk space
    try:
        stat = os.statvfs('.')
        free_space = stat.f_bavail * stat.f_frsize
        total_space = stat.f_blocks * stat.f_frsize
        disk_usage_percent = ((total_space - free_space) / total_space) * 100
        disk_status = 'ok' if disk_usage_percent < 90 else 'warning'
    except Exception:
        disk_status = 'unknown'
        disk_usage_percent = 0
    
    # Overall status
    overall_status = 'healthy' if db_status == 'ok' and disk_status in ['ok', 'unknown'] else 'unhealthy'
    status_code = 200 if overall_status == 'healthy' else 503
    
    return jsonify({
        'status': overall_status,
        'database': db_status,
        'disk': {
            'status': disk_status,
            'usage_percent': round(disk_usage_percent, 2)
        },
        'version': '3.5.0'
    }), status_code

@health_bp.route('/ping')
def ping():
    """Simple ping endpoint"""
    return jsonify({'status': 'ok', 'message': 'pong'}), 200
