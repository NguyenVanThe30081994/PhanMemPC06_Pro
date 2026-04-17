@echo off
chcp 65001 >nul
title Build PhanMemPC06 Offline Package

echo ============================================================
echo    BUILD OFFLINE PACKAGE - PhanMemPC06_Pro v3.5.0
echo ============================================================
echo.

REM Kiểm tra Python đã cài đặt chưa
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python chua duoc cai dat!
    echo Vui long cai dat Python 3.9+ truoc!
    echo Tai Python tai: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python da duoc cai dat

REM Kiểm tra PyInstaller đã cài đặt chưa
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [INFO] Dang cai dat PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] Loi cai dat PyInstaller!
        pause
        exit /b 1
    )
    echo [OK] PyInstaller da duoc cai dat
)

echo.
echo [INFO] Bat dau dong goi...
echo.

REM Chạy PyInstaller với spec file
pyinstaller app_offline.spec --clean --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] Dong goi that bai!
    echo Vui long kiem tra loi phia tren.
    pause
    exit /b 1
)

REM Tạo thư mục package
echo.
echo [INFO] Tao cau truc thu muc...
if not exist "dist\offline_package" mkdir "dist\offline_package"

REM Copy file exe vào thư mục package
if exist "dist\PhanMemPC06_Server" (
    xcopy /E /Y "dist\PhanMemPC06_Server\*" "dist\offline_package\"
    echo [OK] Da copy files vao package
)

REM Copy script chạy server
copy /Y "RUN_SERVER.bat" "dist\offline_package\"
echo [OK] Da copy script chay

REM Tạo README
echo.
echo [INFO] Tao huong dan su dung...
(
echo PHAN MEM QUAN LY PC06 - PHIEN BAN OFFLINE
echo =========================================
echo.
echo HUONG DAN SU DUNG:
echo.
echo 1. Chay file RUN_SERVER.bat hoac PhanMemPC06_Server.exe
echo 2. Mo trinh duyet va truy cap: http://localhost:5000
echo 3. Dang nhap voi tai khoan mac dinh:
echo    - Username: admin
echo    - Password: admin123
echo.
echo LUU Y:
echo - Tat ca du lieu duoc luu tru locally tren may
echo - Khong can ket noi Internet de su dung
echo - Du lieu nam trong thu muc cua ung dung
echo.
echo Cau hinh:
echo - Port mac dinh: 5000
echo - Database: pc06_system.db
echo.
echo Phiên ban: 3.5.0
) > "dist\offline_package\README.txt"

echo [OK] Hoan tat!

echo.
echo ============================================================
echo    BUILD COMPLETED!
echo ============================================================
echo.
echo Package location: dist\offline_package
echo.
echo De chay ung dung, vao thu muc:
echo   dist\offline_package
echo va chay file: RUN_SERVER.bat
echo.
echo Hoac double-click vao: PhanMemPC06_Server.exe
echo.
pause
