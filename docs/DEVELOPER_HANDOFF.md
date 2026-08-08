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

## 2026-08-08 · Codex Agent 优先行动闭环

- P0 已使用本机 Codex SDK 生成真实母稿、Claim 清单和知乎/公众号平台稿。
- P1 已增加内容审核包、逐条事实确认、逐平台批准、浏览器文章同步助手触发与客户端结果归档。
- 同步门禁：未审核的资产或平台稿无法建立同步任务。浏览器同步助手返回符合平台域名的 URL 后只记为 `draft_link_returned / awaiting_human_confirmation`；用户打开草稿并确认正文可见后，才升级为 `draft_saved`并开放发布结果归档。
- 文章同步使用当前浏览器扩展的 `$syncer`，逐平台传入已审核的差异稿；不使用行动摘要代替正文。
- 人工退回后可以沿用原 Codex thread 和已持久化的修改意见生成下一版；旧版标记为历史版本，不允许绕过修订直接改为通过。
- 工作区级内容库位于 `/geo/{workspaceId}/content`，可按审核状态和平台筛选，展开母稿/平台稿，并只在有真实回读时显示草稿链接。
- 内容库由后端返回 `is_latest_version / latest_version_id / latest_version_number`：同一 brief 的旧稿即使因历史 worker 未回写 `superseded`，也只显示为“历史版本”，不再占用“待修订”数量或呈现后续执行步骤。历史筛选和替代版本号保留完整追溯。
- 内容库与审核工作台共用安全 Markdown 阅读器：原始 HTML 一律转义，只允许 `http/https` 链接，并将标题、列表、表格、引用和代码呈现为可读正文。内容库详情使用自然页面流动，不在正文区域增加独立滚动，也不再用卡片套卡片展示母稿和平台稿。
- 最新内容版本的母稿和各平台稿可在内容库直接复制 Markdown 或下载 `.md`；导出由浏览器本地完成，不修改审核、同步或发布状态。历史版本不显示任何交付按钮，只保留正文和退回意见用于追溯。
- 官网稿不走文章同步助手：人工审核通过后，用户显式建立 `manual-website.v1` 交付记录，目标状态为 `handoff_ready / not_required / awaiting_publish`。这表示稿件已交给网站负责人，不表示已上线；内容库单独显示“官网待上线”。
- 网站负责人部署后才能回填同域 HTTPS URL。官网允许记录工作区配置的根页面，外部平台仍必须记录具体文章页；错误域名会被后端拒绝。真实 URL 归档后行动才进入 `ready_for_retest`，且 `final_action_clicked` 始终为 `false`。
- 任何同步结果都保持 `final_action_clicked=false`；最终发布仍由人工完成。P2 已支持人工确认后归档公开 URL，并以原行动的问题、模型和重复次数创建可比复测，输出 `improved / unchanged / regressed / insufficient_evidence`。
- 审核工作台使用固定标题、版本标签和底部决策区，长母稿与事实清单在中间区域滚动；底部持续显示待判断事实与选中平台数量，避免禁用按钮没有原因。移动端关键审核控件保持至少 44px。
- 平台稿不再默认勾选通过：审核员必须先打开具体平台稿，才能勾选该版本。批准 API 同时要求 `platform_keys` 必须是 `reviewed_platform_keys` 的子集，并将已查看平台和 `reviewed_before_approval` 写入审核记录，避免前端绕过人工阅读。
- 审核包同时返回工作区“当前可用”与稿件“实际引用”的带来源品牌事实数。如果事实库已有可追溯事实，而旧稿一条都没有使用，前端显示过时快照提示并禁止通过，审核 API 也返回 `409`；仍可退回并沿用原 Agent thread 生成新版本。
- 审核包进一步区分“活跃但未完成原文核验”与“已完成原文核验”的品牌事实，并返回稿件匹配的未核验事实数。“有来源 URL”不再被等同于“事实已核验”；行动摘要会把这类稿件计入需重新生成，内容库显示独立的“事实待核验”状态，审核与交付继续被阻止。
- 审核警告会直达设置页 `#brand-facts` 事实区。待核验记录可按一次启动串行核验，但每条仍单独调用后端公网与原文核验并写入独立审计记录；界面显示当前事实、完成数、通过/失败数，部分失败不回滚成功结果，也不会提前冒充完成。
- 审核弹窗为可选品牌事实警告保留独立网格行，避免警告出现时挤占正文滚动区。`390×844` 应用内真实浏览器验收中，警告、正文和底部决策区边界连续且无重叠，关闭、平台稿查看与底部决策控件高度均为 44px。
- 无来源主张不再强迫审核员全部“确认属实”。每条必须二选一：`human_confirmed` 表示人工明确背书，`explicitly_unverified` 表示所选稿件将其保留为未知或未采用；两类决策都会写入审核记录，未作决定仍禁止通过。`explicitly_unverified` 不能计入可追溯品牌事实。
- 同步助手显示“连接助手 → 确认平台 → 写入并回读”三段真实状态，不使用虚构百分比；标题与底部人工确认区固定，账号列表在中间区域自然滚动，关键控件保持至少 44px。草稿链接返回只进入“等待打开确认”；未经人工确认正文可见仍不计为已保存。
- 官方文章同步助手页面桥接层只有一个全局 `currentSyncId`，因此平台差异稿必须顺序写入，禁止并发调用多个 `addTask`。每个平台结束后立即把草稿 URL/外部 ID 回读到同一个 distribution run；一个成功、一个失败时保留成功结果并显示 `partial`，重试只处理未成功平台且复用原 run。
- 常规草稿交付以 EgoLite 当前页面注入的 `$syncer` 为准，不依赖设置页保存的 MCP Server 路径。设置页“检测当前页面”会真实调用 `getAccounts`，只把 Wechatsync 官方平台 ID `zhihu`、`juejin`、`csdn`、`51cto`、`weixin`/微信账号计为可写入平台；`zip-download` 等工具能力不能冒充目标平台。后台 MCP 路径和 Token 仅保留在折叠的高级诊断区，已配置不等于当前浏览器可交付。
- 优先行动现已具备知乎、掘金、CSDN、51CTO 的平台契约、独立稿件审核、浏览器同步映射和公开 URL 归档校验；新任务默认选择知乎与掘金，仍可人工改选。Agent 结果必须为每个目标平台返回公开规则来源、限制和独立平台稿，否则整次运行失败且不会进入人工审核。四个平台“真实草稿写入 + 页面回读”仍需在对应 EgoLite 登录账号中逐一验收，代码支持本身不能标记 Phase 3 完成。
- 同一内容资产的外部平台分发只维护一个可扩展的 distribution run。首次仅登录一个平台时，任务仍包含全部已审核目标并显示例如 `1/2 已回读、1 个待写入`；后续登录另一个平台会扩展/复用原任务，不新建一个让前次草稿从内容库汇总中消失的孤立任务。
- 同步账号使用 `type + uid` 作为界面稳定键；同一平台若出现多个账号只能选择一个，避免重复平台结果被后端拒绝。平台列表显示真实 Logo 和逐账号 `uploading / done / failed` 状态；所有目标已回读后入口改为“草稿已写入”并禁用重复同步。
- 发布 URL 在真实复测建立前允许更正；一旦 `retest_batch_id` 已生成即锁定，避免复测快照与后改发布记录发生漂移。重复提交同一 URL 保持幂等。
- Agent 产品化门禁已实装：默认每工作区同时只运行 1 个任务，单次最长 15 分钟；容量已满时 API 拒绝第二个 run，页面显示真实容量和超时上限。排队中取消会立即释放容量；worker 交接竞态也会落为 `cancelled`，不留在虚假运行态。
- SDK turn 超时会调用真实 `interrupt`，持久化为 `failed / timed_out / agent_timeout`，并保留原 Codex thread 恢复入口。尚未建立 thread 的取消/失败任务在界面显示“重新启动”，不再卡在无操作的终止态。
- `GET /api/v1/workspaces/{workspaceId}/agent-runs/{runId}/progress` 统一从持久化事件计算五阶段状态、确定性百分比、耗时和超时余量；前端不再自行猜测阶段。该接口仅返回工件类型、大小和哈希，不暴露 `private_artifacts` 本机路径或元数据。
- `GET /api/v1/workspaces/{workspaceId}/action-workbench-state` 一次返回已持久化的 Agent 运行、审核包、分发任务和已建立复测。优先行动首屏不再对每个行动逐一请求 Agent 与不存在的复测，空复测以空列表表示，不制造 404 错误流量。
- 优先行动右栏已显示五阶段、真实耗时、事件连接/数据库回读状态和持久化结果。执行记录按时间排序；连续重复的公开检索事件在界面合并计数以避免页面过长，原始事件仍完整保留。SSE 不再因每条新事件重新连接，并识别 `run_timed_out` 终态。
- 行动摘要与机会卡使用同一筛选范围的“未闭环机会”口径：已选择但尚未完成可比复测的机会仍计入，卡片显示“行动进行中”而非重复显示待选择。可比复测得出 `improved / unchanged / regressed` 后，关联机会才转为 `completed` 并移出默认列表；`insufficient_evidence` 不完成机会。模型键 `qianwen` 必须映射到通义千问真实 Logo，不使用“AI”占位。
- 行动机会发现已移到后端持久化服务。页面通过真实完成批次、模型和问题筛选；只有完整回答、真实搜索事件、来源 URL 和原始工件同时存在的观测才具备行动资格。切换范围时旧机会不继续显示，已选行动不会被后续刷新误标为过期。
- 回归测试：`tests/test_priority_action_review_sync.py`覆盖 Claim 门禁、逐平台审批、草稿回读、退回意见传入、v2 生成、工作区容量、排队取消竞态、超时落库、进度聚合、私有路径隔离和禁止冒充发布；`tests/test_codex_agent_runtime.py`覆盖 watchdog 真实中断与正常完成后解除超时。
- 回归测试：`tests/test_priority_action_retest.py`覆盖公开 URL 归档、可比复测、结论和证据回链；`tests/test_action_opportunity_scope.py`覆盖真实证据门槛、模型范围与已选机会保留。

