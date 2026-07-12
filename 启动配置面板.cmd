@echo off
chcp 65001 >nul
title IoTCmpt 配置面板
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start-panel.ps1"
if errorlevel 1 pause
