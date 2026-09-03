"""mycoder 工具集。"""

from mycoder.tools.base import BaseTool, EmptyParams, ToolParams
from mycoder.tools.registry import ToolRegistry
from mycoder.tools.toys import CalculatorTool, GetCurrentTimeTool

DEFAULT_TOOLS: list[BaseTool] = [GetCurrentTimeTool(), CalculatorTool()]

__all__ = [
    "DEFAULT_TOOLS",
    "BaseTool",
    "CalculatorTool",
    "EmptyParams",
    "GetCurrentTimeTool",
    "ToolParams",
    "ToolRegistry",
]
