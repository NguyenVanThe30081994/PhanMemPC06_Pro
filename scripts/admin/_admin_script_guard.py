# -*- coding: utf-8 -*-
"""Chốt an toàn chung cho các script quản trị thao tác trực tiếp dữ liệu.

Mọi script trong thư mục này phải gọi require_confirmation() trước khi chạy.
Không đặt biến môi trường PC06_CONFIRM=YES thì script thoát ngay — chống
chạy nhầm trên server production (B8, docs/nghien-cuu-bao-mat-trien-khai-cpanel-2026.md).
"""
import os
import sys


def require_confirmation(tool_name):
    if os.environ.get('PC06_CONFIRM', '').strip().upper() == 'YES':
        return
    print(f"[AN TOAN] {tool_name} thao tac truc tiep tren database dang cau hinh.")
    print("Neu chac chan, chay lai voi bien moi truong xac nhan:")
    print(f"    PC06_CONFIRM=YES python3 {sys.argv[0]}")
    sys.exit(1)


def bootstrap_project_root():
    """Thêm gốc dự án vào sys.path để 'from app import ...' chạy được khi
    script nằm ở scripts/admin/."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    if root not in sys.path:
        sys.path.insert(0, root)
