from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import urlparse


class ContextError(ValueError):
    pass


class Config(TypedDict):
    schema_version: int
    organization: str
    project: str
    repository: str
    kinds: dict[str, str]


class Context(TypedDict):
    primary_root: Path
    config: Config


_ORGANIZATION = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_REPOSITORY = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})/[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$"
)
_SCP_GITHUB = re.compile(
    r"git@github\.com:([A-Za-z0-9][A-Za-z0-9_.-]{0,38}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99})(?:\.git)?$"
)
_KINDS = {
    "feature": "Feature",
    "task": "Task",
    "bug": "Bug",
    "mistake": "Mistake",
    "debt": "Debt",
}


def _git(root: Path, *arguments: str, optional: bool = False) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ContextError("Git is required to resolve the personal project") from error
    if result.returncode and not optional:
        raise ContextError("the selected directory must be inside a Git worktree")
    return result.stdout.strip()


def _is_employer_root(root: Path) -> bool:
    parts = [part.casefold() for part in root.absolute().parts]
    return any(
        parts[index : index + 3] == ["source", "repos", "infonetica"]
        for index in range(len(parts) - 2)
    )


def _primary_root(root: Path) -> Path:
    if root.is_symlink():
        raise ContextError("refusing a linked project path")
    current = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    if _is_employer_root(current):
        raise ContextError(
            "employer worktrees cannot use the personal work-item provider"
        )
    common_directory = Path(
        _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    ).resolve()
    for record in _git(root, "worktree", "list", "--porcelain").split("\n\n"):
        for line in record.splitlines():
            if line.startswith("worktree "):
                primary = Path(line.removeprefix("worktree "))
                git_directory = Path(
                    _git(primary, "rev-parse", "--path-format=absolute", "--git-dir")
                ).resolve()
                if git_directory != common_directory:
                    continue
                if primary.is_symlink():
                    raise ContextError("refusing a linked primary worktree")
                if _is_employer_root(primary):
                    raise ContextError(
                        "employer worktrees cannot use the personal work-item provider"
                    )
                return primary
    raise ContextError("Git did not report a primary worktree")


def _read_object(path: Path, name: str) -> dict[str, object]:
    if path.is_symlink():
        raise ContextError(f"refusing linked {name} declaration")
    if not path.is_file():
        raise ContextError(f"missing {name} declaration")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContextError(f"invalid {name} declaration") from error
    if not isinstance(value, dict):
        raise ContextError(f"invalid {name} declaration")
    return value


def _canonical_repository(origin: str) -> str:
    value = origin.strip()
    scp = _SCP_GITHUB.fullmatch(value)
    if scp:
        canonical = scp.group(1).removesuffix(".git")
    else:
        try:
            parsed = urlparse(value)
            port = parsed.port
        except ValueError as error:
            raise ContextError("origin must use a canonical GitHub URL") from error
        if parsed.scheme == "https":
            valid = (
                not parsed.username
                and not parsed.password
                and parsed.hostname is not None
                and parsed.hostname.casefold() == "github.com"
                and port is None
                and not parsed.query
                and not parsed.fragment
            )
        elif parsed.scheme == "ssh":
            valid = (
                parsed.username == "git"
                and not parsed.password
                and parsed.hostname is not None
                and parsed.hostname.casefold() == "github.com"
                and port is None
                and not parsed.query
                and not parsed.fragment
            )
        else:
            valid = False
        if not valid:
            raise ContextError("origin must use a canonical GitHub URL")
        canonical = parsed.path.removeprefix("/").removesuffix(".git")
    if not _REPOSITORY.fullmatch(canonical):
        raise ContextError("origin must name a canonical GitHub owner/repository")
    if canonical.partition("/")[0].casefold() == "infonetica":
        raise ContextError(
            "employer GitHub origins cannot use the personal work-item provider"
        )
    return canonical.casefold()


def _is_schema_version(value: object) -> bool:
    return type(value) is int and value == 1


def _validate_config(config: dict[str, object]) -> Config:
    expected = {"schema_version", "organization", "project", "repository", "kinds"}
    if set(config) != expected or not _is_schema_version(config.get("schema_version")):
        raise ContextError(
            "personal work-item declaration has unknown or missing fields"
        )
    organization = config["organization"]
    project = config["project"]
    repository = config["repository"]
    kinds = config["kinds"]
    if not isinstance(organization, str) or not _ORGANIZATION.fullmatch(organization):
        raise ContextError("organization must be a lowercase Azure DevOps slug")
    if organization == "infonetica":
        raise ContextError(
            "employer Azure DevOps organizations cannot use the personal "
            "work-item provider"
        )
    if (
        not isinstance(project, str)
        or not project.strip()
        or project != project.strip()
        or any(ord(character) < 32 for character in project)
    ):
        raise ContextError("project must be a nonempty Azure DevOps project name")
    if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
        raise ContextError("repository must be a canonical GitHub owner/repository")
    if kinds != _KINDS:
        raise ContextError(
            "kinds must declare the supported personal Azure work-item types"
        )
    return cast(Config, config)


def _validate_selection(primary_root: Path) -> None:
    selection = _read_object(primary_root / ".problem-records.json", "problem-records")
    if (
        set(selection) != {"schema_version", "provider"}
        or not _is_schema_version(selection.get("schema_version"))
        or selection.get("provider") != "personal:work-item"
    ):
        raise ContextError(
            "problem-records must be exactly schema version 1 with provider "
            "personal:work-item"
        )


def load_context(root: Path) -> Context:
    primary_root = _primary_root(Path(root))
    config = _validate_config(
        _read_object(primary_root / ".personal-work-items.json", "personal work-item")
    )
    _validate_selection(primary_root)
    origin = _git(primary_root, "config", "--get", "remote.origin.url", optional=True)
    if not origin:
        raise ContextError("the primary worktree must define an origin remote")
    if _canonical_repository(origin) != str(config["repository"]).casefold():
        raise ContextError("origin does not match the declared personal repository")
    return Context(primary_root=primary_root, config=config)
