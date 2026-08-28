# Phase 2 优化行动分流、企业责任与局部复测实施规格

> 对应 Goal：R4、R5、R6、R10、R11
> 设计基准：Phase 2 三张 `self-review-passed` image2 设计板
> 当前状态：实施规格已定义；等待用户确认设计。未授权产品代码、数据库迁移或运行态变更。

## 1. 这一阶段真正解决什么

企业不缺一张“行动列表”，缺的是一套能回答以下问题的真实账本：

1. 这是什么类型的行动，应该走哪条交付流程？
2. 谁负责，什么时候交付，审批还剩多久，卡在哪里？
3. 哪一个具体目标已经真实完成，证据是什么？
4. 能否只复测已经完成的目标，而不被其他未完成目标拖住？

因此 Phase 2 的核心不是重画卡片，而是把“行动、目标、证据、审批、复测”拆成五个可追溯对象。

## 2. 当前实现的权威事实与缺口

| 当前事实 | 影响 | Phase 2 决策 |
|---|---|---|
| `geo_optimization_actions_v1` 只有通用 `status/stage`，没有行动类型、负责人、截止和审批 SLA | 官网、结构化数据和文章只能挤进同一条内容流水线 | 增加行动公共字段；类型专属步骤由服务端状态机决定 |
| 当前 `ActionStageUpdate` 允许客户端直接提交任意列出的阶段，只有关闭时检查复测 | 非法跨阶段、越权审批和跳步无法可靠阻止 | 所有变更改走领域命令，客户端不能直接写阶段 |
| 当前完成事实主要存在 `geo_distribution_targets_v1` | 只适合文章/官网交付，不适合 Schema 与第三方信源 | 增加通用行动目标与完成证据账本；发布目标作为文章适配层保留 |
| 当前复测创建代码寻找一组“全部目标都已公开验证”的 distribution run | 任意一个目标完成也不能复测 | 复测入口改为目标级证据门禁；未完成目标不进入该轮归因 |
| 当前 `GeoReobservation` 只关联行动和轮次 | 无法证明一轮复测到底测了哪个完成目标 | 增加复测—目标—证据不可变关联 |
| 当前全局角色和工作区角色同时存在，但写接口主要只校验全局角色 | reviewer/operator 的企业权限边界不够精确 | 新命令同时校验工作区角色、当前负责人和审批人 |
| 当前前端 `priority-actions-workbench.tsx` 同时承担机会、生成、审核、发布和复测 | 继续叠加会导致四类流程互相污染 | 建立 Phase 2 壳层与类型组件，复用已有能力，不复制业务真相 |

## 3. 领域对象

### 3.1 行动公共字段

在 `geo_optimization_actions_v1` 新增：

| 字段 | 类型 | 规则 |
|---|---|---|
| `action_type` | string | `article / official_site / structured_data / third_party_source / legacy_unclassified` |
| `deliverable_type` | string | 文章稿、官网变更、JSON-LD、第三方公开内容等具体交付物 |
| `workflow_version` | string | 新行动固定 `action-flow.v2`；旧行动保留迁移版本 |
| `assignee_user_id` | FK users | 进入 `accepted` 前必填，且必须是当前工作区活跃成员 |
| `due_at` | datetime | 进入 `accepted` 前必填，服务端存 UTC |
| `approval_due_at` | datetime | 当前有效审批的截止时间缓存；没有审批时为空 |
| `approval_requested_at` | datetime | 当前有效审批的发起时间缓存 |
| `blocked_reason_code` | string | 标准原因码，不能只有自由文本 |
| `blocked_note` | text | 对标准原因的业务说明 |
| `affected_question_ids` | JSON array | 去重排序；没有关联问题不能解锁 GEO 复测 |
| `affected_model_keys` | JSON array | 去重排序；使用模型键而非展示名 |
| `scope_fingerprint` | SHA-256 | 选择行动时冻结的全局范围指纹 |
| `measurement_status` | string | `not_eligible / eligible / retesting / partially_measured / measured / inconclusive` |

