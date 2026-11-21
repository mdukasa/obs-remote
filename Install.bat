@echo off
rem Double-click to install (or repair) OBS Remote on this PC.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\install.ps1" %*
echo.
pause
