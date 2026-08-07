# 春秋元泉 GEO 平台真实使用状态

更新时间：2026-07-11

## 当前结论

平台的系统闭环已经可用：目标问题/关键词、成熟度报告、稿件生成、AI 审核评分、人工审核入口、投放计划入口都能跑通。

但正式项目目前还不能宣称已经完成豆包、DeepSeek、Kimi、千问网页端真实存证采集。当前项目 1 的网页端观测入库数为 0，截图证据数为 0；已有报告主要来自真实 API 样本和人工校正，不等同于网页端产品页面观测。

## 已完成

- 项目 1：春秋元泉 GEO 优化 - 大模型 API 治理正式项目。
- 目标问题：15 个。
- 核心关键词：10 个。
- 成熟度报告：2 份。
- 新稿件：8 篇，生成器为 `solution_article_agent_v2`。
- 旧模板稿：已标记为 `needs_revision`，避免继续当正式稿推进。
- 稿件正文与 GEO 后续运营建议已拆分：正文只保留可发布内容，`geo_next_steps` 保存下一步补问题、补关键词、补证据、补信源建议。
- 报告详情页已增加证据提示：当网页端观测或截图证据为 0 时，会明确提示不能作为网页端真实存证报告对外使用。

## 新一轮真实网页端采集包

路径：`outputs/yuanquan_browser_observation_next_real_pack/`

本轮包含 8 条任务：

- 目标问题 1：企业同时用多个大模型怎么统一管理？
- 关键词 1：Token 统一管控
- 平台：豆包、DeepSeek、Kimi、千问

关键文件：

- `observations.json`：填写完整答案、摘要、信源 URL。
- `work-order.md`：逐平台操作工单。
- `raw-evidence/`：放截图或录屏。
- `inspect.sh`：检查缺口。
- `dry-run.sh`：正式入库前校验。
- `import-and-generate.sh`：导入并生成报告、稿件、评分。

## 执行顺序

1. 打开 `outputs/yuanquan_browser_observation_next_real_pack/work-order.md`。
2. 按工单分别打开豆包、DeepSeek、Kimi、千问网页端。
3. 复制完整真实答案到 `observations.json` 的 `raw_answer`。
4. 摘要写到 `answer_summary`。
5. 页面可见信源写到 `source_urls`，没有则保持空数组。
6. 截图或录屏放到 `raw-evidence/`，文件名必须与 `evidence_filename` 一致。
7. 运行 `inspect.sh` 看是否缺答案或截图。
8. 运行 `dry-run.sh` 校验。
9. 运行 `import-and-generate.sh` 正式导入，系统会生成网页端真实观测报告、稿件和 AI 评分。

## 验证结果

- `pnpm run check:api` 通过。
- `pnpm run check:web` 通过。
- `scripts/verify_import_browser_observation_evidence_dir_testclient.py` 通过：临时项目导入 4 平台网页端观测后，可生成成熟度报告、稿件和 AI 评分，并准备下一轮采集包。

## 仍需完成

- 在正式项目 1 中导入真实网页端观测和截图证据。
- 补全更多目标问题和关键词，而不是只采集首个问题/首个关键词。
- 确认 Kimi、千问等网页端是否需要登录、验证码或免费额度限制。
- 后续如要持续每小时监控，优先使用稳定 API 渠道；网页端观测适合作为低频抽样、截图存证和 API 结果校验。
