# 春秋元泉 GEO Agent 仓库指南

本仓库为独立产品 `answerreach-geo`；「春秋元泉」是示例工作区及历史兼容数据，不是全局品牌默认值。所有 Agent 在修改「优先行动、内容生成、平台适配、草稿同步、复测」前，必须先完整阅读：

- [`docs/agent/CODEX_AGENT_EXECUTION_RUNBOOK.md`](docs/agent/CODEX_AGENT_EXECUTION_RUNBOOK.md)
- [`docs/product/CODEX_AGENT_INTEGRATION_IMPLEMENTATION.md`](docs/product/CODEX_AGENT_INTEGRATION_IMPLEMENTATION.md)
- [`docs/design/codex-agent-priority-actions-ui-spec.md`](docs/design/codex-agent-priority-actions-ui-spec.md)

不可违反的边界：

- 不读取、输出、覆盖或提交 `.env` 中的密钥。
- 不替换、删除或重新初始化 `apps/api/geo_platform.db`。
- 不提交数据库、`private_artifacts`、日志、`node_modules` 或 `.next`。
- 不得把 Agent 输出、连接成功或同步请求接受宣称为真实已发布或 GEO 效果改善。
- 系统只能写入草稿；最终发布必须由用户在目标平台确认。
- 任何“已完成”状态都必须有数据库记录和可回读证据。

开发交付前至少完成：`pnpm run check:web`、受影响的 API 验证、真实浏览器验收、隐私文件审计。
