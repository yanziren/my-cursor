"""Day 5 · glob / grep 搜索工具。"""

import asyncio
import shutil

from pydantic import Field

from mycoder.tools.base import BaseTool, ToolParams
from mycoder.tools.files import resolve_in_workspace, workspace_root
from mycoder.tools.output import truncate_output

GREP_MAX_MATCHES = 200


class GlobParams(ToolParams):
    pattern: str = Field(
        description='文件名 glob 模式，相对 path，例如 "*.py" 或 "**/*.md"'
    )
    path: str = Field(default=".", description="起始目录，相对项目根，默认 .")


class GrepParams(ToolParams):
    pattern: str = Field(description="正则表达式，搜索文件内容")
    path: str = Field(default=".", description="搜索目录，相对项目根")
    glob: str | None = Field(
        default=None,
        description='可选文件过滤 glob，例如 "*.py"',
    )


class GlobTool(BaseTool):
    name = "glob"
    description = (
        "按文件名模式查找文件，返回相对项目根的路径列表。"
        "当不知道文件在哪、需要按名称定位时使用；"
        "搜文件内容请用 grep，查看内容请用 read_file。"
    )
    params_model = GlobParams

    async def execute(self, params: ToolParams) -> str:
        assert isinstance(params, GlobParams)
        base, err = resolve_in_workspace(params.path)
        if err:
            return err
        assert base is not None

        if not base.is_dir():
            return f"不是目录: {params.path}"

        root = workspace_root()
        matches: list[str] = []
        for p in sorted(base.glob(params.pattern)):
            if p.is_file():
                matches.append(p.relative_to(root).as_posix())

        if not matches:
            return f"未找到匹配 {params.pattern!r} 的文件（起始 {params.path}）"
        if len(matches) > 500:
            head = matches[:250]
            tail = matches[-250:]
            omitted = len(matches) - 500
            lines = head + [f"... 省略 {omitted} 条 ..."] + tail
            return "\n".join(lines)
        return "\n".join(matches)


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "在文件内容中按正则搜索，返回 文件:行号:内容 格式（底层 ripgrep）。"
        "当需要找符号、字符串、库引用时使用；"
        "不要用 grep 代替 read_file 读全文。"
    )
    params_model = GrepParams

    async def execute(self, params: ToolParams) -> str:
        assert isinstance(params, GrepParams)
        base, err = resolve_in_workspace(params.path)
        if err:
            return err
        assert base is not None

        if not base.exists():
            return f"路径不存在: {params.path}"

        rg = shutil.which("rg")
        if rg:
            cmd = [rg, "--line-number", "--no-heading", "--color=never", params.pattern, str(base)]
            if params.glob:
                cmd.insert(1, f"--glob={params.glob}")
        else:
            # 无 rg 时降级 grep -rn（macOS/BSD grep）
            cmd = ["grep", "-rn", params.pattern, str(base)]
            if params.glob:
                return "本机未安装 ripgrep (rg)，grep 降级模式不支持 glob 过滤，请安装 rg 或去掉 glob。"

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workspace_root(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode or 0

        if exit_code == 1 or not output:
            return f"未找到匹配 {params.pattern!r}（搜索 {params.path}）"
        if exit_code > 1:
            return f"搜索失败 (exit {exit_code}): {output or '未知错误'}"

        lines = output.splitlines()
        if len(lines) > GREP_MAX_MATCHES:
            shown = lines[:GREP_MAX_MATCHES]
            body = "\n".join(shown)
            body += f"\n[... 仅显示前 {GREP_MAX_MATCHES} 条，共 {len(lines)} 条 ...]"
        else:
            body = output

        return truncate_output(body)
