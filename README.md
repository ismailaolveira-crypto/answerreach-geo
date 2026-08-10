# 春秋元泉 GEO

多模型真实观测、证据归档、问题分析与优化草稿工作台。

## 同事下载后直接使用

请从 [`START_HERE.md`](START_HERE.md) 开始。个人电脑版只要求 Docker Desktop，不需要本机安装 Node.js、Python、pnpm 或 uv。

- Windows：双击 `Start-GEO-Windows.cmd`
- macOS：首次右键打开 `Start-GEO.command`
- 启动完成后：在本机注册管理员账号和独立工作区

个人版只绑定 `127.0.0.1`，不会默认暴露到局域网或公网。GitHub 仓库不包含任何真实数据库、`.env` 密钥、Provider Token、私有证据、日志或登录态。

## 主要能力

- 按用户选择的模型 × 问题 × 轮次创建真实观测。
- 账号、公司、工作区和成员角色隔离。
- 观测证据、来源、竞品位置、问题库与优化行动。
- 草稿审核、人工发布边界和可复测记录。
- 本机 Queue Worker 心跳、队列与失败原因展示。

Worker 在线只表示可以消费当前页面新提交的任务，不表示模型调用已完成。Agent 连接、草稿生成或同步请求不等于已发布或 GEO 效果已改善。

## 开发与仓库边界

开发者请先阅读：

- [`AGENTS.md`](AGENTS.md)
- [`docs/DEVELOPER_HANDOFF.md`](docs/DEVELOPER_HANDOFF.md)
- [`docs/local-deployment-modes.md`](docs/local-deployment-modes.md)
- [`docs/current-real-use-status.md`](docs/current-real-use-status.md)

本地验证：

```bash
pnpm run check:api
pnpm run check:web
pnpm run build:web
pnpm run verify:local
```

不得提交真实数据库、`.env` 密钥、`private_artifacts`、日志、`node_modules` 或 `.next`。
