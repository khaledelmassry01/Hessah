@echo off
REM Trigger Daily AI Signal Generation for Market Watch (Windows)
REM This script uses curl to trigger the admin radar scan endpoint

echo ============================================
echo Daily AI Signal Generator - Market Watch
echo ============================================
echo.

REM Configuration - modify these if needed
set CORE_URL=http://localhost:8080
set ADMIN_USER=admin
set ADMIN_PASS=admin123

echo Core backend: %CORE_URL%
echo.

REM Step 1: Check radar status before
echo Checking current radar status...
curl -s -X POST "%CORE_URL%/api/core/admin/radar/status" -H "Content-Type: application/json" 2>nul
if %ERRORLEVEL% neq 0 (
    echo WARNING: Could not connect to core-backend. Is it running?
    echo Make sure the core-backend service is started on %CORE_URL%
    pause
    exit /b 1
)
echo.
echo.

REM Step 2: Trigger the radar scan
echo Triggering admin radar scan...
echo This will populate the daily_ai_signals table with today's predictions.
echo.

curl -s -X POST "%CORE_URL%/api/core/admin/radar/trigger" -H "Content-Type: application/json" 2>nul
if %ERRORLEVEL% neq 0 (
    echo ERROR: Radar trigger failed. Make sure you have ADMIN role access.
    echo.
    echo Alternative: Direct AI engine prediction
echo You can also try calling the AI engine directly at http://localhost:8000/predict
) else (
    echo.
    echo SUCCESS: Radar scan triggered!
    echo The daily AI signals are being generated.
)

echo.
echo ============================================
echo Next steps:
echo 1. Wait 10-30 seconds for the scan to complete
echo 2. Refresh the Market Watch page
echo 3. The API should now return predictions instead of null
echo ============================================
echo.

pause
