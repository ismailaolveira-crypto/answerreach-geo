# 本地真实使用说明

更新日期：2026-07-09

## 当前状态

这套 GEO 平台当前已经切到春秋元泉正式项目数据，不再使用演示采集结果。

已存在的真实项目：

- 公司：春秋元泉
- 项目 ID：1
- 项目名称：春秋元泉 GEO 优化 - 大模型 API 治理正式项目
- 目标问题：15 个
- 核心关键词：10 个
- 产品资料资产：5 份
- 稿件草稿：10 篇
- 稿件评分：11 条
- 真实成功采集结果：6 条
- 成熟度报告：2 份
- 最新校正版成熟度：24 分，L2 偶发可见
- 当前失败采集任务：3 个，均为网络/DNS 或模型访问失败记录，未导入为有效回答
- 当前每小时监测计划：1 个 active，小样本计划只使用方舟 Doubao Seed 2.1 Pro（Provider #10），覆盖目标问题 #1、#2、#4

说明：数据库里没有“春秋元泉被真实提及”的假采集结果。之前的演示结果已经清空；新失败采集会记录为 failed task，不会继续生成报告或稿件。

## 本地登录账号

本地管理员账号：

- 邮箱：`geo-demo-e2e@example.com`
- 密码：`geo-demo-123`

这是本机开发用账号。后续上线或共享前请更换。

## 启动方式

由于当前 Codex 沙箱不允许绑定本地端口，需在普通终端里启动服务。

在项目根目录执行：

```bash
cd /Users/zangqing/Documents/Codex/2026-07-03/wo-x
pnpm run dev:api
```

再打开第二个终端执行：

```bash
cd /Users/zangqing/Documents/Codex/2026-07-03/wo-x
pnpm run dev:web
```

如果要让每小时监测计划自动推进，再打开第三个终端执行：

```bash
cd /Users/zangqing/Documents/Codex/2026-07-03/wo-x
pnpm run worker:crawl
```

如果希望“采集成功后自动生成成熟度报告，并生成 1 篇待审核稿件”，第三个终端改为：

```bash
cd /Users/zangqing/Documents/Codex/2026-07-03/wo-x
pnpm run worker:geo-cycle
```

只检查一次到期计划和队列任务，不常驻运行：

```bash
pnpm run worker:crawl:once
pnpm run worker:geo-cycle:once
```

说明：`pnpm run dev:api` 使用稳定单进程模式，适合真实使用。开发热重载模式保留为：

```bash
pnpm run dev:api:reload
```

如果页面出现 `database is locked`、8000 端口显示占用但访问不通，优先在后端终端按 `Ctrl+C` 停掉旧服务，再重新运行 `pnpm run dev:api`。不要在真实使用时长期使用 reload 模式跑 SQLite。

然后访问：

```text
http://127.0.0.1:3000/projects/1
```

后端健康检查：

```text
http://127.0.0.1:8000/api/health
```

## 已通过检查

以下检查已在 Codex 内完成：

- 后端 ruff 检查通过。
- 前端 TypeScript 检查通过。
- 前端生产构建通过。
- 后端 TestClient 登录通过。
- 项目列表、项目详情、MVP 状态、运营趋势、Provider 列表、Provider 诊断、搜索指标接口均返回 200。

## 真实模型调用状态

方舟/DeepSeek 域名在系统 `curl` 层面可访问：

- `https://ark.cn-beijing.volces.com/api/v3` 返回 401，说明 DNS 和网络可达，只是未带认证头。
- `https://api.deepseek.com` 返回 401，说明 DNS 和网络可达，只是未带认证头。

但 Codex 沙箱内的进程当前可能无法解析这些域名，所以在 Codex 中直接跑真实 Provider 测试或真实采集会失败：

```text
[Errno 8] nodename nor servname provided, or not known
curl: (6) Could not resolve host: api.deepseek.com
```

这属于 Codex 沙箱网络限制，不代表产品代码或 API Key 一定不可用。请在普通终端启动后端后，在页面后台的 Provider 测试页重新测试真实模型，或在普通终端运行真实采集脚本。

## 推荐下一步

