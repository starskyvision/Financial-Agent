@echo off
chcp 65001 >nul
echo ========================================
echo   Financial Agent — Start All Services
echo ========================================
echo.

echo [1/4] Killing old processes...
taskkill /F /IM python.exe 2>nul
taskkill /F /IM celery.exe 2>nul
echo Done.
timeout /t 2 /nobreak >nul

echo [2/4] Starting Docker containers...
docker start financial-agent-redis-1 financial-agent-postgres-1 2>nul
echo Done.
timeout /t 3 /nobreak >nul

echo [3/4] Starting Backend (port 8000)...
start "Backend" cmd /c "cd /d %~dp0 && uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo Waiting 20s for embedder model warm-up...
timeout /t 20 /nobreak >nul

echo [4/4] Starting Celery Worker (worker1)...
start "Celery" cmd /c "cd /d %~dp0 && celery -A services.task_queue.celery_app worker --loglevel=info -P solo -n worker1"
timeout /t 3 /nobreak >nul

echo.
echo ========================================
echo   All services started!
echo.
echo   Backend:  http://localhost:8000
echo   Docs:     http://localhost:8000/docs
echo   Frontend: cd ..\frontend && npm run dev
echo   Celery:   worker1
echo ========================================
echo.
echo Frontend must be started separately:
echo   cd ..\frontend && npm run dev
echo.
pause
