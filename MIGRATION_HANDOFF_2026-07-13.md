# GEO 优化平台迁移交接说明

交接日期：2026-07-13  
工作区：`/Users/zangqing/Documents/Codex/2026-07-03/wo-x`

## 1. 结论先行

这是一个可以在本地运行的多智能体 GEO 优化平台 MVP，前端、后端、SQLite 数据库、数据持久化、管理员后台以及“采集 -> 成熟度报告 -> 撰稿 -> AI 审核 -> 人工审核 -> 投放计划”业务链路均已实现。

当前还不能把它描述为“已经完成国内四大模型网页端真实持续监测”。正式项目已有 6 条真实 API 模型回答样本，但豆包、DeepSeek、Kimi、千问网页端人工观测与截图存证均为 0。下一阶段最重要的工作不是继续增加演示页面，而是完成真实网页端采集存证、稳定持续任务执行，并提高稿件生成与审核的内容质量。

## 2. 技术栈与目录

- 前端：Next.js 15、React 19、TypeScript，目录 `apps/web/`。
- 后端：FastAPI、SQLAlchemy、Pydantic Settings，目录 `apps/api/`。
- 数据库：当前本地使用 SQLite，文件 `apps/api/geo_platform.db`；代码同时包含 PostgreSQL/生产环境配置基础。
- 数据迁移：Alembic，目录 `apps/api/alembic/`。
- 后台任务：数据库队列与定时采集 worker，入口 `scripts/run_crawl_worker.py`。
- 采集与报告：`apps/api/app/services/crawl_runner.py`、`maturity_report.py`。
- 撰稿与审核：`apps/api/app/services/article_workflow.py`、`review_rules.py`。
- API 路由：`apps/api/app/api/routes/`。
- 前端业务页：`apps/web/app/(app)/`。
- 真实网页观测采集包：`outputs/yuanquan_browser_observation_next_real_pack/`。
- 产品需求与历史进度：`outputs/geo_optimization_platform_prd.md`、`outputs/development_progress_2026-07-04.md`。
- 最新真实使用状态：`docs/current-real-use-status.md`。
- CodeGraph：根目录存在 `.codegraph/` 索引；本次交接时 `codegraph` CLI 不在 PATH，索引本身已保留。

## 3. 本地启动

环境建议：Node.js 20+、pnpm 11.9.0、Python 3.11+、uv。

```bash
pnpm install
uv sync --directory apps/api --group dev
./scripts/start-local.sh
./scripts/check-local.sh
```

也可以分别启动：

```bash
pnpm run dev:api
pnpm run dev:web
```

访问地址：

- 前端：`http://127.0.0.1:3000`
- 后端：`http://127.0.0.1:8000`
- 正式项目：`http://127.0.0.1:3000/projects/1`
- Provider 后台：`http://127.0.0.1:3000/admin/providers`

本地演示账号在历史交接文件 `outputs/GEO_PROJECT_HANDOFF_2026-07-06.md` 中。API 地址由 `apps/web/.env.example` 配置，注意 `localhost` 与 `127.0.0.1` 混用可能导致登录 Cookie 行为不同。

## 4. 当前正式项目数据库快照

正式项目：`#1 春秋元泉 GEO 优化 - 大模型 API 治理正式项目`

| 数据项 | 当前数量/状态 |
| --- | --- |
| 目标问题 | 15 |
| 核心关键词 | 10 |
| 采集结果 | 6 |
| 真实 API Provider | DeepSeek 3 条、火山方舟 3 条 |
| 网页端人工观测 | 0 |
| 网页端截图存证 | 0 |
| 引用信源记录 | 0 |
| 成熟度报告 | 2 |
| 稿件 | 21 |
| 稿件审核记录 | 20 |
| 投放记录 | 4 |

报告：

- `#1 春秋元泉 GEO 正式项目启动诊断 - 无 Mock 基线`，28 分，L2。
- `#2 春秋元泉 GEO 成熟度评估报告 - 真实 API 样本校正版`，24 分，L2。

这两份报告都不能作为“四大模型网页端真实搜索存证报告”对外发布。报告详情页已增加证据数量提示，避免把 API 样本和网页端观测混为一谈。

## 5. 四个智能体模块完成度

### 搜索采集智能体

已完成：

- Provider 管理、密钥配置、测试调用、就绪诊断。
- 支持 OpenAI-compatible、火山方舟、千问兼容、Mock、网页端人工观测 Provider。
- 支持目标问题和关键词采集、定时计划、任务日志、成本记录、失败信息。
- 支持导入真实网页端答案、信源 URL 和截图目录。
- 支持根据未覆盖问题/关键词动态生成下一轮采集包。

未完成：

