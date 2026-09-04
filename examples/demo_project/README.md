# Day 5–7 示例项目

故意在 `calc.add` 埋了 bug（用了减法），用于验收「跑测试 → 读报错 → 改代码 → 再跑 → 通过」闭环。

## Day 7 里程碑

在 TUI 中完成两个任务（工作区设为 `examples/demo_project`）：

1. **Bug 修复**：修复 `calc.add`，pytest 全部通过
2. **功能添加**：新增 `subtract(a, b)` 及对应 pytest 用例

```bash
MYCODER_WORKSPACE=examples/demo_project uv run mycoder
```

```bash
cd examples/demo_project
uv run pytest -v   # 修复前应失败
```
