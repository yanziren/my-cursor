"""Day 4 · 文件工具集：read / write / edit + 工作区边界防护。"""

import os
from pathlib import Path

from pydantic import Field

from mycoder.tools.base import BaseTool, ToolParams

DEFAULT_READ_LIMIT = 2000


def workspace_root() -> Path:
    return Path(os.getenv("MYCODER_WORKSPACE", Path.cwd())).resolve()


def resolve_in_workspace(relative: str) -> tuple[Path | None, str | None]:
    """把相对路径解析到工作区内；越界或非法时返回 (None, 错误文案)。"""
    root = workspace_root()
    candidate = Path(relative)
    if candidate.is_absolute():
        return None, f"请使用相对项目根的路径，不要传绝对路径: {relative}"

    try:
        target = (root / candidate).resolve()
    except (OSError, ValueError) as exc:
        return None, f"路径无效 {relative}: {exc}"

    if not target.is_relative_to(root):
        return (
            None,
            f"路径越界：{relative} 解析后在项目根外（根目录 {root}），拒绝访问。",
        )
    return target, None


def format_numbered_lines(lines: list[str], start_line: int = 1) -> str:
    return "\n".join(f"{i}|{line}" for i, line in enumerate(lines, start=start_line))


class ReadFileParams(ToolParams):
    path: str = Field(description="要读取的文件路径，相对项目根")
    offset: int = Field(default=1, ge=1, description="起始行号（1-based）")
    limit: int = Field(
        default=DEFAULT_READ_LIMIT,
        ge=1,
        le=DEFAULT_READ_LIMIT,
        description=f"最多读取行数，上限 {DEFAULT_READ_LIMIT}",
    )


class WriteFileParams(ToolParams):
    path: str = Field(description="要写入的文件路径，相对项目根；不存在则创建")
    content: str = Field(description="写入的全文内容")


class EditFileParams(ToolParams):
    path: str = Field(description="要编辑的文件路径，相对项目根")
    old_string: str = Field(description="要被替换的原文，必须与文件内容精确匹配（含空格与缩进）")
    new_string: str = Field(description="替换后的新文本")
    replace_all: bool = Field(
        default=False,
        description="为 true 时替换所有匹配；默认 false，要求 old_string 在文件中恰好出现一次",
    )


class ReadFileTool(BaseTool):
    name = "read_file"
    description = (
        "读取文本文件并返回带行号的内容（格式：行号|内容）。"
        "编辑文件前必须先 read_file 获取最新内容与精确文本。"
        "当需要查看、总结或对比文件时使用。"
    )
    params_model = ReadFileParams

    async def execute(self, params: ToolParams) -> str:
        assert isinstance(params, ReadFileParams)
        file_path, err = resolve_in_workspace(params.path)
        if err:
            return err
        assert file_path is not None

        if not file_path.is_file():
            return f"文件不存在或不是普通文件: {params.path}。请确认路径，或先用 write_file 创建。"

        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"无法以 UTF-8 读取文件: {params.path}（可能是二进制文件）"
        except OSError as exc:
            return f"读取文件失败 {params.path}: {exc}"

        if not text:
            return "（空文件）"

        all_lines = text.splitlines()
        total = len(all_lines)
        start_idx = params.offset - 1
        if start_idx >= total:
            return f"offset={params.offset} 超出文件总行数 {total}，请先 read_file 确认范围。"

        slice_lines = all_lines[start_idx : start_idx + params.limit]
        body = format_numbered_lines(slice_lines, start_line=params.offset)

        end_line = params.offset + len(slice_lines) - 1
        if params.offset > 1 or end_line < total:
            header = f"[read_file {params.path} 行 {params.offset}-{end_line} / 共 {total} 行]"
            if end_line < total:
                header += f"\n[... 后续还有 {total - end_line} 行，可增大 offset 继续读取 ...]"
            return f"{header}\n{body}"

        if total > DEFAULT_READ_LIMIT:
            truncated = format_numbered_lines(all_lines[:DEFAULT_READ_LIMIT])
            omitted = total - DEFAULT_READ_LIMIT
            return (
                f"[read_file {params.path} 已截断：仅显示前 {DEFAULT_READ_LIMIT} 行 / 共 {total} 行]\n"
                f"[... 省略 {omitted} 行，请用 offset/limit 分段读取 ...]\n"
                f"{truncated}"
            )

        return body


class WriteFileTool(BaseTool):
    name = "write_file"
    description = (
        "创建新文件或整文件覆写 content。"
        "用于新建文件或需要重写整个文件时；局部修改请用 edit_file。"
    )
    params_model = WriteFileParams

    async def execute(self, params: ToolParams) -> str:
        assert isinstance(params, WriteFileParams)
        file_path, err = resolve_in_workspace(params.path)
        if err:
            return err
        assert file_path is not None

        existed = file_path.is_file()
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(params.content, encoding="utf-8")
        except OSError as exc:
            return f"写入失败 {params.path}: {exc}"

        action = "覆写" if existed else "创建"
        line_count = len(params.content.splitlines()) if params.content else 0
        return f"已{action} {params.path}（{line_count} 行，{len(params.content)} 字符）"


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "用 old_string 精确替换为 new_string，适合局部修改。"
        "old_string 必须与 read_file 看到的原文完全一致（含缩进）。"
        "默认要求 old_string 在文件中恰好出现一次；多处匹配时用 replace_all 或加长上下文。"
    )
    params_model = EditFileParams

    async def execute(self, params: ToolParams) -> str:
        assert isinstance(params, EditFileParams)
        file_path, err = resolve_in_workspace(params.path)
        if err:
            return err
        assert file_path is not None

        if not file_path.is_file():
            return (
                f"文件不存在: {params.path}。"
                "请先 read_file 确认路径，或用 write_file 创建该文件。"
            )

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"无法以 UTF-8 编辑文件: {params.path}（可能是二进制文件）"
        except OSError as exc:
            return f"读取文件失败 {params.path}: {exc}"

        count = content.count(params.old_string)
        if count == 0:
            return (
                "old_string 未找到，文件可能已变化或 old_string 与文件内容不完全一致"
                "（空格/缩进/换行都要精确匹配）。请先重新 read_file 获取最新内容后再 edit。"
            )
        if count > 1 and not params.replace_all:
            return (
                f"old_string 在文件中出现 {count} 次，存在歧义。"
                "请包含更多前后行使 old_string 唯一，或设置 replace_all=true 替换全部匹配。"
            )

        if params.replace_all:
            new_content = content.replace(params.old_string, params.new_string)
            replaced = count
        else:
            new_content = content.replace(params.old_string, params.new_string, 1)
            replaced = 1

        try:
            file_path.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            return f"写入失败 {params.path}: {exc}"

        return f"已编辑 {params.path}：替换 {replaced} 处（old_string {len(params.old_string)} 字符 → new_string {len(params.new_string)} 字符）"