1. 用普通终端启动前后端。
2. 登录本地管理员账号。
3. 打开 `/admin/providers`。
4. 对方舟 DeepSeek-V3.2、Doubao Seed 2.1 Pro、GLM-5.2 各跑一次 Provider 测试。
5. 补千问 Key：`QWEN_API_KEY` 或 `DASHSCOPE_API_KEY`，现有千问 Provider 已标记 `enable_search=true`，补 Key 后先测试再激活。
6. Kimi 有两条路线：若继续走火山方舟，需要在方舟控制台确认 Kimi-K2 的真实 endpoint/model id；若走 Moonshot 原生 API，则创建 `Kimi Web Search` Provider，Base URL 用 `https://api.moonshot.cn/v1`。
7. 测试通过后，再在项目 1 启动小批量采集：先 1 个问题、1 个 Provider。
8. 有真实采集结果后，再生成成熟度报告和优化建议。

## 真实采集脚本

自然 GEO 监测采集不要在 prompt 里主动写入“春秋元泉”，否则会污染自然提及率。当前脚本默认只使用 active 且非 mock 的真实 Provider。

默认安全策略：

- 后端任务和 curl 采集在未手动指定 Provider 时，只选择最近一次测试成功的真实 Provider。
- 若要排障 DeepSeek/Kimi/千问等失败渠道，需要显式传 `PROVIDER_IDS=...` 或使用 `probe:providers`。
- 这样持续监测不会因为一个未测试或失败 Provider 把整轮任务拖成失败。

项目页已有一个 active 的每小时小样本监测计划：

- 名称：`春秋元泉 GEO 每小时真实模型监测（小样本）`
- 频率：每 1 小时
- Provider：#10 方舟 Doubao Seed 2.1 Pro
- 问题范围：#1、#2、#4
- 下次执行：以页面 `/projects/1#crawl-schedules` 展示为准

后台已加安全默认值：如果创建定时计划时没有手动选择 Provider，系统只会默认选择最近测试成功的真实 Provider，不会把所有 active 渠道都加入持续监测。

持续监测 worker 会做两件事：

1. 检查 active 且到期的采集计划，创建采集任务并入队。
2. 执行 ready 队列任务，把真实模型结果写入采集结果和用量记录。

闭环 worker `worker:geo-cycle` 会在本轮有成功采集任务时继续生成成熟度报告，并按 `--draft-count` 生成和评分稿件。默认命令生成 1 篇。

如果没有到期计划，`worker:crawl:once` 和 `worker:geo-cycle:once` 会输出空的 `created_task_ids`、`ran_job_ids`、`post_collection`，不会触发 API 调用，也不会生成报告或稿件。

只采集并保存原始响应：

```bash
cd /Users/zangqing/Documents/Codex/2026-07-03/wo-x
QUESTION_IDS=1,2,4 bash scripts/collect_real_answers_curl.sh
```

排障失败渠道时显式指定 Provider，并允许包含未就绪渠道：

```bash
READY_ONLY=0 PROVIDER_IDS=8 QUESTION_IDS=1 bash scripts/collect_real_answers_curl.sh
```

批量恢复探针：只写 Provider 测试记录、用量和告警，不会生成采集结果、报告或稿件。

```bash
pnpm run probe:providers -- --project-id 1 --provider-ids 8,9,12
```

如果探针成功，相关 Provider 会拥有最新成功测试记录，后续可手动加入小样本采集；如果失败，输出和 `outputs/latest_real_provider_probe.json` 会给出 HTTP 错误、模型不存在、缺 key 等原因。

在跑 API 探针之前，可以先做不带 API Key 的网络预检：

```bash
pnpm run check:provider-network -- --provider-ids 8,9,10,11,12,14
```

该命令只做 DNS、TCP、TLS 检查，不调用 `/chat/completions`，不会使用 API Key。若这里失败，说明当前环境连 Provider 域名都访问不了，先不要用探针结果判断 key/model 是否错误。

对 inactive 渠道做恢复探针时，不需要先把坏渠道激活：

```bash
pnpm run probe:providers -- --project-id 1 --provider-ids 11 --allow-inactive
```

确认探针成功后，可以让脚本自动激活该 Provider：

```bash
pnpm run probe:providers -- --project-id 1 --provider-ids 11 --allow-inactive --activate-on-success
```

探针失败只会写入 `last_probe_error`，不会覆盖 `last_blocker` 里的配置类原因；探针成功会清理历史 blocker。

当前会话已验证：

