"""Day 7 · 工具调用一行摘要（折叠展示用）。"""

import json


def _arg_preview(arguments: str, max_len: int = 48) -> str:
    try:
        data = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError:
        return arguments[:max_len]
    if not isinstance(data, dict) or not data:
        return ""
    parts: list[str] = []
    for key, value in data.items():
        text = str(value)
        if len(text) > 24:
            text = text[:21] + "..."
        parts.append(f"{key}={text!r}")
        if len(", ".join(parts)) > max_len:
            break
    return ", ".join(parts)[:max_len]


def summarize_tool_start(name: str, arguments: str) -> str:
    """折叠标题：工具名 + 参数摘要。"""
    preview = _arg_preview(arguments)
    if preview:
        return f"● {name}({preview})"
    return f"● {name}()"


def summarize_tool_result(name: str, result: str) -> str:
    """折叠副标题：执行结果一行摘要。"""
    lines = [ln for ln in result.splitlines() if ln.strip()]
    if name == "read_file":
        numbered = sum(1 for ln in lines if "|" in ln[:8])
        if numbered:
            return f"→ {numbered} 行"
        return f"→ {len(lines)} 行"
    if name in {"write_file", "edit_file"}:
        first = lines[0] if lines else result.strip()
        return f"→ {first[:72]}"
    if name == "bash":
        tail = lines[-1] if lines else result.strip()
        return f"→ {tail[:72]}"
    if name in {"glob", "grep"}:
        count = len(lines)
        return f"→ {count} 条匹配" if count else "→ 无匹配"
    one_line = result.replace("\n", " ").strip()
    if len(one_line) > 72:
        return f"→ {one_line[:69]}..."
    return f"→ {one_line or '（空）'}"
