@echo off
chcp 65001 >nul
echo ========================================
echo  BUILD OFFLINE EXE - PYTHON 3.9
echo ========================================
echo.

REM Kiem tra Python 3.9
echo [1/4] Kiem tra Python 3.9...
py -3.9 --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3.9 chua duoc cai dat!
    echo Vui long cai dat Python 3.9 va cac thu vien can thiet:
    echo   pip install pyinstaller flask flask-sqlalchemy werkzeug openpyxl pandas numpy waitress pillow qrcode markdown
    pause
    exit /b 1
)
echo [OK] Python 3.9 da san sang

REM Cai dat PyInstaller cho Python 3.9
echo.
echo [2/4] Cai dat PyInstaller neu can thiet...
py -3.9 -m pip install pyinstaller --quiet
if %errorlevel% neq 0 (
    echo [WARNING] Khong the cai dat PyInstaller
)

REM Chay PyInstaller
echo.
echo [3/4] Dang dong goi ung dung...
cd /d "%~dp0"
py -3.9 -m PyInstaller app_offline.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo [ERROR] Build that bai!
    pause
    exit /b 1
)

REM Hoan tat
echo.
echo [4/4] Hoan tat!
echo.
echo ========================================
echo  TOII TẠO
echo ========================================
echo.
echo File exe duoc luu tai: dist\PhanMemPC06_Server\
echo.
echo De chay server, double-click: dist\PhanMemPC06_Server\PhanMemPC06_Server.exe
echo Hoac chay file RUN_SERVER.bat trong thu muc do
echo.
pause
