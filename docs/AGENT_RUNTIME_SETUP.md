# Agent 运行时配置

优先行动页的 Agent 选择器会只展示真实诊断结果：本机可用时显示“已就绪/已连接”，缺少安装、登录或密钥时显示“未配置”并禁用执行。选择 Agent 只会改变后续分析和生成任务，不会改变已选择的批次、模型范围或问题范围。

## Codex

Codex 通过 OpenAI 官方本机 SDK 执行，复用当前机器上的 ChatGPT/Codex 登录。完成本机登录后重启 API 和 worker 即可，不需要把密钥写入仓库。

## Claude Agent

安装可选的 Anthropic 官方 Agent SDK：

```bash
cd apps/api
uv sync --extra claude-agent
```

在本机私密环境中设置 `ANTHROPIC_API_KEY`，然后重启 API 和 worker。模型列表可通过 `CLAUDE_AGENT_MODELS` 以逗号分隔配置。

## Hermes

先按 Hermes 官方文档启动 OpenAI-compatible API Server。本项目默认连接 `http://127.0.0.1:8642`，可用 `HERMES_API_URL` 修改；在本机私密环境中设置 `HERMES_API_KEY`。诊断会真实检查 `/health` 和 `/v1/models`，不会把“有配置”冒充为“已连接”。

## OpenClaw

安装 OpenClaw 并在本机完成 `openclaw onboard`，确保 `openclaw` 命令位于 API 和 worker 的 `PATH`。如果需要指定 Agent，在私密环境中设置 `OPENCLAW_AGENT_ID`。系统会使用官方 headless CLI 的 JSON 输出，并只在 `models list --json` 返回可用模型后显示为已就绪。

## 安全与状态边界

- 密钥只存在本机私密环境，不写入数据库、任务快照或 Git。
- 所有 Agent 共用现有的持久化任务、人工审核、草稿回读和发布边界。
- 连接测试不等于真实任务完成；只有结构化结果通过证据校验后才会进入业务流程。
