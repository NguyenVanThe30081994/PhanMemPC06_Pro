@echo off
chcp 65001 >nul
title BUILD PhanMemPC06 PRO - Offline EXE

echo.
echo ==============================================================
echo       BUILD PHAN MEM PC06 PRO - OFFLINE VERSION
echo ==============================================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python chua duoc cai dat!
    echo Vui long cai dat Python 3.9+ truoc khi build!
    echo Tai Python tai: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "delims=" %%i in ('python -c "import sys; print(sys.version)"') do set PYTHON_VER=%%i
echo [OK] Python: %PYTHON_VER%
echo.

REM Check PyInstaller
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] PyInstaller install failed!
        pause
        exit /b 1
    )
)
echo [OK] PyInstaller ready
echo.

echo ==============================================================
echo       BUILDING EXE...
echo ==============================================================
echo.

REM Build with PyInstaller
pyinstaller app_offline.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] BUILD FAILED!
    echo Kiem tra loi phia tren.
    pause
    exit /b 1
)

echo.
echo ==============================================================
echo       BUILD COMPLETED!
echo ==============================================================
echo.

echo Output: dist\PhanMemPC06_Server\PhanMemPC06_Server.exe
echo.

for %%i in ("dist\PhanMemPC06_Server\PhanMemPC06_Server.exe") do set SIZE=%%~zi
set /a SIZE_MB = %SIZE% / 1024 / 1024

echo File size: %SIZE% bytes ^(%SIZE_MB% MB^)
echo.

echo De chay ung dung:
echo   1. Vao thu muc: dist\PhanMemPC06_Server
echo   2. Chay file: PhanMemPC06_Server.exe
echo   3. Mo trinh duyet: http://localhost:5000
echo.

pause