- `pnpm run probe:providers -- --project-id 1 --provider-ids 11,14` 可以正确写入 Kimi/千问 blocker，不会生成采集结果。
- `pnpm run probe:providers -- --project-id 1 --provider-ids 11,14 --allow-inactive` 可用于 inactive 渠道恢复探测；千问会明确提示缺 `QWEN_API_KEY 或 DASHSCOPE_API_KEY`。
- `pnpm run probe:providers -- --project-id 1 --provider-ids 8` 目前失败于本地环境 DNS：`[Errno 8] nodename nor servname provided, or not known`。
- `pnpm run check:provider-network -- --provider-ids 8,9,10,11,12,14` 当前所有 Provider 域名均失败在 DNS 阶段，说明本会话网络环境不适合继续判断真实 API 权限。
- 当前 Codex 提权审批仍打到不支持的 `codex-auto-review`，无法在本会话中重跑外网探针；换到可出网终端后直接重跑上面的 DeepSeek 命令即可。
- 默认就绪 Provider 查询当前只返回 #10，因此普通持续采集只会使用豆包方舟，不会被 DeepSeek/Kimi/千问失败状态拖垮。

导入一次采集结果：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python ../../scripts/import_real_collection.py \
  --project-id 1 \
  --collection-dir ../../outputs/real_collection/<采集目录>
```

跑一轮“真实采集 -> 入库 -> 成熟度报告 -> 生成稿件 -> AI 评分 -> 待人工审核投放计划”：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python ../../scripts/run_real_geo_cycle.py \
  --project-id 1 \
  --question-ids 1,2,4 \
  --draft-count 3
```

脚本默认每次创建新的 `outputs/real_collection/cycle-YYYYMMDD-HHMMSS` 目录。若本轮没有任何 HTTP 200 的真实回答，脚本会返回：

```json
{
  "status": "failed",
  "report_id": null,
  "drafts": []
}
```

这表示采集失败已被记录，但不会污染成熟度报告、稿件或投放计划。

## Provider 状态

- DeepSeek：已配置，active。
- 方舟 GLM-5.2：已配置，active。
- 方舟 Doubao Seed 2.1 Pro：已配置，active。
- 方舟 DeepSeek-V3.2：已配置，active。
- 方舟 Kimi-K2：已配置 key，但当前模型 ID `kimi-k2-250905` 返回 `InvalidEndpointOrModel.NotFound`，已标记 inactive；需要在方舟控制台确认真实 endpoint/model id 后再激活。
- Kimi Web Search：后台模板已更新为 Moonshot 原生 API，默认 Base URL `https://api.moonshot.cn/v1`，模型示例 `kimi-k2.7-code`、`kimi-k2.6`。需要单独 Kimi/Moonshot API Key。
- 千问兼容：已创建 inactive 占位，缺少 DashScope compatible-mode key；已设置 `enable_search=true`，补 `QWEN_API_KEY` 或 `DASHSCOPE_API_KEY` 后可按联网搜索意图测试。
- Mock Provider：inactive，不应参与真实项目采集。

说明：

- 火山方舟、DeepSeek 和普通 OpenAI-compatible Chat Completions 只能证明模型 API 可用，不等价于网页端 AI 搜索。
- Kimi Web Search 和启用 `enable_search` 的千问兼容渠道更接近“联网搜索结果采集”。
- 豆包网页搜索若不能通过方舟应用/Bot 联网插件复现，就需要另做浏览器网页端观测 Provider，并保存截图证据。

## 当前正式项目运营就绪度

项目 1 当前状态以接口 `/api/projects/1/operational-readiness` 为准。该接口专门用于判断春秋元泉项目是否已经达到真实可持续运营，而不是只看演示链路。

最新本地 TestClient 验证结果：

- 状态：`partial`
- 说明：核心闭环可用，但多平台和人工投放闭环仍需补齐
- 已满足：`6/8`
- 已通过人工审核稿件：`1` 篇，稿件 #9 `Token统一管控平台选型指南` 已由系统管理员确认通过
- 最新新增待审稿件：稿件 #11 `如何给不同团队分配独立的 AI 调用配额？`，AI 评分 97 分，等待人工审核、入库和投放承接
- 已绑定投放承接：`1` 篇，稿件 #9 已创建 planned 投放 #4，目标为官网 FAQ / 解决方案页
- 剩余红项：多模型真实采集、网页观测留证

四个平台当前事实：

- 豆包/火山方舟：已就绪，有项目结果 3 条。
- DeepSeek：active 且有历史项目结果 3 条，但最近测试/导入失败，需重新跑通一次 HTTP 200 后恢复为就绪。
- Kimi：当前方舟 Kimi-K2 Provider inactive，模型 ID 需要在方舟或 Moonshot 控制台确认。
- 千问：Provider 已占位并开启 `enable_search`，但缺 `QWEN_API_KEY` 或 `DASHSCOPE_API_KEY`，未激活。