保留现有 `question_plan_id`、`baseline_snapshot`、`selected_scope` 和 `measurement_plan` 作为兼容字段。`question_plan_id` 映射为 `affected_question_ids` 的第一个值，但不再是唯一问题来源。

以下字段由真实关联表计算后返回，不作为可被写坏的冗余数据库列：

- `target_refs[]`
- `completion_evidence_ids[]`
- `completed_target_count`
- `retest_eligible_target_count`

### 3.2 通用行动目标 `geo_action_targets_v1`

一个行动可以有多个平台、页面、Schema 或第三方信源目标。

| 字段 | 说明 |
|---|---|
| `id, workspace_id, action_id` | 租户和归属 |
| `target_key` | 行动内幂等键；`action_id + target_key` 唯一 |
| `target_type` | `platform / official_page / schema / external_source` |
| `platform_key` | 文章平台时使用；其他类型可为空 |
| `display_name` | 用户可读目标名 |
| `target_ref` | URL、页面路径、Schema 类型或信源标识 |
| `delivery_status` | 类型专属交付阶段 |
| `ordinal` | 固定展示顺序 |
| `metadata` | 非权威补充信息，不能存凭据 |
| `completed_at, completed_by_user_id` | 真实完成时间和操作者 |
| `verified_at` | 完成证据通过验证的时间 |

删除目标不作为 P0 操作。用户取消目标时写 `cancelled` 状态并保留事件。

### 3.3 完成证据 `geo_action_completion_evidence_v1`

每一条“已完成”都必须对应一条不可变证据：

| 字段 | 说明 |
|---|---|
| `workspace_id, action_id, target_id` | 精确归属 |
| `evidence_type` | `public_url / same_domain_readback / source_code / schema_validation / external_publication` |
| `source_url` | 公开 URL；不允许本机、内网或带凭据地址 |
| `artifact_uri` | 私有回读工件路径，只允许位于既有 private_artifacts 边界 |
| `sha256` | 证据内容哈希 |
| `verification_status` | `pending / verified / rejected / superseded` |
| `detail` | 回读标题、声明命中、Schema 校验结果等脱敏摘要 |
| `submitted_by_user_id, verified_by_user_id` | 提交与验证主体 |
| `submitted_at, verified_at` | 服务端时间 |
| `supersedes_evidence_id` | 更正时新建记录，不覆盖旧证据 |

证据一旦被复测引用，URL、哈希和验证结果锁定；更正只能创建新证据和新复测。

### 3.4 审批 `geo_action_approvals_v1`

审批不是行动上的一个布尔值，而是有版本的决定：

- `action_id` 必填；`target_id` 可选。
- `approval_type`：`fact / platform_draft / brand_legal / technical / external_content`。
- `status`：`pending / approved / changes_requested / cancelled / expired`。
- `requested_by_user_id / reviewer_user_id / due_at / requested_at / decided_at / note`。
- `subject_fingerprint` 锁定被审批的版本或建议；对象变化后旧审批不能继续生效。
- `action_id + approval_type + version` 唯一；新一轮审批递增版本。

行动上的 `approval_due_at` 与 `approval_requested_at` 只是当前待审批项的查询缓存，权威历史在审批表。

### 3.5 复测目标关联 `geo_reobservation_targets_v1`

保留现有 `geo_reobservations_v1` 作为一次真实复测轮次，并新增：

- `reobservation_id`
- `action_target_id`
- `completion_evidence_id`
- `evidence_sha256`
- `scope_fingerprint`

`reobservation_id + action_target_id` 唯一。一轮允许合并多个目标，但只有以下内容完全一致时才能合并：

- 工作区
- 基线批次
- 受影响问题集合
- 受影响模型集合
- 重复次数
- 范围指纹

否则分别建立复测，不能为了节省任务强行合并。

