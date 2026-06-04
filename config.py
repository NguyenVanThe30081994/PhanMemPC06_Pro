# -*- coding: utf-8 -*-
"""
Configuration constants for PC06 application
"""
import os
from datetime import timedelta

# Security
SECRET_KEY = os.environ.get('SECRET_KEY', 'PC06_FINAL_V3_5_2026')  # Change in production!
SESSION_LIFETIME = int(os.environ.get('SESSION_LIFETIME', 28800))  # 8 hours

# File Upload
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
TASK_FOLDER = os.environ.get('TASK_FOLDER', 'task_files')
LIB_FOLDER = os.environ.get('LIB_FOLDER', 'library_files')
BACKUP_FOLDER = os.environ.get('BACKUP_FOLDER', 'backups')
MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))  # 16MB

ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'pdf', 'docx', 'doc', 'png', 'jpg', 'jpeg'}
ALLOWED_MIME_TYPES = {
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel',
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
    'image/png',
    'image/jpeg'
}

# CSRF Protection
CSRF_TOKEN_LIFETIME = 3600  # 1 hour

# Database
# Prefer setting DATABASE_URL or PC06_DATA_DIR on hosting so the SQLite file
# is stored outside the deployed source tree.
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///pc06_system.db')
PC06_DATA_DIR = os.environ.get('PC06_DATA_DIR', '')

# Session Security
SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_NAME = os.environ.get('SESSION_COOKIE_NAME', 'pc06_session')
SESSION_REFRESH_EACH_REQUEST = True

# Password Policy
MIN_PASSWORD_LENGTH = 8
REQUIRE_UPPERCASE = True
REQUIRE_LOWERCASE = True
REQUIRE_DIGIT = True
REQUIRE_SPECIAL = True

# Login Security
LOGIN_FAILURE_WINDOW_SECONDS = int(os.environ.get('LOGIN_FAILURE_WINDOW_SECONDS', 900))
LOGIN_MAX_FAILURES_PER_USER = int(os.environ.get('LOGIN_MAX_FAILURES_PER_USER', 5))
LOGIN_MAX_FAILURES_PER_IP = int(os.environ.get('LOGIN_MAX_FAILURES_PER_IP', 20))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get('LOGIN_LOCKOUT_SECONDS', 900))
LOGIN_LOCKOUT_MULTIPLIER_MAX = int(os.environ.get('LOGIN_LOCKOUT_MULTIPLIER_MAX', 4))
AUTH_FAILURE_DELAY_MS = int(os.environ.get('AUTH_FAILURE_DELAY_MS', 600))

# Logging
LOG_DIR = 'logs'
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5

# Application
APP_VERSION = '3.5.0'
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