- 没有内置可长期无人值守的豆包、DeepSeek、Kimi、千问网页自动化执行器。
- 正式项目尚未导入任何网页端真实观测或截图。
- API 调用不等于网页产品搜索；普通 DeepSeek/方舟模型接口未证明具备实时联网检索能力。
- 定时 worker 不是系统服务，当前没有确认其长期常驻。

### 撰稿智能体

已完成：

- 可从报告、目标问题和关键词生成稿件。
- 新版生成器为 `solution_article_agent_v2`。
- 正文与 GEO 运营清单已分离：正文仅放可发布内容；`source_context.geo_next_steps` 保存问题缺口、关键词缺口、信源与证据建议。
- 正式项目已生成 8 篇新版草稿，ID 为 15-22。

未完成：

- 当前生成逻辑仍以规则/模板组装为主，内容深度、产品事实引用和差异化表达不足。
- 需要接入真实 LLM 撰稿，并用企业白皮书、FAQ、产品介绍和真实搜索证据做受控上下文。
- 需要增加事实声明、出处、禁用词和品牌口径校验。

### 稿件审核打分智能体

已完成：

- AI 评分、维度分、问题与建议、风险表达、人工通过/退回、优化版生成。
- 管理后台可维护审核规则。
- 稿件详情页可区分正文、评分和 GEO 后续运营事项。

未完成：

- 当前规则对模板化稿件可能给出过高分，分数不能直接等同于可投放质量。
- 缺少事实核验、证据充分性、产品一致性、重复度和 AI 味检测。
- 旧稿件和旧审核记录较多，UI 应更明确地标注“已废弃/被新版替代”。

### 企业 GEO 成熟度研判

已完成：

- 可基于问题、关键词、多 Provider 回答生成成熟度分数、等级、摘要、维度项和建议。
- 报告区分真实 API 样本、网页端观测和截图证据数量。
- 可由网页端观测导入后自动生成报告、稿件和审核记录。

未完成：

- 正式项目样本量只有 6，且没有引用信源和网页端截图，客观性不足。
- 评分模型仍需通过更多真实样本校准，尤其是品牌提及、排名、引用质量、竞品占位和跨模型稳定性。
- 需要给报告增加逐样本证据回链、截图预览、采集时间、平台账号/模型版本等审计字段。

## 6. Provider 与调度状态

- `#8 DeepSeek GEO 采集`：active；已有样本，但最近调用受 DNS/网络影响失败。
- `#9 方舟 GLM-5.2 GEO 采集`：active；配置就绪，缺少近期成功实测记录。
- `#10 方舟 Doubao Seed 2.1 Pro GEO 采集`：active；曾有成功记录，是当前最可信的定时采集 Provider；最近一次任务因 DNS 失败。
- `#11 方舟 Kimi-K2 GEO 采集`：inactive。
- `#12 方舟 DeepSeek-V3.2 GEO 采集`：active；配置就绪，缺少近期成功实测记录。
- `#13 Mock GEO Search`：inactive，正式项目不得重新启用演示数据。
- `#14 千问兼容 GEO 采集`：inactive，缺少有效鉴权。
- `#15-18`：豆包、DeepSeek、Kimi、千问网页端观测 Provider，active，仅用于真实观测导入。

当前定时计划 `#1`：

- 名称：春秋元泉 GEO 每小时真实 API 小样本监测。
- 每小时执行一次。
- Provider：`[10]`。
- 问题：`[1, 2]`。
- 关键词：`[1]`。
- `next_run_at` 已过期，说明 worker 没有稳定常驻或任务没有继续推进。

持续运行命令：

```bash
pnpm run worker:crawl
pnpm run worker:geo-cycle
```

## 7. 当前稿件状态

旧的 `template_agent_v0` 稿件共 13 篇，均已标记为 `needs_revision`，不要继续作为正式稿投放。新版 `solution_article_agent_v2` 稿件共 8 篇，ID 15-22，状态为 `draft`。

特别注意：历史投放记录可能仍关联旧稿件，包括曾被审核通过的旧稿。后续应先清理/归档旧投放关系，再推进新版稿件人工审核。

## 8. 真实网页端采集入口

下一轮采集包：`outputs/yuanquan_browser_observation_next_real_pack/`

包含 8 个任务：豆包、DeepSeek、Kimi、千问各执行 1 个目标问题和 1 个关键词。关键文件：

- `work-order.md`：人工操作工单。
- `observations.json`：填写完整回答、摘要、信源。
- `raw-evidence/`：放截图或录屏。
- `inspect.sh`：检查缺失项。
- `dry-run.sh`：入库前验证。
- `import-and-generate.sh`：正式导入并生成报告、稿件和评分。

当前这些文件仍是待执行模板，不包含真实网页答案和截图。不要把模板文件当成已完成存证。

## 9. 关键验证命令

```bash
pnpm run check:api
pnpm run check:web
pnpm run build:web
pnpm run verify:local
pnpm run verify:browser-pack-gap
```

