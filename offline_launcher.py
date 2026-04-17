# -*- coding: utf-8 -*-
"""
Offline Launcher for PhanMemPC06_Pro
Entry point cho PyInstaller - khởi động Flask server
"""

import os
import sys
import shutil
import subprocess
import webbrowser
import time
from datetime import datetime

# Xác định thư mục của executable (khi đóng gói) hoặc script (khi chạy dev)
if getattr(sys, 'frozen', False):
    # Đang chạy từ executable
    APP_DIR = sys._MEIPASS
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Đang chạy từ source
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = BASE_DIR

# Đảm bảo các thư mục cần thiết tồn tại
def ensure_dirs():
    dirs = ['uploads', 'backups', 'logs', 'task_files', 'library_files', 'tmp']
    for d in dirs:
        path = os.path.join(BASE_DIR, d)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            print(f"[INIT] Tạo thư mục: {d}")

# Kiểm tra và tạo database nếu chưa có
def init_database():
    db_path = os.path.join(BASE_DIR, 'pc06_system.db')
    if not os.path.exists(db_path):
        print("[INIT] Database chưa tồn tại. Khởi tạo...")
        # Import và chạy init_db
        sys.path.insert(0, BASE_DIR)
        try:
            from models import db
            from utils import init_db
            
            # Tạo Flask app tạm để init DB
            from flask import Flask
            app = Flask(__name__)
            app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
            app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
            db.init_app(app)
            
            with app.app_context():
                init_db(app)
                print("[OK] Database đã được khởi tạo thành công!")
                return True
        except Exception as e:
            print(f"[ERROR] Lỗi khởi tạo database: {e}")
            return False
    return True

# Xóa màn hình console
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# Hiển thị banner
def show_banner():
    clear_screen()
    print("=" * 60)
    print("   PHẦN MỀM QUẢN LÝ PC06 - PHIÊN BẢN OFFLINE")
    print("=" * 60)
    print()
    print(f"   Phiên bản: 3.5.0 (Offline)")
    print(f"   Thời gian khởi động: {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}")
    print(f"   Thư mục dữ liệu: {BASE_DIR}")
    print()
    print("=" * 60)
    print()

# Lấy địa chỉ IP local
def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

# Khởi động Flask server
def start_server():
    print("[INFO] Đang khởi động server...")
    print()
    
    # Thêm BASE_DIR vào sys.path để import modules
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    
    # Import Flask app
    try:
        # Đọc app.py và thiết lập đường dẫn
        os.chdir(BASE_DIR)
        
        # Import ứng dụng
        import app as flask_app
        
        print("[OK] Ứng dụng đã được load thành công!")
        print()
        print("-" * 60)
        print("   TRUY CẬP ỨNG DỤNG:")
        print(f"   - Local:   http://localhost:5000")
        print(f"   - Network: http://{get_local_ip()}:5000")
        print("-" * 60)
        print()
        print("Nhấn Ctrl+C để dừng server")
        print()
        
        # Chạy server với waitress (production-ready)
        from waitress import serve
        serve(flask_app.app, host='0.0.0.0', port=5000)
        
    except Exception as e:
        print(f"[ERROR] Lỗi khởi động server: {e}")
        import traceback
        traceback.print_exc()
        input("\nNhấn Enter để thoát...")
        sys.exit(1)

# Main
if __name__ == '__main__':
    show_banner()
    ensure_dirs()
    
    if not init_database():
        print("[WARNING] Tiếp tục khởi động server (database sẽ được tạo khi truy cập)...")
    
    start_server()
