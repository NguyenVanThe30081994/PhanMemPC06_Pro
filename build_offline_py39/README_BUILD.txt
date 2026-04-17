# Build Offline Python 3.9

## Overview
Thu muc chua cac file cau hinh de build offline executable cho PhanMemPC06_Pro su dung Python 3.9.

## File Contents

| File | Description |
|------|-------------|
| `BUILD_PY39.bat` | Script build cho Python 3.9 |
| `app_offline_py39.spec` | PyInstaller spec file |
| `offline_launcher.py` | Entry point cho build |
| `README_BUILD.txt` | File huong dan nay |

## Requirements

### Python 3.9
Python 3.9 can duoc cai dat truoc.Tai tai: https://www.python.org/downloads/

### Dependencies
```bash
pip install pyinstaller flask flask-sqlalchemy werkzeug openpyxl pandas numpy waitress pillow qrcode markdown
```

## Build Steps

### Cach 1: Su dung script
```bash
cd build_offline_py39
py -3.9 -m PyInstaller app_offline_py39.spec --clean --noconfirm
```

### Cach 2: Su dung batch file
```bash
BUILD_PY39.bat
```

## Output
Sau khi build thanh cong, file exe duoc luu tai:
```
dist/PhanMemPC06_Server/PhanMemPC06_Server.exe
```

## Chạy server
```bash
dist/PhanMemPC06_Server/RUN_SERVER.bat
```
Hoac double-click file exe.

## Notes
- Cac thay doi trong thu muc nay KHONG anh huong den ma nguon deploy chinh
- Build offline su dung entry point rieng
- UTF-8 encoding da duoc xu ly san cho console
