"""Day 5 · bash 工具：子进程执行、超时、输出截断、工作目录锁定。"""

import asyncio
import os
import signal

from pydantic import Field

from mycoder.tools.base import BaseTool, ToolParams
from mycoder.tools.files import workspace_root
from mycoder.tools.output import truncate_output

DEFAULT_TIMEOUT = 60


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
    description = (
        "在项目根目录执行 shell 命令，返回合并后的 stdout+stderr。"
        "改完代码后应用它跑测试、lint、git diff 等验证结果；"
        "不要用 bash 代替 read_file/grep/glob（专用工具输出更窄、更稳）。"
    )
    params_model = BashParams

    async def execute(self, params: ToolParams) -> str:
        assert isinstance(params, BashParams)
        cwd = workspace_root()
        if not cwd.is_dir():
            return f"工作目录不存在: {cwd}"

        proc = await asyncio.create_subprocess_shell(
            params.command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )

        try:
            stdout, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=params.timeout_seconds,
            )
        except TimeoutError:
            await _kill_process_group(proc)
            return (
                f"命令超时（>{params.timeout_seconds}s 已终止）: {params.command!r}\n"
                "请缩短任务、拆分命令，或增大 timeout_seconds。"
            )

        output = stdout.decode("utf-8", errors="replace")
        exit_code = proc.returncode if proc.returncode is not None else -1
        truncated = truncate_output(output)
        prefix = f"exit_code={exit_code}\n"
        if truncated != output:
            prefix += "[输出已截断，保头保尾；关键报错通常在尾部]\n"
        return prefix + truncated


async def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        if hasattr(os, "getpgid") and proc.pid:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        pass
    try:
        await proc.wait()
    except ProcessLookupError:
        pass
