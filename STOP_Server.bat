@echo off
setlocal enabledelayedexpansion
title PC06 - Dung Server
color 0C

echo ==========================================
echo    DUNG SERVER PC06
echo ==========================================
echo.

:: Tim va kill process dang chiem cong 5000
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING" 2^>nul') do (
    if "%%a" neq "" (
        echo Tim thay process PID: %%a dang dung cong 5000
        taskkill /F /T /PID %%a >nul 2>&1
        if !ERRORLEVEL! equ 0 (
            echo [OK] Da dung process PID: %%a
            set "FOUND=1"
        ) else (
            echo [LOI] Khong the dung PID: %%a
        )
    )
)

:: Kiem tra lai
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":5000" | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo.
    echo [!] Cong 5000 van con hoat dong. Thu tat bang Python...
    taskkill /F /IM python.exe >nul 2>&1
    taskkill /F /IM python3.exe >nul 2>&1
    echo [OK] Da gui lenh dung Python.
    set "FOUND=1"
)

echo.
if "%FOUND%"=="1" (
    echo [THANH CONG] Server PC06 da duoc dung.
) else (
    echo [THONG BAO] Khong tim thay server nao dang chay tren cong 5000.
)

echo.
pause