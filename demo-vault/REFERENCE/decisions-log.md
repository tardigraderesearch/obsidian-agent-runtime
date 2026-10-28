# Decisions Log

Append-only. Decision, date, reason.

## 2026-02-20: capacitive soil probes

Chose capacitive over resistive probes for [[PROJECTS/greenhouse-controller]].
Reason: resistive probes corrode within weeks in wet soil. Suggested by [[PEOPLE/elisabeth]].

## 2026-03-02: level shifter on the relay line

The relay board needs 5 V logic; the controller outputs 3.3 V. A level shifter is
cheaper and safer than swapping the board.

## 2026-03-06: search index lives outside the vault

The full-text index is a SQLite file in the user cache directory, not in the vault,
so file sync and git never touch a binary database.
