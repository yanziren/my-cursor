# mycoder

按《[30天从零构建Cursor级编程智能体](./30天从零构建Cursor级编程智能体.md)》手册逐天构建的编程智能体（harness 层，对标 Claude Code / OpenCode 的引擎层）。

**当前进度：Day 10 · 会话持久化与断点恢复**

## 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（包管理，取代 pip/poetry）
- [Ollama](https://ollama.com) 在本机运行，并已拉取至少一个对话模型（默认使用 `qwen3.8:27b`）

## 快速开始

```bash
uv sync          # 安装依赖、创建虚拟环境
uv run mycoder   # 启动 Textual TUI（默认，自动写入 ~/.mycoder/sessions/）
uv run mycoder --repl   # 旧版 print REPL，调试用
uv run mycoder resume          # 列出会话（标题 / 时间 / 轮数）并选择恢复
uv run mycoder resume <id>     # 按会话 id 或唯一前缀恢复
uv run mycoder resume --list   # 只列出，不进入
```

TUI 快捷键：`Ctrl+C` 退出 · `Ctrl+L` 清屏（开新会话，旧日志仍留在磁盘） · Enter 发送。

进程中途 `kill -9` 后，用 `mycoder resume` 选中同一会话即可接着跑：JSONL 是 append-only，崩溃最多丢掉最后半行。恢复时若磁盘上有压缩记录，发给模型的仍是「系统提示 + 摘要 + 最近 K 轮」，不会把已压缩原文塞回去。

```bash
# 重放任意会话的消息序列（调试器雏形）
uv run python scripts/replay_session.py ~/.mycoder/sessions/<id>.jsonl
# 会话文件可直接翻查
grep tool_call ~/.mycoder/sessions/*.jsonl
```

会话目录默认 `~/.mycoder/sessions/`，测试或隔离可用 `MYCODER_SESSIONS_DIR` / `MYCODER_HOME` 覆盖。

内置工具：`read_file`、`write_file`、`edit_file`、`bash`、`glob`、`grep`，以及玩具工具 `get_current_time`、`calculator`。文件路径相对项目根，越界路径会被拒绝。工作区根目录默认是当前目录，可用 `MYCODER_WORKSPACE` 覆盖。

Day 5 闭环示例（故意埋 bug 的计算器）：

```bash
MYCODER_WORKSPACE=examples/demo_project uv run mycoder
# 提示：修复失败的测试，改完后用 pytest 验证通过
```

TUI 底栏显示上下文仪表（`▓▓▓░░ 41% (13.2K/32K)`），以 API `usage` 为准。窗口涨满时先裁剪过期工具输出，再把早期轮次收成结构化摘要；聊天区会出现「已压缩 N 条早期消息 → 摘要 T token」。

```bash
# 上下文窗口（与 TUI 仪表上限对齐，修改后需重启 Ollama）
launchctl setenv OLLAMA_CONTEXT_LENGTH 32768
MYCODER_CONTEXT_LENGTH=32768 uv run mycoder   # 可选：覆盖仪表显示上限

# 摘要默认用小模型；可关闭压缩或换模型
# ollama pull qwen3:4b
MYCODER_COMPACT_MODEL=qwen3:4b uv run mycoder
MYCODER_COMPACT=0 uv run mycoder              # 关闭自动压缩（仍可手动观察仪表）

# 8K/16K/32K 窗口速度实测
uv run python scripts/benchmark_context.py
```

详见 [Ollama 上下文实测](./docs/ollama_context_benchmark.md)。

Day 7 里程碑（见 [第一周复盘](./docs/week1_retrospective.md)）：

```bash
MYCODER_WORKSPACE=examples/demo_project uv run mycoder
# 任务 A：修复 calc.add 测试
# 任务 B：新增 subtract 函数与测试
```

Day 6 对比实验（`--repl` 模式）：

```bash
MYCODER_WORKSPACE=examples/demo_project MYCODER_MINIMAL_PROMPT=1 uv run mycoder --repl
MYCODER_WORKSPACE=examples/demo_project uv run mycoder --repl
```

项目约定见根目录 `AGENTS.md`（如「注释一律中文」）。REPL 内 `/prompt` 可查看完整系统提示词。

```bash
uv run pytest tests/ -v              # harness 单测
uv run pytest examples/demo_project/tests -v  # 示例项目（修复前应失败）
```

## 切换模型

无需改代码，用环境变量覆盖：

```bash
MYCODER_MODEL=qwen3:8b uv run mycoder
MYCODER_MODEL=qwen3-coder:30b uv run mycoder   # 可选：Agent 专项 MoE 模型，需先 ollama pull
```

## 重要：调大 Ollama 上下文窗口

Ollama 默认上下文长度很小（约 4096 token），跑智能体必须调大，代价是显存占用上升（Day 8 详解这笔账）。

- macOS（Ollama.app）：

```bash
launchctl setenv OLLAMA_CONTEXT_LENGTH 32768
# 然后退出并重启 Ollama.app 生效
```

- 命令行启动：`OLLAMA_CONTEXT_LENGTH=32768 ollama serve`

## 已踩的坑

- **macOS 系统代理会劫持 localhost 请求**：openai SDK 底层的 httpx 默认信任系统代理，开着代理（Clash/V2Ray 等）时请求本机 Ollama 会得到 502。已在 `providers/ollama.py` 中用 `trust_env=False` 强制直连。
- `qwen3.8:27b` 是思考型模型：思考过程走 Ollama 扩展的 `reasoning` 字段流式返回，REPL 以降暗文字展示，且不写回消息历史（省上下文）。

## 目录结构

按手册 3.2 节预置的骨架，30 天内逐个填充：

```
src/mycoder/
├── providers/        # 模型适配层（Day 1 ollama.py，Day 21 抽象多 Provider）
├── tools/            # 工具集（Day 2 起：base / files / shell / search / todo / task）
├── context/          # 上下文计量与压缩（Day 8-9）
├── session/          # JSONL 会话持久化（Day 10）
├── permissions/      # 权限管道（Day 11）
├── sandbox/          # Docker 执行器（Day 12）
├── indexer/          # tree-sitter + 向量索引（Day 15-16）
├── mcp/              # MCP 客户端（Day 19）
├── prompts/          # 系统提示词组装（Day 6）
├── tui/              # Textual 终端界面（Day 7）
├── server/           # FastAPI 服务（Day 25）
└── repl.py           # Day 1 流式 REPL
```

## 开发约定

- 依赖管理：`uv add <pkg>`（dev 依赖 `uv add --dev <pkg>`），运行一律 `uv run ...`
- 代码检查：`uv run ruff check`
- 每天结束以 git commit 固化当日产出与开发日志
