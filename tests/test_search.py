import pytest

from obsidian_agent_runtime.search import SearchError, format_markdown, fts_query, search


def test_fts_query_quotes_terms_and_keeps_operators():
    assert fts_query("soil moisture") == '"soil" "moisture"'
    assert fts_query("soil OR pump") == '"soil" OR "pump"'
    assert fts_query('"oven spring" bake*') == '"oven spring" "bake"*'
    assert fts_query("a-b (c)") == '"a-b" "(c)"'
    assert fts_query("one two", any_term=True) == '"one" OR "two"'
    assert fts_query("   ") == '""'


def test_search_builds_index_on_first_use(settings):
    assert not settings.db.exists()
    res = search(settings, "capacitive corrosion")
    assert settings.db.exists()
    paths = [h["path"] for h in res["results"]]
    assert paths[0] in {"REFERENCE/soil-moisture-sensors.md", "REFERENCE/decisions-log.md"}
    assert res["match"] == "all"


def test_title_match_ranks_note_first(settings):
    res = search(settings, "sourdough starter")
    assert res["results"][0]["path"] == "PROJECTS/sourdough.md"


def test_snippet_highlights_terms(settings):
    hit = search(settings, "level shifter")["results"][0]
    assert "**" in hit["snippet"]


def test_note_type_filter(settings):
    res = search(settings, "greenhouse", note_type="episodic", top=10)
    assert res["results"]
    assert all(h["path"].startswith("STATE/journal/") for h in res["results"])


def test_or_fallback(settings):
    res = search(settings, "torque zzzunknownzzz")
    assert res["match"] == "any"
    assert res["results"][0]["path"] == "REFERENCE/workshop-tools.md"


def test_no_results(settings):
    res = search(settings, "qwertyuiop")
    assert res["results"] == []
    assert format_markdown(res) == "(no matches)\n"


def test_transcripts_not_searchable(settings):
    res = search(settings, "excluded from the search index")
    assert all(not h["path"].startswith("STATE/transcripts") for h in res["results"])


def test_missing_index_without_auto_index(settings):
    with pytest.raises(SearchError):
        search(settings, "anything", auto_index=False)


def test_invalid_operator_query_raises(settings):
    with pytest.raises(SearchError):
        search(settings, "NOT")
