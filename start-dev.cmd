@echo off
REM ---------------------------------------------------------------
REM Development launcher.
REM Delegates to scripts\start-dev.ps1. Data root lives inside this
REM project (<project>\data); the daily stable copy keeps its own
REM data in wb-stable\data, so experiments never touch daily data.
REM
REM Desktop shortcut and this .cmd share the same logic source.
REM ---------------------------------------------------------------
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-dev.ps1"
if errorlevel 1 pause
