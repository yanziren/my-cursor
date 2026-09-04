# Day 8 · Ollama 上下文窗口实测

> 机器：Apple Silicon · 模型 `qwen3.8:27b` · 固定 prompt「用一句话解释什么是 KV cache。」  
> 通过 Ollama OpenAI 兼容接口 `extra_body.options.num_ctx` 分别设置窗口。

## 如何复现

```bash
# 确保 Ollama 已 pull 模型且服务在跑
uv run python scripts/benchmark_context.py
# 或只测某一档：uv run python scripts/benchmark_context.py 8192
```

结果 JSON 写入 `docs/ollama_context_benchmark.json`。

## 服务端默认窗口（必做）

客户端仪表的 `32K` 上限需与 Ollama **服务端**配置一致，否则超窗会被静默截断：

```bash
# macOS Ollama.app
launchctl setenv OLLAMA_CONTEXT_LENGTH 32768
# 退出并重启 Ollama.app

# 或命令行
OLLAMA_CONTEXT_LENGTH=32768 ollama serve
```

也可在 Modelfile 固化：`PARAMETER num_ctx 32768`。

## 实测记录（2026-09-04 · qwen3.8:27b · Apple Silicon GPU）

| num_ctx | prompt | completion | 耗时 (s) | token/s | ollama 加载 |
|---------|--------|------------|----------|---------|-------------|
| 8192    | 17     | 101        | 18.7     | 5.4     | ~18 GB      |
| 16384   | 17     | 130        | 26.0     | 5.0     | ~18 GB      |
| 32768   | 17     | 165        | 30.4     | 5.4     | ~18 GB      |

原始 JSON：`docs/ollama_context_benchmark.json`。

**观察**：同一条短 prompt 下，更大 `num_ctx` 生成更长 completion（思考型模型）且耗时增加；`ollama ps` 显示加载 CONTEXT 为 32768（已按服务端配置常驻）。显存约 18 GB，与 27B 量化模型一致。

## 超窗失忆复现

1. 临时把窗口调到 **2048**：`MYCODER_CONTEXT_LENGTH=2048 uv run mycoder --repl`
2. 连发多轮大工具输出（如 `grep` 大仓库 + 长对话）
3. 观察模型是否「忘记」系统提示（不再中文注释、不再主动 pytest）
4. 恢复 `32768` 并重启 Ollama

症状原因：Ollama **静默截断最早消息**（往往是 system prompt），不报错。

## 前缀缓存（Prefix Caching）备忘

- 连续多轮请求时，若**消息前缀逐字节相同**，推理引擎可复用 KV cache，只算增量部分。
- **铁律 1**：消息历史只追加、不修改已发送内容。
- **铁律 2**：系统提示词保持稳定；易变信息（秒级时间戳）不要放在前缀（Day 6 日期精确到天即为此）。

云端 API 的 prompt caching 同理，Day 24 再算账。
