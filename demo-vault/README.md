# Demo Vault

A small, fictional vault used to try obsidian-agent-runtime. Everything here is made up.
Jordan is the (fictional) human; "the assistant" is whichever model is reading this.

## Vault Map

| Folder | Purpose |
|---|---|
| `STATE/` | What the assistant is doing now: working context, journal, mistakes. High churn. `STATE/transcripts/` holds raw parked sessions and is not indexed. |
| `PEOPLE/` | Durable facts about people. |
| `PROJECTS/` | One hub note per named project, plus a same-named folder for sub-notes. |
| `REFERENCE/` | Durable knowledge not tied to one project: specs, decisions, how-tos. |
| `SKILLS/` | Procedures the assistant can follow, one `SKILL.md` per folder. |

## Filing Rule

When saving something new, ask in order. The first "yes" wins:

1. Operational state the assistant updates during work? -> `STATE/`
2. About a person? -> `PEOPLE/`
3. Specific to one named project? -> `PROJECTS/<project>.md` or `PROJECTS/<project>/<topic>.md`
4. Durable reference not tied to a project? -> `REFERENCE/`
5. A repeatable procedure? -> `SKILLS/<name>/SKILL.md`

If two answers feel right, the project name is probably wrong.

## Conventions

- File names are `lowercase-kebab-case.md`.
- Link related notes with `[[wikilinks]]` using full paths, e.g. [[PROJECTS/greenhouse-controller]].
- Facts are timeless, dated ("as of 2026-03-09"), or a pointer to where the live truth is.
- Corrections keep history: mark the old line superseded with a date; never silently delete.
- The journal is append-only. `STATE/working-context.md` stays under ~30 lines.
