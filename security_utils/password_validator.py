# -*- coding: utf-8 -*-
"""
Password validation utilities
"""
import re
from config import MIN_PASSWORD_LENGTH, REQUIRE_UPPERCASE, REQUIRE_LOWERCASE, REQUIRE_DIGIT, REQUIRE_SPECIAL

def validate_password(password):
    """
    Validate password strength
    Returns: (success: bool, message: str)
    """
    if not password:
        return False, "Mật khẩu không được để trống"
    
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự"
    
    if REQUIRE_UPPERCASE and not re.search(r'[A-Z]', password):
        return False, "Mật khẩu phải có ít nhất 1 chữ hoa"
    
    if REQUIRE_LOWERCASE and not re.search(r'[a-z]', password):
        return False, "Mật khẩu phải có ít nhất 1 chữ thường"
    
    if REQUIRE_DIGIT and not re.search(r'\d', password):
        return False, "Mật khẩu phải có ít nhất 1 chữ số"
    
    if REQUIRE_SPECIAL and not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Mật khẩu phải có ít nhất 1 ký tự đặc biệt"
    
    # Check for common weak passwords
    weak_passwords = ['12345678', 'password', 'admin123', 'qwerty123', '123456789']
    if password.lower() in weak_passwords:
        return False, "Mật khẩu quá yếu, vui lòng chọn mật khẩu khác"
    
    return True, "Mật khẩu hợp lệ"

def get_password_requirements():
    """Get password requirements as a string"""
    requirements = [f"Ít nhất {MIN_PASSWORD_LENGTH} ký tự"]
    
    if REQUIRE_UPPERCASE:
        requirements.append("có chữ hoa")
    if REQUIRE_LOWERCASE:
        requirements.append("có chữ thường")
    if REQUIRE_DIGIT:
        requirements.append("có chữ số")
    if REQUIRE_SPECIAL:
        requirements.append("có ký tự đặc biệt")
    
    return ", ".join(requirements)
