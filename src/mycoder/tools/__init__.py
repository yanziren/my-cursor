"""mycoder 工具集。"""

from mycoder.tools.base import BaseTool, EmptyParams, ToolParams
from mycoder.tools.files import EditFileTool, ReadFileTool, WriteFileTool
from mycoder.tools.registry import ToolRegistry
from mycoder.tools.toys import CalculatorTool, GetCurrentTimeTool

DEFAULT_TOOLS: list[BaseTool] = [
    ReadFileTool(),
    WriteFileTool(),
    EditFileTool(),
    GetCurrentTimeTool(),
    CalculatorTool(),
]

__all__ = [
    "DEFAULT_TOOLS",
    "BaseTool",
    "CalculatorTool",
    "EditFileTool",
    "EmptyParams",
    "GetCurrentTimeTool",
    "ReadFileTool",
    "ToolParams",
    "ToolRegistry",
    "WriteFileTool",
]
