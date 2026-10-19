from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from personal_work_items import context, credentials, mcp_server

CONFIG: dict[str, object] = {
    "schema_version": 1,
    "organization": "tj-agents",
    "project": "Personal work items",
    "repository": "tommyboy4050/example",
    "kinds": {
        "feature": "Feature",
        "task": "Task",
        "bug": "Bug",
        "mistake": "Mistake",
        "debt": "Debt",
    },
}
SELECTION: dict[str, object] = {"schema_version": 1, "provider": "personal:work-item"}
REAL_RUN = subprocess.run


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return REAL_RUN(
        ["git", "-C", str(root), *arguments], check=True, capture_output=True, text=True
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    write_declarations(root)
    (root / "tracked").write_text("tracked\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    git(root, "remote", "add", "origin", "git@github.com:tommyboy4050/example.git")
    return root


def write_declarations(
    root: Path,
    config: dict[str, object] = CONFIG,
    selection: dict[str, object] = SELECTION,
) -> None:
    (root / ".personal-work-items.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    (root / ".problem-records.json").write_text(json.dumps(selection), encoding="utf-8")


@pytest.fixture
def block_runtime_processes(
    monkeypatch: pytest.MonkeyPatch, project: Path
) -> Callable[..., subprocess.CompletedProcess[str]]:
    fixture_parent = project.parent.resolve()

    def guarded(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if not args or not isinstance(args[0], list):
            raise AssertionError("runtime subprocess requires a command list")
        arguments: list[str] = args[0]
        if (
            arguments
            and arguments[0] == "git"
            and len(arguments) > 2
            and arguments[1] == "-C"
        ):
            try:
                if Path(arguments[2]).resolve().is_relative_to(fixture_parent):
                    return REAL_RUN(arguments, *args[1:], **kwargs)
            except OSError:
                pass
        raise AssertionError(
            f"runtime subprocess blocked: {arguments[0] if arguments else '<empty>'}"
        )

    monkeypatch.setattr(subprocess, "run", guarded)
    return guarded


def assert_rejected_before_credentials(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_runtime_processes: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    get_pat = Mock(side_effect=AssertionError("credential lookup must not run"))
    monkeypatch.setattr(credentials, "get_pat", get_pat)
    with pytest.raises(context.ContextError):
        mcp_server.run(project)
    get_pat.assert_not_called()


def test_feature_path_uses_primary_declarations(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_runtime_processes: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    feature = project.parent / "feature"
    git(project, "worktree", "add", "-b", "feature", str(feature))
    write_declarations(feature, {**CONFIG, "repository": "tommyboy4050/other"})
    loaded = context.load_context(feature)
    assert loaded["primary_root"].resolve() == project.resolve()
    assert loaded["config"] == CONFIG


@pytest.mark.parametrize(
    "config",
    [
        {**CONFIG, "schema_version": True},
        {**CONFIG, "organization": "TJ-Agents"},
        {**CONFIG, "organization": "infonetica"},
        {**CONFIG, "project": " "},
        {**CONFIG, "project": "bad\nproject"},
        {**CONFIG, "unexpected": True},
    ],
)
def test_malformed_config_is_rejected_before_credentials(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_runtime_processes: Callable[..., subprocess.CompletedProcess[str]],
    config: dict[str, object],
) -> None:
    write_declarations(project, config)
    assert_rejected_before_credentials(project, monkeypatch, block_runtime_processes)


@pytest.mark.parametrize(
    "selection",
    [
        {"schema_version": True, "provider": "personal:work-item"},
        {"schema_version": 1, "provider": "github:issue"},
        {"schema_version": 1, "provider": "personal:work-item", "extra": True},
        {"schema_version": 1, "providers": {"primary": "personal:work-item"}},
    ],
)
def test_invalid_provider_is_rejected_before_credentials(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_runtime_processes: Callable[..., subprocess.CompletedProcess[str]],
    selection: dict[str, object],
) -> None:
    write_declarations(project, selection=selection)
    assert_rejected_before_credentials(project, monkeypatch, block_runtime_processes)


@pytest.mark.parametrize(
    "origin",
    [
        "git@github.com:Infonetica/personal.git",
        "https://infonetica@github.com/tommyboy4050/example.git",
        "https://github.com:443/tommyboy4050/example.git",
        "https://github.com/tommyboy4050/example.git?spoofed=true",
        "ssh://someone@github.com/tommyboy4050/example.git",
        "https://dev.azure.com/infonetica/ERM/_git/project",
    ],
)
def test_spoofed_or_employer_origins_are_rejected_before_credentials(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_runtime_processes: Callable[..., subprocess.CompletedProcess[str]],
    origin: str,
) -> None:
    git(project, "remote", "set-url", "origin", origin)
    assert_rejected_before_credentials(project, monkeypatch, block_runtime_processes)


def test_origin_mismatch_is_rejected_before_credentials(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_runtime_processes: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    git(
        project,
        "remote",
        "set-url",
        "origin",
        "git@github.com:tommyboy4050/different.git",
    )
    get_pat = Mock(side_effect=AssertionError("credential lookup must not run"))
    monkeypatch.setattr(credentials, "get_pat", get_pat)
    with pytest.raises(context.ContextError, match="does not match"):
        mcp_server.run(project)
    get_pat.assert_not_called()


def test_employer_root_detection_is_path_specific() -> None:
    assert context._is_employer_root(
        Path("C:/Users/Tommy/source/repos/infonetica/project")
    )
    assert not context._is_employer_root(
        Path("C:/Users/Tommy/source/repos/personal/infonetica-notes")
    )


def test_linked_declaration_is_rejected_before_credentials(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_runtime_processes: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    declaration = project / ".personal-work-items.json"
    target = project / "declaration.json"
    declaration.replace(target)
    try:
        declaration.symlink_to(target.name)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    assert_rejected_before_credentials(project, monkeypatch, block_runtime_processes)


def test_missing_cached_package_fails_before_credentials(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_runtime_processes: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    get_pat = Mock(side_effect=AssertionError("credential lookup must not run"))
    monkeypatch.setattr(credentials, "get_pat", get_pat)
    node = project / "node.exe"
    node.write_text("", encoding="utf-8")
    with pytest.raises(context.ContextError, match="not installed"):
        mcp_server.run(project, executable=node)
    get_pat.assert_not_called()


def test_run_uses_fixed_personal_auth_without_parent_environment_mutation(
    project: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_runtime_processes: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    completed: subprocess.CompletedProcess[str] = subprocess.CompletedProcess("node", 0)
    launched: dict[str, object] = {}

    def launch(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        launched["arguments"] = arguments
        launched["environment"] = kwargs["env"]
        return completed

    original = {
        "AZURE_DEVOPS_EXT_PAT": "work-secret",
        "SYSTEM_ACCESSTOKEN": "work-token",
        "ADO_MCP_AUTH_TOKEN": "ado-token",
    }
    monkeypatch.setattr(
        mcp_server,
        "load_context",
        lambda _: {"primary_root": project, "config": CONFIG},
    )
    monkeypatch.setattr(mcp_server, "command", lambda *_: ["node", "cached-entry"])
    monkeypatch.setattr(credentials, "get_pat", lambda _: "secret-value")
    monkeypatch.setattr(subprocess, "run", launch)
    monkeypatch.setattr(os, "environ", original.copy())
    assert mcp_server.run(project) == 0
    environment = launched["environment"]
    assert isinstance(environment, dict)
    assert environment["PERSONAL_ACCESS_TOKEN"] == "cGVyc29uYWw6c2VjcmV0LXZhbHVl"
    assert "AZURE_DEVOPS_EXT_PAT" not in environment
    assert "SYSTEM_ACCESSTOKEN" not in environment
    assert "ADO_MCP_AUTH_TOKEN" not in environment
    assert os.environ == original
    assert "secret-value" not in str(launched["arguments"])
    assert "secret-value" not in str(environment)


def test_credential_backends_are_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    windows_get = Mock(return_value="windows-token")
    monkeypatch.setattr(credentials, "_windows_get", windows_get)
    assert credentials.get_pat("tj-agents") == "windows-token"
    windows_get.assert_called_once_with("tj-agents:personal-ado:tj-agents")
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.setattr(
        credentials,
        "_secret_tool",
        lambda *_: subprocess.CompletedProcess([], 1, "", ""),
    )
    with pytest.raises(credentials.CredentialError, match="no personal Azure token"):
        credentials.get_pat("tj-agents")


def test_package_entry_launches_node_directly_with_pinned_package(
    project: Path,
) -> None:
    runtime = project / "runtime"
    runtime.mkdir()
    node = runtime / "node.exe"
    node.write_text("", encoding="utf-8")
    package = runtime / "node_modules/@azure-devops/mcp"
    entry = package / "dist/index.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("", encoding="utf-8")
    (package / "package.json").write_text(
        json.dumps(
            {
                "name": "@azure-devops/mcp",
                "version": "2.10.0",
                "bin": {"mcp-server-azuredevops": "dist/index.js"},
            }
        ),
        encoding="utf-8",
    )
    assert mcp_server.command("tj-agents", node, system="nt") == [
        str(node),
        str(entry),
        "tj-agents",
        "--authentication",
        "pat",
        "--domains",
        "core",
        "work-items",
    ]
