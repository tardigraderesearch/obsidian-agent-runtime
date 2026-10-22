"""MCP server (stdio) exposing the vault as an agent's memory.

Tools:
  vault_search  - BM25 full-text search over every note (the memory read interface)
  vault_reindex - refresh the index (incremental by default)

Before a search the server runs a cheap incremental reindex if the last one is
older than ``OAR_REFRESH_SECONDS`` (default 60), so edits made outside the agent
(e.g. in Obsidian) become searchable without a manual step.
"""

from __future__ import annotations

import json
import os
import time

from .config import Settings, load_settings
from .indexer import build_index
from .search import SearchError, search


class VaultService:
    """Transport-independent logic behind the MCP tools (easy to unit test)."""

    def __init__(self, settings: Settings, refresh_seconds: float | None = None):
        self.settings = settings
        if refresh_seconds is None:
            refresh_seconds = float(os.environ.get("OAR_REFRESH_SECONDS", "60"))
        self.refresh_seconds = refresh_seconds
        self._last_index = 0.0

    def _maybe_refresh(self) -> None:
        if self.refresh_seconds < 0:
            return
        if time.monotonic() - self._last_index >= self.refresh_seconds:
            build_index(self.settings)
            self._last_index = time.monotonic()

    def vault_search(self, query: str, top: int = 5, note_type: str = "") -> str:
        try:
            self._maybe_refresh()
            result = search(self.settings, query, top=top, note_type=note_type or None)
        except (SearchError, FileNotFoundError) as e:
            return f"vault_search FAILED: {e}"
        if not result["results"]:
            return json.dumps({**result, "note": "no matches; try other phrasings or fewer terms"}, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False, indent=1)

    def vault_reindex(self, full: bool = False) -> str:
        try:
            stats = build_index(self.settings, full=full)
        except FileNotFoundError as e:
            return f"vault_reindex FAILED: {e}"
        self._last_index = time.monotonic()
        return stats.summary()


def _server_class():
    """mcp 2.x renamed FastMCP to MCPServer; support both major versions."""
    try:
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        from mcp.server.fastmcp import FastMCP

        return FastMCP


def build_server(settings: Settings | None = None):
    service = VaultService(settings or load_settings())
    mcp = _server_class()("vault")

    @mcp.tool()
    def vault_search(query: str, top: int = 5, note_type: str = "") -> str:
        """Search long-term memory: the markdown vault. This is the memory read
        interface (BM25 full-text search over every note, ranked per section).
        Use it whenever you need a fact, past decision, standing rule or project
        context and don't already know the exact file. Try 2-3 phrasings if the
        first misses, then open the top notes to read them in full.

        Args:
            query: search terms. Plain words are ANDed (falling back to OR when
                nothing matches); supports "quoted phrases", prefix*, AND/OR/NOT.
            top: number of results (default 5).
            note_type: optional filter: semantic | procedural | episodic (or any
                custom `type:` used in note frontmatter).

        Returns:
            JSON with ranked results (path, title, heading, snippet, note_type, score).
        """
        return service.vault_search(query, top=top, note_type=note_type)

    @mcp.tool()
    def vault_reindex(full: bool = False) -> str:
        """Refresh the vault search index. Incremental by default (only changed
        files are re-read, deleted ones pruned); full=True rebuilds from scratch.
        Normally unnecessary: searches refresh automatically."""
        return service.vault_reindex(full=full)

    return mcp


def serve(settings: Settings | None = None) -> None:
    build_server(settings).run()