2026-07-13 交接前实测：

- `pnpm run check:api`：通过。
- `pnpm run check:web`：通过。
- `pnpm run build:web`：通过，Next.js 生产构建成功。
- `pnpm run verify:local`：未通过。默认参数仍指向已删除的项目 `#9`；改为 `--project-id 1` 后，验收套件中的临时 Mock Provider 被当前“正式采集禁止 Mock”规则拦截。失败流程产生的临时数据已由测试清理，正式项目计数未变化。接手后需要更新该验收套件，使用隔离测试数据库和与新策略兼容的 fake provider。
- `verify_import_browser_observation_evidence_dir_testclient.py`：通过，验证四平台观测、4 份截图、报告、稿件、评分和下一轮采集包闭环，临时数据已清理。
- `verify_browser_observation_pack_gap_selection_testclient.py`：通过，验证下一轮采集包会跳过已覆盖的平台-问题组合，临时数据已清理。

已建立的重点测试：

- `apps/api/scripts/verify_import_browser_observation_evidence_dir_testclient.py`
- `apps/api/scripts/verify_browser_observation_pack_gap_selection_testclient.py`
- `apps/api/scripts/verify_browser_observation_to_draft_loop_testclient.py`
- `apps/api/scripts/verify_article_source_context_testclient.py`
- `apps/api/scripts/verify_report_evidence_testclient.py`
- `apps/api/scripts/verify_local_acceptance_suite.py`

## 10. 后续事项优先级

### P0：让系统进入真实生产试用

1. 按采集包完成豆包、DeepSeek、Kimi、千问真实网页查询，保存完整答案、信源和截图并导入项目 1。
2. 生成第一份带网页观测和截图回链的正式报告，人工复核每个品牌提及和信源结论。
3. 修复/确认本机到 DeepSeek、火山方舟等域名的 DNS 与网络连通性，逐个 Provider 做最小成功调用。
4. 将 worker 作为 launchd、Docker Compose 或进程管理服务长期运行，补充心跳、失败重试和任务积压告警。
5. 用真实 LLM 和春秋元泉产品资料重做新版稿件，先完成 1-2 篇高质量稿件再批量生成。
6. 收紧审核标准，加入事实与证据检查，避免规则齐全但内容空泛的稿件获得 90+ 分。

### P1：提升日常运营效率

1. 增加截图文件的后端受控访问和前端预览，避免只保存本地 `file://` 路径。
2. 增加采集样本详情页：原回答、信源、品牌提及、竞品、截图、时间、模型版本可逐条审计。
3. 清理旧稿、旧审核和旧投放关系，增加 superseded/archived 状态。
4. 增加稿件编辑保存、版本对比、批注和人工审核操作日志。
5. 增加每平台/问题/关键词覆盖矩阵和下一轮采集建议。
6. 对 API 样本、联网搜索 API 和网页端观测使用不同标签与评分权重。

### P2：发布与规模化

1. 将 SQLite 迁移到 Supabase/PostgreSQL，文件证据迁移到对象存储。
2. 拆分 Web、API、worker 的云部署，并配置 HTTPS、CORS、环境变量和健康检查。
3. 对 Provider 密钥做 KMS/密文存储、权限分级、轮换和审计。
4. 增加多租户、配额、账单、部门归因和客户交付权限。
5. 完善合规、隐私、网页自动化使用条款和数据保留策略。

## 11. 已知风险

- `apps/api/geo_platform.db` 可能保存真实 Provider API 密钥。完整状态包属于敏感文件，只能在受控环境中迁移，不能上传到公开仓库或公开文件分享服务。
- API Key 曾在协作会话中明文提供；正式上线前建议全部轮换。
- 当前目录不是 Git 仓库，没有可供回滚的提交历史。接手后第一件工程事项应是初始化私有 Git 仓库并做基线提交。
- 本地 `node_modules`、`.venv`、`.next` 属于可重建依赖/缓存，迁移包默认排除；版本由 `pnpm-lock.yaml` 和 `apps/api/uv.lock` 锁定。
- `.codegraph/` 已打包，但新环境需重新安装 `codegraph` CLI 或重新建立索引。

## 12. 建议下一个模型的第一轮工作

1. 解压完整状态包并阅读本文件与 `docs/current-real-use-status.md`。
2. 运行依赖安装、`pnpm run check:api`、`pnpm run check:web` 和 `pnpm run verify:local`。
3. 只把项目 1 当作正式项目，禁止创建 Mock/演示采集结果。
4. 检查 Provider 网络连通和 worker 状态，但不要在未确认成本范围时批量调用 API。
5. 完成首轮 8 条真实网页观测与截图导入，形成第一份真正可审计报告。
6. 从新版稿件 #15 开始人工复核，始终保持“正文”和“GEO 后续运营清单”分离。
