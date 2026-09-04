# Day 3 开发日志

抽出 `agent.py` 实现最小 Agent Loop（自然停止 + max_turns 硬停止），新增 `read_file`（行号前缀 `N|内容`），REPL 改为委托 Agent 连续多轮调工具。

Day 2 的单次往返本质是 loop 只转一圈；今天把 while 包上去后，「对比 a.py 和 b.py」会连续两轮 read_file 再综合——这才是 ReAct 形状。`MYCODER_MAX_TURNS=2` 可验证硬停止。

踩坑：loop 每轮都带全量 tools schema，思考型模型每轮都付思考 token；Day 3 先接受这个成本，Day 24 再量化优化。
