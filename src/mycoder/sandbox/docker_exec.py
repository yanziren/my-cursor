"""Day 12 · Docker 沙箱执行器。

bash 只调用 Executor。off 走宿主 subprocess；另外两档用同一只持久容器，
会话开始时启动、结束时销毁。容器里没有宿主家目录，默认 --network none。
沙箱启动失败时把原因交回调用方，绝不静默退回宿主执行。
"""

from __future__ import annotations

import asyncio
import os
import signal
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from mycoder.permissions.config import default_config_path
from mycoder.tools.files import workspace_root

SandboxMode = Literal["off", "workspace-write", "readonly"]
MODES: tuple[SandboxMode, ...] = ("off", "workspace-write", "readonly")
DEFAULT_IMAGE = "mycoder-sandbox:dev"

# coreutils timeout 杀进程后的退出码；外层再把它说成人话
TIMEOUT_EXIT = 124


class SandboxError(RuntimeError):
    """沙箱起不来。文案直接给用户和模型看。"""


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    output: str
    timed_out: bool = False


class Executor(Protocol):
    mode: str

    async def start(self) -> None: ...

    async def run(self, command: str, *, timeout: float) -> ExecResult: ...

    async def aclose(self) -> None: ...


def parse_sandbox_mode(raw: str) -> SandboxMode:
    value = raw.strip().lower()
    if value == "off" or value == "workspace-write" or value == "readonly":
        return value
    raise ValueError(f"未知沙箱模式 {raw!r}，只能是 off、workspace-write 或 readonly")


def _mode_from_toml(path: Path) -> SandboxMode | None:
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"无法解析沙箱配置 {path}: {exc}") from exc
    sandbox = data.get("sandbox") or {}
    if not isinstance(sandbox, dict) or "mode" not in sandbox:
        return None
    raw = sandbox.get("mode")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{path} 的 sandbox.mode 必须是非空字符串")
    return parse_sandbox_mode(raw)


def load_sandbox_mode(workspace: Path) -> SandboxMode:
    """环境变量优先，其次项目 .mycoder/config.toml，再次用户全局配置，默认 off。"""
    env = os.getenv("MYCODER_SANDBOX")
    if env is not None and env.strip():
        return parse_sandbox_mode(env)
    for path in (workspace / ".mycoder" / "config.toml", default_config_path()):
        mode = _mode_from_toml(path)
        if mode is not None:
            return mode
    return "off"


def status_label(mode: str) -> str:
    return f"沙箱 {mode}"


def make_executor(mode: SandboxMode, workspace: Path) -> Executor:
    if mode == "off":
        return LocalExecutor()
    image = os.getenv("MYCODER_SANDBOX_IMAGE", DEFAULT_IMAGE).strip() or DEFAULT_IMAGE
    return DockerExecutor(workspace, mode, image=image)


def container_run_args(
    *,
    name: str,
    workspace: Path,
    mode: SandboxMode,
    image: str,
) -> list[str]:
    """拼 docker run。只挂工作区，不挂家目录；网络默认切断。"""
    if mode == "off":
        raise ValueError("off 模式不启动容器")
    mount = str(workspace.resolve())
    args = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        "--label",
        "mycoder.sandbox=1",
        "-w",
        "/workspace",
    ]
    if mode == "readonly":
        # 根文件系统只读。/tmp 留一块小 tmpfs，否则 bash 自己的临时文件都建不了；
        # /etc 仍然只读，宿主路径除工作区外都不可见。
        args += [
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,size=64m",
            "-v",
            f"{mount}:/workspace:ro",
        ]
    else:
        # 容器自己的 /etc、/root 可写，但是容器内的副本，销毁即消失。
        args += ["-v", f"{mount}:/workspace"]
    args += ["--entrypoint", "sleep", image, "infinity"]
    return args


def annotate_sandbox_output(output: str, *, mode: str) -> str:
    """把内核的英文失败翻译成模型能照着改策略的一句中文。"""
    if mode == "off" or not output:
        return output
    lowered = output.lower()
    notes: list[str] = []
    network_markers = (
        "network is unreachable",
        "network unreachable",
        "could not resolve",
        "couldn't resolve",
        "temporary failure in name resolution",
        "name or service not known",
        "no route to host",
        "failed to connect",
        "couldn't connect",
    )
    if any(marker in lowered for marker in network_markers):
        notes.append(
            "[沙箱] 当前容器没有外网（--network none）。"
            "不要反复重试 curl、pip、npm；改用镜像里已有的 python、git、rg、pytest，"
            "或告诉用户需要把沙箱设为 off。"
        )
    if mode == "readonly" and "read-only file system" in lowered:
        notes.append("[沙箱] 当前是 readonly，容器和工作区都只读。不要改文件。")
    if not notes:
        return output
    return output.rstrip() + "\n" + "\n".join(notes) + "\n"