## 4. 两条状态轴，避免把并行事实塞进一个状态

单个目标可以已经复测，而同一行动的其他目标仍在执行。只用一个 `stage` 无法表达这个事实。

### 4.1 行动交付阶段

```text
proposed
→ accepted
→ in_progress
→ awaiting_approval
→ executing
→ partially_completed
→ completed
```

旁路：`blocked / changes_requested / cancelled`。

### 4.2 测量状态

```text
not_eligible
→ eligible
→ retesting
→ partially_measured
→ measured
```

旁路：`inconclusive`。

兼容字段 `status` 继续输出 `proposed / in_progress / verified / closed`，但由服务层映射，不再允许新接口直接写入。现有 `stage` 承载交付阶段；旧阶段在读取时通过兼容映射显示，不原地伪造历史事件。

## 5. 四类行动的专属目标状态

### 5.1 发布平台文章

```text
target_selected
→ variant_generating
→ awaiting_fact_review
→ awaiting_platform_review
→ draft_write_requested
→ draft_saved
→ awaiting_human_publish
→ publicly_verified
```

- `draft_saved` 不是完成证据，不能复测。
- 只有 `publicly_verified` 且公开 URL 回读成功，目标才完成。
- Phase 2 暂时复用现有分发记录；Phase 5 的 GEO 文章助手替换写草稿入口，不改写这些状态含义。

### 5.2 修改官网页面

```text
gap_confirmed
→ change_proposed
→ awaiting_brand_legal_review
→ handed_to_web_owner
→ deployed
→ same_domain_readback_verified
```

绝不出现平台文章生成或文章助手。

### 5.3 补充结构化数据

```text
schema_gap_confirmed
→ jsonld_proposed
→ awaiting_technical_review
→ deployed
→ source_readback_verified
→ schema_validated
```

完成证据必须同时包含源码回读哈希与确定性 Schema 校验结果。

### 5.4 建设第三方信源

```text
source_selected
→ cooperation_briefed
→ external_execution
→ external_content_live
→ public_readback_verified
```

外部页面必须明确标记为第三方内容，不能伪装成平台自己发布。

## 6. 企业规则与权限

### 6.1 进入执行前

- `proposed → accepted`：负责人、截止时间、至少一个目标、受影响问题和模型必须齐全。
- 负责人必须是当前工作区活跃成员。
- 所有时间由服务端生成并存 UTC；界面按工作区时区展示。

### 6.2 工作区角色

| 角色 | 权限 |
|---|---|
| owner/admin | 分配、转交、延期、取消、指定审批人、处理所有行动 |
| operator | 接受和执行分配给自己的行动、提交证据、声明阻塞；不能替别人审批 |
| reviewer | 只处理分配给自己的审批和退回；不能改负责人或伪造完成 |
| viewer | 只读 |
| super_admin | 具备平台管理权限，但所有动作仍写审计主体 |

新的行动命令不能只使用全局 `WRITE_ROLES`；还必须校验工作区角色和对象归属。

### 6.3 截止和审批 SLA

- 行动截止前 24 小时产生一次 `action_due_soon` 事件。
- 审批剩余 8 小时产生一次 `approval_due_soon` 事件。
- 到期产生 `action_overdue` 或 `approval_overdue`，同一对象同一版本只产生一次。
- 转交、延期、退回、阻塞和解阻塞都写不可变 `GeoActionEvent`。
- 站内通知在 Phase 3 共用通知中心落地；Phase 2 先保证事件、去重键和服务端时间都已存在。

## 7. 局部复测门禁

### 7.1 可复测条件

目标满足全部条件才为 `eligible`：

1. 类型专属最终状态已达到；
2. 至少一条完成证据为 `verified`；
3. 证据有 SHA-256 和精确目标关联；
4. 行动有非空的受影响问题与模型集合；
5. 基线批次、样本和重复次数仍可回读；
6. 创建时冻结完整范围和证据指纹。

