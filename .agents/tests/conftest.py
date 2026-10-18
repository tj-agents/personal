import json
import subprocess
from pathlib import Path

import pytest


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, timeout=15
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(
        root,
        "remote",
        "add",
        "origin",
        "https://github.com/example/personal-project.git",
    )
    (root / ".agents").mkdir()
    (root / ".agents/plugins.json").write_text(
        json.dumps({"plugins": ["personal@tj-agents"]}), encoding="utf-8"
    )
    (root / "tracked").write_text("tracked", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    return root
