"""Day 5 · bash / glob / grep harness 单测。"""

import asyncio
from pathlib import Path

import pytest

from mycoder.tools.output import truncate_output
from mycoder.tools.search import GlobParams, GlobTool, GrepParams, GrepTool
from mycoder.tools.shell import BashParams, BashTool


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MYCODER_WORKSPACE", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_bash_echo(ws: Path) -> None:
    out = await BashTool().execute(BashParams(command="echo hello"))
    assert "exit_code=0" in out
    assert "hello" in out


@pytest.mark.asyncio
async def test_bash_timeout(ws: Path) -> None:
    out = await BashTool().execute(
        BashParams(command="sleep 999", timeout_seconds=1)
    )
    assert "超时" in out


@pytest.mark.asyncio
async def test_bash_output_truncation(ws: Path) -> None:
    out = await BashTool().execute(BashParams(command="seq 1 2500"))
    assert "截断" in out
    assert "exit_code=0" in out


@pytest.mark.asyncio
async def test_glob_find_py(ws: Path) -> None:
    (ws / "a.py").write_text("x", encoding="utf-8")
    (ws / "b.txt").write_text("x", encoding="utf-8")
    out = await GlobTool().execute(GlobParams(pattern="*.py"))
    assert "a.py" in out
    assert "b.txt" not in out


@pytest.mark.asyncio
async def test_grep_find_pattern(ws: Path) -> None:
    (ws / "use_requests.py").write_text("import requests\n", encoding="utf-8")
    out = await GrepTool().execute(GrepParams(pattern="requests"))
    assert "use_requests.py" in out
    assert "requests" in out


def test_truncate_keeps_head_and_tail() -> None:
    text = "\n".join(f"line{i}" for i in range(3000))
    out = truncate_output(text, max_lines=100, head_lines=10, tail_lines=10)
    assert "截断" in out
    assert "line0" in out
    assert "line2999" in out
