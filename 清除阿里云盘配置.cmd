@echo off
chcp 65001 >nul
if exist "%~dp0config.local.json" del /f /q "%~dp0config.local.json"
echo 本机阿里云盘配置已清除。
pause
