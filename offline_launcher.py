# -*- coding: utf-8 -*-
"""
Offline Launcher for PhanMemPC06_Pro
Entry point cho PyInstaller - Khoi dong Flask server voi console visible
"""

import os
import sys
import traceback
from datetime import datetime

# Fix UTF-8 encoding
if sys.platform == 'win32':
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except:
        pass

# Xac dinh thu muc
if getattr(sys, 'frozen', False):
    APP_DIR = sys._MEIPASS
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = BASE_DIR

# Tao thu muc can thiet
def ensure_dirs():
    dirs = ['uploads', 'backups', 'logs', 'task_files', 'library_files', 'tmp']
    for d in dirs:
        path = os.path.join(BASE_DIR, d)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            print(f"[INIT] Tao thu muc: {d}")

# Khoi tao database
def init_database():
    db_path = os.path.join(BASE_DIR, 'pc06_system.db')
    if not os.path.exists(db_path):
        print("[INIT] Database chua ton tai. Khoi tao...")
        sys.path.insert(0, BASE_DIR)
        try:
            from models import db
            from utils import init_db
            from flask import Flask
            app = Flask(__name__)
            app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
            app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
            db.init_app(app)
            with app.app_context():
                init_db(app)
                print("[OK] Database da duoc khoi tao!")
                return True
        except Exception as e:
            print(f"[ERROR] Loi khoi tao database: {e}")
            traceback.print_exc()
            return False
    return True

# Hien thi banner
def show_banner():
    print("=" * 60)
    print("   PHAN MEM QUAN LY PC06 - PHIEN BAN OFFLINE")
    print("=" * 60)
    print()
    print(f"   Phien ban: 3.5.2 (Offline)")
    print(f"   Thoi gian khoi dong: {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}")
    print(f"   Thu muc du lieu: {BASE_DIR}")
    print()
    print("=" * 60)
    print()

# Lay IP local
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

# Khoi dong Flask server
def start_server():
    print("[INFO] Dang khoi dong server...")
    print()
    
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    
    os.chdir(BASE_DIR)
    
    try:
        import app as flask_app
        
        print("[OK] Ung dung da duoc load!")
        print()
        print("-" * 60)
        print("   TRUY CAP UNG DUNG:")
        print(f"   - Local:   http://localhost:5000")
        print(f"   - Network: http://{get_local_ip()}:5000")
        print("-" * 60)
        print()
        print("Nhan Ctrl+C de dung server")
        print()
        
        # Chay server voi waitress - console luon hien thi
        from waitress import serve
        serve(flask_app.app, host='0.0.0.0', port=5000)
        
    except Exception as e:
        print(f"[ERROR] Loi khoi dong server: {e}")
        traceback.print_exc()
        print()
        print("=" * 60)
        print("   SERVER BI LOI - VUI LONG KIEM TRA LOI PHIA TREN")
        print("=" * 60)
        print()
        input("Nhan Enter de thoat...")

# Main
if __name__ == '__main__':
    show_banner()
    ensure_dirs()
    
    if not init_database():
        print("[WARNING] Tiep tuc khoi dong server...")
    
    start_server()
