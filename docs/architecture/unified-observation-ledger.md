# 统一观测账本

## 产品约束

每次观测必须在请求外部模型前创建批次和任务；回答产生后必须在同一事务中绑定运行、证据与状态。前端进度只读取数据库，不自行推测进度，也不存在人工“入库”步骤。

## 主数据关系

```text
geo_observation_batches_v1
  1 ── n geo_observation_tasks_v1
             ├── 1 model/provider snapshot
             ├── 1 question snapshot
             ├── 1 repeat index
             ├── 0..1 geo_observation_runs_v1
             ├── 0..1 geo_evidence_v1
             └── 0..1 queue_jobs
```

- `geo_observation_batches_v1`：一次用户提交的稳定业务记录，保存渠道、问题数、运行次数、任务总数和汇总状态。
- `geo_observation_tasks_v1`：不可合并的最小观测单元，即一个模型 × 一个问题 × 第 N 次。
- `geo_observation_runs_v1`：一次实际适配器调用的执行记录。
- `geo_evidence_v1`：回答原文、引用来源、原始工件、截图和采集环境。
- `queue_jobs`：执行队列，只负责调度、重试和错误；不是产品历史的主表。

## 自动写入时机

1. API 批量/单次观测：提交时创建 batch/task，worker 领取时写 running，回答归档时自动写 run/evidence 并完成 task。
2. 浏览器采样：创建采样矩阵时同步创建 batch/task，sample 完成或失败时同步账本。
3. Yao 数据导入：每次导入创建一个 batch，每个 sample 自动创建 task 并绑定 evidence。
4. 历史数据：迁移 `20260806_0017` 将所有旧证据回填进账本；不丢弃、也不伪造分组。

## 管理查询

GET /api/v1/workspaces/{workspace_id}/observation-ledger`

支持按 `batch_id`、`model_key`、`question_plan_id`、`status`、`source_type` 过滤和分页。每条结果都能定位到模型、问题、轮次、运行、证据和队列任务。

## 数据不变量

- 每条 `geo_evidence_v1` 最多绑定一个账本任务。
- 同一批次内 `sample_key` 唯一。
- 页面显示的完成数和失败数只能由任务状态聚合得出。
- 没有原文、来源和原始响应工件的联网回答不得标为可审计真实证据。
