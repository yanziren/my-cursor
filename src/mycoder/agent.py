"""Day 3 · Agent Loop：智能体的心脏——连续工具调用直到任务完成或触达上限。"""

from mycoder.providers.ollama import OllamaProvider
from mycoder.tools.registry import ToolRegistry


class Agent:
    """最小 Agent Loop：扁平 messages 史 + while 循环 + 自然/硬性停止。"""

    def __init__(
        self,
        provider: OllamaProvider,
        registry: ToolRegistry,
        system_prompt: str,
        max_turns: int = 20,
        verbose: bool = False,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_turns = max_turns
        self.verbose = verbose
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]

    @property
    def tool_schemas(self) -> list[dict]:
        return self.registry.schemas()

    async def run(self, user_input: str) -> tuple[str, int]:
        """执行一轮用户任务，返回 (最终回答, 实际循环轮数)。"""
        self.messages.append({"role": "user", "content": user_input})

        for turn in range(1, self.max_turns + 1):
            resp = self.provider.chat(self.messages, tools=self.tool_schemas)
            self.messages.append(resp.message)

            if not resp.tool_calls:
                return resp.content or "", turn

            if self.verbose:
                print(f"[轮 {turn}] 模型请求 {len(resp.tool_calls)} 个工具调用")
            for call in resp.tool_calls:
                if self.verbose:
                    print(f"  → {call.function.name}({call.function.arguments})")
                result = await self.registry.dispatch(
                    call.function.name,
                    call.function.arguments,
                )
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": result,
                    }
                )

        return f"已达到最大轮数限制 (max_turns={self.max_turns})，任务未完成。", self.max_turns
