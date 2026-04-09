@echo off
setlocal enabledelayedexpansion
title PC06 - Web Server
color 0A

:: ---------------------------------------------------
:: TU DONG CHUYEN VAO THU MUC CHUA FILE BAT NAY
:: ---------------------------------------------------
cd /d "%~dp0"

echo ==========================================
echo    KIEM TRA MOI TRUONG PYTHON
echo ==========================================

:: Mac dinh thu lenh python
set PYTHON_CMD=python
python --version >nul 2>&1
if !ERRORLEVEL! EQU 0 goto :PYTHON_OK

:: Neu khong co thi thu lệnh python3
set PYTHON_CMD=python3
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
echo    GIAI PHONG CONG 5000
echo ==========================================
:: Tim PID dang chiem port 5000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING" 2^>nul') do (
    set "PID_TO_KILL=%%a"
)

if "!PID_TO_KILL!"=="" goto :PORT_OK
echo Dang giai phong cong 5000 (PID: !PID_TO_KILL!)
taskkill /F /T /PID !PID_TO_KILL! >nul 2>&1
timeout /t 1 /nobreak >nul

:PORT_OK
echo [OK] Cong 5000 da san sang.
echo.

echo ==========================================
echo    KIEM TRA THU VIEN
echo ==========================================
if not exist requirements.txt (
    echo [CANH BAO] Khong tim thay requirements.txt
    goto :CHECK_APP
)

echo Dang kiem tra va cai dat thu vien
%PYTHON_CMD% -m pip install -r requirements.txt --disable-pip-version-check
if !ERRORLEVEL! NEQ 0 (
    echo [CANH BAO] Co loi khi pip install. Se thu chay server.
) else (
    echo [OK] Thu vien da san sang.
)

:CHECK_APP
echo.
echo ==========================================
echo    KIEM TRA FILE CHAY
echo ==========================================
set APP_FILE=app.py

if exist app.py goto :DO_START

echo [LOI] Khong tim thay file app.py
echo Thu muc hien tai: %CD%
pause
exit /b 1

:DO_START
echo [OK] Se chay file: %APP_FILE%
echo.

:: Mo browser sau 3 giay
start /b powershell -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://localhost:5000/'" >nul 2>&1

echo ==========================================
echo    DANG CHAY SERVER - http://localhost:5000
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

