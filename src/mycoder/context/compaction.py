"""Day 9 · 上下文压缩：阈值触发、工具输出裁剪、结构化摘要、视图组装。

完整 `messages` 只追加不改写（前缀缓存 + Day 10 落盘仍要原文）。
发给模型的是动态视图：系统提示 + 摘要 + 最近 K 轮原文，旧工具结果在视图里替换为占位。
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

from mycoder.context.budget import estimate_messages_tokens, estimate_text_tokens

# 手册规定的八股文标题：自由总结会丢掉下一轮要用的路径与标识符
SUMMARY_SYSTEM_PROMPT = """请把以下对话压缩成摘要，按顺序输出这些标题：
1) 任务目标  2) 关键决策  3) 读过的文件  4) 改过的文件
5) 跑过的命令与结果  6) 未完成事项  7) 风险与注意点
规则：不要复述系统提示词；条目短而可执行；保留精确的文件路径与函数名。"""

SUMMARY_USER_PREFIX = "<compaction>"
SUMMARY_ASSISTANT = "已记录此前对话摘要，将按其中的目标与未完成事项继续。"
PRUNE_MARK = "的输出已裁剪，需要时请重新读取"

_PATH_IN_JSON = re.compile(r'"path"\s*:\s*"([^"]+)"')
_COMMAND_IN_JSON = re.compile(r'"command"\s*:\s*"([^"]+)"')

Summarizer = Callable[[str], str]


@dataclass(frozen=True)
class CompactConfig:
    """压缩与裁剪开关。reserve 在小窗口上按 limit/4 封顶，避免阈值线为负。"""

    threshold: float = 0.80
    reserve: int = 8192
    keep_recent_turns: int = 4
    prune_after_turns: int = 2
    enabled: bool = True
    max_transcript_chars: int = 60_000

    @classmethod
    def from_env(cls) -> CompactConfig:
        enabled = os.getenv("MYCODER_COMPACT", "1").lower() not in {"0", "false", "no"}
        return cls(
            threshold=_env_float("MYCODER_COMPACT_THRESHOLD", 0.80),
            reserve=_env_int("MYCODER_COMPACT_RESERVE", 8192),
            keep_recent_turns=max(1, _env_int("MYCODER_COMPACT_KEEP_TURNS", 4)),
            prune_after_turns=max(0, _env_int("MYCODER_PRUNE_AFTER_TURNS", 2)),
            enabled=enabled,
        )


@dataclass(frozen=True)
class CompactionRecord:
    """一次压缩的视图记录。原文仍在 messages 里，Day 10 可把此类写成会话 entry。"""

    summary: str
    compacted_count: int
    keep_from: int
    summary_tokens: int


@dataclass(frozen=True)
class PrepareResult:
    """用户轮开始前的准备结果。"""

    records: list[CompactionRecord]
    compacted: CompactionRecord | None
    pruned_tools: int


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def effective_reserve(limit: int, reserve: int) -> int:
    """小窗口不能按 8K 预留，否则压缩永远来不及触发。"""
    if limit <= 0:
        return 0
    return min(reserve, max(0, limit // 4))


def compact_watermark(limit: int, config: CompactConfig) -> int:
    """触发线：(窗口 - 预留) × 阈值。"""
    room = max(0, limit - effective_reserve(limit, config.reserve))
    return int(room * config.threshold)


def should_compact(used: int, limit: int, config: CompactConfig) -> bool:
    if not config.enabled or limit <= 0:
        return False
    return used > compact_watermark(limit, config)


def is_compaction_user(message: dict) -> bool:
    content = message.get("content") or ""
    return message.get("role") == "user" and isinstance(content, str) and content.startswith(
        SUMMARY_USER_PREFIX
    )


def user_turn_starts(messages: list[dict]) -> list[int]:
    """真实用户轮起点（跳过视图里注入的摘要 user，避免把摘要当成一轮任务）。"""
    starts: list[int] = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "user" and not is_compaction_user(msg):
            starts.append(i)
    return starts


def summary_messages(summary: str) -> list[dict]:
    """摘要以 user/assistant 成对注入，避免只有一条 user 破坏后续 tool_calls 配对。"""
    return [
        {
            "role": "user",
            "content": (
                f"{SUMMARY_USER_PREFIX}\n"
                "以下是此前对话的结构化摘要，不是新任务：\n\n"
                f"{summary}\n"
                "</compaction>"
            ),
        },
        {"role": "assistant", "content": SUMMARY_ASSISTANT},
    ]


def assemble_view(messages: list[dict], records: list[CompactionRecord]) -> list[dict]:
    """系统提示 + 最新摘要 + keep_from 之后的原文。不修改传入的 messages。"""
    if not messages:
        return []
    if not records:
        return list(messages)
    record = records[-1]
    keep_from = min(max(record.keep_from, 1), len(messages))
    head = messages[0]
    tail = messages[keep_from:]
    injected = summary_messages(record.summary)
    if head.get("role") == "system":
        return [head, *injected, *tail]
    return [*injected, *tail]


def _tool_meta(messages: list[dict]) -> dict[str, tuple[str, str]]:
    """call_id → (name, arguments)，供占位文案写出如何重新获取。"""
    meta: dict[str, tuple[str, str]] = {}
    for msg in messages:
        for call in msg.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            fn = call.get("function") or {}
            call_id = str(call.get("id") or "")
            if call_id:
                meta[call_id] = (str(fn.get("name") or "tool"), str(fn.get("arguments") or ""))
    return meta


def _recover_target(name: str, arguments: str) -> str:
    try:
        data = json.loads(arguments) if arguments.strip() else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if name in {"read_file", "write_file", "edit_file"}:
        return str(data.get("path") or "")
    if name == "bash":
        return str(data.get("command") or "")[:80]
    if name in {"grep", "glob"}:
        return str(data.get("pattern") or data.get("glob") or "")
    for value in data.values():
        if isinstance(value, str) and value:
            return value[:80]
    return ""


def tool_placeholder(name: str, arguments: str) -> str:
    target = _recover_target(name, arguments)
    if target:
        return f"[{name} {target}{PRUNE_MARK}]"
    return f"[{name}{PRUNE_MARK}]"


def is_pruned_content(content: str) -> bool:
    return PRUNE_MARK in content


def prune_tool_results(
    messages: list[dict],
    prune_after_turns: int,
) -> tuple[list[dict], int]:
    """距今超过 N 个真实用户轮的 tool 结果，在副本里换成可恢复的占位。"""
    if prune_after_turns <= 0:
        return list(messages), 0
    starts = user_turn_starts(messages)
    if len(starts) <= prune_after_turns:
        return list(messages), 0
    protect_from = starts[-prune_after_turns]
    meta = _tool_meta(messages)
    pruned = 0
    view: list[dict] = []
    for index, msg in enumerate(messages):
        if (
            msg.get("role") == "tool"
            and index < protect_from
            and isinstance(msg.get("content"), str)
            and not is_pruned_content(msg["content"])
        ):
            name, arguments = meta.get(str(msg.get("tool_call_id") or ""), ("tool", ""))
            view.append({**msg, "content": tool_placeholder(name, arguments)})
            pruned += 1
        else:
            view.append(msg)
    return view, pruned


def format_transcript(messages: list[dict], *, max_msg_chars: int = 2000) -> str:
    """给摘要模型看的可读抄本；单条过长会截断，避免小模型自己先爆窗。"""
    blocks: list[str] = []
    for msg in messages:
        role = str(msg.get("role") or "?")
        if role == "tool":
            header = f"[tool {msg.get('tool_call_id', '')}]"
        else:
            header = f"[{role}]"
        content = msg.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        if len(content) > max_msg_chars:
            content = content[:max_msg_chars] + "\n…(truncated)"
        blocks.append(f"{header}\n{content}")
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            dumped = json.dumps(tool_calls, ensure_ascii=False)
            if len(dumped) > 1500:
                dumped = dumped[:1500] + "…"
            blocks.append(f"tool_calls: {dumped}")
    return "\n\n".join(blocks)


def fallback_summary(transcript: str) -> str:
    """摘要模型失败时的确定性兜底：至少保住路径，模型还能重新定位。"""
    paths = list(dict.fromkeys(_PATH_IN_JSON.findall(transcript)))
    commands = list(dict.fromkeys(_COMMAND_IN_JSON.findall(transcript)))
    first_user = ""
    marker = "[user]\n"
    if marker in transcript:
        rest = transcript.split(marker, 1)[1]
        first_user = rest.split("\n[")[0].strip()[:400]
    path_line = "、".join(paths[:20]) or "（未见明确路径）"
    cmd_line = "；".join(commands[:8]) or "（未见命令）"
    return (
        "1) 任务目标\n"
        f"{first_user or '（见此前用户请求）'}\n"
        "2) 关键决策\n"
        "摘要模型不可用，以下为从抄本抽取的线索。\n"
        "3) 读过的文件\n"
        f"{path_line}\n"
        "4) 改过的文件\n"
        f"{path_line}\n"
        "5) 跑过的命令与结果\n"
        f"{cmd_line}\n"
        "6) 未完成事项\n"
        "请根据最近轮次原文继续。\n"
        "7) 风险与注意点\n"
        "压缩有损，需要旧文件内容时请重新 read_file。"
    )


def compact(
    messages: list[dict],
    records: list[CompactionRecord],
    config: CompactConfig,
    summarizer: Summarizer,
) -> CompactionRecord | None:
    """折叠 keep_from 之前的原文为一份结构化摘要。消息列表本身不改。"""
    starts = user_turn_starts(messages)
    if len(starts) <= config.keep_recent_turns:
        return None
    keep_from = starts[-config.keep_recent_turns]
    prev_from = records[-1].keep_from if records else 1
    if keep_from <= prev_from:
        return None

    chunks: list[str] = []
    if records:
        chunks.append("此前摘要：\n" + records[-1].summary)
    chunks.append(format_transcript(messages[prev_from:keep_from]))
    transcript = "\n\n".join(chunks)
    if len(transcript) > config.max_transcript_chars:
        transcript = transcript[: config.max_transcript_chars] + "\n…(transcript truncated)"

    try:
        summary = (summarizer(transcript) or "").strip()
    except Exception:  # noqa: BLE001 — 压缩失败不得打断主任务
        summary = ""
    if len(summary) < 40:
        summary = fallback_summary(transcript)

    return CompactionRecord(
        summary=summary,
        compacted_count=keep_from - prev_from,
        keep_from=keep_from,
        summary_tokens=estimate_text_tokens(summary),
    )


def model_view(
    messages: list[dict],
    records: list[CompactionRecord],
    config: CompactConfig,
) -> tuple[list[dict], int]:
    """当前应发给模型的消息视图（组装 + 工具裁剪）。"""
    assembled = assemble_view(messages, records)
    return prune_tool_results(assembled, config.prune_after_turns)


def prepare_context(
    messages: list[dict],
    records: list[CompactionRecord],
    *,
    limit: int,
    config: CompactConfig,
    summarizer: Summarizer,
) -> PrepareResult:
    """用户轮开始前：先裁剪，仍超阈值再压缩。检查点不放进 tool loop。"""
    view, pruned = model_view(messages, records, config)
    used = estimate_messages_tokens(view)
    if not should_compact(used, limit, config):
        return PrepareResult(records=records, compacted=None, pruned_tools=pruned)

    record = compact(messages, records, config, summarizer)
    if record is None:
        return PrepareResult(records=records, compacted=None, pruned_tools=pruned)
    return PrepareResult(records=[*records, record], compacted=record, pruned_tools=pruned)
