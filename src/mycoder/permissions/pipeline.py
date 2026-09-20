"""Day 11 · 权限管道：evaluate 纯裁决，authorize 才跟用户对话。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Literal

from mycoder.permissions.bash import (
    command_prefix,
    has_redirect,
    is_pipe_download_execute,
    split_command_segments,
)
from mycoder.permissions.config import Action, Rule, merge_rules

_RANK: dict[Action, int] = {"allow": 0, "ask": 1, "deny": 2}


@dataclass(frozen=True)
class Decision:
    """一条工具调用的最终裁决。"""

    action: Action
    rule: str | None
    reason: str


@dataclass(frozen=True)
class UserChoice:
    """审批卡片三选一。"""

    action: Literal["allow_once", "allow_session", "deny"]
    reason: str = "用户拒绝了该操作"


@dataclass(frozen=True)
class PermissionRequest:
    """交给 TUI / REPL 的审批请求。"""

    tool_name: str
    params: dict
    preview: str
    reason: str
    call_id: str = ""


Approver = Callable[[PermissionRequest], Awaitable[UserChoice]]


def format_denial(reason: str) -> str:
    """拒绝文案写给模型：说明原因并给出下一步，避免反复撞墙。"""
    return f"该操作被用户拒绝：{reason}。请换一种方式或询问用户。"


def parse_pattern(pattern: str) -> tuple[str, str | None]:
    text = pattern.strip()
    if "(" in text and text.endswith(")"):
        tool, rest = text.split("(", 1)
        return tool.strip(), rest[:-1]
    return text, None


def glob_match(value: str, pattern: str) -> bool:
    """`ls *` 也要能对上光杆 `ls`；不用正则，配置给人读。"""
    if fnmatchcase(value, pattern):
        return True
    return pattern.endswith(" *") and value == pattern[:-2]


def match_subject(tool_name: str, params: dict) -> str:
    if tool_name == "bash":
        return str(params.get("command") or "")
    if tool_name in {"read_file", "write_file", "edit_file"}:
        return str(params.get("path") or "")
    return json.dumps(params, ensure_ascii=False, sort_keys=True)


def preview_call(tool_name: str, params: dict) -> str:
    if tool_name == "bash":
        return str(params.get("command") or "")
    path = params.get("path")
    if isinstance(path, str) and path:
        return path
    return json.dumps(params, ensure_ascii=False)


def _rule_matches(rule: Rule, tool_name: str, subject: str) -> bool:
    tool, arg_glob = parse_pattern(rule.pattern)
    if tool != tool_name:
        return False
    if arg_glob is None or arg_glob == "*":
        return True
    return glob_match(subject, arg_glob)


def _reason_for(rule: Rule) -> str:
    if rule.action == "deny":
        return f"权限规则：{rule.pattern}"
    if rule.action == "ask":
        return f"需要审批：{rule.pattern}"
    return f"权限规则允许：{rule.pattern}"


def _worse(left: Decision, right: Decision) -> Decision:
    if _RANK[right.action] > _RANK[left.action]:
        return right
    return left


class PermissionPipeline:
    """规则链从上到下第一条命中生效；会话记忆只活在内存里。"""

    def __init__(self, rules: list[Rule] | None = None) -> None:
        from mycoder.permissions.config import builtin_rules

        # 无参构造只用内置规则，避免单测误读开发者本机 ~/.mycoder/config.toml
        self.rules = rules if rules is not None else builtin_rules()
        self._session_allow: set[str] = set()

    @classmethod
    def from_workspace(cls, workspace: Path) -> PermissionPipeline:
        return cls(merge_rules(workspace))

    def clear_session(self) -> None:
        """Ctrl+L / 开新会话时丢掉「总是允许」，避免跨任务误授。"""
        self._session_allow.clear()

    def evaluate(self, tool_name: str, params: dict) -> Decision:
        if tool_name == "bash":
            return self._evaluate_bash(str(params.get("command") or ""))
        return self._match_rules(tool_name, params)

    def _match_rules(self, tool_name: str, params: dict) -> Decision:
        subject = match_subject(tool_name, params)
        for rule in self.rules:
            if _rule_matches(rule, tool_name, subject):
                return Decision(rule.action, rule.pattern, _reason_for(rule))
        if tool_name == "bash":
            return Decision("ask", None, "不在白名单中的命令需要审批")
        return Decision("ask", None, f"工具 {tool_name} 需要审批")

    def _evaluate_bash(self, command: str) -> Decision:
        segments = split_command_segments(command)
        if not segments:
            return Decision("ask", None, "不在白名单中的命令需要审批")
        if is_pipe_download_execute(segments):
            return Decision(
                "deny",
                "bash(curl*|sh)",
                "权限规则：管道下载执行（curl|wget + sh|bash）",
            )
        worst = Decision("allow", None, "")
        for segment in segments:
            decision = self._match_rules("bash", {"command": segment})
            if has_redirect(segment) and _RANK[decision.action] < _RANK["ask"]:
                decision = Decision(
                    "ask",
                    "bash(*>*)",
                    "命令含重定向，按写操作审批",
                )
            worst = _worse(worst, decision)
        if worst.action == "allow" and not worst.reason:
            worst = Decision("allow", None, "权限规则允许")
        return worst

    def session_keys(self, tool_name: str, params: dict) -> set[str]:
        """「本会话总是允许」记住触发 ask 的前缀，而不是整句 ls && rm。"""
        if tool_name != "bash":
            return {tool_name}
        command = str(params.get("command") or "")
        keys: set[str] = set()
        for segment in split_command_segments(command):
            decision = self._match_rules("bash", {"command": segment})
            if has_redirect(segment) and decision.action == "allow":
                decision = Decision("ask", "bash(*>*)", "")
            if decision.action != "allow":
                prefix = command_prefix(segment)
                if prefix:
                    keys.add(f"bash:{prefix}")
        if not keys:
            prefix = command_prefix(command)
            if prefix:
                keys.add(f"bash:{prefix}")
        return keys

    def remember_session(self, tool_name: str, params: dict) -> None:
        self._session_allow.update(self.session_keys(tool_name, params))

    def session_allows(self, tool_name: str, params: dict) -> bool:
        keys = self.session_keys(tool_name, params)
        # 必须全部前缀都已放行：rm && git push 不能因为记得 rm 就把 push 放走
        return bool(keys) and keys <= self._session_allow

    async def authorize(
        self,
        tool_name: str,
        params: dict,
        *,
        approver: Approver | None = None,
        call_id: str = "",
    ) -> Decision:
        decision = self.evaluate(tool_name, params)
        if decision.action == "allow":
            return decision
        if decision.action == "deny":
            return decision
        if self.session_allows(tool_name, params):
            return Decision("allow", decision.rule, "本会话已允许此前缀")
        if approver is None:
            return Decision("deny", decision.rule, "需要审批但当前无交互界面")
        choice = await approver(
            PermissionRequest(
                tool_name=tool_name,
                params=params,
                preview=preview_call(tool_name, params),
                reason=decision.reason,
                call_id=call_id,
            )
        )
        if choice.action == "allow_session":
            self.remember_session(tool_name, params)
            return Decision("allow", decision.rule, "用户允许（本会话）")
        if choice.action == "allow_once":
            return Decision("allow", decision.rule, "用户允许一次")
        reason = choice.reason.strip() or "用户拒绝了该操作"
        return Decision("deny", decision.rule, reason)