草稿、候选链接、人工填写但未回读 URL、待部署代码、待对方审核内容均不满足。

### 7.2 新接口行为

`POST /workspaces/{workspace_id}/actions/{action_id}/retests`

请求：

```json
{
  "target_ids": [301],
  "idempotency_key": "..."
}
```

服务端自行读取目标、证据和冻结范围；前端不能提交问题、模型、基线或重复次数覆盖它。

当前 `/actions/{action_id}/retest` 保留兼容：

- 只有一个 eligible 目标时转调新服务。
- 多个 eligible 目标时返回 `409` 并要求客户端明确选择。
- 不再检查“全部平台已发布”。

### 7.3 结论边界

- 结果必须显示本轮目标和证据，而不是只显示行动名称。
- `partially_measured` 代表部分完成目标已有结果，其他目标仍在执行。
- 样本不足、范围不一致或模型异常统一为 `inconclusive`，不得显示改善或下降。
- 行动整体只有在所有要求测量的完成目标都有有效结果时进入 `measured`。

## 8. API 契约

### 8.1 查询

- `GET /workspaces/{id}/actions?view=all|mine|approvals|overdue_blocked`
- `GET /workspaces/{id}/actions/{action_id}`：返回行动、目标、当前审批、责任摘要、复测资格和最近事件。
- `GET /workspaces/{id}/actions/{action_id}/events`
- `GET /workspaces/{id}/actions/{action_id}/retests`

### 8.2 命令

- `POST /actions`：必须声明 `action_type` 和目标。
- `POST /actions/{id}/accept`
- `POST /actions/{id}/assign`
- `POST /actions/{id}/reschedule`
- `POST /actions/{id}/block`
- `POST /actions/{id}/unblock`
- `POST /actions/{id}/targets`
- `POST /actions/{id}/targets/{target_id}/transition`
- `POST /actions/{id}/targets/{target_id}/evidence`
- `POST /actions/{id}/approvals`
- `POST /actions/{id}/approvals/{approval_id}/decide`
- `POST /actions/{id}/retests`

每个命令必须包含幂等键或由版本/目标构成确定性唯一键。非法状态返回 `409`，权限不足返回 `403`，租户外对象返回 `404`。

## 9. 迁移方案

拟新增迁移：`20260824_0030_action_execution_v2.py`。

### 9.1 迁移前

- 自动复制当前数据库到既有安全备份目录，并记录 SHA-256、大小和 SQLite integrity check。
- 记录关键表行数：actions、events、distribution targets、reobservations、content assets。
- 禁止删除、重建或覆盖 `apps/api/geo_platform.db`。

### 9.2 旧行动分类

只使用结构化字段，禁止根据标题关键词猜测：

1. `opportunity_type` 为 website 类，或唯一目标是 `official_site` → `official_site`。
2. 存在非官网 platform variant/distribution target，或明确 `recommended_asset_type=article` → `article`。
3. 明确结构化 `recommended_asset_type=structured_data` → `structured_data`。
4. 明确 `recommended_asset_type=third_party_source` → `third_party_source`。
5. 其他全部 → `legacy_unclassified`。

`legacy_unclassified` 继续可读，但不能自动进入新执行状态；管理员人工归类后才可继续。

### 9.3 旧目标与复测

- 现有 distribution target 一对一建立通用 action target，并保留原外键关系和公开 URL 状态。
- 已公开验证目标建立完成证据，哈希来自既有回读工件或重新确定性回读；无法证明时保持 `pending`，不伪造已验证。
- 既有复测从其 `scope_snapshot.published_targets` 回填复测—目标关联。
- 找不到精确目标的历史复测继续按旧格式只读，标记 `legacy_action_scope`，不伪造目标归因。

### 9.4 回滚

- downgrade 只移除新表、新字段和兼容索引，不删除任何旧表记录。
- 新 Phase 2 命令写入的对象在降级前导出 JSON 账本；不能无损表示时必须停止 downgrade 并说明。

