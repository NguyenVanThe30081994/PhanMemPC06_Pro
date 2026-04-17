# -*- coding: utf-8 -*-
"""
Offline Launcher for PhanMemPC06_Pro
Entry point for PyInstaller - start Flask server
Compatible with Python 3.9
"""

import os
import sys
import shutil
import subprocess
import webbrowser
import time
from datetime import datetime

# Fix UTF-8 encoding for console output - MUST be first
if sys.platform == 'win32':
    # Set environment before any I/O
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'
    
    # Reconfigure stdout/stderr early
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# Determine executable directory (when packaged) or script location (when running dev)
if getattr(sys, 'frozen', False):
    # Running from executable
    APP_DIR = sys._MEIPASS
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Running from source
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = BASE_DIR

# Ensure required directories exist
def ensure_dirs():
    dirs = ['uploads', 'backups', 'logs', 'task_files', 'library_files', 'tmp']
    for d in dirs:
        path = os.path.join(BASE_DIR, d)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            print(f"[INIT] Created directory: {d}")

# Check and create database if not exists
def init_database():
    db_path = os.path.join(BASE_DIR, 'pc06_system.db')
    if not os.path.exists(db_path):
        print("[INIT] Database not exists. Initializing...")
        # Import and run init_db
        sys.path.insert(0, BASE_DIR)
        try:
            from models import db
            from utils import init_db
            
            # Create temporary Flask app to init DB
            from flask import Flask
            app = Flask(__name__)
            app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
            app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
            db.init_app(app)
            
            with app.app_context():
                init_db(app)
                print("[OK] Database initialized successfully!")
                return True
        except Exception as e:
            print(f"[ERROR] Database init error: {e}")
            return False
    return True

# Clear console screen
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

# Display banner (ASCII-safe)
def show_banner():
    clear_screen()
    print("=" * 60)
    print("   PHAN MEM QUAN LY PC06 - OFFLINE VERSION")
    print("=" * 60)
    print()
    print("   Version: 3.5.0 (Offline)")
    print(f"   Start time: {datetime.now().strftime('%H:%M:%S %d/%m/%Y')}")
    print(f"   Data directory: {BASE_DIR}")
    print()
    print("=" * 60)
    print()

# Get local IP address
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

# Start Flask server
def start_server():
    print("[INFO] Starting server...")
    print()
    
    # Add BASE_DIR to sys.path for imports
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    
    # Import Flask app
    try:
        # Set working directory
        os.chdir(BASE_DIR)
        
        # Import application
        import app as flask_app
        
        print("[OK] Application loaded successfully!")
        print()
        print("-" * 60)
        print("   APPLICATION ACCESS:")
        print(f"   - Local:   http://localhost:5000")
        print(f"   - Network: http://{get_local_ip()}:5000")
        print("-" * 60)
        print()
        print("Press Ctrl+C to stop server")
        print()
        
        # Run server with waitress (production-ready)
        from waitress import serve
        serve(flask_app.app, host='0.0.0.0', port=5000)
        
    except Exception as e:
        print(f"[ERROR] Server startup error: {e}")
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")
        sys.exit(1)

# Main
if __name__ == '__main__':
    show_banner()
    ensure_dirs()
    
    if not init_database():
        print("[WARNING] Continue starting server (DB will be created on first access)...")
    
    start_server()
