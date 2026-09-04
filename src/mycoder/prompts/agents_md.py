"""Day 6 · 从工作区向上收集 AGENTS.md（近者优先）。"""

from pathlib import Path


def collect_agents_md(start: Path) -> str:
    """从 start 向上走到 git 根或用户主目录，收集沿途 AGENTS.md。"""
    start = start.resolve()
    home = Path.home()
    sections: list[str] = []
    current = start

    while True:
        agents_file = current / "AGENTS.md"
        if agents_file.is_file():
            try:
                body = agents_file.read_text(encoding="utf-8").strip()
            except OSError:
                body = ""
            if body:
                try:
                    label = str(agents_file.relative_to(start))
                except ValueError:
                    label = str(agents_file)
                sections.append(f"#### {label}\n{body}")

        if (current / ".git").exists() or current == home:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    if not sections:
        return ""
    return "\n\n".join(sections)
