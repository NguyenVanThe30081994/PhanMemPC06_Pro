# -*- coding: utf-8 -*-
"""
Configuration constants for PC06 application
"""
import os

# Security
SECRET_KEY = (os.environ.get('SECRET_KEY') or '').strip()
SESSION_LIFETIME = int(os.environ.get('SESSION_LIFETIME', 28800))  # 8 hours

# File Upload
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
TASK_FOLDER = os.environ.get('TASK_FOLDER', 'task_files')
LIB_FOLDER = os.environ.get('LIB_FOLDER', 'library_files')
BACKUP_FOLDER = os.environ.get('BACKUP_FOLDER', 'backups')
MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))  # 16MB

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png', 'webp', 'zip', 'ppt', 'pptx'}
ALLOWED_MIME_TYPES = {
    'text/plain',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel',
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'application/zip',
    'image/png',
    'image/jpeg',
    'image/webp',
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
HSTS_MAX_AGE_SECONDS = int(os.environ.get('HSTS_MAX_AGE_SECONDS', 31536000))
HSTS_INCLUDE_SUBDOMAINS = os.environ.get('HSTS_INCLUDE_SUBDOMAINS', 'true').lower() == 'true'
HSTS_PRELOAD = os.environ.get('HSTS_PRELOAD', 'false').lower() == 'true'
REFERRER_POLICY = os.environ.get('REFERRER_POLICY', 'strict-origin-when-cross-origin')

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
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get('RATE_LIMIT_WINDOW_SECONDS', 60))
RATE_LIMIT_MAX_REQUESTS = int(os.environ.get('RATE_LIMIT_MAX_REQUESTS', 240))
RATE_LIMIT_MAX_API_REQUESTS = int(os.environ.get('RATE_LIMIT_MAX_API_REQUESTS', 120))
TRUSTED_PROXY_CIDRS = os.environ.get(
    'TRUSTED_PROXY_CIDRS',
    '127.0.0.1/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16',
)
ADMIN_DB_RESET_ENABLED = os.environ.get('ADMIN_DB_RESET_ENABLED', 'false').lower() == 'true'
ADMIN_DB_BACKUP_ENABLED = os.environ.get('ADMIN_DB_BACKUP_ENABLED', 'false').lower() == 'true'
WEB_SYSTEM_UPDATE_ENABLED = os.environ.get('WEB_SYSTEM_UPDATE_ENABLED', 'false').lower() == 'true'
WEB_GIT_PULL_ENABLED = os.environ.get('WEB_GIT_PULL_ENABLED', 'false').lower() == 'true'

# Logging
LOG_DIR = 'logs'
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5

# Application
APP_VERSION = '3.5.0'
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'

# Google Forms integration
GOOGLE_FORMS_ENABLED = os.environ.get('GOOGLE_FORMS_ENABLED', 'False').lower() == 'true'
GOOGLE_FORMS_CREDENTIALS_FILE = os.environ.get('GOOGLE_FORMS_CREDENTIALS_FILE', '')
GOOGLE_FORMS_CREDENTIALS_JSON = os.environ.get('GOOGLE_FORMS_CREDENTIALS_JSON', '')
GOOGLE_FORMS_IMPERSONATED_USER = os.environ.get('GOOGLE_FORMS_IMPERSONATED_USER', '')
