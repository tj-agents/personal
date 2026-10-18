"""Select and deliver mandatory policy for an explicitly adopted personal project."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

IDENTITY = "personal@tj-agents"
START = "<!-- BEGIN personal:current-solution"
END = "<!-- END personal:current-solution -->"
BLOCK = re.compile(r"<!-- BEGIN personal:current-solution sha256:[0-9a-f]{64} -->.*?<!-- END personal:current-solution -->", re.DOTALL)
POLICY = Path(__file__).resolve().parents[3] / "policy/current-solution/SKILL.md"


def fragment() -> str:
    source = POLICY.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not source.startswith("---\n"):
        raise ValueError("policy is missing frontmatter")
    body = source.split("\n---\n", 1)[1].strip()
    if not body:
        raise ValueError("policy body is empty")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return f"{START} sha256:{digest} -->\n{body}\n{END}"


def text(path: Path) -> str:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError(f"refusing linked instruction file: {path}")
    return path.read_text(encoding="utf-8") if path.exists() else ""


def projected(existing: str, block: str) -> str:
    count = len(BLOCK.findall(existing))
    if existing.count(START) != count or existing.count(END) != count or count > 1:
        raise ValueError("personal policy has duplicate or malformed block markers")
    if count:
        return BLOCK.sub(lambda _: block, existing)
    return existing.rstrip() + ("\n\n" if existing.strip() else "") + block + "\n"


def native_plan(root: Path) -> dict[Path, str]:
    block = fragment()
    agents, claude = root / "AGENTS.md", root / "CLAUDE.md"
    agents_text, claude_text = text(agents), text(claude)
    targets = {agents: projected(agents_text, block)}
    if not claude.exists():
        targets[claude] = "@AGENTS.md\n"
    elif imports_agents(claude_text):
        if START in claude_text or END in claude_text:
            raise ValueError("CLAUDE.md imports AGENTS.md and also contains a duplicate personal block")
    else:
        targets[claude] = projected(claude_text, block)
    return targets


def imports_agents(body: str) -> bool:
    fence = None
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[0]
            fence = None if fence == marker else marker if fence is None else fence
        elif fence is None and stripped == "@AGENTS.md":
            return True
    return False


def check_retained_aliases(root: Path) -> None:
    path = root / ".agents/plugins/payloads.json"
    if not path.is_file():
        return
    declaration = json.loads(path.read_text(encoding="utf-8"))
    for field in ("compatibilityAliases", "compatibilitySkillAliases"):
        aliases = declaration.get(field, {})
        if aliases and (not isinstance(aliases, dict) or any(aliases.values())):
            raise ValueError(f"{path}: remove retained {field} and migrate known callers before adopting personal")


def selected(root: Path) -> bool:
    path = root / ".agents/plugins.json"
    if not path.is_file():
        return False
    selection = json.loads(path.read_text(encoding="utf-8"))
    return (selection.get("schema_version") == 1 and IDENTITY in selection.get("plugins", [])
            and selection.get("marketplaces", {}).get("tj-agents", {}).get("repository") == "tj-agents/marketplace")


def run(root: Path, mode: str, selection_tool: Path | None) -> int:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("project root must be a directory")
    check_retained_aliases(root)
    targets = native_plan(root)  # validate every native target before asking Core to write
    if selection_tool is not None:
        result = subprocess.run([sys.executable, "-B", str(selection_tool), "--root", str(root),
                                 "--plugin", "personal", "--mode", mode], check=False)
        if result.returncode:
            return result.returncode
    elif not selected(root):
        raise ValueError("select personal@tj-agents through the shipped machine plugin-selection tool first, or pass --selection-tool")
    if mode != "preview" and not selected(root):
        raise ValueError("Core selection did not declare personal@tj-agents from tj-agents/marketplace")
    changed = {path: value for path, value in targets.items() if text(path) != value}
    if mode == "write":
        for path, value in changed.items():
            path.write_text(value, encoding="utf-8", newline="\n")
    for path in changed:
        print(f"{mode}: {path.relative_to(root).as_posix()}")
    return int(mode == "check" and bool(changed))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("preview", "write", "check"), required=True)
    parser.add_argument("--selection-tool", type=Path)
    args = parser.parse_args()
    try:
        return run(args.root, args.mode, args.selection_tool)
    except (OSError, ValueError, IndexError, TypeError, AttributeError) as error:
        print(f"Personal adoption failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
