@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=C:\Users\MR.KIT\AppData\Local\Programs\Python\Python313\python.exe
if not exist "%PY%" set PY=python
start "" http://localhost:8000
"%PY%" -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
