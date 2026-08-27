@echo off
setlocal enabledelayedexpansion
title PC06 - Dung Server
color 0C

:: ===================================================
::  PC06 - DUNG SERVER (Windows)
::  Giai phong cong PC06_PORT (mac dinh 5000)
::  Chi kill process DANG NGHE tren cong nay, khong kill
::  toan bo python.exe de tranh anh huong tien trinh khac.
:: ===================================================

set "PC06_PORT=%PC06_PORT%"
if "%PC06_PORT%"=="" set "PC06_PORT=5000"

echo ==========================================
echo    DUNG SERVER PC06 (cong %PC06_PORT%)
echo ==========================================
echo.

set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PC06_PORT%" ^| findstr "LISTENING" 2^>nul') do (
    if "%%a" neq "" (
        echo Tim thay process PID: %%a dang dung cong %PC06_PORT%
        taskkill /F /T /PID %%a >nul 2>&1
        if !ERRORLEVEL! equ 0 (
            echo [OK] Da dung process PID: %%a
            set "FOUND=1"
        ) else (
            echo [LOI] Khong the dung PID: %%a
        )
    )
)

:: Kiem tra lai sau 1 giay
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":%PC06_PORT%" | findstr "LISTENING" >nul 2>&1
if !ERRORLEVEL! equ 0 (
    echo.
    echo [!] Cong %PC06_PORT% van con hoat dong.
    echo     Thu tim PID moi va kill truc tiep:
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PC06_PORT%" ^| findstr "LISTENING" 2^>nul') do (
        echo     taskkill /F /T /PID %%a
    )
    set "FOUND=1"
)

echo.
if "!FOUND!"=="1" (
    echo [HOAN TAT] Xu ly xong yeu cau dung server PC06.
) else (
    echo [THONG BAO] Khong tim thay server nao dang chay tren cong %PC06_PORT%.
)

echo.
pause
