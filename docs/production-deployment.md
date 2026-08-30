# 春秋元泉 GEO 云端正式部署

## 先说结论

推荐的第一版正式部署是一台专用 Linux 云服务器和一个域名。仓库已经把以下组件组合成一套：

- Caddy：自动申请和续期 HTTPS 证书；
- Nginx：路由、上传大小限制和登录限流；
- Next.js Web；
- FastAPI API；
- PostgreSQL 16；
- 中央任务 Worker；
- 私有证据文件卷和可校验备份。

这不是演示环境。它会关闭公网自助注册，强制 PostgreSQL、随机密钥、HTTPS Cookie、显式域名和数据库迁移。它适合早期正式客户或一个企业团队，但仍是单机部署，不等于多机高可用。

## 准备什么

1. 一台 4 核 8 GB 起步的 Linux 云服务器；大量并发采集建议 8 核 16 GB 以上。
2. Docker Engine 与 Docker Compose v2。
3. 一个域名，例如 `geo.example.com`。
4. 将该域名的 A 记录指向服务器公网 IPv4；如配置 AAAA，必须也能正确访问该服务器。
5. 云防火墙只对公网开放 `22`、`80`、`443`。PostgreSQL、API、Web 和 Worker 不直接映射公网端口。

先确认 DNS 已指向正确服务器，再启动。否则 Caddy 无法完成证书申请。

## 一键启动

在服务器的项目根目录运行：

```bash
./scripts/geo-cloud.sh start geo.example.com
```

首次启动会：

1. 在管理员用户目录创建权限为 `0600` 的私密配置；
2. 生成数据库、登录签名和 Web/API 内部通信密钥，但不显示密钥；
3. 构建并启动全部容器；
4. 自动运行 Alembic 前向迁移；
5. 等待数据库、API、Web 与 Worker 心跳全部就绪；
6. 在终端安全询问管理员邮箱和两次密码；
7. 验证真实域名的 HTTPS 登录页和健康接口。

管理员密码不会进入命令行参数、仓库文件或脚本输出。其他成员应由管理员通过“工作区邀请”加入，公网注册保持关闭。

成功后的唯一入口是：

```text
https://geo.example.com
```

## 日常操作

```bash
./scripts/geo-cloud.sh status
./scripts/geo-cloud.sh logs
./scripts/geo-cloud.sh backup
./scripts/geo-cloud.sh verify-backup /受控路径/geo-backup-日期时间.gcm
./scripts/geo-cloud.sh stop
```

- `status` 同时检查容器、API、Web、PostgreSQL、Worker 心跳和公网 HTTPS。
- `logs` 只显示最近 150 行；日志仍可能包含内部路径，不要整段转发。
- `verify-backup` 不修改数据库，会用独立备份密钥验证 AES-256-GCM 密文是否完整且可解密。
- `stop` 只停止服务，不删除数据库、证据或 HTTPS 证书。
- 绝对不要运行 `docker compose down -v`。

## 更新与备份

再次运行相同启动命令即可更新：

```bash
./scripts/geo-cloud.sh start
```

检测到已有数据时，启动器会先构建备份所需的 API 工具镜像，再创建一致性备份，最后启动新版并执行迁移。备份会短暂停止 API 与 Worker，避免数据库和证据文件处于不同时间点。

备份默认保存在：

```text
~/.local/share/chunqiu-yuanquan-geo-cloud/backups/日期-时间/
```

每份完整备份目录最终只保留一个 `geo-backup-日期时间.gcm`。它是经过 AES-256-GCM 认证加密的密文，内部包含：

- `database.dump`：PostgreSQL 自定义格式逻辑备份；
- `artifacts.tar.gz`：附件、截图和交付证据；
- `env.cloud`：解密与登录所需密钥；
- `SHA256SUMS`：三个文件的哈希；
- `BACKUP_COMPLETE`：完成标记。

脚本会先执行 `pg_restore --list`、归档读取和 SHA-256 生成，再加密整个包，立即验证 GCM 标签，成功后才删除本次临时明文。

独立备份密钥位于 `~/.config/chunqiu-yuanquan-geo/backup.key`，不在备份密文内。密文和密钥必须分开保存在受控位置；丢失密钥就无法恢复，两者都绝不能提交 GitHub。

## 灾难恢复原则

恢复不是普通“重启”，它会覆盖目标数据库，因此不自动执行。管理员应先在隔离服务器演练：

1. 用 `verify-backup` 和原 `backup.key` 校验密文；
2. 在隔离目录调用 `secure_backup_bundle.py decrypt` 解密并展开归档；
3. 校验包内 `BACKUP_COMPLETE` 和 `SHA256SUMS`；
4. 恢复 `env.cloud`，权限设为 `0600`；
5. 用 `pg_restore` 恢复 `database.dump`，并恢复 `artifacts.tar.gz` 到证据卷；
6. 启动服务并运行 `status`，再用真实管理员检查工作区、附件回读和 Worker 心跳。

数据库与 `env.cloud` 必须成对恢复。只恢复数据库、不恢复原加密密钥，会导致已保存的 Provider 凭据无法解密。正式投用前应由运维人员做一次隔离恢复演练，而不是等故障发生后第一次尝试。

## 这套部署保护了什么

- API、数据库和 Web 均不直接暴露公网，只由 Caddy 的 80/443 进入。
- 生产模式拒绝 SQLite、默认登录密钥、HTTP CORS、通配 Host、自动建表和公网注册。
- 登录有网关限流和数据库持久化失败限流；伪造转发 IP 不会绕过 BFF 身份判断。
- Web 与 API 使用独立内部代理密钥；浏览器拿不到该密钥。
- 应用容器以非 root 用户运行，删除 Linux capabilities，并启用 `no-new-privileges`。
- 日志有大小和文件数上限，避免无限占满系统盘。
- 最终外部平台发布仍必须由用户确认；部署成功不代表飞书、企业微信、钉钉或内容平台已经授权。

## 仍需按企业规模升级的部分

这套方案是“真实可运行的安全单机版”，不是无限扩展架构。出现下列情况时再升级，避免过早堆复杂基础设施：

- 要求服务器故障时自动切换：改为托管 PostgreSQL、多副本 API/Web 和负载均衡；
- 证据文件超过单机磁盘或需要跨机：迁移到 S3、R2、OSS 等对象存储；
- Worker 长期高并发：拆分独立 Worker 节点并增加队列治理；
- 企业要求统一登录：接入经过审批的 OIDC/SAML/企业身份系统；
- 有合规要求：补充集中审计、密钥托管、备份保留策略和恢复演练记录。

“能启动”不等于“企业验收完成”。正式交付还应验证域名证书、管理员登录、邀请成员、权限隔离、附件保存回读、备份、隔离恢复和告警接收。
