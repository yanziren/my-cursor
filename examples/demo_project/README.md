# Day 5 示例项目

故意在 `calc.add` 埋了 bug（用了减法），用于验收「跑测试 → 读报错 → 改代码 → 再跑 → 通过」闭环。

```bash
cd examples/demo_project
uv run pytest -v
```

智能体验收提示词（工作区设为 `examples/demo_project`）：

```text
修复失败的测试，改完后用 pytest 验证通过
```
