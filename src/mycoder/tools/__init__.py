"""mycoder 工具集。"""

from mycoder.sandbox.docker_exec import Executor
from mycoder.tools.base import BaseTool, EmptyParams, ToolParams
from mycoder.tools.files import EditFileTool, ReadFileTool, WriteFileTool
from mycoder.tools.registry import ToolRegistry
from mycoder.tools.search import GlobTool, GrepTool
from mycoder.tools.shell import BashTool
from mycoder.tools.toys import CalculatorTool, GetCurrentTimeTool


def build_default_tools(executor: Executor | None = None) -> list[BaseTool]:
    """每次新建一套工具。沙箱执行器按会话注入，避免全局共用一只容器。"""
    return [
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        BashTool(executor),
        GlobTool(),
        GrepTool(),
        GetCurrentTimeTool(),
        CalculatorTool(),
    ]


DEFAULT_TOOLS: list[BaseTool] = build_default_tools()

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
    "build_default_tools",
]
