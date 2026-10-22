#!/usr/bin/env python3
"""Claude Code SessionStart hook: inject the vault's live working context.

Fires on startup, resume, /clear and after compaction, so a fresh or compacted
session always starts knowing the current task. Stdlib only.

Config (env):
  OAR_VAULT            vault root (default: $CLAUDE_PROJECT_DIR, then the hook payload's cwd)
  OAR_CONTEXT_FILES    comma-separated vault-relative files to inject
                       (default: STATE/working-context.md)
  OAR_CONTEXT_MAX      max characters per file (default: 4000)
"""
import json
import os
import pathlib
import sys


def build_context(payload: dict) -> str:
    vault = pathlib.Path(
        os.environ.get("OAR_VAULT") or os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    )
    files = [f.strip() for f in os.environ.get("OAR_CONTEXT_FILES", "STATE/working-context.md").split(",") if f.strip()]
    limit = int(os.environ.get("OAR_CONTEXT_MAX", "4000"))
    parts = []
    for rel in files:
        p = (vault / rel).resolve()
        if vault.resolve() not in p.parents or not p.is_file():
            continue  # stay inside the vault; silently skip missing files
        text = p.read_text(encoding="utf-8", errors="replace")
        if len(text) > limit:
            text = text[:limit] + "\n[... truncated ...]"
        parts.append(f"[{rel}]\n{text.strip()}")
    return "\n\n".join(parts)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    event = payload.get("hook_event_name", "SessionStart")
    context = build_context(payload)
    if context:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
