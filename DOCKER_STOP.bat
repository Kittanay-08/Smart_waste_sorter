@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================
echo   Smart Waste Sorter - Docker Stopper
echo ==============================================
echo กำลังหยุด Docker Container...
docker compose down
echo.
echo หยุดการทำงานของ Docker Container เรียบร้อยแล้ว!
echo ==============================================
pause
