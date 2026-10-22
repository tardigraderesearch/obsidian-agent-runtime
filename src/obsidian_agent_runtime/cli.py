"""Command-line entry point: ``obsidian-agent-runtime`` (alias ``oar``)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import load_settings


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--vault", help="vault root (default: $OAR_VAULT, $OBSIDIAN_VAULT_PATH, or cwd)")
    p.add_argument("--db", help="index database path (default: $OAR_DB or a per-vault file in ~/.cache)")
    p.add_argument(
        "--exclude",
        action="append",
        metavar="PREFIX",
        help="vault-relative path prefix to skip (repeatable; replaces the default STATE/transcripts)",
    )


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="obsidian-agent-runtime",
        description="Turn a markdown (Obsidian) vault into searchable persistent memory for Claude Code.",
    )
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="build or refresh the FTS5 index")
    _common(p)
    p.add_argument("--full", action="store_true", help="rebuild from scratch")
    p.add_argument("--file", action="append", metavar="PATH", help="re-index only these files (repeatable)")

    p = sub.add_parser("search", help="search the vault from the shell")
    _common(p)
    p.add_argument("query", nargs="+")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--type", dest="note_type", help="filter by note type (semantic|procedural|episodic|...)")
    p.add_argument("--json", action="store_true", help="JSON output")

    p = sub.add_parser("serve", help="run the MCP server on stdio")
    _common(p)

    p = sub.add_parser("init", help="write .mcp.json, .claude/ hooks+agents and CLAUDE.md into a vault")
    p.add_argument("vault", help="vault root to wire up")
    p.add_argument("--force", action="store_true", help="overwrite existing files")
    p.add_argument("--python", help="interpreter recorded in the configs (default: this one)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "init":
        from .init import init_vault

        try:
            report = init_vault(Path(args.vault), force=args.force, python=args.python)
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            return 2
        for dest, action in report:
            print(f"{action:>8}  {dest}")
        print("\nNext: open the vault in Claude Code (`cd <vault> && claude`) and approve the 'vault' MCP server.")
        return 0

    settings = load_settings(args.vault, args.db, args.exclude)

    if args.cmd == "index":
        from .indexer import build_index, index_paths

        try:
            stats = index_paths(settings, args.file) if args.file else build_index(settings, full=args.full)
        except FileNotFoundError as e:
            print(e, file=sys.stderr)
            return 2
        print(stats.summary())
        print(f"DB: {settings.db}")
        return 0

    if args.cmd == "search":
        from .search import SearchError, format_json, format_markdown, search

        try:
            result = search(settings, " ".join(args.query), top=args.top, note_type=args.note_type)
        except (SearchError, FileNotFoundError) as e:
            print(e, file=sys.stderr)
            return 1
        sys.stdout.write(format_json(result) if args.json else format_markdown(result))
        return 0

    if args.cmd == "serve":
        from .server import serve

        serve(settings)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
