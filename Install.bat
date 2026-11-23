@echo off
rem Double-click to set up (or repair) OBS Remote on this PC. It opens the setup window.
rem Install.bat -Console runs setup in this console instead (so do -Port N, -Tailscale, -NoTailscale, -SkipFirewall, -SkipStartup).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\install.ps1" %*
if %errorlevel%==10 exit /b 0
echo.
pause
