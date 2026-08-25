# -*- coding: utf-8 -*-
"""Reset mật khẩu tài khoản admin — CHỈ dùng khi mất quyền truy cập.

Đã dời vào scripts/admin/ kèm chốt an toàn: phải xác nhận bằng biến môi
trường PC06_CONFIRM=YES (B8, docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md).
Cách chạy:
    PC06_CONFIRM=YES python3 scripts/admin/reset_admin.py
"""
import _admin_script_guard

_admin_script_guard.bootstrap_project_root()

from models import db, User  # noqa: E402
from app import app  # noqa: E402


def reset_admin():
    with app.app_context():
        u = User.query.filter_by(username='admin').first()
        if u:
            print(f"Resetting password for admin (ID: {u.id})...")
            # Directly set password via models' set_password
            u.set_password('123')
            db.session.commit()
            print("[OK] Admin password reset to: 123")
        else:
            print("[ERROR] Admin user not found!")

if __name__ == '__main__':
    _admin_script_guard.require_confirmation('reset_admin')
    reset_admin()
