@echo off
rem Runs build.ps1 with PowerShell from any terminal:  build  |  build -Flash COM6  |  build -Flash COM6 -Monitor
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
exit /b %ERRORLEVEL%