快速自检：

```bash
cd /Users/zangqing/Documents/Codex/2026-07-03/wo-x
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python -c 'import json; from fastapi.testclient import TestClient; from app.main import app; client=TestClient(app); token=client.post("/api/auth/login", json={"email":"geo-demo-e2e@example.com","password":"geo-demo-123"}).json()["access_token"]; res=client.get("/api/projects/1/operational-readiness", headers={"Authorization":f"Bearer {token}"}); res.raise_for_status(); print(json.dumps(res.json(), ensure_ascii=False, indent=2))'
```

项目页 `/projects/1` 顶部会显示同一份“正式运营就绪度”，用于日常判断哪些环节已经可用、哪些平台仍需补配置或补采集。

后台 `/admin/providers` 和单个 Provider 测试页会显示恢复探针命令。运营上建议先按后台显示的命令恢复 Provider，再回到项目页看正式运营就绪度。

也可以用命令行验收：

```bash
# 严格验收：要求项目达到 ready，且至少 3 个真实平台就绪；当前应失败
pnpm run verify:yuanquan

# 日常可用性检查：允许 partial，用于确认核心闭环仍然可用；当前应通过
pnpm run verify:yuanquan:partial

# 严格验收 + Provider 网络预检：失败时会同时说明是否 DNS/TCP/TLS 阻塞
pnpm run verify:yuanquan:network

# 日常可用性检查 + Provider 网络预检
pnpm run verify:yuanquan:partial-network
```

当前严格验收失败原因应包括：

- `multi_model_results`：已就绪平台 `1/4`，真实结果 `6` 条。等 DeepSeek、Kimi、千问至少再跑通两个平台后，该项才应该转绿。
- `browser_observation_evidence`：当前网页观测 `0` 条、截图证据 `0` 条。该项要求豆包、DeepSeek、Kimi、千问 4 个网页端平台都有观测样本，并且至少有 4 条截图/录屏证据。若 API/DNS 暂时不可用，可先在 `/projects/1#browser-observation` 录入网页端答案和截图证据，作为真实人工观测样本进入报告和复核链路。

首次使用网页端观测前，可初始化四个网页观测渠道：

```bash
pnpm run ensure:browser-observation-providers
```

该命令只创建/更新 `browser_observation` Provider，不创建采集结果，不会污染成熟度报告。初始化后，项目页网页观测区会显示豆包、DeepSeek、Kimi、千问网页端入口。

网页端观测区还会生成“下一批网页观测任务”，默认按 4 个平台和前 10 个目标问题做覆盖清单。点击“填入表单”会自动带入平台、Provider、目标问题和实际提问；点击“打开网页”后，把网页端答案、截图/录屏文件或地址、可见信源 URL 回填并入库。单条录入支持直接上传 PNG/JPG/WEBP/GIF/PDF/MP4/MOV 证据文件，系统会保存到 `outputs/browser-observation-evidence/project-1/` 并自动写入 `file://...` 存证路径；批量导入支持 `--evidence-dir`，JSON 里只填 `evidence_filename` 即可自动归档；如果证据已经放在对象存储或共享盘，也可以只填写截图/录屏地址。

如果已经一次性拿到豆包、DeepSeek、Kimi、千问四个平台的答案，可以使用项目页 `/projects/1#browser-observation` 的“批量录入四平台观测”。该入口接受 JSON 数组，字段与单条录入一致：

```json
[
  {
    "platform_name": "豆包",
    "target_question_id": 1,
    "prompt_text": "企业同时用多个大模型怎么统一管理？",
    "raw_answer": "粘贴网页端完整答案",
    "answer_summary": "可选摘要",
    "observation_url": "https://www.doubao.com/chat/",
    "evidence_filename": "豆包-question-1.png",
    "screenshot_url": "",
    "source_urls": ["https://example.com/source"],
    "observer_name": "运营同事",
    "note": "网页端人工观测，含截图留证"
  }
]
```

批量入口会按 `platform_name` 自动匹配对应 `browser_observation` Provider，并在成功后回显入库条数、信源条数和截图证据条数。批量入口默认勾选“只校验不入库”，适合先上传填写好的 JSON 做格式、占位符、四平台覆盖和截图字段校验；校验通过后，再取消该选项正式入库。项目页批量入口也支持采集包格式：JSON 中填写 `evidence_filename`，截图/录屏放入 `outputs/yuanquan_browser_observation_pack_q1/raw-evidence/`，页面入库时会自动归档为 `file://` 存证路径。命令行批量导入时推荐把四个平台截图放到一个目录，并加 `--evidence-dir`，脚本会把文件复制到 `outputs/browser-observation-evidence/project-1/` 后写入标准 `file://` 存证路径。

