import json
import subprocess
import tomllib
from pathlib import Path

import pytest
from personal_work_items.configuration import configure
from personal_work_items.context import ContextError
from personal_work_items.fingerprint import require_release, source_digest
from tj_work_items.records import ItemError


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, timeout=15
    )


def setup(project: Path, mode: str = "write") -> dict[str, object]:
    return configure(
        project, "personal-example", "Personal", "example/personal-project", mode
    )


def test_configuration_preview_and_check_do_not_write(project: Path) -> None:
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    result = setup(project, "preview")
    assert not result["ready"]
    assert isinstance(result["changed"], list)
    assert ".mcp.json" in result["changed"]
    assert not (project / ".personal-work-items.json").exists()
    assert not setup(project, "check")["ready"]
    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file() and ".git" not in path.parts
    } == before


def test_configuration_preserves_other_host_settings_and_is_repeatable(
    project: Path,
) -> None:
    (project / ".codex").mkdir()
    (project / ".codex/config.toml").write_text(
        'model = "example"\n[mcp_servers.other]\ncommand = "other"\n', encoding="utf-8"
    )
    (project / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "other"}}, "custom": True}),
        encoding="utf-8",
    )
    (project / ".claude").mkdir()
    (project / ".claude/settings.local.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(git status)"]}}), encoding="utf-8"
    )
    assert setup(project)["ready"]
    assert setup(project, "check") == {"mode": "check", "changed": [], "ready": True}
    codex = tomllib.loads((project / ".codex/config.toml").read_text(encoding="utf-8"))
    claude = json.loads((project / ".mcp.json").read_text(encoding="utf-8"))
    assert codex["model"] == "example"
    assert codex["mcp_servers"]["other"] == {"command": "other"}
    assert claude["mcpServers"]["other"] == {"command": "other"}
    assert claude["custom"]
    personal = codex["mcp_servers"]["personal_work_item"]
    assert personal == claude["mcpServers"]["personal_work_item"]
    assert personal["command"] == "personal-work-item-mcp"
    assert personal["args"][-1] == source_digest()
    assert str(project) not in json.dumps(personal)
    assert "env" not in personal
    approval = json.loads(
        (project / ".claude/settings.local.json").read_text(encoding="utf-8")
    )
    assert approval["permissions"] == {"allow": ["Bash(git status)"]}
    assert approval["enabledMcpjsonServers"] == ["personal_work_item"]
    assert json.loads(
        (project / ".problem-records.json").read_text(encoding="utf-8")
    ) == {"schema_version": 1, "provider": "personal:work-item"}


def test_configuration_from_feature_worktree_targets_primary(project: Path) -> None:
    feature = project.parent / "feature"
    git(project, "worktree", "add", "-b", "feature", str(feature))
    nested = feature / "nested"
    nested.mkdir()
    setup(nested)
    assert (project / ".personal-work-items.json").exists()
    assert not (feature / ".personal-work-items.json").exists()
    for host_root in (project, feature):
        assert (host_root / ".codex/config.toml").exists()
        assert (host_root / ".mcp.json").exists()
        assert (host_root / ".claude/settings.local.json").exists()
    assert setup(nested, "check")["ready"]


@pytest.mark.parametrize(
    "path,value",
    [
        (
            ".problem-records.json",
            {"schema_version": 1, "provider": "work-items:manage"},
        ),
        (".personal-work-items.json", {"schema_version": 1, "organization": "another"}),
        (
            ".mcp.json",
            {
                "mcpServers": {
                    "personal_work_item": {"command": "owned-by-someone-else"}
                }
            },
        ),
    ],
)
def test_configuration_refuses_unverified_replacement(
    project: Path, path: str, value: dict[str, object]
) -> None:
    target = project / path
    original = json.dumps(value)
    target.write_text(original, encoding="utf-8")
    with pytest.raises(ContextError):
        setup(project)
    assert target.read_text(encoding="utf-8") == original
    assert not (project / ".codex/config.toml").exists()


def test_configuration_requires_explicit_personal_profile(project: Path) -> None:
    (project / ".agents/plugins.json").write_text(
        '{"plugins": ["engineering@tj-agents"]}', encoding="utf-8"
    )
    with pytest.raises(ContextError, match="adopt"):
        setup(project)
    assert not (project / ".problem-records.json").exists()


def test_configuration_rejects_linked_parent_before_writes(project: Path) -> None:
    actual = project / "actual-codex"
    actual.mkdir()
    try:
        (project / ".codex").symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ContextError, match="linked"):
        setup(project)
    assert not (project / ".problem-records.json").exists()


def test_release_mismatch_fails_before_any_transport() -> None:
    with pytest.raises(ItemError, match="version"):
        require_release("another-version", None)
    with pytest.raises(ItemError, match="source"):
        require_release(None, "0" * 64)
    require_release(None, source_digest())


def test_configuration_preserves_explicit_mcp_disable(project: Path) -> None:
    settings = project / ".claude/settings.local.json"
    settings.parent.mkdir()
    original = json.dumps({"disabledMcpjsonServers": ["personal_work_item"]})
    settings.write_text(original, encoding="utf-8")
    with pytest.raises(ContextError, match="explicitly disables"):
        setup(project)
    assert settings.read_text(encoding="utf-8") == original
    assert not (project / ".personal-work-items.json").exists()
