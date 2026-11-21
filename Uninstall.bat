@echo off
rem Double-click to stop OBS Remote and remove it from startup and the firewall.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\uninstall.ps1"
echo.
pause
