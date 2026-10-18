import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from . import __version__
from .context import (
    ContextError,
    _canonical_repository,
    _git,
    _primary_root,
    _validate_config,
)
from .fingerprint import source_digest

_BEGIN = "# BEGIN personal-work-item MCP"
_END = "# END personal-work-item MCP"
_BLOCK = re.compile(
    r"(?ms)^# BEGIN personal-work-item MCP\n.*?^# END personal-work-item MCP\n?"
)


def _text(path: Path, root: Path) -> str | None:
    current = path
    while current != root:
        if current.is_symlink():
            raise ContextError("refusing a linked personal configuration path")
        current = current.parent
    if not path.exists():
        return None
    if not path.is_file():
        raise ContextError("personal configuration target must be a regular file")
    return path.read_text(encoding="utf-8")


def _object(text: str | None) -> dict[str, Any]:
    value = {} if text is None else json.loads(text)
    if not isinstance(value, dict):
        raise ContextError("personal configuration must be a JSON object")
    return value


def _json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _owned_server(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"command", "args"}:
        return False
    args = value.get("args")
    return (
        value.get("command") == "personal-work-item-mcp"
        and isinstance(args, list)
        and len(args) == 6
        and args[:3] == ["--root", ".", "--require-version"]
        and args[4] == "--require-source"
        and isinstance(args[3], str)
        and isinstance(args[5], str)
    )


def _codex(text: str | None, server: dict[str, Any]) -> str:
    original = text or ""
    document = tomllib.loads(original)
    entry = document.get("mcp_servers", {}).get("personal_work_item")
    blocks = list(_BLOCK.finditer(original))
    if (
        len(blocks) > 1
        or original.count(_BEGIN) != len(blocks)
        or original.count(_END) != len(blocks)
    ):
        raise ContextError("personal MCP block markers are invalid")
    if entry is not None and (not blocks or not _owned_server(entry)):
        raise ContextError("Codex personal MCP entry has another owner")
    remaining = _BLOCK.sub("", original).rstrip()
    block = (
        f"{_BEGIN}\n[mcp_servers.personal_work_item]\n"
        f"command = {json.dumps(server['command'])}\n"
        f"args = {json.dumps(server['args'])}\n{_END}\n"
    )
    result = (remaining + "\n\n" if remaining else "") + block
    tomllib.loads(result)
    return result


def _write_batch(changed: dict[Path, str], originals: dict[Path, str | None]) -> None:
    staged: dict[Path, Path] = {}
    written: list[Path] = []
    try:
        for path, value in changed.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
            ) as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
                staged[path] = Path(handle.name)
        for path, temporary in staged.items():
            if (
                path.read_text(encoding="utf-8") if path.exists() else None
            ) != originals[path]:
                raise ContextError(
                    "configuration changed during setup; retry after its writer "
                    "finishes"
                )
            temporary.replace(path)
            written.append(path)
    except (OSError, ValueError):
        for path in reversed(written):
            original = originals[path]
            if path.read_text(encoding="utf-8") != changed[path]:
                continue
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(original, encoding="utf-8", newline="\n")
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def configure(
    root: Path, organization: str, project: str, repository: str, mode: str
) -> dict[str, Any]:
    if mode not in ("preview", "write", "check"):
        raise ContextError("unsupported configuration mode")
    primary = _primary_root(root)
    config = _validate_config(
        {
            "schema_version": 1,
            "organization": organization,
            "project": project,
            "repository": repository,
            "kinds": {
                "feature": "Feature",
                "task": "Task",
                "bug": "Bug",
                "mistake": "Mistake",
                "debt": "Debt",
            },
        }
    )
    if (
        _canonical_repository(_git(primary, "config", "--get", "remote.origin.url"))
        != repository.lower()
    ):
        raise ContextError("origin does not match the requested personal repository")
    selection = _object(_text(primary / ".agents/plugins.json", primary))
    selected_plugins = selection.get("plugins")
    if (
        not isinstance(selected_plugins, list)
        or "personal@tj-agents" not in selected_plugins
    ):
        raise ContextError(
            "explicitly adopt the personal profile before selecting its "
            "work-item provider"
        )
    declared = {"schema_version": 1, "provider": "personal:work-item"}
    targets = {
        primary / ".personal-work-items.json": _json(config),
        primary / ".problem-records.json": _json(declared),
    }
    for path, value in targets.items():
        existing = _text(path, primary)
        if existing is not None and _object(existing) != _object(value):
            raise ContextError(
                "existing provider configuration differs; perform a verified "
                "migration before replacing it"
            )
    server = {
        "command": "personal-work-item-mcp",
        "args": [
            "--root",
            ".",
            "--require-version",
            __version__,
            "--require-source",
            source_digest(),
        ],
    }
    current = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    boundaries = dict.fromkeys(targets, primary)
    for host_root in sorted({primary, current}):
        codex = host_root / ".codex/config.toml"
        targets[codex] = _codex(_text(codex, host_root), server)
        claude = host_root / ".mcp.json"
        document = _object(_text(claude, host_root))
        servers = document.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            raise ContextError("Claude MCP server configuration must be an object")
        existing_server = servers.get("personal_work_item")
        if existing_server is not None and not _owned_server(existing_server):
            raise ContextError("Claude personal MCP entry has another owner")
        servers["personal_work_item"] = server
        targets[claude] = _json(document)
        settings = host_root / ".claude/settings.local.json"
        approval = _object(_text(settings, host_root))
        if "personal_work_item" in approval.get("disabledMcpjsonServers", []):
            raise ContextError(
                "Claude explicitly disables personal_work_item; "
                "reconcile that setting first"
            )
        enabled = approval.setdefault("enabledMcpjsonServers", [])
        if not isinstance(enabled, list) or not all(
            isinstance(name, str) for name in enabled
        ):
            raise ContextError("Claude MCP approval configuration must be a list")
        if "personal_work_item" not in enabled:
            enabled.append("personal_work_item")
        targets[settings] = _json(approval)
        boundaries.update({codex: host_root, claude: host_root, settings: host_root})
    originals = {path: _text(path, boundaries[path]) for path in targets}
    changed = {
        path: value for path, value in targets.items() if value != originals[path]
    }
    if mode == "write":
        _write_batch(changed, originals)
    return {
        "mode": mode,
        "changed": [
            path.relative_to(primary).as_posix()
            if boundaries[path] == primary
            else "current-worktree/" + path.relative_to(current).as_posix()
            for path in changed
        ],
        "ready": not changed or mode == "write",
    }
