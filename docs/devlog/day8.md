# Day 8 开发日志

新增 `context/budget.py`：API `usage` 为准、`estimate_messages_tokens` 兜底；TUI 底栏 `▓▓▓░░ 41% (13.2K/32K)`。Provider 记录完整 `prompt_tokens`/`completion_tokens`；Agent 每轮模型调用后发 `UsageUpdate`。

踩坑：Ollama 默认 4096 窗口对智能体「出生即残废」——必须 `OLLAMA_CONTEXT_LENGTH=32768` 并重启服务；超窗截断 system 且不报错。仪表 limit 读 `MYCODER_CONTEXT_LENGTH` / `OLLAMA_CONTEXT_LENGTH`，与服务器 num_ctx 应对齐。
