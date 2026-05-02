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
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///pc06_system.db')

# Session Security
SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# Password Policy
MIN_PASSWORD_LENGTH = 8
REQUIRE_UPPERCASE = True
REQUIRE_LOWERCASE = True
REQUIRE_DIGIT = True
REQUIRE_SPECIAL = False

# Logging
LOG_DIR = 'logs'
LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5

# Application
APP_VERSION = '3.5.0'
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
