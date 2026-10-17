@echo off
REM ---------------------------------------------------------------
REM Development launcher.
REM Runs the workbench against an isolated data directory so that
REM experiments never touch the daily-use instance stored in
REM %LOCALAPPDATA%\PersonalWorkbench.
REM
REM To temporarily run against the real (daily) data instead:
REM   set WORKBENCH_DATA_DIR=
REM   start.cmd
REM ---------------------------------------------------------------
set "WORKBENCH_DATA_DIR=%LOCALAPPDATA%\PersonalWorkbench-dev"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start.ps1"
if errorlevel 1 pause
