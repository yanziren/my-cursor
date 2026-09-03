"""Day 2 · 工具基类：Pydantic 参数模型同时生成 schema 与运行时校验。"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class ToolParams(BaseModel):
    """工具参数基类；无参工具用 EmptyParams。"""


class EmptyParams(ToolParams):
    """无参工具的占位参数模型。"""


class BaseTool(ABC):
    name: str
    description: str
    params_model: type[ToolParams]

    def schema(self) -> dict:
        """导出 OpenAI tools 格式，parameters 由 Pydantic 自动生成。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.params_model.model_json_schema(),
            },
        }

    @abstractmethod
    async def execute(self, params: ToolParams) -> str:
        """子类实现具体逻辑；入参已通过 model_validate。"""
