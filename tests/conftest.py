import shutil
from pathlib import Path

import pytest

from obsidian_agent_runtime.config import load_settings

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "demo-vault"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    dest = tmp_path / "vault"
    shutil.copytree(DEMO, dest)
    return dest


@pytest.fixture
def settings(vault: Path, tmp_path: Path):
    return load_settings(vault, tmp_path / "index.db")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    for var in ("OAR_VAULT", "OAR_DB", "OAR_EXCLUDE", "OBSIDIAN_VAULT_PATH", "CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
