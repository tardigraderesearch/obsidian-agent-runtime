# Mistakes

Append-only. What went wrong, and the rule that prevents a repeat.

## 2026-03-02: claimed the pump test passed without checking

Said the relay test was done before reading the log; the relay had never switched.
Rule: verify before claiming done. Read the output, then report.

## 2026-03-06: filed sourdough notes under REFERENCE

The starter feeding ratio is specific to one project, so it belongs in
[[PROJECTS/sourdough]], not `REFERENCE/`. Moved it and left a pointer.
