@echo off
chcp 65001 >nul
title Uninstall PhanMemPC06 Offline

cls
echo.
echo  _____ _____ _____ _____ _____ 
echo ^|  _  ^|  _  ^|   __^|   __^|   __^
echo ^|   __^|   __^|   __^|   __^|   __^
echo ^|__^|  ^|__^|  ^|____^|____^|_____^|
echo.
echo    GOI Y GO CAI DAT
echo.

set "SCRIPT_DIR=%~dp0"

echo Ban muon go cai dat PhanMemPC06_Pro offline?
echo.
echo Luu y:
echo   - Tat ca du lieu trong thu muc nay se bi xoa
echo   - Neu can, hay sao luu du lieu quan trong truoc!
echo.
echo CAC FILE SE BI XOA:
echo   - pc06_system.db (Database)
echo   - uploads\ (Files tai len)
echo   - backups\ (Backup files)
echo   - logs\ (Log files)
echo.
set /p CONFIRM="Ban co chac muon go cai dat? (y/n): "

if /i not "%CONFIRM%"=="y" (
    echo.
    echo Huy bo goi cai dat.
    pause
    exit /b 0
)

echo.
echo Dang goi cai dat...

REM Xóa các file dữ liệu
if exist "pc06_system.db" del /q "pc06_system.db"
if exist "uploads" rd /s /q "uploads"
if exist "backups" rd /s /q "backups"
if exist "logs" rd /s /q "logs"
if exist "task_files" rd /s /q "task_files"
if exist "library_files" rd /s /q "library_files"
if exist "tmp" rd /s /q "tmp"

REM Giữ lại executable và scripts
echo.
echo Da xoa du lieu thanh cong!
echo.
echo Cac file can duoi:
echo   - PhanMemPC06_Server.exe
echo   - RUN_SERVER.bat
echo   - UNINSTALL.bat
echo   - README.txt
echo.
echo De xoa hoan toan, xoa thu muc nay.
echo.
pause
