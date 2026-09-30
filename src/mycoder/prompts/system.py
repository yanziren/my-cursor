"""Day 6 · 系统提示词组装：身份 → 准则 → 工具 → 安全 → AGENTS.md → 环境。"""

import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from mycoder.prompts.agents_md import collect_agents_md
from mycoder.sandbox.docker_exec import SandboxMode
from mycoder.tools.base import BaseTool
from mycoder.tools.files import workspace_root

MAX_PROMPT_CHARS = 4500  # 粗估 1500 token（字符数 / 3）


def _run_git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def collect_environment(workspace: Path) -> str:
    """环境信息：OS、cwd、git、日期（精确到天）、顶层目录一览。"""
    lines = [
        f"- 操作系统: {platform.system()} {platform.release()}",
        f"- 工作区: {workspace}",
        f"- 今天日期: {datetime.now(tz=UTC).date().isoformat()}",
    ]

    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], workspace)
    if branch:
        lines.append(f"- 当前 git 分支: {branch}")
        status = _run_git(["status", "--short"], workspace)
        if status:
            preview = status.splitlines()[:8]
            lines.append("- git 状态:\n```\n" + "\n".join(preview) + "\n```")

    try:
        entries = sorted(workspace.iterdir(), key=lambda p: p.name)[:30]
        names = [f"{p.name}/" if p.is_dir() else p.name for p in entries]
        lines.append("- 工作区顶层: " + ", ".join(names))
    except OSError:
        pass

    return "\n".join(lines)


def _tool_guide(tools: list[BaseTool]) -> str:
    lines = []
    for tool in tools:
        first_sentence = tool.description.split("。")[0].strip()
        lines.append(f"- **{tool.name}**: {first_sentence}。")
    return "\n".join(lines)


def sandbox_section(mode: SandboxMode) -> str | None:
    """沙箱开启时告诉模型：没网、没有宿主家目录、readonly 不能写。"""
    if mode == "off":
        return None
    lines = [
        "## 沙箱",
        f"- bash 在 Docker 容器内执行，模式 {mode}，默认无网络。",
        (
            "- curl、pip install、npm install 会失败。看到无网络后不要重试同类命令，"
            "改用容器里已有的 python、git、rg、pytest，或告诉用户把沙箱设为 off。"
        ),
        "- 宿主家目录和 ~/.ssh 在容器里不存在，不要去读。",
        "- 工作区在容器内的路径是 /workspace。",
    ]
    if mode == "readonly":
        lines.append("- 容器和工作区都是只读的，不要改文件，不要用重定向写入。")
    else:
        lines.append(
            "- 只有工作区挂载可写。改 /workspace 里的文件会写回宿主项目；"
            "改 /etc 等其他路径只影响这只容器，销毁后消失。"
        )
    return "\n".join(lines)


def build_system_prompt(
    tools: list[BaseTool],
    workspace: Path | None = None,
    *,
    include_agents: bool = True,
    include_environment: bool = True,
    minimal: bool = False,
    sandbox_mode: SandboxMode = "off",
) -> str:
    """拼装系统提示词；minimal=True 时仅保留极简身份（供对比实验）。"""
    ws = (workspace or workspace_root()).resolve()

    if minimal:
        return "你是一个简洁的中文助手，直接回答用户问题。"

    identity = (
        "你是 mycoder，一个编程智能体 harness：帮用户在真实代码仓库里完成读代码、改代码、"
        "跑命令、验证结果等工程任务。回答简洁，以完成任务为准。"
    )

    work_rules = (
        "## 工作准则\n"
        "- 先探索再动手：大仓库用 glob/grep 定位，再 read_file。\n"
        "- 局部修改优先 edit_file；只有新建或整文件重写才用 write_file。\n"
        "- 改完代码必须用 bash 跑测试或相关命令验证，通过后再宣布完成。\n"
        "- 工具失败时读错误信息，换思路重试，不要无脑重复同一调用。\n"
        "- 问候、概念解释等不涉及仓库的任务，直接回答，不要滥用工具。"
    )

    tool_section = "## 工具使用指南\n" + _tool_guide(tools)

    security = (
        "## 安全边界\n"
        "- 不要读取或修改 .env、密钥、凭证文件。\n"
        "- 不要执行明显破坏性的 bash（如 rm -rf、强制 push），除非用户明确要求。"
    )

    parts = [identity, work_rules, tool_section, security]
    sandbox = sandbox_section(sandbox_mode)
    if sandbox:
        parts.append(sandbox)

    if include_agents:
        agents = collect_agents_md(ws)
        if agents:
            parts.append("## 项目约定（AGENTS.md）\n" + agents)

    if include_environment:
        parts.append("## 当前环境\n" + collect_environment(ws))

    prompt = "\n\n".join(parts)

    if len(prompt) > MAX_PROMPT_CHARS:
        # 环境块最长，优先压缩目录一览
        prompt = build_system_prompt(
            tools,
            ws,
            include_agents=include_agents,
            include_environment=False,
            minimal=False,
            sandbox_mode=sandbox_mode,
        )
        if include_environment:
            env = collect_environment(ws).splitlines()[:4]
            prompt += "\n\n## 当前环境\n" + "\n".join(env)

    return prompt


def estimate_tokens(text: str) -> int:
    """Day 8 之前粗估：字符数 / 3。"""
    return len(text) // 3
