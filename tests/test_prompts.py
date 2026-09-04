"""Day 6 · 系统提示词与 AGENTS.md 单测。"""

from pathlib import Path

import pytest

from mycoder.prompts.agents_md import collect_agents_md
from mycoder.prompts.system import build_system_prompt, collect_environment, estimate_tokens
from mycoder.tools import DEFAULT_TOOLS


def test_collect_agents_md_nearest_first(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "pkg" / "sub"
    sub.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("root rule", encoding="utf-8")
    (sub / "AGENTS.md").write_text("sub rule", encoding="utf-8")

    text = collect_agents_md(sub)
    assert "sub rule" in text
    assert "root rule" in text
    assert text.index("sub rule") < text.index("root rule")


def test_build_system_prompt_under_token_budget() -> None:
    prompt = build_system_prompt(DEFAULT_TOOLS)
    assert estimate_tokens(prompt) <= 1500
    assert "工作准则" in prompt
    assert "read_file" in prompt
    assert "AGENTS.md" in prompt or "项目约定" in prompt


def test_minimal_prompt_for_ab_comparison() -> None:
    full = build_system_prompt(DEFAULT_TOOLS)
    minimal = build_system_prompt(DEFAULT_TOOLS, minimal=True)
    assert len(minimal) < len(full)
    assert "工作准则" not in minimal


def test_environment_has_date_and_git() -> None:
    env = collect_environment(Path.cwd())
    assert "今天日期:" in env
    assert len(env.split("今天日期:")[1].splitlines()[0].strip()) == 10  # YYYY-MM-DD
    if (Path.cwd() / ".git").exists():
        assert "git 分支" in env


def test_agents_md_injected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("MYCODER_WORKSPACE", str(tmp_path))
    (tmp_path / "AGENTS.md").write_text("注释一律中文", encoding="utf-8")
    prompt = build_system_prompt(DEFAULT_TOOLS, tmp_path)
    assert "注释一律中文" in prompt
