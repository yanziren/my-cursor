"""Day 11 · 权限规则：内置默认 + 用户全局 toml + 项目 toml（项目优先）。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Action = Literal["allow", "ask", "deny"]

# 同一层内 deny → ask → allow，避免宽 allow 盖掉 sudo
BUILTIN_DENY: tuple[str, ...] = (
    "bash(sudo *)",
)
BUILTIN_ASK: tuple[str, ...] = (
    "bash(rm *)",
    "bash(git push*)",
    "bash(git reset*)",
    "bash(git clean*)",
    "bash(chmod *)",
    "bash(chown *)",
    "bash(kill *)",
    "bash(curl *)",
    "bash(wget *)",
)
BUILTIN_ALLOW: tuple[str, ...] = (
    "read_file",
    "glob",
    "grep",
    "get_current_time",
    "calculator",
    "write_file",
    "edit_file",
    "bash(ls *)",
    "bash(cat *)",
    "bash(head *)",
    "bash(tail *)",
    "bash(pwd *)",
    "bash(echo *)",
    "bash(pytest *)",
    "bash(ruff *)",
    "bash(uv *)",
    "bash(git status*)",
    "bash(git diff*)",
    "bash(git log*)",
    "bash(git show*)",
    "bash(git branch*)",
)


@dataclass(frozen=True)
class Rule:
    """一条匹配规则；pattern 形如 `read_file` 或 `bash(git push*)`。"""

    pattern: str
    action: Action


def default_mycoder_home() -> Path:
    home = os.getenv("MYCODER_HOME")
    return Path(home).expanduser() if home else Path.home() / ".mycoder"


def default_config_path() -> Path:
    return default_mycoder_home() / "config.toml"


def layer_rules(
    allow: list[str] | tuple[str, ...],
    ask: list[str] | tuple[str, ...],
    deny: list[str] | tuple[str, ...],
) -> list[Rule]:
    return (
        [Rule(pattern, "deny") for pattern in deny]
        + [Rule(pattern, "ask") for pattern in ask]
        + [Rule(pattern, "allow") for pattern in allow]
    )


def builtin_rules() -> list[Rule]:
    return layer_rules(BUILTIN_ALLOW, BUILTIN_ASK, BUILTIN_DENY)


def load_toml_layer(path: Path) -> list[Rule]:
    """文件不存在则跳过；坏 toml 直接抛，避免带着错误规则裸奔。"""
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"无法解析权限配置 {path}: {exc}") from exc
    perm = data.get("permissions") or {}
    if not isinstance(perm, dict):
        return []
    allow = _string_list(perm.get("allow"))
    ask = _string_list(perm.get("ask"))
    deny = _string_list(perm.get("deny"))
    return layer_rules(allow, ask, deny)


def _string_list(raw: object) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TypeError("permissions.allow/ask/deny 必须是字符串数组")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("权限规则必须是非空字符串")
        out.append(item.strip())
    return out


def merge_rules(workspace: Path) -> list[Rule]:
    """项目层整段插到最前，所以陌生仓库能把 write_file 从 allow 收到 ask。"""
    project = load_toml_layer(workspace / ".mycoder" / "config.toml")
    user = load_toml_layer(default_config_path())
    return project + user + builtin_rules()
