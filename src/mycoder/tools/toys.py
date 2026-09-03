"""Day 2 · 玩具工具：get_current_time 与 calculator。"""

import ast
import operator
from datetime import UTC, datetime

from pydantic import Field

from mycoder.tools.base import BaseTool, EmptyParams, ToolParams

_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        return _BINARY_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    raise ValueError("仅支持数字与 + - * / // % ** 运算")


class GetCurrentTimeTool(BaseTool):
    name = "get_current_time"
    description = (
        "获取当前日期与时间（含时区）。"
        "当用户询问现在几点、今天几号、当前时间时使用；"
        "问候、闲聊或不需要真实时间的问题不要调用。"
    )
    params_model = EmptyParams

    async def execute(self, params: ToolParams) -> str:
        now = datetime.now(UTC).astimezone()
        return now.strftime("%Y-%m-%d %H:%M:%S %Z")


class CalculatorParams(ToolParams):
    expression: str = Field(
        description="要计算的数学表达式，支持 + - * / // % ** 与括号，例如 123 * 456"
    )


class CalculatorTool(BaseTool):
    name = "calculator"
    description = (
        "计算数学表达式并返回数值结果。"
        "当用户要求做算术或需要精确数值时使用；"
        "纯文字解释、问候或与计算无关的问题不要调用。"
    )
    params_model = CalculatorParams

    async def execute(self, params: ToolParams) -> str:
        assert isinstance(params, CalculatorParams)
        try:
            tree = ast.parse(params.expression, mode="eval")
            value = _safe_eval(tree)
        except (SyntaxError, ValueError, TypeError, ZeroDivisionError) as exc:
            return f"无法计算表达式 {params.expression!r}: {exc}"
        if value.is_integer():
            return str(int(value))
        return str(value)
