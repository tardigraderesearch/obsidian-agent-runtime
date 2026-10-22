"""`init`: wire a vault into Claude Code by rendering the templates into it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# (template path relative to templates/, destination relative to the vault, executable)
FILES = (
    ("CLAUDE.md", "CLAUDE.md", False),
    ("mcp.json", ".mcp.json", False),
    ("settings.json", ".claude/settings.json", False),
    ("agents/vault-recall.md", ".claude/agents/vault-recall.md", False),
    ("agents/vault-memory.md", ".claude/agents/vault-memory.md", False),
    ("hooks/session_context.py", ".claude/hooks/session_context.py", True),
    ("hooks/reindex.py", ".claude/hooks/reindex.py", True),
)


def templates_dir() -> Path:
    packaged = Path(__file__).resolve().parent / "templates"
    if packaged.is_dir():
        return packaged
    repo = Path(__file__).resolve().parents[2] / "templates"  # source checkout / editable install
    if repo.is_dir():
        return repo
    raise FileNotFoundError("templates directory not found in package or source tree")


def render(text: str, vault: Path, python: str) -> str:
    # JSON-escape the substitutions so paths with quotes/backslashes stay valid in JSON templates.
    py = json.dumps(python)[1:-1]
    v = json.dumps(str(vault))[1:-1]
    return text.replace("{{PYTHON}}", py).replace("{{VAULT}}", v)


def init_vault(vault: Path, force: bool = False, python: str | None = None) -> list[tuple[str, str]]:
    """Render templates into ``vault``. Returns [(dest, action)] with action written|skipped."""
    vault = vault.expanduser().resolve()
    if not vault.is_dir():
        raise FileNotFoundError(f"vault not found: {vault}")
    python = python or sys.executable
    src_root = templates_dir()
    report = []
    for src_rel, dest_rel, executable in FILES:
        dest = vault / dest_rel
        if dest.exists() and not force:
            report.append((dest_rel, "skipped (exists; use --force)"))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render((src_root / src_rel).read_text(encoding="utf-8"), vault, python), encoding="utf-8")
        if executable:
            dest.chmod(0o755)
        report.append((dest_rel, "written"))
    return report
