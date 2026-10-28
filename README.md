# obsidian-agent-runtime

[![CI](https://github.com/tardigraderesearch/obsidian-agent-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/tardigraderesearch/obsidian-agent-runtime/actions/workflows/ci.yml)

**Part of ARI → [tardigraderesearch/ari](https://github.com/tardigraderesearch/ari).** This is ARI's open engine: the search
server, hooks, subagents and idle watcher that let [Claude Code](https://docs.claude.com/en/docs/claude-code)
use a markdown vault (Obsidian, or any folder of `.md` notes) as its long-term memory. What each piece does, the
architecture diagram and how search works are described in the [ARI README](https://github.com/tardigraderesearch/ari#the-open-engine-obsidian-agent-runtime).
This repo holds the source, install steps and quickstart.

## Quickstart (about 5 minutes)

Requires Python 3.11+ with SQLite FTS5 support (standard CPython builds include it), and Claude Code installed and signed in for step 2. Commands assume a POSIX shell.

```bash
git clone https://github.com/tardigraderesearch/obsidian-agent-runtime
cd obsidian-agent-runtime
python3 -m venv .venv && . .venv/bin/activate
pip install .

# 1. Index and search the bundled fictional demo vault from the shell
obsidian-agent-runtime index  --vault demo-vault
obsidian-agent-runtime search --vault demo-vault --top 3 "capacitive probes"
```

Expected output:

```
Indexed: 16 files / 56 chunks. Unchanged: 0. Pruned: 0. (0.00s)
DB: ~/.cache/obsidian-agent-runtime/demo-vault-<hash>.db
- [[REFERENCE/decisions-log.md]] > 2026-02-20: capacitive soil probes (semantic, bm25=-5.42)
  Chose **capacitive** over resistive **probes** for [[PROJECTS/greenhouse-controller]]. Reason: resistive **probes** corrode within weeks in…
- [[REFERENCE/soil-moisture-sensors.md]] > Capacitive (semantic, bm25=-4.18)
  …Needs per-**probe** calibration (dry and wet reference readings) because boards vary.
- [[PROJECTS/greenhouse-controller.md]] > Decisions (semantic, bm25=-3.89)
  - **Capacitive** **probes**, not resistive. See [[REFERENCE/decisions-log]].
```

The 17th file, `STATE/transcripts/...`, is excluded on purpose: raw transcripts are staging data, not memory.

```bash
# 2. Wire a copy of the demo vault into Claude Code
cp -r demo-vault ~/oar-demo
obsidian-agent-runtime init ~/oar-demo
cd ~/oar-demo && claude
```

Approve the `vault` MCP server when prompted, then try:

- "What am I working on?" (answered from the injected working context)
- "Why did we choose capacitive probes?" (the agent spawns `vault-recall`, which calls `vault_search`)
- "Remember that Elisabeth is returning the oscilloscope on April 20." (the agent spawns
  `vault-memory`, which updates `PEOPLE/priya.md` or `REFERENCE/workshop-tools.md`; the
  PostToolUse hook makes the edit searchable immediately)

`oar` is a short alias for `obsidian-agent-runtime`.

## Wiring into Claude Code by hand

`obsidian-agent-runtime init <vault>` writes all of this for you (it skips any file that already exists, with no merging, and `--force` overwrites those files entirely, so back up an existing `.mcp.json`, `.claude/settings.json` or `CLAUDE.md` first). To do it manually:

`.mcp.json` in the vault root:

```json
{
  "mcpServers": {
    "vault": {
      "type": "stdio",
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "obsidian_agent_runtime", "serve"],
      "env": { "OAR_VAULT": "/path/to/vault" }
    }
  }
}
```

`.claude/settings.json`:

```json
{
  "permissions": { "allow": ["mcp__vault__vault_search", "mcp__vault__vault_reindex"] },
  "enabledMcpjsonServers": ["vault"],
  "autoMemoryEnabled": false,
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command",
        "command": "\"/path/to/venv/bin/python\" \"$CLAUDE_PROJECT_DIR/.claude/hooks/session_context.py\"" }] }
    ],
    "PostToolUse": [
      { "matcher": "Write|Edit|MultiEdit",
        "hooks": [{ "type": "command",
          "command": "\"/path/to/venv/bin/python\" \"$CLAUDE_PROJECT_DIR/.claude/hooks/reindex.py\"" }] }
    ]
  }
}
```

Then copy `templates/hooks/*.py` to `.claude/hooks/`, `templates/agents/*.md` to
`.claude/agents/`, and adapt `templates/CLAUDE.md` into the vault root. The adapter
assumes the vault has a `README.md` describing its layout and a filing rule; see
`demo-vault/README.md` for a minimal example.

### Configuration

| Variable | Used by | Default |
|---|---|---|
| `OAR_VAULT` (or `OBSIDIAN_VAULT_PATH`) | CLI, server, hooks | current directory (hooks: `$CLAUDE_PROJECT_DIR`) |
| `OAR_DB` | CLI, server, reindex hook | `~/.cache/obsidian-agent-runtime/<vault-name>-<hash>.db` |
| `OAR_EXCLUDE` | indexer | `STATE/transcripts` (comma-separated prefixes, added to the default) |
| `OAR_REFRESH_SECONDS` | server | `60` (`-1` disables auto-refresh) |
| `OAR_CONTEXT_FILES` | SessionStart hook | `STATE/working-context.md` (comma-separated) |
| `OAR_CONTEXT_MAX` | SessionStart hook | `4000` characters per file |

## Idle watcher (optional)

Parks an idle long-running session's transcript into the vault and `/clear`s it
([how it works](https://github.com/tardigraderesearch/ari#the-open-engine-obsidian-agent-runtime)).
Pass `--on-park "CMD"` or set `OAR_ON_PARK` to run `CMD <transcript-path>` after each park.

Run these from the cloned repository root (the quickstart left you in the demo vault). The watcher needs Linux, tmux and a systemd user manager.

```bash
cd /path/to/obsidian-agent-runtime
mkdir -p ~/.config/systemd/user
watcher/start-session.sh ~/my-vault assistant          # tmux session "assistant" running claude
python3 watcher/idle_watcher.py --vault ~/my-vault --tmux-target assistant --dry-run --force
cp watcher/systemd/oar-idle-watcher.* ~/.config/systemd/user/   # edit paths first
systemctl --user daemon-reload && systemctl --user enable --now oar-idle-watcher.timer
```

It is stdlib-only and tracks previously parked content in a local state file to avoid duplicate parking.

## Development

```bash
cd /path/to/obsidian-agent-runtime
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
```

## License

MIT. See [LICENSE](LICENSE).

## How this was built
AI is used here as a tool to speed up implementation. I design the system and
define what "working" means. When issues are found, they're identified, and
ARI — my own agent system — fixes them against those checks.
