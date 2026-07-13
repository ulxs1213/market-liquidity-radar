@echo off
setlocal
cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 goto :missing_powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_windows.ps1" %*
goto :finished

:missing_powershell
echo [ERROR] Windows PowerShell was not found.
pause
exit /b 1

:finished
set "EXIT_CODE=%ERRORLEVEL%"
if NOT "%EXIT_CODE%"=="0" pause
endlocal & exit /b %EXIT_CODE%
