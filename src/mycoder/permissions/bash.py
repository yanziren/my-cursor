"""Day 11 · bash 命令切分：不追求完整 shell 语法，漏网交给 Day 12 沙箱。"""

from pathlib import Path

# git / uv 第二词才是真正动作；只记 argv0 会把 git push 和 git status 混成同一把钥匙
_TWO_WORD_COMMANDS = frozenset(
    {"git", "npm", "uv", "cargo", "pip", "docker", "apt", "brew"}
)
_DOWNLOADERS = frozenset({"curl", "wget"})
_SHELLS = frozenset({"sh", "bash"})


def split_command_segments(command: str) -> list[str]:
    """按 `;` `&&` `||` `|` 与换行切开。不解析引号。"""
    segments: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(command)
    while i < n:
        pair = command[i : i + 2]
        if pair in {"&&", "||"}:
            _flush_segment(segments, buf)
            i += 2
            continue
        ch = command[i]
        if ch in {";", "|", "\n"}:
            _flush_segment(segments, buf)
            i += 1
            continue
        buf.append(ch)
        i += 1
    _flush_segment(segments, buf)
    if segments:
        return segments
    stripped = command.strip()
    return [stripped] if stripped else []


def _flush_segment(segments: list[str], buf: list[str]) -> None:
    text = "".join(buf).strip()
    buf.clear()
    if text:
        segments.append(text)


def has_redirect(segment: str) -> bool:
    """`>` / `>>` 会覆盖文件，即使左侧是 echo 也至少要 ask。"""
    return ">" in segment


def command_prefix(segment: str) -> str:
    """会话记忆用的命令前缀：`rm`、`git push`。"""
    tokens = segment.split()
    while tokens and "=" in tokens[0] and not tokens[0].startswith("="):
        tokens = tokens[1:]
    if not tokens:
        return ""
    cmd = Path(tokens[0]).name
    if cmd in _TWO_WORD_COMMANDS and len(tokens) > 1 and not tokens[1].startswith("-"):
        return f"{cmd} {tokens[1]}"
    return cmd


def first_word(segment: str) -> str:
    prefix = command_prefix(segment)
    return prefix.split()[0] if prefix else ""


def is_pipe_download_execute(segments: list[str]) -> bool:
    """`curl … | sh` 这类：下载器与 shell 同时出现则整句 deny。"""
    words = {first_word(seg) for seg in segments}
    return bool(words & _DOWNLOADERS) and bool(words & _SHELLS)
