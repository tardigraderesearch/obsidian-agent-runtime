"""BM25 search over the FTS5 index built by :mod:`obsidian_agent_runtime.indexer`."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass

from .config import Settings
from .indexer import build_index

FTS_KEYWORDS = {"AND", "OR", "NOT", "NEAR"}
# bm25 column weights, in table column order:
# path(unindexed), title, heading, body, links, tags, note_type(unindexed)
BM25_WEIGHTS = (0.0, 5.0, 3.0, 1.0, 2.0, 2.0, 0.0)


class SearchError(RuntimeError):
    pass


@dataclass
class Hit:
    path: str
    title: str
    heading: str
    snippet: str
    note_type: str
    score: float  # bm25: lower (more negative) is a better match


def fts_query(query: str, any_term: bool = False) -> str:
    """Turn free text into a safe FTS5 query.

    Each plain term is quoted (so punctuation can't break the parser); a trailing
    ``*`` is kept as a prefix match. Explicit AND/OR/NOT/NEAR and "quoted phrases"
    pass through. ``any_term`` joins plain terms with OR instead of the implicit AND.
    """
    parts: list[str] = []
    buf = query.strip()
    i = 0
    tokens: list[tuple[str, bool]] = []  # (text, is_phrase)
    while i < len(buf):
        if buf[i].isspace():
            i += 1
            continue
        if buf[i] == '"':
            j = buf.find('"', i + 1)
            j = len(buf) if j == -1 else j
            tokens.append((buf[i + 1 : j], True))
            i = j + 1
            continue
        j = i
        while j < len(buf) and not buf[j].isspace() and buf[j] != '"':
            j += 1
        tokens.append((buf[i:j], False))
        i = j
    prev_was_term = False
    for text, is_phrase in tokens:
        if not is_phrase and text in FTS_KEYWORDS:
            parts.append(text)
            prev_was_term = False
            continue
        prefix = (not is_phrase) and text.endswith("*")
        clean = text.rstrip("*").replace('"', "") if not is_phrase else text.replace('"', "")
        if not clean.strip():
            continue
        if any_term and prev_was_term:
            parts.append("OR")
        parts.append(f'"{clean}"' + ("*" if prefix else ""))
        prev_was_term = True
    return " ".join(parts) if parts else '""'


def _run(conn: sqlite3.Connection, match: str, top: int, note_type: str | None) -> list[Hit]:
    weights = ", ".join(str(w) for w in BM25_WEIGHTS)
    sql = f"""
        SELECT path, title, heading, snippet(vault_fts, 3, '**', '**', '…', 16),
               note_type, bm25(vault_fts, {weights}) AS score
        FROM vault_fts WHERE vault_fts MATCH ?
    """
    params: list = [match]
    if note_type:
        sql += " AND note_type = ?"
        params.append(note_type)
    sql += " ORDER BY score LIMIT ?"
    params.append(max(1, int(top)))
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        raise SearchError(f"FTS query failed ({e}); query was: {match}") from e
    return [Hit(r[0], r[1], r[2], " ".join(r[3].split()), r[4], round(r[5], 4)) for r in rows]


def search(settings: Settings, query: str, top: int = 5, note_type: str | None = None, auto_index: bool = True) -> dict:
    """Search the vault. Builds the index on first use when ``auto_index`` is set.

    Tries all terms first (AND); if nothing matches and the query had more than
    one plain term, falls back to any term (OR) and reports ``"match": "any"``.
    """
    if not settings.db.exists():
        if not auto_index:
            raise SearchError(f"index not found: {settings.db} (run `obsidian-agent-runtime index` first)")
        build_index(settings)
    conn = sqlite3.connect(str(settings.db))
    try:
        hits = _run(conn, fts_query(query), top, note_type)
        mode = "all"
        if not hits:
            relaxed = fts_query(query, any_term=True)
            if relaxed != fts_query(query):
                hits = _run(conn, relaxed, top, note_type)
                mode = "any"
    finally:
        conn.close()
    return {"query": query, "match": mode, "results": [asdict(h) for h in hits]}


def format_markdown(result: dict) -> str:
    hits = result["results"]
    if not hits:
        return "(no matches)\n"
    lines = []
    if result.get("match") == "any":
        lines.append("_(no note matched every term; showing notes that match any term)_")
    for h in hits:
        head = f" > {h['heading']}" if h["heading"] else ""
        lines.append(f"- [[{h['path']}]]{head} ({h['note_type']}, bm25={h['score']:.2f})")
        lines.append(f"  {h['snippet']}")
    return "\n".join(lines) + "\n"


def format_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=1) + "\n"
