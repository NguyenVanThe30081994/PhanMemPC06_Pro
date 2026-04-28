# -*- coding: utf-8 -*-
"""
File upload validation utilities
"""
from werkzeug.utils import secure_filename
from config import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES, MAX_CONTENT_LENGTH

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_file_upload(file):
    """
    Validate uploaded file for security
    Returns: (success: bool, message: str, filename: str)
    """
    if not file or not file.filename:
        return False, "No file provided", None
    
    # Check filename
    if not allowed_file(file.filename):
        return False, "File type not allowed", None
    
    # Check file size
    file.seek(0, 2)  # Seek to end
    size = file.tell()
    file.seek(0)  # Reset to beginning
    
    if size > MAX_CONTENT_LENGTH:
        max_mb = MAX_CONTENT_LENGTH // 1024 // 1024
        return False, f"File too large (max {max_mb}MB)", None
    
    if size == 0:
        return False, "File is empty", None
    
    # Try to check MIME type (optional, requires python-magic)
    try:
        import magic
        mime = magic.from_buffer(file.read(1024), mime=True)
        file.seek(0)
        
        if mime not in ALLOWED_MIME_TYPES:
            return False, f"Invalid file type: {mime}", None
    except ImportError:
        # python-magic not installed, skip MIME check
        pass
    except Exception as e:
        # Error reading file, but continue
        file.seek(0)
    
    safe_filename = secure_filename(file.filename)
    return True, "File is valid", safe_filename

def validate_file_size(file, max_size=None):
    """Check file size without reading entire file"""
    if max_size is None:
        max_size = MAX_CONTENT_LENGTH
    
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    
    return size <= max_size
