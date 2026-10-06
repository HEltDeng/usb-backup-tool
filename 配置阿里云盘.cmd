@echo off
chcp 65001 >nul
setlocal
set "TARGET=%~dp0config.local.json"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$secure=Read-Host '请输入阿里云盘 refresh token（输入不会显示）' -AsSecureString;" ^
  "$ptr=[Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure);" ^
  "try {$token=[Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr); if ([string]::IsNullOrWhiteSpace($token)) {throw 'Token不能为空'}; $remote=Read-Host '云端目录（直接回车使用 /USB_Backup）'; if ([string]::IsNullOrWhiteSpace($remote)) {$remote='/USB_Backup'}; [ordered]@{upload_enabled=$true;refresh_token=$token;remote_root=$remote}|ConvertTo-Json|Set-Content -LiteralPath $env:TARGET -Encoding UTF8; Write-Host '配置成功。请完全退出旧程序后重新启动 EXE。'} finally {[Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)}"
if errorlevel 1 echo 配置失败，未写入有效配置。
pause
