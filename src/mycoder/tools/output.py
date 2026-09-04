"""工具输出截断：保头保尾，避免撑爆上下文。"""

DEFAULT_MAX_LINES = 2000
DEFAULT_MAX_BYTES = 30_000
DEFAULT_HEAD_LINES = 40
DEFAULT_TAIL_LINES = 40


def truncate_output(
    text: str,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    max_bytes: int = DEFAULT_MAX_BYTES,
    head_lines: int = DEFAULT_HEAD_LINES,
    tail_lines: int = DEFAULT_TAIL_LINES,
) -> str:
    if not text:
        return "（无输出）"

    lines = text.splitlines()
    line_truncated = len(lines) > max_lines
    byte_truncated = len(text.encode("utf-8")) > max_bytes

    if not line_truncated and not byte_truncated:
        return text

    if line_truncated:
        keep_head = min(head_lines, max_lines // 2)
        keep_tail = min(tail_lines, max_lines - keep_head)
        omitted = len(lines) - keep_head - keep_tail
        body = (
            "\n".join(lines[:keep_head])
            + f"\n[... 截断 {omitted} 行 ...]\n"
            + "\n".join(lines[-keep_tail:])
        )
    else:
        body = text

    encoded = body.encode("utf-8")
    if len(encoded) <= max_bytes:
        return body

    # 字节仍超限：按 UTF-8 安全截断后再保尾
    head_bytes = max_bytes // 2
    tail_bytes = max_bytes - head_bytes
    head_part = encoded[:head_bytes].decode("utf-8", errors="ignore")
    tail_part = encoded[-tail_bytes:].decode("utf-8", errors="ignore")
    omitted_bytes = len(encoded) - head_bytes - tail_bytes
    return f"{head_part}\n[... 截断约 {omitted_bytes} 字节 ...]\n{tail_part}"
