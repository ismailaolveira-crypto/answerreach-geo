# 春秋元泉 GEO 本地双模式部署

## 结论

同一套代码支持两种形态：

- **个人模式**：只允许本机 `127.0.0.1` 访问，SQLite 与证据文件保存在 Docker 数据卷，适合下载到个人电脑独立使用。
- **局域网团队模式**：一台可信主机运行 Web、API、PostgreSQL 和中央队列，成员通过 `http://主机IP:3000` 登录同一套数据。

两种模式都不上传 EgoLite Cookie、平台密码、浏览器本地存储或 Codex 登录 Token。局域网模式中的 Local Agent 采用出站心跳，不在成员电脑开放可执行命令的 HTTP 端口。

## 参考的开源方法

- [GitHub Actions Runner](https://github.com/actions/runner)：自托管 Runner 安装在执行机器上，由 Runner 主动连接控制面接收任务。
- [GitLab Runner](https://github.com/gitlabhq/gitlab-runner)：控制面协调任务，Runner 在自己的机器执行并回传结果。
- [Gitea](https://github.com/go-gitea/gitea)：一个可自托管程序同时支持个人安装、组织与成员权限。
- [AppFlowy](https://github.com/AppFlowy-IO/AppFlowy)：同一产品同时提供个人桌面使用和自托管协作形态。

本项目只借鉴边界和通信方式，没有复制这些项目代码。V1 Local Agent 只注册设备与报告非敏感健康状态；**在线不等于已领取或完成任务**。

## 个人模式

前置条件：Docker Desktop。

```bash
pnpm run deploy:personal:config
pnpm run deploy:personal
```

打开：

```text
http://127.0.0.1:3000
```

特点：

- 网关只绑定 `127.0.0.1`，局域网其他电脑无法访问。
- SQLite worker 并发固定为 8，避免 125 个并发写入造成锁库。
- 数据位于 `geo_personal_data` Docker 卷；停止容器不会删除数据。
- 不要运行 `docker compose down -v`，`-v` 会删除个人数据卷。

## 局域网团队模式

在主机上确认固定局域网 IP，例如 `192.168.1.20`：

```bash
pnpm run deploy:lan:config --host 192.168.1.20
pnpm run deploy:lan
```

同一网络的成员打开：

```text
http://192.168.1.20:3000
```

局域网模式强制：

- PostgreSQL；配置成 SQLite 时 API 会拒绝启动。
- 独立随机 `AUTH_SECRET`；默认开发密钥会被拒绝。
- 125 个中央 worker 并发槽；实际吞吐仍受模型供应商 QPS、429 和主机资源限制。
- 工作区成员关系；同公司但未加入该工作区的账号返回 404。

不要直接把端口映射到公网。跨办公地点访问应由管理员配置公司 VPN/Tailscale 或正式 HTTPS 反向代理，而不是路由器端口转发。

## 邀请成员

1. 所有者/管理员打开“工作区设置”。
2. 在“工作区成员”输入邮箱并选择角色。
3. 系统生成一次性链接；通过公司内部安全渠道发给成员。
4. 成员打开链接：已有账号填写原密码，新成员设置密码。
5. 链接成功使用后立即失效；数据库只保存 SHA-256 摘要。

## 连接成员电脑的 Local Agent

1. 成员进入工作区设置，点击“生成 20 分钟设备接入码”。
2. 在该成员电脑的项目目录运行界面给出的命令。
3. 再启动心跳：

界面命令默认使用 `http://HOST:3000`；如果部署时改了 `GEO_HTTP_PORT`，将命令中的 `3000` 替换为实际端口。

```bash
pnpm run worker:local-agent
```

Local Agent 本地配置保存在：

```text
~/.config/chunqiu-yuanquan-geo/local-agent.json
```

该文件包含不透明设备 Token，权限为 `0600`，不得共享或提交。服务端只保存 Token 哈希，并只接收：操作系统、Agent 版本、EgoLite 是否安装/运行、Codex 是否可用等布尔状态。它不会读取平台登录态内容。

## EgoLite 与任务边界

- Web 页面的文章同步仍由当前用户在自己的 EgoLite 中点击并人工确认。
- 主机看见“EgoLite 运行中”只表示 Local Agent 的进程检查结果，不表示某个平台已登录。
- V1 Local Agent `execution_mode=status_only`，不会接收远程 Shell，也不会被当作观测完成证据。
- 后续若开放远程任务领取，必须另做任务包下载、事件回传、结果校验和撤销协议，不能直接让 Local Agent 访问中央数据库。

## 备份

- 个人模式：定期停 worker 后备份 `geo_personal_data` 与 `geo_personal_artifacts` 卷。
- 局域网模式：定期执行 PostgreSQL 逻辑备份，并备份 `geo_lan_artifacts` 卷。
- 任何备份都应加密并限制为管理员可读。
