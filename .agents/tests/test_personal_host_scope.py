import json
from pathlib import Path
from typing import Any

import pytest
from personal_work_items.host_scope import isolate


def test_host_isolation_changes_only_selected_personal_project(
    project: Path, tmp_path: Path
) -> None:
    profile = tmp_path / ".claude.json"
    work = "C:/work/infonetica/ERM"
    original: dict[str, Any] = {
        "mcpServers": {
            "azure-devops": {"command": "node", "args": ["Infonetica"]},
            "azure": {"command": "azure"},
            "other": {"command": "other"},
        },
        "projects": {
            work: {
                "mcpServers": {"azure-devops": {"command": "unchanged-work"}},
                "disabledMcpServers": ["other"],
            }
        },
        "otherSetting": True,
    }
    profile.write_text(json.dumps(original), encoding="utf-8")
    assert not isolate(project, "example/personal-project", profile, "preview")["ready"]
    assert json.loads(profile.read_text(encoding="utf-8")) == original
    assert isolate(project, "example/personal-project", profile, "write")["ready"]
    changed = json.loads(profile.read_text(encoding="utf-8"))
    assert changed["mcpServers"] == original["mcpServers"]
    assert changed["projects"][work] == original["projects"][work]
    assert changed["otherSetting"] is True
    assert changed["projects"][project.as_posix()]["disabledMcpServers"] == [
        "azure-devops",
        "azure",
    ]
    assert isolate(project, "example/personal-project", profile, "check")["ready"]


def test_host_isolation_refuses_unrelated_repository_before_reading_profile(
    project: Path, tmp_path: Path
) -> None:
    profile = tmp_path / ".claude.json"
    profile.write_text("invalid JSON deliberately never read", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        isolate(project, "another/repository", profile, "write")
    assert profile.read_text(encoding="utf-8") == "invalid JSON deliberately never read"


def test_host_isolation_preserves_existing_project_controls(
    project: Path, tmp_path: Path
) -> None:
    profile = tmp_path / ".claude.json"
    profile.write_text(
        json.dumps(
            {
                "projects": {
                    project.as_posix(): {
                        "disabledMcpServers": ["other", "azure-devops"],
                        "custom": {"keep": True},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    isolate(project, "example/personal-project", profile, "write")
    selected = json.loads(profile.read_text(encoding="utf-8"))["projects"][
        project.as_posix()
    ]
    assert selected["custom"] == {"keep": True}
    assert selected["disabledMcpServers"] == ["other", "azure-devops", "azure"]


def test_host_isolation_rejects_employer_worktree_before_profile_read(
    project: Path, tmp_path: Path
) -> None:
    import subprocess

    from personal_work_items.context import ContextError

    current = tmp_path / "source/repos/infonetica/personal-worktree"
    current.parent.mkdir(parents=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(project),
            "worktree",
            "add",
            "-b",
            "employer-location",
            str(current),
        ],
        check=True,
        capture_output=True,
        timeout=15,
    )
    profile = tmp_path / ".claude.json"
    profile.write_text("deliberately invalid unread profile", encoding="utf-8")
    with pytest.raises(ContextError, match="employer"):
        isolate(current, "example/personal-project", profile, "write")
    assert profile.read_text(encoding="utf-8") == "deliberately invalid unread profile"