class LocalExecutor:
    """宿主直跑，行为与 Day 5 的 bash 一致。"""

    mode = "off"

    async def start(self) -> None:
        return

    async def aclose(self) -> None:
        return

    async def run(self, command: str, *, timeout: float) -> ExecResult:
        cwd = workspace_root()
        if not cwd.is_dir():
            return ExecResult(1, f"工作目录不存在: {cwd}")

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            await _kill_process_group(proc)
            return ExecResult(-1, "", timed_out=True)

        output = (stdout or b"").decode("utf-8", errors="replace")
        code = proc.returncode if proc.returncode is not None else -1
        return ExecResult(code, output)


class DockerExecutor:
    """一只持久容器承接本会话的全部 bash。以 root 跑，这样容器内 /etc 可写，爆炸半径仍留在容器里。"""

    def __init__(self, workspace: Path, mode: SandboxMode, image: str = DEFAULT_IMAGE) -> None:
        if mode == "off":
            raise ValueError("DockerExecutor 不用于 off 模式")
        self.mode: SandboxMode = mode
        self.workspace = workspace.resolve()
        self.image = image
        self.name = f"mycoder-sbx-{uuid.uuid4().hex[:12]}"
        self._lock = asyncio.Lock()
        self._started = False
        self._closed = False
        self._start_error: str | None = None

    async def start(self) -> None:
        async with self._lock:
            if self._closed:
                raise SandboxError("沙箱容器已经销毁")
            if self._start_error:
                raise SandboxError(self._start_error)
            if self._started:
                return
            try:
                await self._start_locked()
            except SandboxError as exc:
                self._start_error = str(exc)
                raise
            self._started = True

    async def _start_locked(self) -> None:
        info = await _exec(["docker", "info"], timeout=15)
        if info.returncode != 0:
            detail = info.output.strip() or "docker info 失败"
            raise SandboxError(
                "Docker 守护进程没在跑，沙箱无法启动，命令不会改在宿主执行。"
                f"请打开 Docker，或设置 MYCODER_SANDBOX=off。\n{detail}"
            )
        await ensure_image(self.image)
        args = container_run_args(
            name=self.name,
            workspace=self.workspace,
            mode=self.mode,
            image=self.image,
        )
        created = await _exec(args, timeout=60)
        if created.returncode != 0:
            raise SandboxError(
                f"沙箱容器启动失败（模式 {self.mode}）:\n{created.output.strip()}"
            )

    async def run(self, command: str, *, timeout: float) -> ExecResult:
        try:
            await self.start()
        except SandboxError as exc:
            return ExecResult(1, str(exc))

        seconds = max(1, int(timeout))
        # 在容器内用 timeout 杀掉命令本身，不动充当 init 的 sleep。
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            "-w",
            "/workspace",
            self.name,
            "timeout",
            "--signal=KILL",
            str(seconds),
            "bash",
            "-lc",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout + 5)
        except TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except ProcessLookupError:
                pass
            return ExecResult(-1, "", timed_out=True)

        output = (stdout or b"").decode("utf-8", errors="replace")
        code = proc.returncode if proc.returncode is not None else -1
        return ExecResult(code, output, timed_out=code == TIMEOUT_EXIT)

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            self._started = False
        # 没创建过也 rm -f：docker 对未知名字返回非 0，忽略即可。
        try:
            await _exec(["docker", "rm", "-f", self.name], timeout=30)
        except SandboxError:
            return


@dataclass(frozen=True)
class _Completed:
    returncode: int
    output: str


async def ensure_image(image: str = DEFAULT_IMAGE) -> None:
    """镜像不存在才构建。构建上下文只有 Dockerfile，不把整个仓库送进 docker。"""
    inspected = await _exec(["docker", "image", "inspect", image], timeout=20)
    if inspected.returncode == 0:
        return
    dockerfile = Path(__file__).with_name("Dockerfile")
    if not dockerfile.is_file():
        raise SandboxError(f"找不到沙箱 Dockerfile: {dockerfile}")
    built = await _exec(
        ["docker", "build", "-t", image, "-f", str(dockerfile), str(dockerfile.parent)],
        timeout=900,
    )
    if built.returncode != 0:
        raise SandboxError(f"沙箱镜像构建失败:\n{built.output.strip()}")


async def _exec(args: list[str], *, timeout: float) -> _Completed:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError as exc:
        raise SandboxError(
            "找不到 docker 命令。请先安装并启动 Docker，或设置 MYCODER_SANDBOX=off。"
        ) from exc
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        try:
            await proc.wait()
        except ProcessLookupError:
            pass
        shown = " ".join(args[:2])
        raise SandboxError(f"docker 命令超时（>{timeout:.0f}s）: {shown}") from None
    output = (stdout or b"").decode("utf-8", errors="replace")
    code = proc.returncode if proc.returncode is not None else -1
    return _Completed(code, output)


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
