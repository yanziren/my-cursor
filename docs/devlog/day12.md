Day 12 把 bash 从「宿主 subprocess」改成 Executor。一开始想沙箱起不来就退回直跑，这样开发省事，但这正好把闸门拆了：用户选了 workspace-write，命令仍会打到宿主。所以启动失败只返回说明，绝不降级。

另一处是只读档。容器 `--read-only` 之后，bash 连自己的临时文件都写不出，命令还没跑到用户脚本就失败。给 `/tmp` 留了一小块 tmpfs，`/etc` 和工作区挂载仍然只读。workspace-write 用 root 跑，是为了让 `rm /etc/hosts` 真的发生在容器副本里；代价是容器写回工作区的文件可能属主是 root。
