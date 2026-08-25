@echo off
title XOA DATABASE PC06
color 0C

echo.
echo =============================================
echo     XOA DATABASE VA TAO MOI HE THONG PC06
echo =============================================
echo.
echo [CANH BAO] Toan bo du lieu se bi xoa vinh vien!
echo.
set /p confirm="Nhap 'Y' de xac nhan xoa: "
if /i NOT "%confirm%"=="Y" (
    echo Da huy thao tac. An phim bat ky de thoat.
    pause > nul
    exit /b
)

echo.
echo Dang dung server neu dang chay...
taskkill /f /im python.exe >nul 2>&1

echo Dang xoa database...
if exist pc06_system.db (
    del /f /q pc06_system.db
    echo [OK] Da xoa pc06_system.db
) else (
    echo [INFO] Khong co file database.
)

echo.
echo Dang khoi tao database moi...
python -c "from app import app; from models import db; app.app_context().__enter__(); db.create_all(); print('[OK] Database moi da duoc tao thanh cong!')"

echo.
echo =============================================
echo    HOAN THANH! Database da duoc khoi tao moi.
echo    Chay Start_Server.bat de bat dau he thong.
echo =============================================
echo.
pause
