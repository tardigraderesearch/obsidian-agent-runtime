"""Build and incrementally refresh a SQLite FTS5 index over a markdown vault.

Each note is split into heading-sized chunks (one per ``##`` section; sections
larger than ``CHUNK_MAX_BYTES`` are sub-split on ``###`` or on paragraphs), so a
search hit points at the relevant section rather than a whole file.

Incremental mode compares each file's mtime and size with what was recorded at
the last index run and only re-reads changed files; deleted files are pruned.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from .config import Settings

SCHEMA_VERSION = "2"
CHUNK_MAX_BYTES = 8 * 1024

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
H1_RE = re.compile(r"^# +(.+?)\s*$", re.MULTILINE)
H2_RE = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)
H3_RE = re.compile(r"^### +(.+?)\s*$", re.MULTILINE)
CONFLICT_RE = re.compile(r"\.conflict-|\.sync-conflict-")


@dataclass
class IndexStats:
    indexed_files: int = 0
    indexed_chunks: int = 0
    unchanged: int = 0
    pruned: int = 0
    seconds: float = 0.0

    def summary(self) -> str:
        return (
            f"Indexed: {self.indexed_files} files / {self.indexed_chunks} chunks. "
            f"Unchanged: {self.unchanged}. Pruned: {self.pruned}. ({self.seconds:.2f}s)"
        )


# --------------------------------------------------------------------------- parsing


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Return (frontmatter dict, body). Invalid or non-mapping YAML yields {}."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    body_start = end + 4
    if body_start < len(text) and text[body_start] == "\n":
        body_start += 1
    try:
        fm = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        fm = {}
    return (fm if isinstance(fm, dict) else {}), text[body_start:]


def split_by_h2(body: str) -> list[tuple[str, str]]:
    matches = list(H2_RE.finditer(body))
    if not matches:
        h1 = H1_RE.search(body)
        return [(h1.group(1).strip() if h1 else "", body)]
    chunks = []
    preamble = body[: matches[0].start()]
    if preamble.strip():
        h1 = H1_RE.search(preamble)
        chunks.append((h1.group(1).strip() if h1 else "", preamble))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        chunks.append((m.group(1).strip(), body[m.end() : end]))
    return chunks


def subdivide_oversized(heading: str, content: str, max_bytes: int = CHUNK_MAX_BYTES) -> list[tuple[str, str]]:
    if len(content.encode("utf-8")) <= max_bytes:
        return [(heading, content)]
    h3 = list(H3_RE.finditer(content))
    if h3:
        out = []
        preamble = content[: h3[0].start()]
        if preamble.strip():
            out.append((heading, preamble))
        for i, m in enumerate(h3):
            end = h3[i + 1].start() if i + 1 < len(h3) else len(content)
            sub = m.group(1).strip()
            out.append((f"{heading} / {sub}" if heading else sub, content[m.end() : end]))
        return out
    out, buf, size, part = [], [], 0, 1
    for para in re.split(r"\n\s*\n", content):
        psize = len(para.encode("utf-8")) + 2
        if buf and size + psize > max_bytes:
            out.append((f"{heading} (part {part})" if heading else f"part {part}", "\n\n".join(buf)))
            buf, size, part = [para], psize, part + 1
        else:
            buf.append(para)
            size += psize
    if buf:
        label = heading if part == 1 else (f"{heading} (part {part})" if heading else f"part {part}")
        out.append((label, "\n\n".join(buf)))
    return out


def chunk_note(body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for heading, content in split_by_h2(body):
        out.extend(subdivide_oversized(heading, content))
    return [(h, c) for h, c in out if c.strip()]


def extract_wikilinks(body: str) -> str:
    targets = set()
    for m in WIKILINK_RE.finditer(body):
        link = m.group(1).strip()
        if link:
            targets.add(link)
            if "/" in link:
                targets.add(link.rsplit("/", 1)[-1])
    return " ".join(sorted(targets))


def frontmatter_tags(fm: dict) -> str:
    tags = fm.get("tags")
    if isinstance(tags, str):
        return " ".join(t.strip().lstrip("#") for t in re.split(r"[,\s]+", tags) if t.strip())
    if isinstance(tags, list):
        return " ".join(str(t).lstrip("#") for t in tags)
    return ""


def classify_note_type(rel_path: str, fm: dict) -> str:
    """Coarse memory type used for filtering.

    A ``type:`` frontmatter key always wins. Otherwise:
    ``SKILLS/...`` -> procedural; any ``journal`` folder -> episodic; else semantic.
    """
    declared = fm.get("type")
    if isinstance(declared, str) and declared.strip():
        return declared.strip().lower()
    parts = rel_path.split("/")
    if parts[0].lower() == "skills":
        return "procedural"
    if any(p.lower() == "journal" for p in parts[:-1]):
        return "episodic"
    return "semantic"


def note_title(rel_path: str, fm: dict, body: str) -> str:
    if isinstance(fm.get("title"), str):
        return fm["title"]
    h1 = H1_RE.search(body)
    return h1.group(1).strip() if h1 else Path(rel_path).stem.replace("-", " ")


# --------------------------------------------------------------------------- file walking


def relpath(path: Path, vault: Path) -> str:
    return path.relative_to(vault).as_posix()


def should_skip(path: Path, settings: Settings) -> bool:
    try:
        rel = path.relative_to(settings.vault)
    except ValueError:
        return True
    if any(p in settings.skip_dirs for p in rel.parts[:-1]):
        return True
    if path.name.startswith(".") or CONFLICT_RE.search(path.name):
        return True
    rel_posix = rel.as_posix()
    return any(rel_posix == ex or rel_posix.startswith(ex + "/") for ex in settings.excludes)


def iter_notes(settings: Settings) -> Iterable[Path]:
    for md in sorted(settings.vault.rglob("*.md")):
        if md.is_file() and not should_skip(md, settings):
            yield md


# --------------------------------------------------------------------------- database


def connect(db_path: Path, rebuild: bool = False) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS oar_meta(key TEXT PRIMARY KEY, value TEXT)")
    row = conn.execute("SELECT value FROM oar_meta WHERE key = 'schema'").fetchone()
    if rebuild or (row and row[0] != SCHEMA_VERSION):
        conn.executescript("DROP TABLE IF EXISTS vault_fts; DROP TABLE IF EXISTS vault_files;")
    conn.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
            path UNINDEXED, title, heading, body, links, tags, note_type UNINDEXED,
            tokenize = 'porter unicode61 remove_diacritics 1'
        );
        CREATE TABLE IF NOT EXISTS vault_files(
            path TEXT PRIMARY KEY, mtime REAL, size INTEGER, sha1 TEXT,
            chunks INTEGER, indexed_at REAL
        );
        """
    )
    conn.execute("INSERT OR REPLACE INTO oar_meta(key, value) VALUES ('schema', ?)", (SCHEMA_VERSION,))
    conn.commit()
    return conn


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(65536), b""):
            h.update(blk)
    return h.hexdigest()