## 2026-08-08 · 竞品范围报告持久化

- `POST /api/v1/workspaces/{workspaceId}/competitor-insights` 仍只使用当前筛选范围内的真实 Provider 证据生成 DeepSeek 分析，但成功结果现在会追加写入 `geo_competitor_insight_snapshots_v1`；报告快照是派生分析，绝不计入观测批次、任务、证据或 GEO 指标。
- `GET /api/v1/workspaces/{workspaceId}/competitor-insights` 按账号、工作区、时间范围、模型、问题和证据上限恢复最近一份精确范围报告。同公司不同账号也不会互相读取报告。
- 每个快照保存范围指纹、输入指纹、全部输入证据 ID 和模型实际引用的证据 ID。当前证据、问题文案、品牌目录或匹配规则变化后，旧报告仍可审计，但 API 返回 `is_stale=true`，界面明确提示重新生成，不把旧结论伪装成当前结论。
- 浏览器 `sessionStorage` 只作为首屏缓存；后端快照是恢复依据。完整报告可从新标签页直接打开，并显示账号报告编号、生成范围、真实回答数、证据回链和“不计入 GEO 观测指标”的边界。
- 完整报告正文改为随页面自然向下流动，不再在正文区域建立独立滚动条。读取、生成、恢复失败和数据过期均有独立的真实状态与重试入口，并支持 `prefers-reduced-motion`。
- 迁移：`20260808_0023_competitor_insight_snapshots.py`。回归测试：`tests/test_competitor_insight_snapshot.py` 覆盖持久化、不污染观测、跨账号隔离和输入变化过期判定。
- 本机真实验收生成账号报告 `#1`：输入 187 条真实证据，模型引用 5 条证据；从全新标签页恢复成功。该数据只存在本地数据库，不进入 Git。

