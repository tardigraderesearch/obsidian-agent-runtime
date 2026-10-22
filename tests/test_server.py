import asyncio
import json

from obsidian_agent_runtime.server import VaultService, build_server


def test_service_search_returns_json(settings):
    svc = VaultService(settings, refresh_seconds=0)
    out = json.loads(svc.vault_search("watering schedule tomato", top=3))
    assert out["results"][0]["path"] == "PROJECTS/greenhouse-controller/watering-schedule.md"
    assert set(out["results"][0]) == {"path", "title", "heading", "snippet", "note_type", "score"}


def test_service_picks_up_new_notes_via_refresh(settings, vault):
    svc = VaultService(settings, refresh_seconds=0)
    svc.vault_search("anything")
    (vault / "REFERENCE/beekeeping.md").write_text("# Beekeeping\nHives need a water source nearby.\n")
    out = json.loads(svc.vault_search("hives water"))
    assert out["results"][0]["path"] == "REFERENCE/beekeeping.md"


def test_service_errors_are_strings(settings):
    svc = VaultService(settings, refresh_seconds=0)
    assert svc.vault_search("NOT").startswith("vault_search FAILED")


def test_service_reindex(settings):
    svc = VaultService(settings)
    assert svc.vault_reindex(full=True).startswith("Indexed: 16 files")


def test_mcp_server_registers_only_vault_tools(settings):
    mcp = build_server(settings)
    tools = asyncio.run(mcp.list_tools())
    assert sorted(t.name for t in tools) == ["vault_reindex", "vault_search"]


def test_mcp_tool_call(settings):
    mcp = build_server(settings)
    result = asyncio.run(mcp.call_tool("vault_search", {"query": "bottom bracket"}))
    # mcp 1.x returns (content, structured) or a content list; mcp 2.x a CallToolResult
    if isinstance(result, tuple):
        result = result[0]
    content = getattr(result, "content", result)
    text = content[0].text
    assert "PROJECTS/bike-rebuild.md" in text
