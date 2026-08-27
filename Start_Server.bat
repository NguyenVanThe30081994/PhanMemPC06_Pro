@echo off
setlocal enabledelayedexpansion
title PC06 - Web Server (Local)
color 0A

:: ===================================================
::  PC06 - KHOI DONG SERVER LOCAL (Windows)
::  Cap nhat 2026-08 theo code moi nhat:
::    - Tu dung venv neu co (.venv / venv)
::    - Tu cai thu vien thieu theo requirements.txt
::    - Tu chay migrate.py (backfill runtime) - bo qua bang
::      PC06_SKIP_MIGRATE=1
::    - Host/port qua PC06_HOST / PC06_PORT (mac dinh 127.0.0.1:5000)
::    - CHONG CHAY TRUNG: bao neu cong 5000 da bi chiem
::  Dung server: STOP_Server.bat hoac Ctrl+C
:: ===================================================

cd /d "%~dp0"

set "PC06_HOST=%PC06_HOST%"
if "%PC06_HOST%"=="" set "PC06_HOST=127.0.0.1"
set "PC06_PORT=%PC06_PORT%"
if "%PC06_PORT%"=="" set "PC06_PORT=5000"
set "FLASK_ENV=%FLASK_ENV%"
if "%FLASK_ENV%"=="" set "FLASK_ENV=development"

echo ==========================================
echo    KIEM TRA MOI TRUONG PYTHON
echo ==========================================

:: Uu tien venv neu da tao san
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
    goto :PYTHON_OK
)
if exist "venv\Scripts\python.exe" (
    set "PYTHON_CMD=venv\Scripts\python.exe"
    goto :PYTHON_OK
)

:: Mac dinh thu lenh python
set "PYTHON_CMD=python"
python --version >nul 2>&1
if !ERRORLEVEL! EQU 0 goto :PYTHON_OK

:: Neu khong co thi thu python3
set "PYTHON_CMD=python3"
python3 --version >nul 2>&1
if !ERRORLEVEL! EQU 0 goto :PYTHON_OK

echo.
echo [LOI] Khong tim thay Python tren may tinh nay!
echo Vui long cai dat Python 3.x tu: https://python.org
echo.
pause
exit /b 1

:PYTHON_OK
echo [OK] Tim thay Python. Dang dung: %PYTHON_CMD%
echo.

echo ==========================================
echo    KIEM TRA THU VIEN
echo ==========================================
%PYTHON_CMD% -c "import flask, sqlalchemy, docx" >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo [OK] Thu vien da san sang.
) else (
    if not exist requirements.txt (
        echo [CANH BAO] Khong tim thay requirements.txt
    ) else (
        echo [..] Thieu thu vien - dang cai dat theo requirements.txt ...
        %PYTHON_CMD% -m pip install -r requirements.txt --disable-pip-version-check
        if !ERRORLEVEL! NEQ 0 (
            echo [CANH BAO] Co loi khi pip install. Se thu chay server.
        ) else (
            echo [OK] Thu vien da san sang.
        )
    )
)

echo.
echo ==========================================
echo    KIEM TRA CONG %PC06_PORT%
echo ==========================================
:: Tim PID dang chiem port - neu co thi BAO (khong tu kill de tranh mat du lieu DB)
set "PID_BUSY="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PC06_PORT%" ^| findstr "LISTENING" 2^>nul') do (
    set "PID_BUSY=%%a"
)

if "!PID_BUSY!"=="" goto :PORT_OK
echo [CANH BAO] Cong %PC06_PORT% dang duoc chiem boi PID: !PID_BUSY!
for /f "tokens=*" %%n in ('tasklist /FI "PID eq !PID_BUSY!" /FO CSV /NH 2^>nul') do echo            Tien trinh: %%n
echo            Chay STOP_Server.bat de giai phong, hoac dat PC06_PORT khac.
echo.
choice /C YN /M "Ban co muon giai phong cong nay (kill PID !PID_BUSY!) khong"
if !ERRORLEVEL! EQU 1 (
    taskkill /F /T /PID !PID_BUSY! >nul 2>&1
    timeout /t 1 /nobreak >nul
    echo [OK] Da giai phong cong %PC06_PORT%.
) else (
    echo [DUNG] Khong kill. Thoat.
    pause
    exit /b 1
)

:PORT_OK
echo [OK] Cong %PC06_PORT% da san sang.

echo.
echo ==========================================
echo    MIGRATION / BACKFILL RUNTIME
echo ==========================================
if "%PC06_SKIP_MIGRATE%"=="1" (
    echo [BO QUA] PC06_SKIP_MIGRATE=1
    goto :CHECK_APP
)
echo [..] Kiem tra migration / backfill runtime (migrate.py) ...
%PYTHON_CMD% migrate.py >nul 2>&1
if !ERRORLEVEL! EQU 0 (
    echo [OK] Migration OK.
) else (
    echo [CANH BAO] migrate.py that bai - bo qua, server van khoi dong.
    echo            Chi tiet: chay tay "python migrate.py" de xem loi.
)

:CHECK_APP
echo.
echo ==========================================
echo    KIEM TRA FILE CHAY
echo ==========================================
set "APP_FILE=app.py"

if exist app.py goto :DO_START

echo [LOI] Khong tim thay file app.py
echo Thu muc hien tai: %CD%
pause
exit /b 1

:DO_START
echo [OK] Se chay file: %APP_FILE%
echo.

:: Mo browser sau 3 giay
start /b powershell -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://%PC06_HOST%:%PC06_PORT%/'" >nul 2>&1

echo ==========================================
echo    DANG CHAY SERVER - http://%PC06_HOST%:%PC06_PORT%
echo    FLASK_ENV=%FLASK_ENV%  (dat DEBUG=true de bat debug)
echo ==========================================
echo.
echo  NHAN CTRL+C DE DUNG SERVER.
echo  CUA SO NAY PHAI LUON MO DE SERVER HOAT DONG.
echo.

%PYTHON_CMD% %APP_FILE%

echo.
echo ==========================================
echo    SERVER DA DUNG. Ma loi: %ERRORLEVEL%
echo ==========================================
echo.
echo [!] Neu server bi loi (tu tat), vui long chup anh man hinh nay.
pause
