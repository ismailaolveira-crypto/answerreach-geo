# Agent 运行时配置

优先行动页的 Agent 选择器会只展示真实诊断结果：本机登录可复用时显示“已连接”，仅检测到本地 profile 时显示“已配置”，缺少安装或登录时显示“未配置”并禁用执行。选择 Agent 只会改变后续分析和生成任务，不会改变已选择的批次、模型范围或问题范围。

## Codex

Codex 通过 OpenAI 官方本机 SDK 执行，复用当前机器上的 ChatGPT/Codex 登录。完成本机登录后重启 API 和 worker 即可，不需要把密钥写入仓库。

## Claude Code

安装 Claude Code 并使用自己的 Claude 账号登录：

```bash
claude auth login
claude auth status
```

系统通过官方 `claude -p --output-format json --json-schema` 调用，复用 Claude Code 自己管理的订阅登录或 API 认证，不要把凭据复制到项目。模型列表可通过 `CLAUDE_AGENT_MODELS` 以逗号分隔配置。

## Hermes

安装 Hermes 后执行 `hermes model` 选择自己的 provider 和默认模型。系统优先使用官方本机 `hermes chat --quiet -q` 调用该 profile；页面的“已配置”只表示 profile 完整，真实 provider 鉴权仍以首次执行结果为准。Hermes 当前版本没有稳定的逐次推理强度参数，因此页面显示“使用 Agent 本机配置”，不伪造控制。

只有明确配置 `HERMES_API_KEY` 时，系统才会在本机 CLI 不可用时回退到 `HERMES_API_URL` 的 OpenAI-compatible HTTP 模式。

## OpenClaw

安装 OpenClaw 并在本机完成 `openclaw onboard`，确保 `openclaw` 命令位于 API 和 worker 的 `PATH`。如果需要指定 Agent，在私密环境中设置 `OPENCLAW_AGENT_ID`。系统会使用官方 headless CLI 的 JSON 输出，并只在 `models list --json` 返回可用模型后显示为已就绪。

## 安全与状态边界

- 密钥只存在本机私密环境，不写入数据库、任务快照或 Git。
- 所有 Agent 共用现有的持久化任务、人工审核、草稿回读和发布边界。
- 连接测试不等于真实任务完成；只有结构化结果通过证据校验后才会进入业务流程。
