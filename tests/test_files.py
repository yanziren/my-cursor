"""Day 4 · 文件工具 harness 单测。"""

from pathlib import Path

import pytest

from mycoder.tools.files import (
    EditFileParams,
    EditFileTool,
    ReadFileParams,
    ReadFileTool,
    WriteFileParams,
    WriteFileTool,
    resolve_in_workspace,
    workspace_root,
)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("MYCODER_WORKSPACE", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_resolve_blocks_escape(ws: Path) -> None:
    _, err = resolve_in_workspace("../outside.txt")
    assert err is not None
    assert "越界" in err


@pytest.mark.asyncio
async def test_write_and_read(ws: Path) -> None:
    write = WriteFileTool()
    msg = await write.execute(WriteFileParams(path="a.txt", content="line1\nline2\n"))
    assert "创建" in msg

    read = ReadFileTool()
    out = await read.execute(ReadFileParams(path="a.txt"))
    assert "1|line1" in out
    assert "2|line2" in out


@pytest.mark.asyncio
async def test_edit_unique_success(ws: Path) -> None:
    (ws / "config.py").write_text("DEBUG = True\n", encoding="utf-8")
    edit = EditFileTool()
    msg = await edit.execute(
        EditFileParams(path="config.py", old_string="DEBUG = True", new_string="DEBUG = False")
    )
    assert "已编辑" in msg
    assert (ws / "config.py").read_text(encoding="utf-8") == "DEBUG = False\n"


@pytest.mark.asyncio
async def test_edit_ambiguous_without_replace_all(ws: Path) -> None:
    (ws / "dup.py").write_text("x=1\nx=1\n", encoding="utf-8")
    edit = EditFileTool()
    msg = await edit.execute(
        EditFileParams(path="dup.py", old_string="x=1", new_string="x=2")
    )
    assert "出现 2 次" in msg
    assert (ws / "dup.py").read_text(encoding="utf-8") == "x=1\nx=1\n"


@pytest.mark.asyncio
async def test_edit_replace_all(ws: Path) -> None:
    (ws / "dup.py").write_text("x=1\nx=1\n", encoding="utf-8")
    edit = EditFileTool()
    msg = await edit.execute(
        EditFileParams(
            path="dup.py",
            old_string="x=1",
            new_string="x=2",
            replace_all=True,
        )
    )
    assert "替换 2 处" in msg
    assert (ws / "dup.py").read_text(encoding="utf-8") == "x=2\nx=2\n"


@pytest.mark.asyncio
async def test_edit_missing_file_guidance(ws: Path) -> None:
    edit = EditFileTool()
    msg = await edit.execute(
        EditFileParams(path="nope.py", old_string="a", new_string="b")
    )
    assert "不存在" in msg
    assert "read_file" in msg or "write_file" in msg


@pytest.mark.asyncio
async def test_read_truncation_notice(ws: Path) -> None:
    lines = "\n".join(f"line{i}" for i in range(2500))
    (ws / "big.txt").write_text(lines, encoding="utf-8")
    out = await ReadFileTool().execute(ReadFileParams(path="big.txt"))
    assert "截断" in out or "后续还有" in out
    assert "1|line0" in out


def test_workspace_root_env(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYCODER_WORKSPACE", str(ws))
    assert workspace_root() == ws.resolve()
