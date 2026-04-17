@echo off
chcp 65001 >nul
title PhanMemPC06 Server

cls
echo.
echo  _   _  _____  _____  _____  _____  _____ 
echo ^| \ ^| ^|/ ____^|^|_   _^|^|_   _^|^|_   _^|/ ____^|
echo ^|  \^| ^| (___    ^| ^|    ^| ^|    ^| ^|  ^| ^|     
echo ^|     \ \___ \   ^| ^|    ^| ^|    ^| ^|  ^| ^|     
echo ^| |\  |____) ^| _^|_|_  _^|_|_  _^|_|_ ^| ^|____^|
echo ^|_^| \_^|_____/ ^|____^||____^||_____^| \_____^|
echo.
echo    PHIEN BAN OFFLINE - Version 3.5.0
echo.

REM Kiểm tra xem có đang chạy từ thư mục package không
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Tạo thư mục cần thiết nếu chưa có
if not exist "uploads" mkdir uploads
if not exist "backups" mkdir backups
if not exist "logs" mkdir logs
if not exist "task_files" mkdir task_files
if not exist "library_files" mkdir library_files
if not exist "tmp" mkdir tmp

echo [INFO] Khoi tao du lieu...
echo.

REM Kiểm tra database
if not exist "pc06_system.db" (
    echo [INFO] Phat hien lan chay dau tien!
    echo [INFO] He thong se tu dong tao database.
    echo.
)

echo [INFO] Khoi dong Server...
echo.
echo    Dia chi truy cap:
echo    - Local:   http://localhost:5000
echo    - Network: http://%COMPUTERNAME%:5000
echo.
echo    Nhan Ctrl+C de dung server
echo.
echo ============================================================
echo.

REM Chạy server
start "" "http://localhost:5000"
PhanMemPC06_Server.exe

REM Nếu chương trình kết thúc (lỗi), đợi người dùng
echo.
echo Server da dung!
pause
