import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .context import ContextError, _canonical_repository, _git, _primary_root

_SERVERS = ("azure-devops", "azure")


def _normal(path: str) -> str:
    value = path.replace("\\", "/").rstrip("/")
    return value.casefold() if os.name == "nt" else value


def isolate(root: Path, repository: str, profile: Path, mode: str) -> dict[str, Any]:
    if mode not in ("preview", "write", "check"):
        raise ContextError("unsupported host isolation mode")
    primary = _primary_root(root)
    if (
        _canonical_repository(_git(primary, "config", "--get", "remote.origin.url"))
        != repository.casefold()
    ):
        raise ContextError("explicit personal repository does not match its Git origin")
    current = Path(_git(root, "rev-parse", "--show-toplevel"))
    if profile.is_symlink():
        raise ContextError("refusing a linked Claude user configuration")
    original = profile.read_bytes() if profile.is_file() else None
    document = {} if original is None else json.loads(original)
    if not isinstance(document, dict):
        raise ContextError("Claude user configuration must be an object")
    proposed = copy.deepcopy(document)
    projects = proposed.setdefault("projects", {})
    if not isinstance(projects, dict):
        raise ContextError("Claude project configuration must be an object")
    scopes = {primary.as_posix(), current.as_posix()}
    normalized = {_normal(scope) for scope in scopes}
    scopes.update(key for key in projects if _normal(key) in normalized)
    changed = []
    for scope in sorted(scopes):
        project = projects.setdefault(scope, {})
        if not isinstance(project, dict):
            raise ContextError("Claude project settings must be an object")
        disabled = project.setdefault("disabledMcpServers", [])
        if not isinstance(disabled, list) or not all(
            isinstance(name, str) for name in disabled
        ):
            raise ContextError("Claude disabled MCP server settings must be a list")
        before = list(disabled)
        disabled.extend(name for name in _SERVERS if name not in disabled)
        if before != disabled:
            changed.append(scope)
    if proposed.get("mcpServers") != document.get("mcpServers"):
        raise ContextError("host isolation cannot change global MCP definitions")
    if changed and mode == "write":
        backup = profile.parent / ".claude/backups/personal-project-isolation"
        backup.mkdir(mode=0o700, parents=True, exist_ok=True)
        backup.chmod(0o700)
        if original is not None:
            receipt = backup / (hashlib.sha256(original).hexdigest() + ".json")
            if not receipt.exists():
                with receipt.open("xb") as handle:
                    receipt.chmod(0o600)
                    handle.write(original)
        profile.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=profile.parent,
                delete=False,
            ) as handle:
                json.dump(proposed, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            if (profile.read_bytes() if profile.exists() else None) != original:
                raise ContextError(
                    "Claude configuration changed during setup; retry after its "
                    "writer finishes"
                )
            temporary.replace(profile)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {
        "mode": mode,
        "project_scopes": changed,
        "disabled_servers": list(_SERVERS),
        "ready": not changed or mode == "write",
    }
