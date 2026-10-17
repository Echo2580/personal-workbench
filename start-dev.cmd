@echo off
REM ---------------------------------------------------------------
REM Development launcher.
REM Delegates to scripts\start-dev.ps1, which points the workbench at
REM an isolated data directory so experiments never touch the
REM daily-use instance stored in %LOCALAPPDATA%\PersonalWorkbench.
REM
REM Desktop shortcut and this .cmd share the same logic source.
REM ---------------------------------------------------------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev.ps1"
if errorlevel 1 pause
