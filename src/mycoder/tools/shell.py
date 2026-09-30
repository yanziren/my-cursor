"""Day 12 · bash 工具：只调 Executor，沙箱与宿主直跑由配置决定。"""

from pydantic import Field

from mycoder.sandbox.docker_exec import (
    ExecResult,
    Executor,
    LocalExecutor,
    annotate_sandbox_output,
)
from mycoder.tools.base import BaseTool, ToolParams
from mycoder.tools.output import truncate_output

DEFAULT_TIMEOUT = 60

_HOST_DESCRIPTION = (
    "在项目根目录执行 shell 命令，返回合并后的 stdout+stderr。"
    "改完代码后应用它跑测试、lint、git diff 等验证结果；"
    "不要用 bash 代替 read_file/grep/glob（专用工具输出更窄、更稳）。"
)
_SANDBOX_DESCRIPTION = (
    "在 Docker 沙箱内执行 shell 命令，返回合并后的 stdout+stderr。"
    "默认没有外网；curl、pip、npm 失败时不要重试，告诉用户或改用镜像里已有的 python、git、rg、pytest。"
    "宿主家目录不在容器里，不要去读 ~/.ssh。"
    "不要用 bash 代替 read_file/grep/glob。"
)


class BashParams(ToolParams):
    command: str = Field(description="要在项目根目录执行的 shell 命令，例如 uv run pytest -v")
    timeout_seconds: int = Field(
        default=DEFAULT_TIMEOUT,
        ge=1,
        le=600,
        description="超时秒数，默认 60，最大 600",
    )


class BashTool(BaseTool):
    name = "bash"
    description = _HOST_DESCRIPTION
    params_model = BashParams

    def __init__(self, executor: Executor | None = None) -> None:
        self.executor = executor or LocalExecutor()
        if self.executor.mode != "off":
            self.description = _SANDBOX_DESCRIPTION

    async def execute(self, params: ToolParams) -> str:
        assert isinstance(params, BashParams)
        result = await self.executor.run(
            params.command,
            timeout=float(params.timeout_seconds),
        )
        return format_command_result(
            result,
            command=params.command,
            timeout=params.timeout_seconds,
            mode=self.executor.mode,
        )


def format_command_result(
    result: ExecResult,
    *,
    command: str,
    timeout: float,
    mode: str,
) -> str:
    if result.timed_out:
        return (
            f"命令超时（>{timeout:g}s 已终止）: {command!r}\n"
            "请缩短任务、拆分命令，或增大 timeout_seconds。"
        )
    truncated = truncate_output(result.output)
    prefix = f"exit_code={result.exit_code}\n"
    if truncated != result.output:
        prefix += "[输出已截断，保头保尾；关键报错通常在尾部]\n"
    body = prefix + truncated
    return annotate_sandbox_output(body, mode=mode)
