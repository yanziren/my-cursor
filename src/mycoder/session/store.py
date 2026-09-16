"""Day 10 · JSONL 会话存储：append-only 事件日志，崩溃最多丢最后半行。"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from mycoder.context.compaction import CompactionRecord

TITLE_SYSTEM_PROMPT = (
    "把用户的第一条消息压成不超过 20 个字的会话标题。"
    "只输出标题，不要引号、标点或解释。"
)

_INTERRUPTED_TOOL = "（会话中断，工具未执行完成。请重新调用该工具。）"


def now_iso() -> str:
    """UTC 时间戳，便于跨时区排序；展示时再转本地。"""
    return datetime.now(UTC).isoformat()


def new_entry_id() -> str:
    return uuid.uuid4().hex


def default_sessions_dir() -> Path:
    override = os.getenv("MYCODER_SESSIONS_DIR")
    if override:
        return Path(override).expanduser()
    home = os.getenv("MYCODER_HOME")
    root = Path(home).expanduser() if home else Path.home() / ".mycoder"
    return root / "sessions"


def fallback_title(text: str) -> str:
    """小模型不可用时的标题：首行截断，保证列表里总能读到点什么。"""
    line = " ".join(text.strip().split())
    if not line:
        return "新会话"
    return line[:30] + ("…" if len(line) > 30 else "")


def clean_generated_title(raw: str, fallback: str) -> str:
    title = (raw or "").strip().splitlines()[0].strip().strip("「」\"'")
    for ch in ("。", ".", "！", "!", "？", "?"):
        title = title.replace(ch, "")
    title = title.strip()
    if len(title) < 2:
        return fallback
    return title[:40]


class SessionMeta(BaseModel):
    """侧车元数据：标题可在首轮结束后改写，不能塞进 append-only 的 JSONL。"""

    title: str = "新会话"
    created_at: str
    workspace: str | None = None
    titled_by_model: bool = False


class EntryBase(BaseModel):
    id: str
    parent_id: str | None = None
    ts: str


class MessageEntry(EntryBase):
    type: Literal["message"] = "message"
    message: dict


class CompactionEntry(EntryBase):
    type: Literal["compaction"] = "compaction"
    summary: str
    compacted_count: int
    keep_from: int
    summary_tokens: int


class ModelChangeEntry(EntryBase):
    type: Literal["model_change"] = "model_change"
    model: str


SessionEntry = Annotated[
    MessageEntry | CompactionEntry | ModelChangeEntry,
    Field(discriminator="type"),
]

_ENTRY_ADAPTER: TypeAdapter[MessageEntry | CompactionEntry | ModelChangeEntry] = TypeAdapter(
    SessionEntry
)


@dataclass
class SessionSnapshot:
    """对事件流重放得到的状态。"""

    messages: list[dict]
    records: list[CompactionRecord]
    model: str | None
    last_id: str | None
    entries: list[MessageEntry | CompactionEntry | ModelChangeEntry] = field(
        default_factory=list
    )


@dataclass(frozen=True)
class SessionSummary:
    """会话列表行：标题、时间、轮数。"""

    id: str
    title: str
    created_at: str
    updated_at: str
    turns: int
    path: Path
    model: str | None = None
    workspace: str | None = None


def repair_incomplete_tool_calls(messages: list[dict]) -> list[dict]:
    """kill -9 可能停在 assistant.tool_calls 之后；补占位以免下一轮 API 拒收。"""
    pending: list[str] = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant":
            pending = []
            for call in msg.get("tool_calls") or []:
                if isinstance(call, dict) and call.get("id"):
                    pending.append(str(call["id"]))
        elif role == "tool":
            cid = str(msg.get("tool_call_id") or "")
            pending = [item for item in pending if item != cid]
        elif role == "user":
            pending = []
    if not pending:
        return messages
    extra = [
        {"role": "tool", "tool_call_id": cid, "content": _INTERRUPTED_TOOL}
        for cid in pending
    ]
    return [*messages, *extra]


class SessionStore:
    """一个会话对应一个 JSONL 文件：~/.mycoder/sessions/<id>.jsonl。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.session_id = path.stem
        self._head_id: str | None = None
        self._meta: SessionMeta | None = None

    @property
    def meta_path(self) -> Path:
        return self.path.with_suffix(".meta.json")

    @property
    def short_id(self) -> str:
        return self.session_id[:8]

    @property
    def title(self) -> str:
        return self._load_meta().title

    @property
    def titled_by_model(self) -> bool:
        return self._load_meta().titled_by_model

    @classmethod
    def create(cls, directory: Path | None = None) -> SessionStore:
        folder = directory or default_sessions_dir()
        folder.mkdir(parents=True, exist_ok=True)
        store = cls(folder / f"{new_entry_id()}.jsonl")
        store.path.touch()
        store._meta = SessionMeta(title="新会话", created_at=now_iso())
        store._write_meta(store._meta)
        return store

    @classmethod
    def open(cls, session_id: str, directory: Path | None = None) -> SessionStore:
        path = resolve_session_path(session_id, directory)
        store = cls(path)
        store._ensure_complete_lines()
        entries = store.read_entries()
        store._head_id = entries[-1].id if entries else None
        return store

    def is_default_title(self) -> bool:
        meta = self._load_meta()
        return meta.title == "新会话" and not meta.titled_by_model

    def set_title(self, title: str, *, by_model: bool = False) -> None:
        meta = self._load_meta()
        meta.title = title or meta.title
        meta.titled_by_model = by_model or meta.titled_by_model
        self._write_meta(meta)

    def ensure_workspace(self, workspace: str) -> None:
        meta = self._load_meta()
        if meta.workspace == workspace:
            return
        meta.workspace = workspace
        self._write_meta(meta)

    def append_message(self, message: dict) -> MessageEntry:
        entry = MessageEntry(
            id=new_entry_id(),
            parent_id=self._head_id,
            ts=now_iso(),
            message=message,
        )
        self._append(entry)
        return entry

    def append_compaction(self, record: CompactionRecord) -> CompactionEntry:
        entry = CompactionEntry(
            id=new_entry_id(),
            parent_id=self._head_id,
            ts=now_iso(),
            summary=record.summary,
            compacted_count=record.compacted_count,
            keep_from=record.keep_from,
            summary_tokens=record.summary_tokens,
        )
        self._append(entry)
        return entry

    def append_model_change(self, model: str) -> ModelChangeEntry:
        entry = ModelChangeEntry(
            id=new_entry_id(),
            parent_id=self._head_id,
            ts=now_iso(),
            model=model,
        )
        self._append(entry)
        return entry

    def replay(self) -> SessionSnapshot:
        """读全部 entry → 还原 messages / 压缩记录 / 最后一次模型。"""
        self._ensure_complete_lines()
        entries = self.read_entries()
        self._head_id = entries[-1].id if entries else None
        messages: list[dict] = []
        records: list[CompactionRecord] = []
        model: str | None = None
        for entry in entries:
            if isinstance(entry, MessageEntry):
                messages.append(entry.message)
            elif isinstance(entry, CompactionEntry):
                records.append(
                    CompactionRecord(
                        summary=entry.summary,
                        compacted_count=entry.compacted_count,
                        keep_from=entry.keep_from,
                        summary_tokens=entry.summary_tokens,
                    )
                )
            elif isinstance(entry, ModelChangeEntry):
                model = entry.model
        return SessionSnapshot(
            messages=messages,
            records=records,
            model=model,
            last_id=self._head_id,
            entries=entries,
        )

    def read_entries(self) -> list[MessageEntry | CompactionEntry | ModelChangeEntry]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        entries: list[MessageEntry | CompactionEntry | ModelChangeEntry] = []
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                entries.append(_ENTRY_ADAPTER.validate_python(data))
            except (json.JSONDecodeError, ValidationError):
                # 崩溃只截断最后一行；中间损坏不能跳过，否则 keep_from 会错位
                if index == len(lines) - 1:
                    break
                raise
        return entries

    def summarize(self) -> SessionSummary:
        snapshot = self.replay()
        meta = self._load_meta()
        turns = sum(1 for msg in snapshot.messages if msg.get("role") == "user")
        timestamps = [entry.ts for entry in snapshot.entries]
        updated = timestamps[-1] if timestamps else meta.created_at
        title = meta.title
        if title == "新会话":
            first_user = next(
                (
                    msg.get("content")
                    for msg in snapshot.messages
                    if msg.get("role") == "user" and isinstance(msg.get("content"), str)
                ),
                None,
            )
            if isinstance(first_user, str) and first_user.strip():
                title = fallback_title(first_user)
        return SessionSummary(
            id=self.session_id,
            title=title,
            created_at=meta.created_at,
            updated_at=updated,
            turns=turns,
            path=self.path,
            model=snapshot.model,
            workspace=meta.workspace,
        )

    def _append(self, entry: MessageEntry | CompactionEntry | ModelChangeEntry) -> None:
        self._ensure_complete_lines()
        line = entry.model_dump_json(ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        self._head_id = entry.id

    def _ensure_complete_lines(self) -> None:
        """丢掉未以换行结束的最后半行，避免下次 append 与半行粘连。"""
        if not self.path.exists():
            return
        with self.path.open("rb+") as fh:
            data = fh.read()
            if not data or data.endswith(b"\n"):
                return
            last_nl = data.rfind(b"\n")
            fh.seek(0)
            fh.truncate()
            if last_nl >= 0:
                fh.write(data[: last_nl + 1])
            fh.flush()
            os.fsync(fh.fileno())

    def _load_meta(self) -> SessionMeta:
        if self._meta is not None:
            return self._meta
        if self.meta_path.exists():
            try:
                self._meta = SessionMeta.model_validate_json(
                    self.meta_path.read_text(encoding="utf-8")
                )
                return self._meta
            except (ValidationError, json.JSONDecodeError):
                pass
        created = now_iso()
        if self.path.exists():
            created = datetime.fromtimestamp(
                self.path.stat().st_ctime, tz=UTC
            ).isoformat()
        self._meta = SessionMeta(title="新会话", created_at=created)
        return self._meta

    def _write_meta(self, meta: SessionMeta) -> None:
        self._meta = meta
        tmp = self.meta_path.with_suffix(".meta.json.tmp")
        tmp.write_text(meta.model_dump_json(ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.meta_path)


def list_sessions(
    directory: Path | None = None, *, include_empty: bool = False
) -> list[SessionSummary]:
    folder = directory or default_sessions_dir()
    if not folder.exists():
        return []
    summaries: list[SessionSummary] = []
    for path in folder.glob("*.jsonl"):
        store = SessionStore(path)
        summaries.append(store.summarize())
    if not include_empty:
        summaries = [item for item in summaries if item.turns > 0]
    summaries.sort(key=lambda item: item.updated_at, reverse=True)
    return summaries


def resolve_session_path(token: str, directory: Path | None = None) -> Path:
    folder = directory or default_sessions_dir()
    exact = folder / f"{token}.jsonl"
    if exact.exists():
        return exact
    as_path = Path(token).expanduser()
    if as_path.exists() and as_path.suffix == ".jsonl":
        return as_path
    matches = sorted(folder.glob(f"{token}*.jsonl"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        ids = ", ".join(p.stem[:12] for p in matches)
        raise FileNotFoundError(f"会话 id 前缀不唯一: {token}（{ids}）")
    raise FileNotFoundError(f"找不到会话: {token}")
