# obsidian-agent-runtime

[![CI](https://github.com/evilhobo1911/obsidian-agent-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/evilhobo1911/obsidian-agent-runtime/actions/workflows/ci.yml)

Turn a plain markdown vault (an Obsidian vault, or any folder of `.md` notes) into
persistent, searchable memory for [Claude Code](https://docs.claude.com/en/docs/claude-code).

**Models are interpreters; the vault is the memory.** Context windows end, sessions get
compacted, and you may switch models or runtimes. Notes on disk survive all of that, stay
human-readable and editable in Obsidian, diff cleanly in git, and can be read by any other
agent. This package supplies the small amount of glue that makes Claude Code treat a vault
that way:

| Piece | What it does |
|---|---|
| **`vault_search` MCP server** | SQLite FTS5 index with BM25 ranking, chunked per `##` section; incremental reindex; stdio MCP server exposing `vault_search` and `vault_reindex`. |
| **`CLAUDE.md` adapter** | A thin runtime adapter that `@`-imports the vault's own `README.md` (the canonical rules) and adds only Claude Code-specific facts. |
| **SessionStart hook** | Loads the saved working context at startup, resume, `/clear` and after compaction. |
| **PostToolUse hook** | Re-indexes the affected note after successful Write/Edit tool calls. Other changes (shell, Obsidian, git) are picked up before a later search once the refresh interval has passed (default 60 s). |
| **`vault-recall` / `vault-memory` subagents** | Memory reads and writes run in subagents, keeping intermediate tool output out of the main conversation. |
| **Idle watcher** | Parks an idle long-running session's transcript into the vault, then `/clear`s it. Includes an `on_park` hook point for your own post-processing. |

It is deliberately small: one dependency for MCP, one for YAML frontmatter, no embeddings,
no background daemon. The indexer and MCP server make no network requests of their own; when Claude Code reads retrieved notes, that content goes to your configured model provider like any other context.

## Quickstart (about 5 minutes)

Requires Python 3.11+ with SQLite FTS5 support (standard CPython builds include it), and Claude Code installed and signed in for step 2. Commands assume a POSIX shell.

```bash
git clone https://github.com/evilhobo1911/obsidian-agent-runtime
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

The 17th file, `STATE/transcripts/...`, is excluded on purpose (see below).

```bash
# 2. Wire a copy of the demo vault into Claude Code
cp -r demo-vault ~/oar-demo
obsidian-agent-runtime init ~/oar-demo
cd ~/oar-demo && claude
```

Approve the `vault` MCP server when prompted, then try:

- "What am I working on?" (answered from the injected working context)
- "Why did we choose capacitive probes?" (the agent spawns `vault-recall`, which calls `vault_search`)
- "Remember that Priya is returning the oscilloscope on April 20." (the agent spawns
  `vault-memory`, which updates `PEOPLE/priya.md` or `REFERENCE/workshop-tools.md`; the
  PostToolUse hook makes the edit searchable immediately)

`oar` is a short alias for `obsidian-agent-runtime`.

## Architecture

```
               Claude Code session (cwd = vault)
  ┌──────────────────────────────────────────────────────────────┐
  │ CLAUDE.md ──@import──> README.md (vault's own rules)         │
  │                                                              │
  │ SessionStart hook ──> injects STATE/working-context.md       │
  │                                                              │
  │ main agent ──spawns──> vault-recall  (read-only)  ─┐         │
  │            ──spawns──> vault-memory  (read/write) ─┤         │
  │                                                    │ MCP     │
  │ PostToolUse(Write|Edit) ──> reindex one file       │ stdio   │
  └─────────────────────────────────┬──────────────────┼─────────┘
                                    │                  v
                                    │      obsidian-agent-runtime serve
                                    │        vault_search / vault_reindex
                                    v                  │
        ~/.cache/obsidian-agent-runtime/<vault>.db  <──┘  (SQLite FTS5, BM25)
                       ^
                       │ incremental index (mtime+size, then sha1)
              markdown vault on disk  <── Obsidian, git, other agents
                       ^
                       │ STATE/transcripts/*.md
        idle_watcher.py (systemd timer) ──> on_park hook ──> /clear via tmux
```

### Index and search details

- **Chunking:** one chunk per `##` section (preamble keeps the `#` title); sections over
  8 KB are sub-split on `###`, then on paragraphs. Hits point at the section, not the file.
- **Columns and weights:** `title` (5), `heading` (3), `links` (wikilink targets, 2),
  `tags` (frontmatter tags, 2), `body` (1). Porter stemming plus unicode61 tokenizer.
- **Query handling:** plain words are quoted and ANDed; if nothing matches, the search
  falls back to OR and reports `"match": "any"`. `"phrases"`, `prefix*`, AND/OR/NOT/NEAR
  pass through.
- **Note types:** a `type:` frontmatter key wins; otherwise `SKILLS/...` is `procedural`,
  anything in a `journal/` folder is `episodic`, the rest `semantic`. Filter with
  `note_type` (MCP) or `--type` (CLI).
- **Incremental:** files whose mtime and size are unchanged are skipped without being read;
  a touched-but-identical file is detected by sha1 and not re-chunked; deleted files are
  pruned. The server also runs an incremental pass before a search if the last one is more
  than `OAR_REFRESH_SECONDS` (default 60) old, so edits made in Obsidian show up.
- **Skipped by default:** `.obsidian/`, `.trash/`, `.git/`, `.claude/`, `node_modules/`,
  any folder named `credentials/`, dotfiles, sync-conflict copies, and `STATE/transcripts/`
  (raw session dumps are staging data, not memory). Change the prefix list with
  `--exclude` / `OAR_EXCLUDE`.
- **Index location:** outside the vault (`$XDG_CACHE_HOME` or `~/.cache`), one DB per
  vault path, so Obsidian sync and git never see a binary database.

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

For a long-lived session (for example one kept running in tmux and reached remotely),
`watcher/idle_watcher.py` runs every 10 minutes from a systemd user timer:

1. finds the running Claude Code session whose working directory is the vault;
2. once its last message is `--idle-min` minutes old (default 180), writes the new part of
   the conversation to `STATE/transcripts/YYYY-MM-DD-HHMM-<slug>-<id>.md` (user turns and
   the assistant's visible replies; tool chatter dropped);
3. calls `on_park(transcript_path)`, a documented **no-op hook point**. Pass
   `--on-park "CMD"` or set `OAR_ON_PARK` to run `CMD <path>` (a summarizer that distills
   the transcript into notes, a notifier, a backup job, ...);
4. sends `/clear` to the tmux target, so the next conversation starts clean and the
   SessionStart hook re-injects the working context.

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

## Limitations

- **Lexical search only.** BM25 does not know that "watering" and "irrigation" are related.
  The recall subagent compensates by trying several phrasings, which works well for a
  personal vault but is not semantic retrieval. Embeddings are a possible future option.
- **No write tools in the MCP server by design.** Writes go through Claude Code's own
  Write/Edit tools (visible, permissioned, diffable). Filing quality depends on the vault's
  README rules and on the model following them.
- **Single writer assumed.** Nothing locks notes against concurrent edits by two agents.
- **The idle watcher depends on Claude Code's on-disk session layout**
  (`~/.claude/sessions/*.json`, `~/.claude/projects/<dir>/<id>.jsonl`), which is not a
  public API and may change between releases. `/clear` delivery needs tmux. The
  `--match` option reads `/proc` (Linux).
- **Secrets.** Folders named `credentials/` are skipped, but anything else in the vault is
  indexed and readable by the agent. Keep secrets out of notes.
- CI tests Python 3.11 and 3.12 on Linux; also run locally on 3.14. Not yet tested inside an interactive Claude Code session beyond the hooks and MCP server. macOS should work; Windows is untested.

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
