"""Day 12 · 沙箱模式、挂载参数，以及 Docker 可用时的隔离验收。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mycoder.prompts.system import build_system_prompt, sandbox_section
from mycoder.sandbox.docker_exec import (
    DockerExecutor,
    ExecResult,
    annotate_sandbox_output,
    container_run_args,
    load_sandbox_mode,
    status_label,
)
from mycoder.tools import DEFAULT_TOOLS
from mycoder.tools.shell import BashParams, BashTool, format_command_result


def _docker_daemon_up() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def test_status_label_names_mode() -> None:
    assert status_label("off") == "沙箱 off"
    assert status_label("workspace-write") == "沙箱 workspace-write"
    assert status_label("readonly") == "沙箱 readonly"


def test_env_overrides_project_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MYCODER_HOME", str(home))
    (home / "config.toml").write_text('[sandbox]\nmode = "readonly"\n', encoding="utf-8")
    ws = tmp_path / "ws"
    (ws / ".mycoder").mkdir(parents=True)
    (ws / ".mycoder" / "config.toml").write_text(
        '[sandbox]\nmode = "workspace-write"\n',
        encoding="utf-8",
    )
    assert load_sandbox_mode(ws) == "workspace-write"
    monkeypatch.setenv("MYCODER_SANDBOX", "off")
    assert load_sandbox_mode(ws) == "off"


def test_project_config_overrides_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("MYCODER_HOME", str(home))
    monkeypatch.delenv("MYCODER_SANDBOX", raising=False)
    (home / "config.toml").write_text('[sandbox]\nmode = "off"\n', encoding="utf-8")
    ws = tmp_path / "ws"
    (ws / ".mycoder").mkdir(parents=True)
    (ws / ".mycoder" / "config.toml").write_text(
        '[sandbox]\nmode = "readonly"\n',
        encoding="utf-8",
    )
    assert load_sandbox_mode(ws) == "readonly"


def test_unknown_mode_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCODER_SANDBOX", "yolo")
    with pytest.raises(ValueError, match="未知沙箱模式"):
        load_sandbox_mode(tmp_path)


def test_workspace_write_mounts_only_workspace(tmp_path: Path) -> None:
    args = container_run_args(
        name="sbx",
        workspace=tmp_path,
        mode="workspace-write",
        image="mycoder-sandbox:dev",
    )
    assert args[args.index("--network") + 1] == "none"
    assert "--read-only" not in args
    mount = args[args.index("-v") + 1]
    assert mount == f"{tmp_path.resolve()}:/workspace"
    assert ".ssh" not in " ".join(args)
    assert str(Path.home()) not in " ".join(args)


def test_readonly_mount_is_read_only(tmp_path: Path) -> None:
    args = container_run_args(
        name="sbx",
        workspace=tmp_path,
        mode="readonly",
        image="mycoder-sandbox:dev",
    )
    assert "--read-only" in args
    mount = args[args.index("-v") + 1]
    assert mount.endswith(":/workspace:ro")
    assert args[args.index("--network") + 1] == "none"


def test_off_mode_has_no_sandbox_prompt() -> None:
    assert sandbox_section("off") is None
    prompt = build_system_prompt(DEFAULT_TOOLS, sandbox_mode="off")
    assert "## 沙箱" not in prompt


def test_sandbox_prompt_mentions_offline() -> None:
    prompt = build_system_prompt(DEFAULT_TOOLS, sandbox_mode="workspace-write")
    assert "无网络" in prompt
    assert "~/.ssh" in prompt
    readonly = sandbox_section("readonly")
    assert readonly is not None
    assert "只读" in readonly


def test_network_failure_is_explained() -> None:
    raw = "curl: (6) Could not resolve host: baidu.com\n"
    text = annotate_sandbox_output(raw, mode="workspace-write")
    assert "没有外网" in text
    assert "不要反复重试" in text
    assert annotate_sandbox_output(raw, mode="off") == raw


@pytest.mark.asyncio
async def test_bash_formats_sandbox_network_error() -> None:
    class _Fake:
        mode = "workspace-write"

        async def start(self) -> None:
            return

        async def aclose(self) -> None:
            return

        async def run(self, command: str, *, timeout: float) -> ExecResult:
            return ExecResult(6, "curl: (6) Could not resolve host: baidu.com\n")

    out = await BashTool(_Fake()).execute(BashParams(command="curl https://baidu.com"))
    assert "exit_code=6" in out
    assert "没有外网" in out


@pytest.mark.asyncio
async def test_sandbox_start_failure_does_not_fall_back_to_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_exec(args: list[str], *, timeout: float) -> SimpleNamespace:
        assert args[0] == "docker"
        return SimpleNamespace(returncode=1, output="Cannot connect to the Docker daemon")

    monkeypatch.setattr("mycoder.sandbox.docker_exec._exec", _fake_exec)
    executor = DockerExecutor(tmp_path, "workspace-write")
    result = await executor.run("echo leaked", timeout=5)
    assert result.exit_code == 1
    assert "不会改在宿主执行" in result.output
    formatted = format_command_result(
        result,
        command="echo leaked",
        timeout=5,
        mode=executor.mode,
    )
    assert "exit_code=1" in formatted


@pytest.mark.skipif(not _docker_daemon_up(), reason="Docker 守护进程未运行")
@pytest.mark.asyncio
async def test_workspace_write_isolates_host(tmp_path: Path) -> None:
    executor = DockerExecutor(tmp_path, "workspace-write")
    host_hosts = Path("/etc/hosts").read_bytes()
    try:
        missing = await executor.run("cat ~/.ssh/id_rsa", timeout=30)
        assert missing.exit_code != 0
        assert "No such file" in missing.output or "not found" in missing.output.lower()

        removed = await executor.run(
            "rm -f /etc/hosts && test ! -e /etc/hosts && echo removed",
            timeout=30,
        )
        assert removed.exit_code == 0
        assert "removed" in removed.output
        assert Path("/etc/hosts").read_bytes() == host_hosts

        written = await executor.run("echo ok > sandbox_probe.txt", timeout=30)
        assert written.exit_code == 0
        assert (tmp_path / "sandbox_probe.txt").read_text(encoding="utf-8").strip() == "ok"
        await executor.run("rm -f sandbox_probe.txt", timeout=30)

        offline = await executor.run("curl -I --max-time 5 https://baidu.com", timeout=30)
        assert offline.exit_code != 0
        explained = format_command_result(
            offline,
            command="curl -I --max-time 5 https://baidu.com",
            timeout=30,
            mode="workspace-write",
        )
        assert "没有外网" in explained

        tools = await executor.run(
            "pytest --version && rg --version && git --version && node --version",
            timeout=60,
        )
        assert tools.exit_code == 0, tools.output
    finally:
        await executor.aclose()


@pytest.mark.skipif(not _docker_daemon_up(), reason="Docker 守护进程未运行")
@pytest.mark.asyncio
async def test_readonly_cannot_write_workspace(tmp_path: Path) -> None:
    executor = DockerExecutor(tmp_path, "readonly")
    try:
        denied = await executor.run("echo nope > /workspace/nope.txt", timeout=30)
        assert denied.exit_code != 0
        assert not (tmp_path / "nope.txt").exists()
        explained = format_command_result(
            denied,
            command="echo nope > /workspace/nope.txt",
            timeout=30,
            mode="readonly",
        )
        assert "只读" in explained
    finally:
        await executor.aclose()
