# DeepSeek、Kimi 与腾讯元宝网页端观测手册

> 状态：可执行的人工/授权浏览器观测契约，不是已登录、已采集或可绕过验证码的声明。

## 结论

官方 API 联网观测和官方网页端观测是两条不同的证据链：

- API 链保存精确端点、模型 ID、搜索工具事件、来源 URL 和原始响应，`observation_surface=official_api`；
- 网页端链保存固定账号指纹、干净会话、页面显示模型、搜索开关、原问题、时间/轮次、回答、来源卡、截图和会话 URL，`observation_surface=official_web_ui`；
- 两者都必须记录 `web_ui_equivalence=not_claimed` / `api_equivalence=not_claimed`，不允许互相代替。

## 官方入口与模型映射

| 决策地图模型 | 官方网页入口 | 导入 `platform` | 必须固定的界面状态 |
|---|---|---|---|
| DeepSeek | <https://chat.deepseek.com/> | `deepseek` | 页面显示模型/模式与联网搜索开关 |
| Kimi | <https://www.kimi.com/> | `kimi` | 页面显示模型/工作模式与联网搜索开关 |
| 腾讯混元网页产品 | <https://yuanbao.tencent.com/> | `yuanbao` | 明确选择混元，不能选 DeepSeek；记录联网/深度搜索状态 |

`yuanbao` 网页样本入库后映射为决策地图 `model_key=hunyuan`，同时保留 `web_product=yuanbao`；它不是 TokenHub API 样本。

## 每个样本的固定步骤

1. 使用专用浏览器 Profile；不导出 Cookie、Token 或密码。
2. 记录非敏感账号别名与本地 SHA-256 指纹，同一账号/设置不得中途变更。
3. 新建空白会话，确认无历史上下文、附件或记忆提示。
4. 选定页面显示的模型/模式，设定联网搜索为 `explicit_on` 或记录为 `automatic`；对整个设置快照计算 SHA-256。
5. 在同一 `observation_group_id` 中，按统一问题、相邻时间窗和指定 `repeat_index` 提交；不改写问题。
6. 等到回答与来源卡完全稳定后，保存完整回答原文、每个来源卡 URL、页面截图、原始工件、会话 URL、开始/完成时间。
7. 若登录失效、出现验证码/风控、无来源卡或无法保存截图，将样本记为失败或 `partial`；不补造 URL，不绕过平台控制。

## 导入契约

将脱敏工件通过当前工作区接口导入：

```text
POST /api/v1/workspaces/{workspace_id}/imports/yao
```

`browser_assisted + auditable` 会强制校验官方域名、观测组、时间、账号/模型/搜索设置、回答工件、来源卡、截图和会话 URL。最小结构：

```json
{
  "platform": "kimi",
  "sample_mode": "browser_assisted",
  "evidence_level": "auditable",
  "prompt_version": "v1",
  "observation_group_id": "geo_20260810_a1",
  "samples": [{
    "sample_id": "kimi-q1-r1",
    "question": "原始问题原文",
    "repeat_index": 1,
    "ok": true,
    "started_at": "2026-08-10T10:00:00+08:00",
    "finished_at": "2026-08-10T10:01:00+08:00",
    "raw_artifact_uri": "file:///authorized-private-artifact/answer.json",
    "screenshot_uri": "file:///authorized-private-artifact/page.png",
    "conversation_url": "https://www.kimi.com/...",
    "answer_text": "完整回答",
    "references": [{"title": "来源卡标题", "url": "https://source.example/page"}],
    "web_ui_context": {
      "account_alias": "audit-account-a",
      "account_fingerprint": "64位小写SHA256",
      "model_display_name": "页面实际显示名称",
      "search_setting": "explicit_on",
      "new_conversation": true,
      "locale": "zh-CN",
      "timezone": "Asia/Shanghai",
      "settings_snapshot_sha256": "64位小写SHA256"
    }
  }]
}
```

## 当前人工边界

仓库已具备严格的网页观测导入与证据分类，但不保存平台凭据，也不在后端绕过登录、验证码或风控。因此首次登录、页面控件变更后的重新定位、验证码和最终页面确认仍需要人工。在这些边界未通过前，不得声称“网页端复刻已完成”。

## 官方 API 依据

- DeepSeek Anthropic API：<https://api-docs.deepseek.com/guides/anthropic_api/>
- DeepSeek 模型与端点：<https://api-docs.deepseek.com/quick_start/pricing/>
- Kimi 官方 Formula 工具：<https://platform.kimi.com/docs/guide/use-official-tools>
- Kimi 联网搜索：<https://platform.kimi.com/docs/guide/use-web-search>
- 腾讯 TokenHub 混元调用：<https://cloud.tencent.com/document/product/1823/132252>
- 腾讯 TokenHub 联网搜索：<https://cloud.tencent.com/document/product/1823/132358>
