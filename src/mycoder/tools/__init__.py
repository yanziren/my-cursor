"""mycoder 工具集。"""

from mycoder.tools.base import BaseTool, EmptyParams, ToolParams
from mycoder.tools.files import EditFileTool, ReadFileTool, WriteFileTool
from mycoder.tools.registry import ToolRegistry
from mycoder.tools.search import GlobTool, GrepTool
from mycoder.tools.shell import BashTool
from mycoder.tools.toys import CalculatorTool, GetCurrentTimeTool

DEFAULT_TOOLS: list[BaseTool] = [
    ReadFileTool(),
    WriteFileTool(),
    EditFileTool(),
    BashTool(),
    GlobTool(),
    GrepTool(),
    GetCurrentTimeTool(),
    CalculatorTool(),
]

__all__ = [
    "DEFAULT_TOOLS",
    "BaseTool",
    "BashTool",
    "CalculatorTool",
    "EditFileTool",
    "EmptyParams",
    "GetCurrentTimeTool",
    "GlobTool",
    "GrepTool",
    "ReadFileTool",
    "ToolParams",
    "ToolRegistry",
    "WriteFileTool",
]
