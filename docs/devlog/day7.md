# Day 7 开发日志

Agent Loop 改为事件流（`TextDelta` / `ToolCallStart` / `ToolCallEnd` / `TurnEnd`），`agent.py` 零 print。Ollama 新增 `stream_chat_with_tools`；Textual TUI 消费事件做流式渲染与工具折叠。CLI 默认进 TUI，`--repl` 保留 print 模式。

踩坑：Textual 的 `Collapsible` 不适合直接子类化——在 `on_mount` 里 mount 更稳。流式 markdown 按手册先纯文本、完成后再 Markdown 重渲。
