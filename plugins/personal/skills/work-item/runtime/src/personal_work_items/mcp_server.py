from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tj_work_items.records import ItemError

from . import __version__, credentials
from .context import ContextError, load_context
from .fingerprint import require_release

_PACKAGE_NAME = "@azure-devops/mcp"
_PACKAGE_VERSION = "2.10.0"


def _arguments(organization: str) -> list[str]:
    return [organization, "--authentication", "pat", "--domains", "core", "work-items"]


def _package_entry(node: Path, platform: str) -> Path | None:
    roots = [node.parent / "node_modules"]
    if platform == "posix":
        roots.append(node.parent.parent / "lib" / "node_modules")
    for root in roots:
        package = root / "@azure-devops" / "mcp"
        try:
            details = json.loads((package / "package.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            details.get("name") != _PACKAGE_NAME
            or details.get("version") != _PACKAGE_VERSION
        ):
            continue
        binary = details.get("bin")
        entry = (
            binary.get("mcp-server-azuredevops") if isinstance(binary, dict) else binary
        )
        path = package / entry if isinstance(entry, str) else None
        if path is not None and path.is_file():
            return path
    return None


def command(
    organization: str, executable: Path | None = None, system: str | None = None
) -> list[str]:
    platform = system or os.name
    if platform not in {"nt", "posix"}:
        raise ContextError("personal Azure work items support Windows and Linux")
    node = executable or Path(shutil.which("node") or "")
    if not node.is_file() or (platform == "nt" and node.name.casefold() != "node.exe"):
        name = "node.exe" if platform == "nt" else "node"
        raise ContextError(f"{name} is required to launch personal Azure work items")
    entry = _package_entry(node, platform)
    if entry is None:
        raise ContextError(
            "the pinned @azure-devops/mcp@2.10.0 package is not installed "
            "beside Node.js; install it before launching personal Azure work items"
        )
    return [str(node), str(entry), *_arguments(organization)]


def _environment(token: str) -> dict[str, str]:
    environment = dict(os.environ)
    for name in tuple(environment):
        upper = name.upper()
        if (
            name == "PERSONAL_ACCESS_TOKEN"
            or upper in {"SYSTEM_ACCESSTOKEN", "ADO_MCP_AUTH_TOKEN"}
            or (
                "AZURE" in upper
                and any(marker in upper for marker in ("TOKEN", "PAT", "AUTH"))
            )
        ):
            environment.pop(name, None)
    environment["PERSONAL_ACCESS_TOKEN"] = base64.b64encode(
        f"personal:{token}".encode()
    ).decode("ascii")
    return environment


def run(root: Path, executable: Path | None = None) -> int:
    loaded = load_context(root)
    config = loaded["config"]
    organization = config["organization"]
    if not isinstance(organization, str):
        raise ContextError("personal work-item declaration has an invalid organization")
    launch = command(organization, executable)
    token = credentials.get_pat(organization)
    return subprocess.run(launch, env=_environment(token), check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Launch the isolated personal Azure DevOps MCP server."
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--require-version")
    parser.add_argument("--require-source")
    parser.add_argument("--root", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        require_release(arguments.require_version, arguments.require_source)
        return run(arguments.root)
    except (
        ContextError,
        credentials.CredentialError,
        ItemError,
        OSError,
        ValueError,
    ) as error:
        print(f"Personal Azure MCP failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
