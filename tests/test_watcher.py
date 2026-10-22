import datetime as dt
import importlib.util
import json
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "idle_watcher", Path(__file__).resolve().parents[1] / "watcher" / "idle_watcher.py"
)
watcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(watcher)

SID = "11111111-2222-3333-4444-555555555555"
T0 = dt.datetime(2026, 3, 9, 12, 0, tzinfo=dt.timezone.utc)


def iso(minutes):
    return (T0 + dt.timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def write_session(claude_dir: Path, vault: Path, lines: list[dict]):
    (claude_dir / "sessions").mkdir(parents=True)
    (claude_dir / "sessions" / "1.json").write_text(
        json.dumps({"pid": os.getpid(), "sessionId": SID, "cwd": str(vault)})
    )
    proj = claude_dir / "projects" / watcher.project_dir_name(str(vault))
    proj.mkdir(parents=True)
    (proj / f"{SID}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def user(text, minutes, **kw):
    return {"type": "user", "timestamp": iso(minutes), "message": {"content": text}, **kw}


def assistant(blocks, minutes):
    return {"type": "assistant", "timestamp": iso(minutes), "message": {"content": blocks}}


LINES = [
    user("What is probe B's offset?", 0),
    assistant([{"type": "tool_use", "name": "mcp__vault__vault_search", "input": {"query": "probe B"}}], 1),
    {"type": "user", "timestamp": iso(1), "message": {"content": [{"type": "tool_result", "content": "..."}]}},
    assistant([{"type": "text", "text": "About 6% wetter than probe A."}], 2),
    user("<command-name>/cost</command-name>", 3),
    assistant([{"type": "text", "text": "cost output"}], 3),
    {
        "type": "user",
        "timestamp": iso(4),
        "isMeta": True,
        "message": {"content": [{"type": "text", "text": '<channel source="plugin:chat">\nthanks!\n</channel>'}]},
    },
    assistant(
        [
            {"type": "text", "text": "internal note"},
            {"type": "tool_use", "name": "mcp__plugin_chat__reply", "input": {"text": "You're welcome."}},
        ],
        5,
    ),
]


@pytest.fixture
def env(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    claude_dir = tmp_path / "claude"
    write_session(claude_dir, vault, LINES)
    return vault, claude_dir, tmp_path / "state.json"


def args(env, *extra):
    vault, claude_dir, state = env
    return ["--vault", str(vault), "--claude-dir", str(claude_dir), "--state-file", str(state), *extra]


def test_conversation_parsing(env):
    vault, claude_dir, _ = env
    path = claude_dir / "projects" / watcher.project_dir_name(str(vault)) / f"{SID}.jsonl"
    msgs, source = watcher.conversation(path)
    assert [(r, t) for r, t, _ in msgs] == [
        ("USER", "What is probe B's offset?"),
        ("ASSISTANT", "About 6% wetter than probe A."),
        ("USER", "thanks!"),
        ("ASSISTANT", "You're welcome."),
    ]
    assert source == "plugin:chat"


def test_not_idle_yet_does_nothing(env):
    vault = env[0]
    assert watcher.main(args(env, "--idle-min", "180"), now=T0 + dt.timedelta(minutes=30)) == 0
    assert not (vault / "STATE/transcripts").exists()


def test_parks_after_idle_and_calls_on_park(env, tmp_path):
    vault = env[0]
    marker = tmp_path / "on_park_received.txt"
    hook = f"sh -c 'echo \"$0\" > {marker}'"
    rc = watcher.main(args(env, "--idle-min", "60", "--on-park", hook), now=T0 + dt.timedelta(minutes=120))
    assert rc == 0
    files = list((vault / "STATE/transcripts").glob("*.md"))
    assert len(files) == 1
    body = files[0].read_text()
    assert body.startswith("# Parked Transcript")
    assert "## USER\n\nthanks!" in body and "internal note" not in body
    assert marker.read_text().strip() == str(files[0])

    # second run: already parked, nothing new
    watcher.main(args(env, "--idle-min", "60"), now=T0 + dt.timedelta(minutes=300))
    assert len(list((vault / "STATE/transcripts").glob("*.md"))) == 1


def test_dry_run_writes_nothing(env, capsys):
    vault = env[0]
    watcher.main(args(env, "--force", "--dry-run"), now=T0)
    assert not (vault / "STATE/transcripts").exists()
    assert "DRY RUN" in capsys.readouterr().out


def test_on_park_is_noop_by_default(tmp_path):
    watcher.on_park(tmp_path / "x.md")  # must not raise or run anything


def test_no_session_for_other_vault(tmp_path, capsys):
    claude_dir = tmp_path / "claude"
    write_session(claude_dir, tmp_path / "other", LINES)
    (tmp_path / "vault").mkdir()
    rc = watcher.main(
        ["--vault", str(tmp_path / "vault"), "--claude-dir", str(claude_dir), "--state-file", str(tmp_path / "s")]
    )
    assert rc == 0 and "no live session" in capsys.readouterr().out
