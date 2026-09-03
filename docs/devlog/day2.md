# Day 2 开发日志

Day 2 完成工具基类（Pydantic schema + model_validate）、两个玩具工具（get_current_time / calculator）、工具注册表与 REPL 单次工具往返。

核心认知：模型只输出 tool_calls JSON，真正执行与回填 role=tool 消息全是 harness 的事。Provider 新增非流式 `chat()` 专用于工具轮（解析 finish_reason=tool_calls 比流式简单）；最终回答仍走同一接口。

踩坑：思考型模型 assistant 消息有 tool_calls 时 content 必须留空，否则 reasoning 污染历史导致下轮行为异常。Pydantic 对 `expression` 传数组会直接 ValidationError，错误文案原样塞回 tool 消息即可让模型重试（Day 13 会制度化）。

验收：「现在几点」触发 get_current_time；「你好」不调用工具；`/messages` 可打印含 tool_calls 与 tool 的完整序列。
