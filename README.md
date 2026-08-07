# GEO Optimization Platform

多智能体协同的企业 GEO 优化服务系统，当前已推进到可本地使用的 MVP 闭环。

> 同事接手开发请先阅读 [`docs/DEVELOPER_HANDOFF.md`](docs/DEVELOPER_HANDOFF.md)、[`MIGRATION_HANDOFF_2026-07-13.md`](MIGRATION_HANDOFF_2026-07-13.md) 和 [`docs/current-real-use-status.md`](docs/current-real-use-status.md)。真实数据库、Provider Token 和网页端登录态不会进入 Git 仓库。

## 当前能力

- 搜索采集：支持 Mock、OpenAI-compatible、火山方舟等 Provider，支持目标问题和关键词多语境采集。
- 真实模型接入：Provider 管理、测试调用、采集前置检查、真实/Mock 样本区分。
- 成熟度报告：生成企业 GEO 成熟度报告，包含样本可信度、真实 API 样本、关键词语境覆盖、交付就绪度。
- 撰稿智能体：可从报告缺口和推荐选题生成稿件。
- 稿件审核：AI 审核评分、人工通过/退回、优化版生成。
- 投放与复盘：稿件进入投放计划、发布、投放复盘、下一轮优化目标。
- 客户交付：交付包、公开分享链接、客户确认。
- 管理后台：Provider、队列、告警、用量、审核标准、报告模板、用户管理。

## 快速启动

推荐一条命令同时启动 API 和 Web：

```bash
./scripts/start-local.sh
```

启动后检查本地服务是否真的可访问：

```bash
./scripts/check-local.sh
```

如果需要分开启动：

API:

```bash
pnpm run dev:api
```

Web:

```bash
pnpm run dev:web
```

打开：

```text
http://127.0.0.1:3000
```

常用入口：

```text
http://127.0.0.1:3000/admin/providers
http://127.0.0.1:3000/projects
```

演示账号见 `outputs/GEO_PROJECT_HANDOFF_2026-07-06.md`。

默认前端 API 地址来自 `apps/web/.env.example`：

```text
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

## 本地验收

完整本地验收：

```bash
pnpm run verify
```

分步验收：

```bash
pnpm run check:api
pnpm run check:web
pnpm run build:web
pnpm run verify:local
```

`verify:local` 不绑定本地端口，适合在 Codex 沙箱或端口受限环境中验证后端业务闭环。

## 真实模型小样本

在本机网络和 API Key 可用时，先跑 dry-run 看调用范围：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/run_real_provider_smoke.py --project-id 9 --provider-ids 9,12 --question-limit 1 --keyword-limit 0 --dry-run
```

确认后去掉 `--dry-run` 执行一次真实小样本。输出会写入：

```text
outputs/latest_real_provider_smoke.json
```

如果失败，先看 `/admin/providers` 的采集就绪状态和最近任务错误。

## 重要文件

- PRD: `outputs/geo_optimization_platform_prd.md`
- 开发进度: `outputs/development_progress_2026-07-04.md`
- 交接说明: `outputs/GEO_PROJECT_HANDOFF_2026-07-06.md`
- 最新验收快照: `outputs/latest_local_acceptance_suite.json`
- 脱敏交接数据库: `outputs/geo_platform.sanitized.db`
- 脱敏交接包: `outputs/geo-platform-handoff-2026-07-06.tar.gz`

## 安全提醒

`apps/api/geo_platform.db` 可能包含真实 Provider API Key，不能外发。

对外交接时使用：

```text
outputs/geo_platform.sanitized.db
outputs/geo-platform-handoff-2026-07-06.tar.gz
```

交接包会排除 live DB、虚拟环境、构建产物和依赖目录。
