# USB Backup V10 测试报告

日期：2026-08-09  
环境：Windows 64 位，Python 3.11.9

## 最终结果

- 语法检查：通过。
- 自动化测试：15/15 通过。
- 真实模拟大文件：256 MiB、256 个 1 MiB 分块，复制 SHA-256 一致，Deflate ZIP 成功。
- 中途拔盘状态：20 MiB→5 MiB 比例模拟通过，部分文件和 `_partial.zip` 的成员大小均为 5 MiB。
- PyInstaller 单文件无控制台 EXE：构建成功。
- EXE 自检：退出码 0。
- 真实 USB/真实阿里云盘：未调用。

## 命令

```powershell
python -m compileall -q .\main.py .\usb_backup_v10 .\tests
python -m unittest discover -s .\tests -p 'test_*.py' -v
python .\tests\integration_large.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name USB_Backup_V10 --distpath .\dist --workpath .\build --specpath . .\main.py
```

## 覆盖矩阵

1. 小文件、嵌套目录和空目录。
2. 大文件多分块读取，读取请求始终有 64 KiB/1 MiB 上限。
3. 设备未就绪时保留部分字节并生成 `_partial.zip`。
4. 写入空间不足时不生成伪完整正式文件。
5. ZIP 失败保留恢复目录。
6. 安全清理拒绝非托管用户目录。
7. 拒绝把备份根目录设在源 U 盘内部。
8. 缺 Token、网络超时保留 ZIP；上传成功只删除 ZIP、不删除源。
9. 进程崩溃遗留目录在下次启动恢复为部分 ZIP。
10. Token 不进入 Settings repr，日志过滤 Token/Authorization。
11. 普通可移动盘和 USB 总线固定盘被接受，内部固定盘拒绝。
12. 周期扫描去重，物理移除再插入后会重新触发。

## 测试闭环

- 第一轮 9 项测试中 2 项失败：Windows 对只读文件描述符执行 `fsync` 返回 `Bad file descriptor`。
- 修复：ZIP 关闭后以 `r+b` 句柄调用 FlushFileBuffers/fsync。
- 第二轮 9/9 通过。
- 首次运行 256 MiB 脚本失败：直接执行脚本时模块搜索路径只包含 tests。
- 修复：测试入口显式加入 V10 根目录；复测通过，输出 `PASS bytes=268435456 chunks=256 zip_bytes=268517971`。
- 加入崩溃恢复、自复制保护和双通道检测测试后，最终 15/15 通过。

## 未覆盖

- 真实 20 GB USB、真实拔盘控制器错误、真实 FAT32/NTFS/exFAT。
- D 盘实际空间不足和真实权限策略。
- 真实阿里云盘令牌、代理、OAuth 权限及服务端接口兼容性。
