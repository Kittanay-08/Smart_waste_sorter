@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================
echo   Smart Waste Sorter - Docker Launcher
echo ==============================================
echo [1/3] กำลังสร้าง Image และเริ่ม Container...
docker compose up -d --build
if errorlevel 1 (
    echo [ERROR] ไม่สามารถเริ่ม Docker Container ได้ กรุณาตรวจสอบว่า Docker Desktop เปิดอยู่หรือไม่
    pause
    exit /b 1
)
echo [2/3] Docker Container ทำงานเรียบร้อยแล้ว!
echo [3/3] กำลังเปิดเว็บเบราว์เซอร์...
timeout /t 2 /nobreak >nul
start "" http://localhost:8000
echo.
echo เข้าใช้งานได้ที่: http://localhost:8000
echo หากต้องการหยุดการทำงาน สามารถดับเบิลคลิกไฟล์ DOCKER_STOP.bat ได้เลยครับ
echo ==============================================
pause
