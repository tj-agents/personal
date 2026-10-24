"""Read the personal rules contract and resolve whether a checkout selects personal@tj-agents."""

import hashlib
import json
from pathlib import Path
import subprocess

PERSONAL = "personal@tj-agents"
CONTRACT = Path(__file__).resolve().parent.parent / "SKILL.md"


def policy(contract=CONTRACT):
    source = contract.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    if not source.startswith("---\n"):
        raise ValueError("policy is missing frontmatter")
    body = source.split("\n---\n", 1)[1].strip()
    if not body:
        raise ValueError("policy body is empty")
    return body, hashlib.sha256(source.encode("utf-8")).hexdigest()


def repository_root(directory):
    try:
        result = subprocess.run(["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError:
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def selects_personal(root):
    try:
        selection = json.loads((Path(root) / ".agents/plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    plugins = selection.get("plugins") if isinstance(selection, dict) else None
    return isinstance(plugins, list) and PERSONAL in plugins
