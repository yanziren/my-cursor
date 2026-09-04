# Day 5 开发日志

新增 bash（超时 + 进程组终杀 + stdout/stderr 合并 + 保头保尾截断）、glob、grep（优先 rg）。`examples/demo_project` 埋 calc.add bug 供闭环验收。

自我验证闭环形状：bash(pytest 失败) → read/edit → bash(pytest 通过)。grep 输出窄于 bash 自由拼管道，专用工具站在模型 RL 训练分布的顺风处。

踩坑：pytest 输出动辄千行，不截断会撑爆上下文；超时必须 killpg，否则 sleep 999 挂死 Agent Loop。
