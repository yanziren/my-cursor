# Day 11 开发日志

权限闸门插在 `registry.dispatch` 之前：规则链产出 allow / ask / deny。只读工具默认放行，`pytest`/`git status` 白名单直过，`rm`/`git push`/`sudo` 走审批或拒绝。deny 把理由当 tool 结果回传，模型才能改路而不是空失败。

踩坑：组合命令必须按最危险片段裁决（`ls && rm` 不能因为 `ls` 白名单就放行）；`git` 要记两词前缀，否则 `git push` 和 `git status` 会共用同一把「本会话允许」钥匙。TUI 用 `push_screen_wait` 让出事件环，审批时工具气泡改成「等待审批」，避免用户以为命令已经在跑。
