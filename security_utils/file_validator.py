# -*- coding: utf-8 -*-
"""
File upload validation utilities
"""
import zipfile
from werkzeug.utils import secure_filename
from config import ALLOWED_EXTENSIONS, ALLOWED_MIME_TYPES, MAX_CONTENT_LENGTH

_OLE_SIGNATURE = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
_ZIP_BASED_EXTENSIONS = {'docx', 'xlsx', 'pptx', 'zip'}
_FILE_SIGNATURE_CHECKS = {
    'pdf': lambda buf: buf.startswith(b'%PDF'),
    'png': lambda buf: buf.startswith(b'\x89PNG\r\n\x1a\n'),
    'jpg': lambda buf: buf.startswith(b'\xff\xd8\xff'),
    'jpeg': lambda buf: buf.startswith(b'\xff\xd8\xff'),
    'webp': lambda buf: buf.startswith(b'RIFF') and buf[8:12] == b'WEBP',
    'doc': lambda buf: buf.startswith(_OLE_SIGNATURE),
    'xls': lambda buf: buf.startswith(_OLE_SIGNATURE),
    'txt': lambda buf: b'\x00' not in buf,
}

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _detect_signature_mismatch(file, extension):
    header = file.read(8192)
    file.seek(0)

    if extension in _ZIP_BASED_EXTENSIONS:
        if not zipfile.is_zipfile(file):
            file.seek(0)
            return f'Nội dung file không khớp với định dạng .{extension}'
        file.seek(0)
        return None

    checker = _FILE_SIGNATURE_CHECKS.get(extension)
    if checker and not checker(header):
        return f'Nội dung file không khớp với định dạng .{extension}'
    return None

def validate_file_upload(file):
    """
    Validate uploaded file for security
    Returns: (success: bool, message: str, filename: str)
    """
    if not file or not file.filename:
        return False, "No file provided", None
    
    safe_filename = secure_filename(file.filename)
    if not safe_filename:
        return False, "Invalid filename", None

    extension = safe_filename.rsplit('.', 1)[1].lower() if '.' in safe_filename else ''
    if not extension or not allowed_file(safe_filename):
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

    signature_error = _detect_signature_mismatch(file, extension)
    if signature_error:
        return False, signature_error, None
    
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

    return True, "File is valid", safe_filename

def validate_file_size(file, max_size=None):
    """Check file size without reading entire file"""
    if max_size is None:
        max_size = MAX_CONTENT_LENGTH
    
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    
    return size <= max_size
