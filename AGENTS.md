# mycoder 项目约定

- **代码注释一律使用中文**（含新增函数、类、模块 docstring）。
- 包管理使用 **uv**（`uv add` / `uv run`），不要使用 pip 或 poetry。
- 运行测试：`uv run pytest`；示例闭环：`MYCODER_WORKSPACE=examples/demo_project uv run mycoder`。
- 提交前：`uv run ruff check`。
