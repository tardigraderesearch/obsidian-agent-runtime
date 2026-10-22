#!/usr/bin/env python3
"""Idle watcher: park an idle Claude Code session's transcript into the vault, then /clear it.

Long-lived sessions (for example one kept running in tmux and reached from a phone)
accumulate context forever. This script, run every few minutes by a systemd user
timer or cron, does what a human would do after a long break:

  1. find the live Claude Code session whose working directory is the vault;
  2. if its last conversational message is at least --idle-min minutes old and there
     is conversation not yet exported, write it to STATE/transcripts/ as markdown
     (user turns, and the assistant's visible replies; tool chatter is dropped);
  3. call the ``on_park`` hook point with the transcript path (no-op by default);
  4. send ``/clear`` to the session's tmux pane, so the next conversation starts
     fresh and the SessionStart hook re-injects the working context.

Stdlib only; Linux/macOS. Flags: --dry-run, --force, --idle-min N. See --help.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys

# Messages relayed into Claude Code by a channel plugin arrive wrapped in <channel> tags.
CHANNEL_RE = re.compile(r'<channel source="([^"]+)"[^>]*>\n?(.*?)\n?</channel>', re.S)
COMMAND_PREFIXES = ("<command-", "<local-command", "Base directory for this skill", "Caveat:")


def log(msg: str) -> None:
    print(f"[idle-watcher] {msg}", flush=True)


def project_dir_name(cwd: str) -> str:
    """Claude Code stores transcripts under ~/.claude/projects/<cwd with non-alphanumerics as '-'>."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, TypeError, ValueError):
        return False


def cmdline(pid: int) -> str:
    try:
        return pathlib.Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return ""


