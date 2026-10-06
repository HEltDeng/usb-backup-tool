# USB Backup V10

Windows 10/11 后台静默 U 盘抢救备份工具。程序采用“本地数据优先”设计：复制、ZIP 和云上传是三个明确阶段，网络问题不能破坏本地成果。

## 这版解决的核心问题

- U 盘中的文件按 1 MiB 分块写入 `D:\USB_Backup`，不会整文件读入内存。
- 每累计 32 MiB 调用刷新和磁盘同步；大文件复制过程中，目标目录可看到持续增长的 `*.usbbackup.partial`/写入文件。
- 完整文件先写临时名，大小校验成功后才原子改成正式文件。
- 拔盘或 I/O 中断后，不丢弃已经落盘的字节；生成清单并压缩为 `_partial.zip`。
- ZIP 使用 Deflate、Zip64 和逐文件 1 MiB 读取。ZIP 成功并重新打开验证前，绝不删除恢复目录。
- 压缩失败保留恢复目录；上传失败保留 ZIP；只有上传成功才删除 ZIP，永不删除 U 盘源文件。
- 使用 WM_DEVICECHANGE 加 2 秒周期扫描双通道检测，兼容普通 U 盘及被 Windows 标为固定磁盘的 USB SSD/移动硬盘。
- 程序或电脑在复制中异常退出时，下次启动会识别自己的遗留目录，改成部分备份并生成 `_partial.zip`。

## 启动

1. 确认 D 盘有足够空间。最坏情况需要“已复制数据 + ZIP”两份空间。
2. 双击 `USB_Backup_V10.exe`。程序没有窗口，可在任务管理器查看。
3. 插入 U 盘。日志位于 `D:\USB_Backup\backup_log.txt`。
4. 同一时间只处理一个 U 盘，其他任务进入串行队列。

## 拔盘后的结果

例如 20 GB 文件复制到约 5 GB 时拔盘：

1. 已同步到 D 盘的字节保存在以 `.usbbackup.partial` 结尾的文件中。
2. `backup_manifest.json` 记录预期大小、已复制大小和错误。
3. 程序停止读取该 U 盘，并把当前恢复目录压缩成 `任务名_partial.zip`。
4. ZIP 成功后才删除未压缩恢复目录；ZIP 失败则目录保持原样。

ZIP 必须在拔盘后才能封闭中央目录并成为可正常打开的 ZIP。复制时并行生成同一个 ZIP 会使断电/崩溃时 ZIP 本身也可能不可用，因此 V10 先保证部分原文件落盘，再压缩它，这是更可靠的恢复顺序。

## 阿里云盘配置

不要在聊天、源码、README 或快捷方式参数中发送真实 Token。双击 EXE 同目录的 `配置阿里云盘.cmd`，在本机隐藏输入 refresh token，并填写云端目录；脚本会在 EXE 旁生成被 Git 忽略的 `config.local.json`，同时启用上传。配置后必须结束旧进程并重新启动 EXE，日志应显示：

```text
上传启用=True | Token配置=True
```

也可使用用户环境变量：

```powershell
[Environment]::SetEnvironmentVariable('ALIDRIVE_REFRESH_TOKEN', '你的refresh token', 'User')
[Environment]::SetEnvironmentVariable('ALIDRIVE_UPLOAD_ENABLED', 'true', 'User')
[Environment]::SetEnvironmentVariable('ALIDRIVE_REMOTE_ROOT', '/USB_Backup', 'User')
```

当前适配层按照需求中的兼容接口调用 `auth.aliyundrive.com/v2/account/token`、`create_with_proof`、分片 PUT 和 `complete`。阿里云盘的开放平台 OAuth 凭据与个人客户端 refresh token 不是同一种东西；真实账号联调前需确认你提供的是哪种凭据。自动化测试不消耗真实额度。

如果启用代理后出现 TLS EOF、连接重置或超时，先关闭代理测试，或让 `auth.aliyundrive.com` 和 `api.aliyundrive.com` 直连。若日志是 `Token配置=False`，则程序尚未发起网络请求，与代理无关。

## 待上传 ZIP 恢复

网络失败的 ZIP 留在备份根目录。下次程序启动时，只要上传已启用且 Token 存在，会按文件名顺序重试已有 ZIP；第一个失败后停止本轮重试，避免无限请求。

## 配置项

| 环境变量 | 默认值 | 说明 |
|---|---:|---|
| `USB_BACKUP_ROOT` | `D:\USB_Backup` | 本地备份根目录 |
| `USB_BACKUP_COPY_CHUNK` | `1048576` | 复制块大小 |
| `USB_BACKUP_FLUSH_BYTES` | `33554432` | 强制落盘间隔 |
| `USB_BACKUP_ARCHIVE_CHUNK` | `1048576` | ZIP 读取块大小 |
| `USB_BACKUP_SCAN_INTERVAL` | `2` | USB 周期扫描秒数 |
| `ALIDRIVE_UPLOAD_ENABLED` | `false` | 是否启用上传 |
| `ALIDRIVE_REFRESH_TOKEN` | 空 | refresh token |
| `ALIDRIVE_REMOTE_ROOT` | `/USB_Backup` | 云端目录 |
| `ALIDRIVE_PART_SIZE` | `5242880` | 上传分片大小 |
| `ALIDRIVE_MAX_RETRIES` | `3` | 单请求最大尝试次数 |
| `ALIDRIVE_TIMEOUT_SECONDS` | `30` | 请求超时 |

## 故障排查

- 没有检测到设备：等待 10 秒；确认设备在资源管理器中有盘符；提供日志中“USB 周期扫描异常”附近内容。
- D 盘空间不足：压缩不会开始或失败后保留恢复目录；先扩容或修改 `USB_BACKUP_ROOT`。
- `_partial.zip`：表示设备被拔出或至少一个文件没有复制完整，不应当成完整镜像。
- 上传失败：ZIP 会保留。只提供状态码和错误行，切勿发送 Token 或完整 Authorization。
- 程序没有窗口：这是预期行为；使用任务管理器结束进程。

## 开发与构建

```powershell
python -m unittest discover -s .\tests -p 'test_*.py' -v
python .\tests\integration_large.py
.\build.cmd
```

依赖 Python 3.8+、psutil、pywin32、requests；构建使用 PyInstaller。不要自动联网安装依赖。

## GitHub 源码恢复与平台边界

私有仓库：`HEltDeng/usb-backup-tool`；当前源码分支 `migration/source-baseline`，保留现有 V10 实现。仓库名称不绑定版本。
Mac 可以 clone、编辑和继续维护代码；本产品使用 Windows WM_DEVICECHANGE、win32api/win32gui 与 pywin32，不能在 macOS 原生运行，也不能用 Mac 原生 Python 直接构建 Windows EXE。需要可用的 Windows 开发环境/构建机器；本轮不做跨平台改写。

Windows 新环境使用 Python 3.11，创建虚拟环境，运行 `python -m pip install -r requirements.txt`。构建还需安装 PyInstaller，再运行 `build.cmd`；仓库保留 `USB_Backup_V10.spec`。自动化检查为 `python -m unittest discover -s tests -p "test_*.py"`。大文件集成测试需显式选择容量，不能当普通恢复步骤自动执行。
从 `.env.example` 或 `config.local.example.json` 重建本机配置。真实 Token、config.local.json、USB 用户文件、备份 ZIP、测试大文件和日志不进入 Git。没有 Windows 环境时，源码恢复已完成也不代表原生运行环境就绪。
