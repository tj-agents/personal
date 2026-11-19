---
name: use
description: Use when explicitly adopting or checking personal policy in a repository, including its native instructions.
kind: utility
domain: personal
profile: core
applicability: explicitly adopted personal projects
requires: python, agent
provenance: house
---

# Use personal project policy

Use only for a project Tommy explicitly identifies as personal. Never infer scope from its location or
from every repository on a machine. Preserve unrelated work and use the project's owning delivery branch.

Run `python <skill-directory>/scripts/use.py --root <project> --mode write --selection-tool <agent-plugins>/scripts/adopt_plugins.py`.
Resolve the selection tool from the installed `agent:plugins` skill, which ships it; do not
assemble or maintain another copy. Preview with `--mode preview`, and use the identical command with
`--mode check` in CI. Use `python3` on Linux/macOS. Requires Python 3.11 or newer.

The `agent:plugins` tool owns plugin declarations and host settings. This command selects `personal@tj-agents`,
generates the mandatory native instruction block in AGENTS.md, merges distinct CLAUDE.md instructions into
AGENTS.md once each, and leaves CLAUDE.md as the exact `@AGENTS.md` pointer; `@./AGENTS.md` is the same
pointer, and any other Claude-only `@path` import is refused rather than copied in as plain text. It also
removes its own earlier-generated `.github/workflows/check-personal-policy.yml` CI caller, since adoption
no longer wires CI enforcement, while refusing to touch a workflow of that name it did not generate. It
refuses retained compatibility declarations and broken block markers. Check fails while a retired
`current-solution` policy block remains; write replaces it in place with the current block. The policy has one authored body;
generated native blocks are checked, never edited by hand.
This is native instruction delivery, not a claim of plugin hook execution or trust.

Adoption does not write `.agents/repository.json`. The owner's default in its `<owner>/.github` repository
applies; a repository that needs a different merge policy commits its own `merge` section, as the GitHub
Actions merge-policy utility describes.


```powershell
# Windows, from a checkout of tj-agents/personal, for an explicitly personal repository:
python -B .agents/personal/utility/use/scripts/use.py --root C:/repos/my-app --mode preview --selection-tool C:/repos/agent/.agents/agent/utility/plugins/scripts/adopt_plugins.py
# Review the preview, then use --mode write; CI uses --mode check.
# Linux/macOS use python3 and their checkout paths with the same arguments.
```

Before declaring adoption complete, run its check and verify a fresh actual Claude and Codex entry point
in the project on supported platforms. Confirm the rule was loaded and inspect its installed selection;
a version command or a generated file is insufficient. Keep any missing host evidence with the goal.
