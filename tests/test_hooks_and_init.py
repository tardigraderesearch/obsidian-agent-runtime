import json
import os
import subprocess
import sys
from pathlib import Path

from obsidian_agent_runtime.cli import main as cli_main
from obsidian_agent_runtime.config import load_settings
from obsidian_agent_runtime.init import init_vault, templates_dir
from obsidian_agent_runtime.search import search

HOOKS = templates_dir() / "hooks"


def run_hook(name, payload, env):
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=60,
    )


def test_session_context_injects_working_context(vault):
    r = run_hook("session_context.py", {"hook_event_name": "SessionStart"}, {"CLAUDE_PROJECT_DIR": str(vault)})
    assert r.returncode == 0
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "SessionStart"
    assert out["additionalContext"].startswith("[STATE/working-context.md]")
    assert "probe B" in out["additionalContext"]


def test_session_context_truncates_and_rejects_escape(vault, tmp_path):
    (tmp_path / "outside.md").write_text("secret")
    env = {
        "OAR_VAULT": str(vault),
        "OAR_CONTEXT_FILES": "STATE/working-context.md,../outside.md,missing.md",
        "OAR_CONTEXT_MAX": "50",
    }
    r = run_hook("session_context.py", {}, env)
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "[... truncated ...]" in ctx
    assert "secret" not in ctx


def test_session_context_silent_without_files(tmp_path):
    r = run_hook("session_context.py", {"cwd": str(tmp_path)}, {})
    assert r.returncode == 0 and r.stdout == ""


def test_reindex_hook_indexes_written_note(vault):
    settings = load_settings(vault)  # default per-vault db, same as the hook uses
    note = vault / "REFERENCE/rainwater.md"
    note.write_text("# Rainwater\nThe barrel holds 200 litres.\n")
    payload = {"hook_event_name": "PostToolUse", "tool_name": "Write", "tool_input": {"file_path": str(note)}}
    r = run_hook("reindex.py", payload, {"CLAUDE_PROJECT_DIR": str(vault), "XDG_CACHE_HOME": os.environ["XDG_CACHE_HOME"]})
    assert r.returncode == 0 and r.stdout == ""
    res = search(settings, "rainwater barrel", auto_index=False)
    assert res["results"][0]["path"] == "REFERENCE/rainwater.md"


def test_reindex_hook_ignores_outside_and_garbage(vault, tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_text("x")
    env = {"CLAUDE_PROJECT_DIR": str(vault)}
    assert run_hook("reindex.py", {"tool_input": {"file_path": str(outside)}}, env).returncode == 0
    r = subprocess.run([sys.executable, str(HOOKS / "reindex.py")], input="not json", capture_output=True, text=True)
    assert r.returncode == 0


def test_init_renders_valid_configs(vault):
    report = dict(init_vault(vault, python="/opt/py/bin/python"))
    assert all(v == "written" for v in report.values())
    mcp = json.loads((vault / ".mcp.json").read_text())
    server = mcp["mcpServers"]["vault"]
    assert server["command"] == "/opt/py/bin/python"
    assert server["env"]["OAR_VAULT"] == str(vault.resolve())
    settings = json.loads((vault / ".claude/settings.json").read_text())
    assert "mcp__vault__vault_search" in settings["permissions"]["allow"]
    assert settings["hooks"]["PostToolUse"][0]["matcher"] == "Write|Edit|MultiEdit"
    assert os.access(vault / ".claude/hooks/reindex.py", os.X_OK)
    assert "{{" not in (vault / "CLAUDE.md").read_text()
    # second run must not clobber
    assert all(v.startswith("skipped") for v in dict(init_vault(vault)).values())


def test_cli_search_and_help(vault, capsys):
    assert cli_main(["index", "--vault", str(vault)]) == 0
    assert cli_main(["search", "--vault", str(vault), "oscilloscope"]) == 0
    out = capsys.readouterr().out
    assert "REFERENCE/workshop-tools.md" in out
    r = subprocess.run([sys.executable, "-m", "obsidian_agent_runtime", "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "serve" in r.stdout



def test_templates_only_use_known_placeholders():
    import re

    for p in Path(templates_dir()).rglob("*"):
        if p.is_file() and p.suffix in {".md", ".json", ".py"}:
            assert set(re.findall(r"{{(\w+)}}", p.read_text())) <= {"PYTHON", "VAULT"}, p
