"""Path resolution for the vault and its search index.

Precedence (first match wins):

vault: explicit argument > ``OAR_VAULT`` > ``OBSIDIAN_VAULT_PATH`` > current directory
db:    explicit argument > ``OAR_DB`` > ``$XDG_CACHE_HOME/obsidian-agent-runtime/<vault-name>-<hash>.db``

The index lives outside the vault on purpose: a SQLite file inside a synced or
git-tracked vault gets corrupted by sync tools and bloats history.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

# Directory names skipped anywhere in the tree.
DEFAULT_SKIP_DIRS = frozenset({".obsidian", ".trash", ".git", ".claude", "node_modules", "credentials"})
# Vault-relative path prefixes skipped (raw session dumps are staging data, not memory).
DEFAULT_EXCLUDES = ("STATE/transcripts",)


def _split_env_list(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(p.strip().strip("/") for p in re.split(r"[,:]", value) if p.strip())


def resolve_vault(vault: str | os.PathLike | None = None) -> Path:
    raw = vault or os.environ.get("OAR_VAULT") or os.environ.get("OBSIDIAN_VAULT_PATH") or os.getcwd()
    return Path(raw).expanduser().resolve()


def default_db_for(vault: Path) -> Path:
    cache = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    digest = hashlib.sha1(str(vault).encode("utf-8")).hexdigest()[:10]
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", vault.name).strip("-") or "vault"
    return cache / "obsidian-agent-runtime" / f"{name}-{digest}.db"


def resolve_db(vault: Path, db: str | os.PathLike | None = None) -> Path:
    raw = db or os.environ.get("OAR_DB")
    return Path(raw).expanduser().resolve() if raw else default_db_for(vault)


@dataclass(frozen=True)
class Settings:
    vault: Path
    db: Path
    skip_dirs: frozenset[str] = DEFAULT_SKIP_DIRS
    excludes: tuple[str, ...] = DEFAULT_EXCLUDES


def load_settings(
    vault: str | os.PathLike | None = None,
    db: str | os.PathLike | None = None,
    excludes: tuple[str, ...] | list[str] | None = None,
) -> Settings:
    v = resolve_vault(vault)
    ex = tuple(excludes) if excludes is not None else (DEFAULT_EXCLUDES + _split_env_list(os.environ.get("OAR_EXCLUDE")))
    return Settings(vault=v, db=resolve_db(v, db), excludes=tuple(e.strip("/") for e in ex if e))
