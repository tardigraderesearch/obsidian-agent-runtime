#!/usr/bin/env python3
"""Claude Code PostToolUse hook (Write|Edit|MultiEdit): make a just-written note
searchable right away by re-indexing only that file (milliseconds).

Must run under the interpreter that has obsidian-agent-runtime installed
(`init` writes that interpreter into .claude/settings.json). Never blocks the
agent: any failure exits 0 silently.

Config (env): OAR_VAULT (default: $CLAUDE_PROJECT_DIR), OAR_DB, OAR_EXCLUDE.
"""
import json
import os
import pathlib
import sys


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        tool_input = payload.get("tool_input") or {}
        target = tool_input.get("file_path") or tool_input.get("notebook_path")
        vault = os.environ.get("OAR_VAULT") or os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd")
        if not target or not vault or not str(target).endswith(".md"):
            return 0
        vault_p = pathlib.Path(vault).resolve()
        target_p = pathlib.Path(target)
        if not target_p.is_absolute():
            target_p = vault_p / target_p
        if vault_p not in target_p.resolve().parents:
            return 0  # wrote outside the vault
        from obsidian_agent_runtime.config import load_settings
        from obsidian_agent_runtime.indexer import index_paths

        index_paths(load_settings(vault_p), [target_p])
    except Exception:  # noqa: BLE001 - a hook must never break the session
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
