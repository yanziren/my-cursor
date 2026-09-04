# Day 6 开发日志

抽出 `prompts/system.py` 结构化组装系统提示词（身份/准则/工具指南/安全/AGENTS.md/环境），`agents_md.py` 从工作区向上收集 AGENTS.md（近者优先）。repl 去掉硬编码 SYSTEM_PROMPT；`MYCODER_MINIMAL_PROMPT=1` 可跑对比实验。

环境注入日期精确到天（避免秒级时间戳打碎前缀缓存，Day 8 会展开）。根目录 AGENTS.md 规定「注释一律中文」。

踩坑：提示词不是越长越好——控制在约 1500 token 内，行为问题优先工具层与错误文案，解决不了再进提示词。