项目页批量表单默认勾选“入库后立即生成成熟度报告”和“生成报告后继续生成首篇稿件并评分”。提交后会直接跳转到新稿件详情页，并显示本次网页端观测、成熟度报告、稿件评分已经串联完成。若取消“生成稿件”选项，则提交后会跳转到新报告详情页；报告页顶部也有“生成首篇稿件并评分”和“批量生成稿件并评分”按钮。

同一能力也有后端接口，可供后续自动化或外部脚本直接调用：

```http
POST /api/projects/{project_id}/browser-observations/bulk
Content-Type: application/json

{
  "observations": [
    {
      "platform_name": "豆包",
      "prompt_text": "企业同时用多个大模型怎么统一管理？",
      "raw_answer": "粘贴网页端完整答案",
      "evidence_filename": "豆包-question-1.png",
      "screenshot_url": "",
      "source_urls": ["https://example.com/source"]
    }
  ]
}
```

接口返回 `created_count`、`result_ids`、`source_count`、`screenshot_evidence_count` 和每条 `CrawlResultDetail`。

带 `network` 的验收命令会把同一次 DNS/TCP/TLS 预检摘要写入：

- `outputs/latest_yuanquan_operational_readiness.json`
- `outputs/latest_provider_network_check.json`

如果 `network_check.environment_blocker=true` 且所有失败都在 `dns` 阶段，说明当前运行环境连 Provider 域名都解析不了，应先换到可出网普通终端或修复 DNS，再判断 API Key、模型权限和采集链路。

项目页 `/projects/1` 的“正式运营就绪度”和后台 `/admin/providers` 会读取同一份最近网络预检快照。页面不会自动发起外网请求，也不会消耗 API 额度；它只展示最近一次 `verify:yuanquan:network`、`verify:yuanquan:partial-network` 或 `check:provider-network` 留下的结果。

## 2026-07-09 交互与留证修复记录

本轮已完成的真实可用性修复：

- 稿件详情页现在优先加载项目和稿件正文；审核记录、内容资产、投放记录任一辅助接口失败时，不再导致整页打不开，而是在页面中提示“部分数据暂时没有加载成功”。
- 项目页 AI 撰稿按钮、稿件审核按钮、网页端观测入库按钮均已接入统一 `SubmitButton`，提交时会显示“生成稿件中...”“评分中...”“观测入库中...”。
- 全局表单提交反馈从 9 秒延长到 30 秒，适配生成稿件、AI 评分、网页观测入库等较慢操作。
- 网页观测入库 action 已加错误回跳；如果后端/API/鉴权失败，项目页会带 `action_error` 展示失败原因，不会静默无反馈。

已验证：

```bash
pnpm run check:web
pnpm run check:api
```

均通过。

后端 TestClient 已验证：

- 登录 `geo-demo-e2e@example.com`
- 创建稿件
- AI 评分
- 读取稿件详情依赖接口
- 创建网页端观测样本
- 写入 `crawl_result`、`citation_sources` 和截图证据计数
- 重新生成成熟度报告后，`evidence_quality` 会统计网页端观测样本数、截图/录屏证据数、网页端覆盖平台数和平台名称
- Markdown/PDF 报告会展示“网页端覆盖平台数”和“网页端覆盖平台”

烟测数据均已清理，没有污染正式项目。

当前仍不能直接证明 API 多模型采集恢复，因为非沙箱提权网络预检被 Codex 当前审批配置拦截：

```text
Automatic approval review failed: Model "codex-auto-review" is not supported ... url: https://ccdan.cc.cd/v1/responses
```

因此，在审批配置修好前，不要把“无法提权复测网络”误判为 Provider Key 一定失效。当前可继续使用网页端观测留证路线推进真实 GEO 工作：豆包、DeepSeek、Kimi、千问各录入至少 1 条带截图证据的样本，严格验收中的 `browser_observation_evidence` 才会转绿。

