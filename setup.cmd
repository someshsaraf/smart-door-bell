@echo off
rem Runs setup.ps1 with PowerShell from any terminal (cmd or PowerShell) or a double-click.
rem (In cmd, "setup.ps1" opens the file in Notepad: .ps1 scripts only run inside PowerShell.)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
exit /b %ERRORLEVEL%
