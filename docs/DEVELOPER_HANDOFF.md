# GEO 优化平台开发交接说明

## 项目状态

这是正式项目代码仓库。当前重点项目为项目 ID `1`，产品对象为“春秋元泉 Token 统一管控平台”。

当前已完成：

- 每周采集调度，不再按每小时执行。
- 25 个问题 × 每题 4 次，共 100 次真实大模型 API 回答采集。
- 任务级报告隔离，报告不会混入历史采集任务。
- GEO 评分、品牌提及/推荐统计和竞品分析。
- 报告 #6 的详细竞品分析说明文档，包括问题级样本、网页观测计划、网址线索核验和内容发布建议。

重要口径：API 模型回答不等于网页端真实搜索结果。网页端豆包、DeepSeek、Kimi、千问观测必须人工执行并保存截图后才能作为网页端证据。

## 安全边界

以下内容不会进入 Git 仓库：

- `.env` 和本地环境变量。
- `*.db`、`*.sqlite`、`*.sqlite3`，特别是可能含真实 Provider Token 的 `apps/api/geo_platform.db`。
- `outputs/`、虚拟环境、依赖目录、构建产物和本地工具。

仓库中只保留 `.env.example` / `.env.production.example`。接手人需要自行配置真实密钥，禁止在代码、Issue、提交记录或聊天中粘贴 Token。

## 本地恢复

环境要求：

- Node.js 与 pnpm。
- Python 3.12。
- `uv`。
- 本地开发可使用 SQLite；正式部署建议 PostgreSQL。

安装并启动：

```bash
pnpm install
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local
./scripts/start-local.sh
./scripts/check-local.sh
```

`start-local.sh` 会同时启动 Web、API 与队列 Worker。若拆开启动，必须另开一个终端执行：

```bash
pnpm run dev:worker
```

它会领取已入队的 `geo_observation.collect` 任务，并使用已配置的模型渠道实际采集
回答、来源和搜索证据。只运行 Web 与 API 时，任务会停在队列中而不会自行完成。

默认入口：

- Web：`http://localhost:3000`
- API：`http://127.0.0.1:8000`
- 项目 1：`http://localhost:3000/projects/1`

数据库不会随 GitHub 仓库分发。需要迁移真实状态时，项目负责人应通过受控渠道提供脱敏数据库或执行正式数据库迁移，不能把真实数据库提交到 GitHub。

## 验收命令

```bash
pnpm run check:api
pnpm run check:web
pnpm run build:web
pnpm run verify:local
```

完整验收：

```bash
pnpm run verify
```

## 关键代码位置

- API：`apps/api/app/`
- Web：`apps/web/app/`
- 数据模型：`apps/api/app/models/`
- 数据库迁移：`apps/api/migrations/versions/`
- 采集 Worker：`scripts/run_crawl_worker.py`
- 任务级报告：`apps/api/app/services/maturity_report.py`
- 竞品说明文档生成：`apps/api/scripts/build_project1_competitive_analysis.py`
- 当前真实使用状态：`docs/current-real-use-status.md`
- 迁移说明：`MIGRATION_HANDOFF_2026-07-13.md`

## 项目 1 当前数据口径

当前报告 #6 对应采集任务 #8：

- 100/100 次真实 API 回答成功。
- 25 个问题，每题 4 个样本。
- Mock 样本 0。
- 春秋元泉被提及 17 次、被推荐 1 次。
- 竞品推荐位共 23 次。
- 只有 3/100 条回答带网址线索；97/100 条无网址。
- 网址线索不能证明模型生成时真实检索过对应页面。

这些运行数据存在本地数据库中，不在 Git 仓库里。仓库中的说明文档和生成脚本用于解释逻辑与复现结构，不替代真实数据库备份。

## 下一步开发建议

1. 完成豆包、DeepSeek、Kimi、千问网页端观测与截图回填。
2. 为春秋元泉补齐官网产品能力、适用企业、部署方式、真实案例和对比页的一手资料。
3. 将网页观测和截图纳入报告评分，但继续与 API 回答分开统计。
4. 为每周 Worker 增加正式进程托管与失败告警。
5. 增加任务级报告和竞品说明文档的自动化测试。

## 协作约定

- 从 `main` 创建功能分支，使用 Pull Request 合并。
- 提交前至少运行 `pnpm run check:api` 和 `pnpm run check:web`。
- 不生成 Mock 或演示数据来替代正式项目验收。
- 所有“真实可用”结论必须由数据库、日志、API 或浏览器截图证明。