专项验收命令：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/verify_browser_observation_evidence_testclient.py
```

该脚本会创建临时项目，通过 `/browser-observations/bulk` 一次写入豆包、DeepSeek、Kimi、千问 4 条网页端观测样本，生成成熟度报告，验证报告 JSON/Markdown 中包含网页端平台覆盖指标，并验证运营就绪检查中的 `browser_observation_evidence` 可以转绿，然后清理临时数据。

报告到稿件闭环专项验收命令：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/verify_browser_observation_to_draft_loop_testclient.py
```

该脚本会创建临时项目，通过 `/browser-observations/bulk` 一次写入豆包、DeepSeek、Kimi、千问 4 条网页端观测样本，生成成熟度报告，基于报告生成首篇稿件并完成 AI 评分；同时验证稿件 `source_context` 已绑定成熟度报告、4 条网页观测结果 ID 和四个平台名称，验证审核记录包含“报告承接度”评分，最后清理临时数据。

完整闭环烟测已固化为专项脚本并通过：临时项目一次写入四平台观测、生成成熟度报告、生成首篇稿件并完成 AI 评分，最后清理临时数据。正式项目仍需录入真实四平台网页端答案和截图，才能从 `partial` 进入更高就绪状态。

如果 Codex 内置浏览器或当前安全策略无法直接打开豆包、DeepSeek、Kimi、千问网页端，不要绕过限制。使用外部浏览器完成真实提问和截图，然后把观测 JSON 导入正式项目：

推荐先为正式项目生成一套完整采集包：

```bash
pnpm run prepare:yuanquan-pack
```

该命令会生成：

```text
outputs/yuanquan_browser_observation_pack_q1/
├── README.md
├── observations.json
├── work-order.md
├── raw-evidence/
├── inspect.sh
├── dry-run.sh
└── import-and-generate.sh
```

采集执行者只需要按 `work-order.md` 打开豆包、DeepSeek、Kimi、千问网页端，把完整答案填入 `observations.json`，并把截图/录屏放进 `raw-evidence/`。文件名要与 JSON 里的 `evidence_filename` 一致。填完后先看 `README.md` 中的 dry-run 命令，再执行正式导入命令。

填到一半也可以随时检查采集包状态：

```bash
pnpm run inspect:yuanquan-pack
```

这个检查不会入库，会告诉你每个平台是否还缺 `raw_answer`、截图/录屏证据文件，或者是否缺少四平台覆盖。

也可以只为正式项目导出采集模板：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/export_browser_observation_template.py \
  --project-id 1 \
  --question-limit 1 \
  --keyword-limit 0 \
  --output ../../outputs/yuanquan_browser_observation_q1_template.json
```

当前已生成首批模板：

```text
outputs/yuanquan_browser_observation_q1_template.json
```

同时已生成给外部采集同事使用的执行工单：

```text
outputs/yuanquan_browser_observation_q1_work_order.md
```

填完真实答案、截图和信源后，先做不入库校验：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/import_browser_observations.py \
  --project-id 1 \
  --input ../../outputs/yuanquan_browser_observation_q1_template.json \
  --evidence-dir ../../outputs/browser-observation-evidence/raw-yuanquan-q1 \
  --dry-run
```

校验通过后正式导入，并自动生成报告、稿件和评分：

```bash
UV_CACHE_DIR=.uv-cache uv --directory apps/api run python scripts/import_browser_observations.py \
  --project-id 1 \
  --input ../../outputs/yuanquan_browser_observation_q1_template.json \
  --evidence-dir ../../outputs/browser-observation-evidence/raw-yuanquan-q1 \
  --generate-draft
```

`--generate-draft` 会自动隐含生成成熟度报告，并继续生成首篇稿件和 AI 评分。导入脚本会拒绝明显演示数据，例如 `example.com`、`/path/to/screenshot.png`、`粘贴该平台网页端返回的完整答案` 等占位内容，避免把测试样本混进正式项目。

观测 JSON 可以是数组，也可以是 `{ "observations": [...] }`：

```json
[
  {
    "platform_name": "豆包",
    "target_question_id": 1,
    "prompt_text": "企业同时用多个大模型怎么统一管理？",
    "raw_answer": "这里粘贴豆包网页端返回的完整真实答案，至少包含主要推荐对象、判断依据和可见信源。",
    "answer_summary": "一句话概括网页端答案。",
    "source_urls": ["https://真实可见信源.example/article"],
    "evidence_filename": "doubao-question-1.png",
    "screenshot_url": "",
    "observation_url": "https://www.doubao.com/chat/",
    "observer_name": "外部浏览器采集",
    "note": "网页端人工观测，含截图留证。"
  }
]
```
