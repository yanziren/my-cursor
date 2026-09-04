# Day 4 开发日志

Day 4 完成文件三件套：read_file（行号 + offset/limit 截断）、write_file、edit_file（唯一性校验 + replace_all），路径 resolve 后 `is_relative_to` 工作区根（`MYCODER_WORKSPACE` 默认可 cwd）。

edit 错误文案按手册写给模型看：未找到 → 先 read；多处匹配 → 加长 old_string 或 replace_all。config.py 供验收「DEBUG 改 False」。

踩坑：old_string 必须与 read 看到的完全一致（换行/空格），这是 harness 故意严格——改错在应用前拦截，比 silent 改错强。
