#!/usr/bin/env bash
# Start (or attach to) a long-lived Claude Code session on the vault inside tmux,
# so the idle watcher can find it and /clear it.
#   usage: start-session.sh /path/to/vault [tmux-session-name] [extra claude args...]
set -euo pipefail
VAULT="${1:?usage: start-session.sh /path/to/vault [session-name] [claude args...]}"
NAME="${2:-assistant}"
shift $(( $# >= 2 ? 2 : 1 ))
if ! tmux has-session -t "$NAME" 2>/dev/null; then
  tmux new-session -d -s "$NAME" -c "$VAULT" claude "$@"
fi
exec tmux attach -t "$NAME"
