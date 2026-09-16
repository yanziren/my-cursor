# Day 10 开发日志

会话改成 JSONL 事件日志（`~/.mycoder/sessions/<id>.jsonl`）：每行一个 entry，`message` / `compaction` / `model_change` 三种起步，带 `id`/`parent_id`/时间戳。Agent 每追加一条消息立刻 `write + fsync`，压缩记录单独落盘。`mycoder resume` 列出标题、时间、轮数并重放；恢复时按最新压缩点组装视图，原文仍在文件里但不进模型窗口。附了 `scripts/replay_session.py` 重放消息序列。

踩坑：`kill -9` 可能截断最后半行——下次 append 前必须先裁到最后一个换行，否则新行会和半行粘成非法 JSON。另一处是崩溃停在 `assistant.tool_calls` 之后：恢复时要补「会话中断」的 tool 占位，否则下一轮 API 会拒收。标题用侧车 `.meta.json` 原子改写，因为 JSONL 不能更新已写行。
