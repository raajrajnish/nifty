@echo off
rem Double-click after the market closes (~15:45): analyse today, update the database, forward paper test.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\eod.ps1"
