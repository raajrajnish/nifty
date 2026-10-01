@echo off
rem Double-click each morning: asks for today's Groww token, then (re)starts the dashboard.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\morning.ps1" %*
