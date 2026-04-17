# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for PhanMemPC06_Pro - Offline Standalone Version
Chạy: pyinstaller app_offline.spec --clean --noconfirm
"""

import os
import sys
import shutil
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Đường dẫn gốc của project
ROOT_DIR = os.path.abspath(os.path.dirname(SPEC))

# Các thư mục cần đóng gói
DATA_DIRS = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('routes', 'routes'),
    ('v2_logic_configs', 'v2_logic_configs'),
]

# Các file cần đóng gói
DATA_FILES = [
    ('models.py', '.'),
    ('utils.py', '.'),
    ('pc06_excel_engine.py', '.'),
    ('pc06_excel_scanner.py', '.'),
    ('excel_renderer.py', '.'),
    ('auto_backup.py', '.'),
    ('reset_admin.py', '.'),
    ('reset_categories.py', '.'),
    ('seed_categories.py', '.'),
    ('passenger_wsgi.py', '.'),
    ('version.txt', '.'),
]

# Tạo danh sách datas cho PyInstaller
datas = []

# Thêm thư mục
for src, dst in DATA_DIRS:
    src_path = os.path.join(ROOT_DIR, src)
    if os.path.exists(src_path):
        datas.append((src_path, dst))

# Thêm file
for src, dst in DATA_FILES:
    src_path = os.path.join(ROOT_DIR, src)
    if os.path.exists(src_path):
        datas.append((src_path, dst))

# Hidden imports - các module cần thiết
hiddenimports = [
    # Flask core
    'flask',
    'flask.app',
    'flask.blueprints',
    'flask.globals',
    'flask.sessions',
    'flask.templating',
    'flask.wrappers',
    
    # Flask extensions
    'flask_sqlalchemy',
    'flask_sqlalchemy.models',
    'flask_sqlalchemy.session',
    
    # SQLAlchemy
    'sqlalchemy',
    'sqlalchemy.orm',
    'sqlalchemy.engine',
    'sqlalchemy.pool',
    'sqlalchemy.dialects.sqlite',
    'sqlalchemy.types',
    
    # Werkzeug
    'werkzeug',
    'werkzeug.security',
    'werkzeug.routing',
    'werkzeug.wrappers',
    'werkzeug.wsgi',
    
    # Data processing
    'openpyxl',
    'openpyxl.workbook',
    'openpyxl.worksheet',
    'openpyxl.cell',
    'openpyxl.styles',
    'openpyxl.utils',
    'pandas',
    'pandas.core',
    'pandas.core.frame',
    'numpy',
    'numpy.core',
    
    # Image processing
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    
    # Utils
    'logging',
    'logging.handlers',
    'json',
    'datetime',
    'collections',
    're',
    'os',
    'sys',
    'shutil',
    'time',
    'zipfile',
    'io',
    
    # Routes modules
    'routes',
    'routes.auth',
    'routes.admin',
    'routes.forms',
    'routes.portal',
    'routes.tasks',
    'routes.ranking',
    'routes.api',
    'routes.reports_v2',
    'routes.shortlink',
    'routes.convert',
    'routes.excel_builder',
    
    # Other modules
    'googleapiclient',
    'google_auth_httplib2',
    'google_auth_oauthlib',
    'urllib3',
]

# Thu thập tất cả submodule cần thiết
for module in ['flask', 'werkzeug', 'sqlalchemy', 'openpyxl', 'pandas', 'PIL', 'jinja2', 'markupsafe', 'itsdangerous', 'click', 'blinker', 'dateutil', 'pytz']:
    try:
        submodules = collect_submodules(module)
        hiddenimports.extend(submodules)
    except:
        pass

a = Analysis(
    ['offline_launcher.py'],  # Entry point
    pathex=[ROOT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy._core',
        'scipy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PhanMemPC06_Server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Hiển thị console để thấy logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Có thể thêm icon sau
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PhanMemPC06_Server',
)
