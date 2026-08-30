# 春秋元泉 GEO 个人电脑版

这是运行在你自己电脑上的个人版，不是公网云服务。账号、工作区、任务、数据库和证据都保存在本机 Docker 数据卷中。

## 安装前只需准备 Docker Desktop

- Windows：[Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/)
- macOS：[Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/)

安装后先启动 Docker Desktop，等待界面显示 Docker Engine 正在运行。不需要另外安装 Node.js、Python、pnpm 或 uv。

## Windows 首次启动

1. 从 GitHub 下载 ZIP，右键“全部解压”，不要直接在 ZIP 预览中运行。
2. 双击 `Start-GEO-Windows.cmd`。
3. 首次会下载并构建组件，完成后自动打开注册页。
4. 创建你自己的管理员账号和工作区。

Windows 若提示 WSL2 或虚拟化未开启，请先按 Docker Desktop 提示修复并重启电脑。

## macOS 首次启动

1. 从 GitHub 下载 ZIP 并解压。
2. 首次右键 `Start-GEO.command`，选择“打开”。
3. 首次会下载并构建组件，完成后自动打开注册页。
4. 创建你自己的管理员账号和工作区。

## 日常操作

| 目的 | Windows | macOS |
|---|---|---|
| 启动并打开页面 | `Start-GEO-Windows.cmd` | `Start-GEO.command` |
| 检查 Web、API、数据库和 Worker | `Status-GEO-Windows.cmd` | `Status-GEO.command` |
| 停止服务但保留数据 | `Stop-GEO-Windows.cmd` | `Stop-GEO.command` |
| 备份数据、证据和本机密钥 | `Backup-GEO-Windows.cmd` | `Backup-GEO.command` |

默认访问地址是 `http://127.0.0.1:3000`。如果 3000 端口已被占用，首次启动会在 3001–3010 中选择空闲端口，不会结束其他程序。

## 首次进入后

1. 注册本机管理员账号。
2. 在“模型与渠道”中配置你有权使用的 Provider，并先执行连接测试。
3. 只提交当前页面选定的模型、问题和轮次；启动 Worker 不会重新执行历史批次。

连接成功只代表 Provider 可调用，不代表已完成真实联网观测。草稿生成、Agent 连接或同步请求也不代表已发布；最终发布必须由用户在目标平台确认。

## 数据与更新

- 数据库卷：`chunqiu_yuanquan_geo_personal_data`
- 证据卷：`chunqiu_yuanquan_geo_personal_artifacts`
- macOS 本机配置与密钥：`~/.config/chunqiu-yuanquan-geo/.env.personal`
- Windows 本机配置与密钥：`%LOCALAPPDATA%\ChunqiuYuanquanGEO\.env.personal`
- macOS 加密备份：`~/.local/share/chunqiu-yuanquan-geo/backups`，独立密钥：`~/.config/chunqiu-yuanquan-geo/backup.key`
- Windows 加密备份：`%LOCALAPPDATA%\ChunqiuYuanquanGEO\backups`，独立密钥：`%LOCALAPPDATA%\ChunqiuYuanquanGEO\backup.key`

停止服务、重启 Docker Desktop、或将新版本解压到另一个目录，都不会改变上述固定数据卷和用户配置。更新前先运行备份入口，然后直接在新版本中启动。日常更新不需要手动复制密钥，但做灾难恢复时必须同时拿到另行保管的 `backup.key`。

不要运行 `docker compose down -v`。`-v` 会删除数据卷。备份目录只保留认证加密的 `.gcm` 文件，但密文和 `backup.key` 仍不得上传 GitHub 或转发。

## 当前边界

- Docker 个人版的 Web、API、SQLite 和采集 Worker 可独立运行。
- 宿主机上的 Codex、Claude、Hermes、OpenClaw 或 EgoLite 登录不会自动进入容器。对应 Agent/浏览器功能必须另行配置并通过真实诊断，不能仅凭 SDK 安装状态宣称可用。
- 个人版默认 Worker 并发为 8，程序允许的上限仍为 125。实际速度受电脑性能、SQLite 写入、供应商 QPS 和 429 限流影响。