def live_session(claude_dir: pathlib.Path, vault: pathlib.Path, match: str = "") -> str | None:
    """Session id of a running Claude Code process whose cwd is the vault (optionally whose
    command line contains ``match``)."""
    for f in sorted((claude_dir / "sessions").glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if d.get("cwd") != str(vault) or not pid_alive(d.get("pid")):
            continue
        if match and match not in cmdline(int(d["pid"])):
            continue
        if d.get("sessionId"):
            return d["sessionId"]
    return None


def ts(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def conversation(path: pathlib.Path) -> tuple[list[tuple[str, str, str]], str]:
    """Return ([(role, text, timestamp)], source) from a Claude Code JSONL transcript.

    Slash-command turns and tool chatter are dropped. For the assistant, replies sent
    through a channel plugin's ``reply`` tool win over plain text (that is what the
    user actually received)."""
    out: list[tuple[str, str, str]] = []
    turn = None
    source = "claude-code"

    def flush() -> None:
        if turn and not turn["cmd"]:
            texts = turn["replies"] or turn["texts"]
            if texts:
                out.append(("ASSISTANT", "\n\n".join(texts).strip(), turn["last"]))

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        t, m = d.get("type"), d.get("message") or {}
        c = m.get("content")
        if t == "user":
            text = c if isinstance(c, str) else None
            if isinstance(c, list) and c and isinstance(c[0], dict) and c[0].get("type") == "text":
                first = c[0].get("text") or ""
                if not d.get("isMeta"):
                    text = first
                elif CHANNEL_RE.search(first):
                    text = first
            if not text:
                continue  # tool results, meta entries
            ch = CHANNEL_RE.search(text)
            if ch:
                source, text = ch.group(1), ch.group(2)
            elif text.lstrip().startswith(COMMAND_PREFIXES):
                flush()
                turn = {"cmd": True, "replies": [], "texts": [], "last": d.get("timestamp")}
                continue
            flush()
            out.append(("USER", text.strip(), d.get("timestamp")))
            turn = {"cmd": False, "replies": [], "texts": [], "last": d.get("timestamp")}
        elif t == "assistant" and turn is not None and isinstance(c, list):
            turn["last"] = d.get("timestamp") or turn["last"]
            for b in c:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and str(b.get("name", "")).endswith("__reply"):
                    turn["replies"].append(str((b.get("input") or {}).get("text", "")))
                elif b.get("type") == "text" and b.get("text", "").strip():
                    turn["texts"].append(b["text"])
    flush()
    return out, source


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50] or "chat"


def render(sid: str, source: str, msgs: list, idle_min: float) -> tuple[str, str]:
    """Return (file name, markdown body) for a parked transcript."""
    first = next((t for r, t, _ in msgs if r == "USER"), "chat")
    start = ts(msgs[0][2]).astimezone()
    name = f"{start.strftime('%Y-%m-%d-%H%M')}-{slug(first[:60])}-{sid[:8]}.md"
    lines = [
        "# Parked Transcript",
        "",
        f"- session_id: `{sid}`",
        f"- source: `{source}`",
        f"- runtime: claude-code (idle-watcher, idle {idle_min:.0f} min)",
        f"- exported_at: {dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        "---",
        "",
    ]
    for role, text, _ in msgs:
        lines += [f"## {role}", "", text, ""]
    return name, "\n".join(lines).rstrip() + "\n"


def on_park(transcript: pathlib.Path, command: str = "") -> None:
    """Hook point, called once per parked transcript. No-op by default.

    Pass ``--on-park "CMD"`` (or set OAR_ON_PARK) to run ``CMD <transcript path>``,
    e.g. a summarizer that distills the transcript into notes, a notifier, or a
    sync job. Failures are logged and never block the /clear step.
    """
    if not command:
        return
    try:
        r = subprocess.run(shlex.split(command) + [str(transcript)], capture_output=True, text=True, timeout=120)
        log(f"on_park rc={r.returncode} {(r.stdout or r.stderr).strip()[-200:]}")
    except Exception as e:  # noqa: BLE001
        log(f"on_park failed: {e}")


def send_clear(target: str, socket: str = "") -> bool:
    base = ["tmux"] + (["-L", socket] if socket else [])
    if subprocess.run(base + ["has-session", "-t", target], capture_output=True).returncode != 0:
        log(f"tmux target {target!r} not found; skipped /clear")
        return False
    subprocess.run(base + ["send-keys", "-t", target, "/clear", "Enter"], check=False)
    log("sent /clear (fresh session; SessionStart hook re-injects working context)")
    return True


def parse_args(argv=None) -> argparse.Namespace:
    home = pathlib.Path.home()
    cache = pathlib.Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", default=os.environ.get("OAR_VAULT"), help="vault root (default: $OAR_VAULT)")
    ap.add_argument("--idle-min", type=float, default=float(os.environ.get("OAR_IDLE_MIN", 180)))
    ap.add_argument("--out-dir", help="where transcripts go (default: <vault>/STATE/transcripts)")
    ap.add_argument("--claude-dir", default=str(home / ".claude"), help="Claude Code config dir")
    ap.add_argument("--state-file", default=str(cache / "obsidian-agent-runtime" / "idle-watcher.json"))
    ap.add_argument("--match", default="", help="only sessions whose command line contains this string")
    ap.add_argument("--tmux-target", default=os.environ.get("OAR_TMUX_TARGET", ""), help="tmux session/pane to /clear")
    ap.add_argument("--tmux-socket", default=os.environ.get("OAR_TMUX_SOCKET", ""), help="tmux -L socket name")
    ap.add_argument("--on-park", default=os.environ.get("OAR_ON_PARK", ""), help="command run with the transcript path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="park now regardless of idle time")
    a = ap.parse_args(argv)
    if not a.vault:
        ap.error("--vault (or $OAR_VAULT) is required")
    return a


def main(argv=None, now: dt.datetime | None = None) -> int:
    a = parse_args(argv)
    vault = pathlib.Path(a.vault).expanduser().resolve()
    claude_dir = pathlib.Path(a.claude_dir).expanduser()
    out_dir = pathlib.Path(a.out_dir).expanduser() if a.out_dir else vault / "STATE" / "transcripts"
    state_file = pathlib.Path(a.state_file).expanduser()

    sid = live_session(claude_dir, vault, a.match)
    if not sid:
        log("no live session for this vault")
        return 0
    path = claude_dir / "projects" / project_dir_name(str(vault)) / f"{sid}.jsonl"
    if not path.exists():
        log(f"no transcript for {sid}")
        return 0
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    done_upto = state.get(sid)
    msgs, source = conversation(path)
    new = [m for m in msgs if m[2] and (not done_upto or ts(m[2]) > ts(done_upto))]
    if len([m for m in new if m[1]]) < 2:
        log(f"{sid[:8]}: nothing new to park ({len(new)} msgs)")
        return 0
    now = now or dt.datetime.now(dt.timezone.utc)
    idle = (now - ts(new[-1][2])).total_seconds() / 60
    if idle < a.idle_min and not a.force:
        log(f"{sid[:8]}: {len(new)} new msgs, idle {idle:.0f}/{a.idle_min:.0f} min")
        return 0
    name, body = render(sid, source, new, idle)
    out = out_dir / name
    if a.dry_run:
        log(f"DRY RUN would write {out} ({len(new)} msgs, idle {idle:.0f} min)")
        print(body[:1500])
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(out)
    state[sid] = new[-1][2]
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=1))
    log(f"parked {len(new)} msgs -> {out}")
    on_park(out, a.on_park)
    if a.tmux_target:
        send_clear(a.tmux_target, a.tmux_socket)
    return 0


if __name__ == "__main__":
    sys.exit(main())
