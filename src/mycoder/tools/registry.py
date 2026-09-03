"""Day 2 · 工具注册表：schema 汇总与按名分发。"""

import json

from pydantic import ValidationError

from mycoder.tools.base import BaseTool, ToolParams


class ToolRegistry:
    def __init__(self, tools: list[BaseTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    async def dispatch(self, name: str, arguments: str) -> str:
        tool = self._tools.get(name)
        if tool is None:
            return f"未知工具: {name}"

        try:
            raw = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError as exc:
            return f"参数 JSON 解析失败: {exc}"

        try:
            params: ToolParams = tool.params_model.model_validate(raw)
        except ValidationError as exc:
            return f"参数校验失败:\n{exc}"

        return await tool.execute(params)