## 2026-08-08 · 官网可引用性审计

- 优先行动页已增加“官网可引用性”真实检查，明确区分 HTTP 可访问与原始 HTML 可直接读取，不会把 JavaScript 外壳当作已有产品正文。
- `POST /api/v1/workspaces/{workspaceId}/website-audits` 只检查工作区已配置的官网；限制 `http/https` 与 80/443 端口，每次重定向都重新校验公网 IP，拒绝私有网络目标。
- 每次检查持久化首页、`robots.txt` 与 `sitemap.xml` 的原始响应、SHA-256、大小和截断状态；对外 API 只返回工件清单和哈希，不返回原始文档。
- 存储表为 `geo_website_audits_v1`，迁移版本 `20260808_0022`；最新结果通过 `GET /api/v1/workspaces/{workspaceId}/website-audits/latest` 回读。
- 页面的等待态不显示虚假百分比，检查完成前不显示绿色结果；结果仅表示页面抓取与引用基础，不计入模型出现率。
- 每次审计完成后，`materialize_website_opportunity` 按问题码集合确定性创建或更新 `website_citation_readiness` 机会；相同问题不重复堆积，问题消失会把仍开放的旧机会标为 `stale`。
- 机会通过 `scope_snapshot` 引用审计 ID、原始 HTML SHA-256、工件清单和发现项，不向 `geo_evidence_v1` 填造模型证据。
- 选择后可进入本机 Codex，但目标锁定为 `official_site`；上下文包含受限长度的原始 HTML 片段与明确解释边界。
- 官网稿通过人工审核后只进入内容库和网站负责人交付，不启用文章同步助手，也不自动显示为已上线。
- 真实运行 `Action #6 / Run #2 / 内容资产 #2` 已完成：5 次公开搜索、9 条主张（7 条有来源、2 条待人工确认），耗时 4 分 16 秒。由于当时品牌事实库为 0，产出被识别为通用整改框架，未审核、未同步、未发布。
- 设置页已增加“04 · Agent 事实底座”：品牌事实需要名称、可公开陈述和公开 `http/https` 来源，可停用/恢复但不删除历史；Token 与密钥仍不回显。
- 若官网审计包含 `client_rendering_required`、`server_visible_content_missing` 或 `server_visible_content_too_short`，启动 Agent 前必须有启用且带来源的品牌事实；官网原始 HTML 已有完整产品正文时不额外阻塞。
- Agent 结果快照保存使用过的品牌事实 ID、带来源事实 ID 和数量。历史整改框架在审核工作台显示明确警告，前端批准按钮与后端审核 API 双重拒绝批准；刷新行动页默认恢复最新 Action。
- 真实修订 `Action #6 / Run #2 / 内容资产 #3 v2` 已完成：第 2 轮耗时 3 分 33 秒，使用 3 条官网来源品牌事实，生成 1 个官网版本、11 条主张（10 条有来源、1 条待人工确认）。当前保持 `awaiting_review`，尚未批准、交付或发布。
- 恢复和修订沿用同一个 run 时，进度接口按最新 `run_queued / resume_queued / revision_queued` 边界计算本轮耗时、事件与工件；界面同时显示轮次、本轮事件数和累计事件数，不再把首轮耗时或旧工件冒充为当前轮结果。
- 官网审核门禁以内容资产内实际引用的启用品牌事实为准：Claim 需要匹配事实 ID，或同时匹配事实正文与来源 URL。单独修改 Agent 结果快照不能绕过门禁；后续新稿会把匹配的 Claim 持久化为 `support_type=brand_fact` 并保存 `support_id`。
- `tests/test_website_audit.py` 覆盖事实缺失门禁、无效来源 URL、停用/恢复、审批拒绝和有来源后允许通过。

## 2026-08-08 · 运营状态真实性

- `/geo/{workspaceId}/operations` 与决策地图的模型选择器统一使用 `collection_ready` 作为“可发起观测”口径；旧测试早于当前渠道配置时必须显示“需要重新测试”，不能继续记为可用。
- 运营状态页展示最近 5 个持久化真实观测批次，数字直接来自批次 API，不由前端推算；每行显示任务矩阵、成功/失败数和确定性完成进度。
- 点击批次行进入现有任务矩阵，可继续查看逐任务状态、失败原因和成功证据；“查看全部批次”进入完整分页归档。
- 核心 readiness 或批次接口失败时页面不会用空数据伪装正常状态；等待、运行、成功、部分失败和失败使用后端真实状态。
- 批次 API、决策地图和优先行动统一使用 `geo_observation_batches_v1.id`；`queue_jobs.id` 仅是内部执行凭据，不再作为产品批次号。历史列表因此也包含没有现存队列父任务的已迁移真实批次。
- 批次详情从 `geo_observation_tasks_v1` 聚合模型、问题、状态、错误与证据；GET 请求不再反向修改队列或台账状态。
