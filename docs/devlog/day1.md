# Day 1 开发日志

工程脚手架（uv + src 布局 + 3.2 节目录骨架）与流式 REPL 完成，ruff 通过，冒烟测试通过。

踩坑两个：

1. **系统代理劫持 localhost**：openai SDK 底层 httpx 默认读 macOS 系统代理，开着 Clash/V2Ray 时请求本机 Ollama 直接 502。curl 正常但 Python 失败是关键线索（curl 只认环境变量代理）。解法：`httpx2.Client(trust_env=False)` 强制直连。
2. **思考型模型的流式形状**：`qwen3.8:27b`（及 qwen3 系）的思考过程走 Ollama 扩展的 `delta.reasoning` 字段，`delta.content` 在思考期间一直为空——只打印 content 会让终端静默半分钟像卡死。REPL 把 reasoning 降暗流式显示，且不写回消息历史（省上下文窗口）。

Day 1 冒烟测试在旧默认 `qwen3.6:27b` 上测得 11.4 token/s；项目默认已切换为 `qwen3.8:27b`。若仍偏慢，备选：`MYCODER_MODEL=qwen3:8b` 或 MoE 的 `qwen3-coder:30b`。