## 10. 服务层和文件边界

新增建议：

- `apps/api/app/v1/action_workflow.py`：状态机、前置条件、派生状态。
- `apps/api/app/v1/action_workflow_routes.py`：新查询与命令，不继续膨胀 `routes.py`。
- `apps/api/app/v1/action_workflow_schemas.py`：请求/响应对象。
- `apps/api/app/v1/action_retest_service.py`：目标级资格、冻结和合并规则。
- `apps/web/src/components/actions-v2/`：列表、详情、目标、审批、局部复测组件。
- 现有 `priority-actions-workbench.tsx` 保留机会判断、Agent、内容审核与旧行动兼容；新壳层通过明确 props 复用，不复制 API 规则。

禁止前端根据文案推断阶段、审批或证据是否有效。

## 11. 实施顺序

### Slice 2A：模型与迁移

- 新字段、新表、枚举常量和只读迁移预检。
- 迁移后行数、外键、哈希和旧 API 回读验证。

### Slice 2B：状态机与责任

- 四类目标状态机。
- 接受、分配、转交、延期、阻塞、审批命令。
- 工作区角色和不可变事件。

### Slice 2C：证据与局部复测

- 类型专属证据验证器。
- 移除全部目标完成门禁。
- 目标级复测冻结、合并规则和多轮结果。

### Slice 2D：桌面与移动 UI

- 按已通过 image2 一比一实现。
- 我的行动、待我审批、逾期阻塞。
- 四类详情、唯一主操作和移动底部工作表。

每个 Slice 完成后独立验证，不把数据库、API 和 UI 一次性混成一个不可回退大改。

## 12. 验收矩阵

### 数据与迁移

- 迁移前后旧行动、事件、草稿、分发、复测行数不减少。
- `PRAGMA integrity_check` 为 `ok`，foreign key check 为空。
- 所有无法确定类型的旧行动为 `legacy_unclassified`，没有被默认当文章。

### 状态机

- 四类行动只返回自己的步骤和字段。
- 无负责人或截止时间不能接受。
- 非法跳步返回 409，并记录拒绝审计事件。
- 转交、延期、退回和阻塞均可回读历史。
- operator 不能替别人审批；reviewer 不能伪造完成。

### 局部复测

- 四平台文章中只有知乎公开验证时，可单独复测知乎。
- CSDN 只有草稿时不能进入该轮复测。
- 官网、Schema、第三方信源各有一条真实证据即可复测对应目标。
- 不同问题、模型、基线或范围指纹不能被合并。
- 结果明确写出目标 ID、证据 ID、证据哈希和冻结范围。

### UI

- 1440px、1024px、390px 三档真实浏览器验收。
- 列表能看清负责人、截止、停留、审批 SLA、阻塞和下一步。
- 点击行动在原位或详情面板展开，不跳回主图。
- 任何页面不把草稿、同步请求、人工填 URL 当成已发布。
- 官方 Logo、44px 点击区、键盘、Escape、减少动态/透明度均通过。

### 固定命令

- `pnpm run check:web`
- `pnpm --dir apps/web run build`
- Phase 2 新增 API 测试 + 现有 priority action/retest/review 测试
- Alembic upgrade/downgrade/upgrade 在数据库副本上验证
- 真实浏览器全流程
- 隐私文件审计和 change bundle audit

## 13. 停止条件

出现以下任一情况立即停止实现并保留证据：

- 设计未获得用户明确确认。
- 迁移无法证明旧数据不丢失或回滚副本不可读。
- 必须覆盖旧发布/复测记录才能建立新目标关系。
- 真实数据无法支持设计中的负责人、审批或目标级证据。
- 前端、API 和数据库对同一行动状态出现不同结论。
- 为实现 Phase 2 被迫扩张到 CRM、外部消息渠道、最终发布或 Phase 5 插件。
