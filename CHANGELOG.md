# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-22

### Added

- SQLite FTS5 indexer for markdown vaults: per-section chunking, frontmatter tags and
  types, wikilink targets, weighted BM25, incremental reindex (mtime/size, then sha1) with
  pruning of deleted notes, single-file reindex.
- `vault_search` and `vault_reindex` tools on a stdio MCP server, with automatic
  incremental refresh before searches.
- `obsidian-agent-runtime` / `oar` CLI: `index`, `search`, `serve`, `init`.
- Claude Code templates: `CLAUDE.md` adapter, SessionStart working-context hook,
  PostToolUse reindex hook, `vault-recall` and `vault-memory` subagents, `.mcp.json` and
  `settings.json`.
- Idle watcher that parks idle session transcripts into the vault and `/clear`s the
  session, with an `on_park` hook point; systemd user timer and tmux launcher examples.
- Fictional demo vault, pytest suite, GitHub Actions CI for Python 3.11 and 3.12.
