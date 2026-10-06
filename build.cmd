@echo off
python -m PyInstaller --noconfirm --clean --onefile --windowed --name USB_Backup_V10 --distpath .\dist --workpath .\build --specpath . .\main.py
if errorlevel 1 exit /b %errorlevel%
copy /y ".\配置阿里云盘.cmd" ".\dist\配置阿里云盘.cmd" >nul
copy /y ".\清除阿里云盘配置.cmd" ".\dist\清除阿里云盘配置.cmd" >nul
echo Build completed: dist\USB_Backup_V10.exe
