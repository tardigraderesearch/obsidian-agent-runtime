import os
import sqlite3
import time

from obsidian_agent_runtime.config import load_settings, resolve_db
from obsidian_agent_runtime.indexer import (
    build_index,
    chunk_note,
    classify_note_type,
    extract_wikilinks,
    index_paths,
    parse_frontmatter,
    should_skip,
    subdivide_oversized,
)


def _paths(db):
    with sqlite3.connect(db) as c:
        return {r[0] for r in c.execute("SELECT path FROM vault_files")}


def test_frontmatter_parsed_and_stripped():
    fm, body = parse_frontmatter("---\ntags: [a, b]\ntype: Episodic\n---\n# Title\nbody\n")
    assert fm == {"tags": ["a", "b"], "type": "Episodic"}
    assert body.startswith("# Title")


def test_bad_frontmatter_is_ignored():
    fm, body = parse_frontmatter("---\n: : [\n---\ntext")
    assert fm == {}
    assert body == "text"


def test_chunking_by_h2_keeps_preamble():
    chunks = chunk_note("# Note\nintro\n\n## One\nalpha\n\n## Two\nbeta\n")
    assert [h for h, _ in chunks] == ["Note", "One", "Two"]


def test_oversized_section_is_split():
    big = "\n\n".join(["word " * 300] * 10)  # ~15 KB, no H3
    parts = subdivide_oversized("Big", big, max_bytes=4096)
    assert len(parts) > 1
    assert parts[0][0] == "Big (part 1)"
    assert all(len(c.encode()) <= 4096 + 2000 for _, c in parts)


def test_wikilinks_include_basename():
    assert extract_wikilinks("see [[PROJECTS/foo|Foo]] and [[bar#sec]]") == "PROJECTS/foo bar foo"


def test_note_type_rules():
    assert classify_note_type("SKILLS/x/SKILL.md", {}) == "procedural"
    assert classify_note_type("STATE/journal/2026-01-01.md", {}) == "episodic"
    assert classify_note_type("REFERENCE/x.md", {}) == "semantic"
    assert classify_note_type("REFERENCE/x.md", {"type": "Decision"}) == "decision"


def test_skip_rules(settings, vault):
    assert should_skip(vault / "STATE/transcripts/x.md", settings)
    assert should_skip(vault / ".obsidian/x.md", settings)
    assert should_skip(vault / "PEOPLE/credentials/api.md", settings)
    assert should_skip(vault / "notes/a.sync-conflict-2026.md", settings)
    assert not should_skip(vault / "PEOPLE/jordan.md", settings)


def test_full_index_of_demo_vault(settings):
    stats = build_index(settings)
    paths = _paths(settings.db)
    assert stats.indexed_files == len(paths) == 16  # 17 files minus the excluded transcript
    assert not any(p.startswith("STATE/transcripts") for p in paths)
    assert stats.indexed_chunks > stats.indexed_files


def test_incremental_reindex(settings, vault):
    build_index(settings)
    again = build_index(settings)
    assert again.indexed_files == 0 and again.unchanged == 16

    note = vault / "PEOPLE/priya.md"
    note.write_text(note.read_text() + "\n## New\nPriya now keeps bees.\n")
    os.utime(note, (time.time() + 5, time.time() + 5))
    (vault / "PROJECTS/bike-rebuild.md").unlink()
    (vault / "REFERENCE/new-note.md").write_text("# New note\nhello\n")

    stats = build_index(settings)
    assert stats.indexed_files == 2
    assert stats.pruned == 1
    assert "PROJECTS/bike-rebuild.md" not in _paths(settings.db)


def test_touch_without_content_change_is_cheap(settings, vault):
    build_index(settings)
    note = vault / "PEOPLE/jordan.md"
    os.utime(note, (time.time() + 10, time.time() + 10))
    stats = build_index(settings)
    assert stats.indexed_files == 0 and stats.unchanged == 16


def test_index_paths_single_file_and_delete(settings, vault):
    build_index(settings)
    new = vault / "REFERENCE/compost.md"
    new.write_text("# Compost\nTurn the pile weekly.\n")
    stats = index_paths(settings, [new, vault / "README.txt", vault / "STATE/transcripts/x.md"])
    assert stats.indexed_files == 1
    new.unlink()
    stats = index_paths(settings, ["REFERENCE/compost.md"])
    assert stats.pruned == 1
    assert "REFERENCE/compost.md" not in _paths(settings.db)


def test_custom_excludes(vault, tmp_path):
    s = load_settings(vault, tmp_path / "x.db", excludes=["STATE"])
    build_index(s)
    assert not any(p.startswith("STATE/") for p in _paths(s.db))


def test_default_db_is_outside_vault_and_per_vault(vault, tmp_path):
    a = resolve_db(vault)
    b = resolve_db(tmp_path)
    assert vault not in a.parents
    assert a != b
