# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for PhanMemPC06_Pro - Offline Standalone Version
Chay: pyinstaller app_offline.spec --clean --noconfirm
"""

import os
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

# Collect data files
numpy_data_files = collect_data_files('numpy')
pandas_data_files = collect_data_files('pandas')

block_cipher = None
ROOT_DIR = os.path.abspath(os.path.dirname(SPEC))

# Thu muc can dong goi
DATA_DIRS = [
    ('templates', 'templates'),
    ('static', 'static'),
    ('routes', 'routes'),
    ('v2_logic_configs', 'v2_logic_configs'),
]

# File can dong goi
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
    ('requirements.txt', '.'),
]

# Tao danh sach datas
datas = []
for src, dst in DATA_DIRS:
    src_path = os.path.join(ROOT_DIR, src)
    if os.path.exists(src_path):
        datas.append((src_path, dst))

for src, dst in DATA_FILES:
    src_path = os.path.join(ROOT_DIR, src)
    if os.path.exists(src_path):
        datas.append((src_path, dst))

# Hidden imports
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
    
    # Excel processing
    'openpyxl',
    'openpyxl.workbook',
    'openpyxl.worksheet',
    'openpyxl.cell',
    'openpyxl.styles',
    'openpyxl.utils',
    
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
    
    # Routes
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
    'routes.excel_builder',
    
    # Other
    'googleapiclient',
    'google_auth_httplib2',
    'google_auth_oauthlib',
    'urllib3',
    'qrcode',
    'qrcode.image',
    'qrcode.image.pil',
    'markdown',
    'markdown.core',
    'PIL.ImageQt',
    'waitress',
]

# Collect submodules
for module in ['flask', 'werkzeug', 'sqlalchemy', 'openpyxl', 'PIL', 'jinja2', 'markupsafe', 'itsdangerous', 'click', 'blinker', 'dateutil', 'pytz']:
    try:
        submodules = collect_submodules(module)
        hiddenimports.extend(submodules)
    except:
        pass

# Add numpy/pandas data files
datas = datas + list(numpy_data_files) + list(pandas_data_files)

binaries = []

a = Analysis(
    ['offline_launcher.py'],
    pathex=[ROOT_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
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
    console=True,  # Hien thi console de xem logs
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
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
