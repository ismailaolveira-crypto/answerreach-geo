# 入答代码架构边界

这份文档描述当前代码的真实结构，作为后续开发、自动审计和人工验收的共同边界；具体发布状态以当前分支和 PR 为准。

## 1. 总体结构

```text
浏览器
  -> Next.js 页面 / Server Actions / BFF 路由
       -> 统一 Web API 配置与会话边界
            -> FastAPI 总路由
                 -> 领域路由
                      -> 领域服务
                           -> SQLAlchemy 模型与迁移后的数据库
```

核心规则：页面不直接拼内部 API 地址；服务层不反向依赖 HTTP 路由；应用启动不修改数据库结构；外部平台草稿、发布和效果状态都以可回读证据为准。

## 2. 后端边界

`apps/api/app/api/router.py` 只负责组装路由。`apps/api/app/v1/routes.py` 保留行动闭环、复测、品牌事实和审计等尚未独立迁移的相邻流程，不再承载全部 V1 API。

| 领域 | 所有者 |
|---|---|
| 问题治理 | `question_routes.py` |
| 观测批次、任务与台账 | `observation_routes.py` |
| 工作区、浏览器账号与集成 | `workspace_routes.py` |
| 证据与四类洞察 | `insight_routes.py` |
| 内容、平台适配、草稿与发布记录 | `content_delivery_routes.py` |
| Agent 运行、事件与工件 | `agent_run_routes.py` |
| 通用工作区访问检查 | `route_support.py` |
| Provider 测试和观测业务逻辑 | `app/services/` |

公开 API 路径和请求响应结构保持兼容。服务层禁止导入 `routes` 或 `*_routes`，自动审计同时检查 Python 应用依赖图不存在循环。

## 3. 前端边界

- `src/lib/api-config.ts`：唯一的 API 地址来源。
- `src/lib/session-security.ts`：唯一的会话 Cookie 名称和安全属性来源。
- `src/lib/server-api.ts`：服务端鉴权请求、JSON 错误处理和 BFF 响应转发。
- `src/lib/cleanroom-v1-api.ts`：现代 GEO 的服务端类型化 API 门面。
- `src/lib/api.ts` 与 `app/actions.ts`：旧 `/projects`、`/admin` 流程的兼容门面；现代 `/geo` 页面不得新增依赖。
- 各 `/geo/[workspaceId]` 子目录：页面、交互组件和 Server Actions 就近放置。

优化行动工作台的纯 UI 与格式化逻辑已移到 `priority-actions-workbench-ui.tsx`，主组件只保留状态、请求和业务流程。Lint 以 0 warning 为门禁；受保护证据、动态平台素材和小型官方 Logo 明确保留原生 `<img>`，不经过会改变鉴权行为的 Next 图片代理。

## 4. 数据与外部副作用

- Alembic 是唯一数据库结构权威；启动仅检查迁移头，不自动建表或升级。
- 本地正式数据库不得被测试替换、初始化或清空。
- 零成本浏览器验收使用临时数据库和临时账号，不启动 Provider 付费采集。
- 办公平台连接、草稿回读、人工发布和 GEO 改善分别记录，不互相冒充。

## 5. 自动守护

`python3 scripts/acceptance_architecture_audit.py` 会阻止：

- pnpm 与 npm 锁文件并存；
- Python 应用依赖环或服务层反向依赖路由；
- Web API 地址、会话 Cookie 名称再次散落；
- 现代 GEO 页面重新依赖旧根级 Server Actions；
- 核心总路由、兼容门面和工作台组件重新无上限膨胀；
- 未锁定的 CI Action、容器镜像或不安全部署配置。

机器门禁是 `pnpm run verify`。它不替代 EgoLite 实际点击，也不替代用户对这份架构的最终验收。