def _remove(conn: sqlite3.Connection, rel: str) -> None:
    conn.execute("DELETE FROM vault_fts WHERE path = ?", (rel,))
    conn.execute("DELETE FROM vault_files WHERE path = ?", (rel,))


def index_file(conn: sqlite3.Connection, path: Path, settings: Settings, force: bool = False) -> int | None:
    """Index one note. Returns chunks written, or None when the file was unchanged/unreadable."""
    rel = relpath(path, settings.vault)
    st = path.stat()
    prev = conn.execute("SELECT mtime, size, sha1 FROM vault_files WHERE path = ?", (rel,)).fetchone()
    if not force and prev and prev[0] == st.st_mtime and prev[1] == st.st_size:
        return None
    sha = _sha1(path)
    if not force and prev and prev[2] == sha:
        conn.execute("UPDATE vault_files SET mtime = ?, size = ? WHERE path = ?", (st.st_mtime, st.st_size, rel))
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    fm, body = parse_frontmatter(text)
    title = note_title(rel, fm, body)
    ntype = classify_note_type(rel, fm)
    tags = frontmatter_tags(fm)
    _remove(conn, rel)
    chunks = chunk_note(body)
    for heading, content in chunks:
        conn.execute(
            "INSERT INTO vault_fts(path, title, heading, body, links, tags, note_type) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rel, title, heading, content, extract_wikilinks(content), tags, ntype),
        )
    conn.execute(
        "INSERT INTO vault_files(path, mtime, size, sha1, chunks, indexed_at) VALUES (?, ?, ?, ?, ?, ?)",
        (rel, st.st_mtime, st.st_size, sha, len(chunks), time.time()),
    )
    return len(chunks)


def build_index(settings: Settings, full: bool = False) -> IndexStats:
    """Index the whole vault (incremental unless ``full``)."""
    t0 = time.perf_counter()
    if not settings.vault.is_dir():
        raise FileNotFoundError(f"vault not found: {settings.vault}")
    stats = IndexStats()
    conn = connect(settings.db, rebuild=full)
    try:
        with conn:
            on_disk = set()
            for md in iter_notes(settings):
                on_disk.add(relpath(md, settings.vault))
                n = index_file(conn, md, settings, force=full)
                if n is None:
                    stats.unchanged += 1
                else:
                    stats.indexed_files += 1
                    stats.indexed_chunks += n
            known = {r[0] for r in conn.execute("SELECT path FROM vault_files")}
            for rel in known - on_disk:
                _remove(conn, rel)
                stats.pruned += 1
    finally:
        conn.close()
    stats.seconds = time.perf_counter() - t0
    return stats


def index_paths(settings: Settings, paths: Iterable[str | Path]) -> IndexStats:
    """Re-index specific files only (used by the post-write hook). Missing files are removed."""
    t0 = time.perf_counter()
    stats = IndexStats()
    conn = connect(settings.db)
    try:
        with conn:
            for p in paths:
                path = Path(p)
                if not path.is_absolute():
                    path = settings.vault / path
                path = path.resolve()
                if path.suffix.lower() != ".md" or should_skip(path, settings):
                    continue
                rel = relpath(path, settings.vault)
                if not path.exists():
                    _remove(conn, rel)
                    stats.pruned += 1
                    continue
                n = index_file(conn, path, settings)
                if n is None:
                    stats.unchanged += 1
                else:
                    stats.indexed_files += 1
                    stats.indexed_chunks += n
    finally:
        conn.close()
    stats.seconds = time.perf_counter() - t0
    return stats
